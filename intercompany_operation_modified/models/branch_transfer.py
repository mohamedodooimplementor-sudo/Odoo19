# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IntercompanyPickingTransfer(models.Model):
    """Branches Transfer > Picking Transfer.

    Moves stock between two companies through an intermediate (transit)
    location, in two legs:
        1) Send leg:    location_sent_id      -> intermediate_location_id
        2) Receive leg: intermediate_location_id -> location_receive_id

    Workflow:
        draft -> to_approve -> approved (leg 1 picking created)
              -> send_approved (leg 1 validated, leg 2 picking created)
              -> received (leg 2 validated / done)
    Manager-only: approve.
    """
    _name = 'intercompany.picking.transfer'
    _description = 'Intercompany Branches Picking Transfer'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: _('New'),
    )

    company_sent_id = fields.Many2one(
        'res.company', string='Company Sent', required=True, tracking=True)
    location_sent_id = fields.Many2one(
        'stock.location', string='Sent Location', required=True, tracking=True,
        domain="[('usage', '=', 'internal'), ('company_id', '=', company_sent_id)]")

    company_receive_id = fields.Many2one(
        'res.company', string='Company Receive', required=True, tracking=True)
    location_receive_id = fields.Many2one(
        'stock.location', string='Receive Location', required=True, tracking=True,
        domain="[('usage', '=', 'internal'), ('company_id', '=', company_receive_id)]")

    intermediate_location_id = fields.Many2one(
        'stock.location', string='Intermediate Location', required=True, tracking=True,
        domain="[('usage', '=', 'inventory')]",
        default=lambda self: self._default_intermediate_location_id(),
        help='Transit / inventory-loss type location used as a bridge between '
             'the two companies, since a single stock move cannot directly '
             'cross two different companies.')

    def _default_intermediate_location_id(self):
        return self.env.ref(
            'intercompany_operation_modified.stock_location_branches_transfer_intermediate',
            raise_if_not_found=False)

    def _default_location_for_company(self, company):
        """Best-guess default internal location for a company: its main
        warehouse's stock location, falling back to any internal location."""
        if not company:
            return self.env['stock.location']
        warehouse = self.env['stock.warehouse'].search(
            [('company_id', '=', company.id)], limit=1)
        if warehouse and warehouse.lot_stock_id:
            return warehouse.lot_stock_id
        return self.env['stock.location'].search([
            ('usage', '=', 'internal'), ('company_id', '=', company.id),
        ], limit=1)

    @api.onchange('company_sent_id')
    def _onchange_company_sent_id(self):
        if self.company_sent_id:
            self.location_sent_id = self._default_location_for_company(self.company_sent_id)
        else:
            self.location_sent_id = False

    @api.onchange('company_receive_id')
    def _onchange_company_receive_id(self):
        if self.company_receive_id:
            self.location_receive_id = self._default_location_for_company(self.company_receive_id)
        else:
            self.location_receive_id = False


    line_ids = fields.One2many(
        'intercompany.picking.transfer.line', 'transfer_id',
        string='Products',)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('to_approve', 'To Approve'),
        ('approved', 'Approved'),
        ('send_approved', 'Send Approved'),
        ('received', 'Received'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    submitted_by = fields.Many2one('res.users', string='Submitted By', readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    reject_reason = fields.Text(string='Rejection Reason', readonly=True, copy=False)

    send_picking_id = fields.Many2one(
        'stock.picking', string='Send Picking (Sent → Intermediate)', readonly=True, copy=False)
    receive_picking_id = fields.Many2one(
        'stock.picking', string='Receive Picking (Intermediate → Receive)', readonly=True, copy=False)

    picking_count = fields.Integer(compute='_compute_picking_count')

    @api.depends('send_picking_id', 'receive_picking_id')
    def _compute_picking_count(self):
        for rec in self:
            rec.picking_count = len(rec.send_picking_id) + len(rec.receive_picking_id)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'intercompany.picking.transfer') or _('New')
        return super().create(vals_list)

    # ── workflow ────────────────────────────────────────────────────────
    def action_submit(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Please add at least one product line.'))
            rec.write({'state': 'to_approve', 'submitted_by': self.env.user.id, 'reject_reason': False})

    def action_open_reject_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject with Reason'),
            'res_model': 'intercompany.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': 'intercompany.picking.transfer',
                'default_res_id': self.id,
            },
        }

    def action_refuse(self):
        """Manager-only: opens the reject wizard to capture a reason."""
        return self.action_open_reject_wizard()

    def _do_refuse(self, reason):
        """Manager-only: refuse a submitted/approved transfer back to draft, with a reason."""
        self.ensure_one()
        if self.state not in ('to_approve', 'approved'):
            raise UserError(_('Only transfers "To Approve" or "Approved" can be refused.'))
        self.write({'state': 'draft', 'reject_reason': reason})
        self.message_post(body=_('Rejected by %s: %s') % (self.env.user.name, reason))
        if self.submitted_by:
            self.message_post(
                body=_('Your transfer %s was rejected.\nReason: %s') % (self.display_name, reason),
                partner_ids=self.submitted_by.partner_id.ids)

    def action_approve(self):
        """Manager only — creates the first (Send) internal transfer:
        location_sent -> intermediate."""
        self.ensure_one()
        if not self.env.user.has_group('intercompany_operation_modified.group_intercompany_manager'):
            raise UserError(_('Only a Manager can approve this transfer.'))
        if self.state != 'to_approve':
            raise UserError(_('Only transfers in "To Approve" state can be approved.'))

        picking = self._create_picking(
            company=self.company_sent_id,
            src_location=self.location_sent_id,
            dst_location=self.intermediate_location_id,
        )
        self.write({
            'state': 'approved',
            'approved_by': self.env.user.id,
            'send_picking_id': picking.id,
        })

    def action_send_approve(self):
        """Confirms/validates the Send picking and creates the Receive picking:
        intermediate -> location_receive."""
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_('Please approve the transfer first.'))
        if not self.send_picking_id:
            raise UserError(_('Send picking not found.'))

        self._validate_picking(self.send_picking_id)

        picking = self._create_picking(
            company=self.company_receive_id,
            src_location=self.intermediate_location_id,
            dst_location=self.location_receive_id,
        )
        self.write({
            'state': 'send_approved',
            'receive_picking_id': picking.id,
        })

    def action_receive_approve(self):
        """Confirms/validates the Receive picking."""
        self.ensure_one()
        if self.state != 'send_approved':
            raise UserError(_('Please confirm the Send leg first.'))
        if not self.receive_picking_id:
            raise UserError(_('Receive picking not found.'))

        self._validate_picking(self.receive_picking_id)
        self.write({'state': 'received'})

    def action_cancel(self):
        for rec in self:
            for picking in (rec.send_picking_id | rec.receive_picking_id):
                if picking.state not in ('done', 'cancel'):
                    picking.action_cancel()
            rec.state = 'cancelled'

    def action_reset_draft(self):
        for rec in self:
            rec.write({'state': 'draft', 'submitted_by': False, 'approved_by': False})

    # ── helpers ─────────────────────────────────────────────────────────
    def _get_picking_type(self, company, src_location, dst_location):
        """Pick an internal transfer picking type belonging to `company`.

        Deliberately does NOT fall back to another company's operation type:
        doing so silently causes the move to be costed/journaled against the
        wrong company (e.g. missing valuation entry on the sending company).
        """
        picking_type = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('company_id', '=', company.id),
        ], limit=1)
        if not picking_type:
            raise UserError(_(
                'No "Internal Transfer" operation type found for company %s.\n'
                'Go to Inventory > Configuration > Operation Types (while '
                'switched to that company) and make sure an Internal '
                'Transfers type exists and is linked to a warehouse. '
                'Without it, stock moves for this company may not generate '
                'the expected accounting/valuation entries.'
            ) % company.name)
        return picking_type

    def _create_picking(self, company, src_location, dst_location):
        self.ensure_one()
        picking_type = self._get_picking_type(company, src_location, dst_location)
        Picking = self.env['stock.picking'].with_company(company)
        picking = Picking.create({
            'picking_type_id': picking_type.id,
            'location_id': src_location.id,
            'location_dest_id': dst_location.id,
            'company_id': company.id,
            'origin': self.name,
            'intercompany_picking_transfer_id': self.id,
            'move_ids_without_package': [(0, 0, {
                'name': line.product_id.display_name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty,
                'product_uom': line.product_uom_id.id or line.product_id.uom_id.id,
                'location_id': src_location.id,
                'location_dest_id': dst_location.id,
                'company_id': company.id,
            }) for line in self.line_ids],
        })
        picking.action_confirm()
        picking.action_assign()
        return picking

    def _validate_picking(self, picking):
        if picking.state == 'done':
            return
        for move in picking.move_ids_without_package:
            if not move.move_line_ids:
                move._set_quantity_done(move.product_uom_qty)
                continue
            for move_line in move.move_line_ids:
                qty = move_line.reserved_uom_qty if hasattr(move_line, 'reserved_uom_qty') \
                    else move.product_uom_qty
                if hasattr(move_line, 'quantity'):
                    move_line.quantity = qty
                    if hasattr(move_line, 'picked'):
                        move_line.picked = True
                else:
                    move_line.qty_done = qty
        picking.button_validate()

    def action_view_pickings(self):
        self.ensure_one()
        pickings = self.send_picking_id | self.receive_picking_id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transfer Pickings'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('id', 'in', pickings.ids)],
        }


class IntercompanyPickingTransferLine(models.Model):
    _name = 'intercompany.picking.transfer.line'
    _description = 'Intercompany Branches Picking Transfer Line'

    transfer_id = fields.Many2one(
        'intercompany.picking.transfer', string='Transfer',
        required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    product_uom_id = fields.Many2one(
        'uom.uom', string='UoM',
        domain="[('category_id', '=', product_uom_category_id)]")
    product_uom_category_id = fields.Many2one(
        related='product_id.uom_id.category_id')
    qty = fields.Float(string='Quantity', default=1.0, required=True)

    qty_on_hand = fields.Float(
        string='On Hand (Sent)',
        compute='_compute_qty_on_hand',
        digits='Product Unit of Measure',
        help='Quantity available in the sending location for this product.',
    )

    @api.depends('product_id', 'transfer_id.location_sent_id')
    def _compute_qty_on_hand(self):
        for line in self:
            if not line.product_id:
                line.qty_on_hand = 0.0
                continue
            location = line.transfer_id.location_sent_id
            if location:
                quants = self.env['stock.quant'].search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id', '=', location.id),
                ])
                line.qty_on_hand = sum(quants.mapped('quantity'))
            else:
                # Fallback: use product's standard on-hand qty
                line.qty_on_hand = line.product_id.qty_available

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id


class IntercompanyPickingTransferStockPicking(models.Model):
    _inherit = 'stock.picking'

    intercompany_picking_transfer_id = fields.Many2one(
        'intercompany.picking.transfer', string='Branches Picking Transfer', readonly=True)


class IntercompanyPaymentTransfer(models.Model):
    """Branches Transfer > Payment Transfer.

    Simple intercompany cash transfer: an outbound payment in the sending
    company's journal and an inbound payment in the receiving company's
    journal, linked together. Manager-only approval.
    """
    _name = 'intercompany.payment.transfer'
    _description = 'Intercompany Branches Payment Transfer'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: _('New'))

    company_sent_id = fields.Many2one(
        'res.company', string='Company Sent', required=True, tracking=True)
    journal_sent_id = fields.Many2one(
        'account.journal', string='Sent Journal', required=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_sent_id)]")

    company_receive_id = fields.Many2one(
        'res.company', string='Company Receive', required=True, tracking=True)
    journal_receive_id = fields.Many2one(
        'account.journal', string='Receive Journal', required=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_receive_id)]")

    amount = fields.Monetary(string='Amount', required=True,)
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,)
    date = fields.Date(string='Date', default=fields.Date.context_today,)
    memo = fields.Char(string='Memo',)

    intermediate_account_id = fields.Many2one(
        'account.account', string='Intermediate Account', required=True,
        default=lambda self: self._default_intermediate_account_id(),
        help='Clearing account both the outbound and the inbound payment '
             'are posted against, so the transfer balances between the two '
             'companies. Defaults to the shared "Branches Transfer - '
             'Intermediate Clearing" account but can be changed.')

    @api.onchange('company_sent_id')
    def _onchange_company_sent_id(self):
        """Auto-fill the default bank/cash journal for the sending company."""
        if self.company_sent_id:
            journal = self.env['account.journal'].search([
                ('type', 'in', ('bank', 'cash')),
                ('company_id', '=', self.company_sent_id.id),
            ], limit=1)
            self.journal_sent_id = journal
        else:
            self.journal_sent_id = False

    @api.onchange('company_receive_id')
    def _onchange_company_receive_id(self):
        """Auto-fill the default bank/cash journal for the receiving company."""
        if self.company_receive_id:
            journal = self.env['account.journal'].search([
                ('type', 'in', ('bank', 'cash')),
                ('company_id', '=', self.company_receive_id.id),
            ], limit=1)
            self.journal_receive_id = journal
        else:
            self.journal_receive_id = False

    def _default_intermediate_account_id(self):
        return self.env.ref(
            'intercompany_operation_modified.account_branches_transfer_intermediate',
            raise_if_not_found=False)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('to_approve', 'To Approve'),
        ('approved', 'Approved'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    submitted_by = fields.Many2one('res.users', string='Submitted By', readonly=True, copy=False)
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    reject_reason = fields.Text(string='Rejection Reason', readonly=True, copy=False)

    payment_sent_id = fields.Many2one('account.payment', string='Outbound Payment', readonly=True, copy=False)
    payment_receive_id = fields.Many2one('account.payment', string='Inbound Payment', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'intercompany.payment.transfer') or _('New')
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if not rec.amount:
                raise UserError(_('Please set an amount greater than zero.'))
            rec.write({'state': 'to_approve', 'submitted_by': self.env.user.id, 'reject_reason': False})

    def action_open_reject_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject with Reason'),
            'res_model': 'intercompany.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': 'intercompany.payment.transfer',
                'default_res_id': self.id,
            },
        }

    def action_refuse(self):
        """Manager-only: opens the reject wizard to capture a reason."""
        return self.action_open_reject_wizard()

    def _do_refuse(self, reason):
        """Manager-only: refuse a submitted payment transfer back to draft, with a reason."""
        self.ensure_one()
        if self.state != 'to_approve':
            raise UserError(_('Only transfers "To Approve" can be refused.'))
        self.write({'state': 'draft', 'reject_reason': reason})
        self.message_post(body=_('Rejected by %s: %s') % (self.env.user.name, reason))
        if self.submitted_by:
            self.message_post(
                body=_('Your transfer %s was rejected.\nReason: %s') % (self.display_name, reason),
                partner_ids=self.submitted_by.partner_id.ids)

    def action_approve(self):
        """Manager only — creates and posts both payments."""
        self.ensure_one()
        if not self.env.user.has_group('intercompany_operation_modified.group_intercompany_manager'):
            raise UserError(_('Only a Manager can approve this transfer.'))
        if self.state != 'to_approve':
            raise UserError(_('Only transfers in "To Approve" state can be approved.'))

        Payment = self.env['account.payment']
        outbound = Payment.with_company(self.company_sent_id).create({
            'payment_type': 'outbound',
            'partner_type': 'supplier',
            'journal_id': self.journal_sent_id.id,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'date': self.date,
            'memo': self.memo or self.name,
            'company_id': self.company_sent_id.id,
            'destination_account_id': self.intermediate_account_id.id,
        })
        inbound = Payment.with_company(self.company_receive_id).create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'journal_id': self.journal_receive_id.id,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'date': self.date,
            'memo': self.memo or self.name,
            'company_id': self.company_receive_id.id,
            'destination_account_id': self.intermediate_account_id.id,
        })
        # Post each payment individually: some third-party modules
        # (e.g. account_check) override action_post() assuming a
        # single-record recordset, so posting a combined recordset
        # of 2 payments together can break them.
        outbound.action_post()
        inbound.action_post()

        self.write({
            'state': 'posted',
            'approved_by': self.env.user.id,
            'payment_sent_id': outbound.id,
            'payment_receive_id': inbound.id,
        })

    def action_cancel(self):
        for rec in self:
            for payment in (rec.payment_sent_id | rec.payment_receive_id):
                if payment.state not in ('cancelled',):
                    payment.action_cancel()
            rec.state = 'cancelled'

    def action_reset_draft(self):
        for rec in self:
            rec.write({'state': 'draft', 'submitted_by': False, 'approved_by': False})

    def action_view_payments(self):
        self.ensure_one()
        payments = self.payment_sent_id | self.payment_receive_id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transfer Payments'),
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'domain': [('id', 'in', payments.ids)],
        }
