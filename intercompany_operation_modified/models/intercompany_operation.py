# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IntercompanyOperation(models.Model):
    _name = 'intercompany.operation'
    _description = 'Intercompany Operation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Operation No.',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        required=True,
        tracking=True,
    )
    operation_type = fields.Selection([
        ('sale', 'Sale'),
        ('purchase', 'Purchase'),
        ('payment', 'Payment'),
        ('landed_cost', 'Landed Cost'),
    ], string='Operation Type', required=True, default='sale', tracking=True)

    operation_date = fields.Date(
        string='Operation Date',
        required=True,
        default=fields.Date.today,
        tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    currency_rate = fields.Float(
        string='Currency Rate',
        compute='_compute_currency_rate',
        digits=(12, 6),
        help='Accounting exchange rate of the selected currency vs. the company currency, '
             'as of the operation date.',
    )
    payment_term_id = fields.Many2one(
        'account.payment.term',
        string='Payment Terms',
        tracking=True,
        help='Payment terms applied to the sale/purchase orders generated from this operation.',
    )
    company_ids = fields.Many2many(
        'res.company',
        string='Companies',
        compute='_compute_company_ids',
        store=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('to_approve', 'To Approve'),
        ('approved', 'Approved'),
        ('confirmed', 'Confirmed'),
        ('pickings_confirmed', 'Pickings Confirmed'),
        ('lc_invoiced', 'LC Invoiced'),
        ('landed_cost_created', 'Landed Cost Created'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    # Sale/Purchase lines
    line_ids = fields.One2many(
        'intercompany.operation.line',
        'operation_id',
        string='Operation Lines',
    )

    # Payment lines (for payment type)
    payment_line_ids = fields.One2many(
        'intercompany.operation.payment.line',
        'operation_id',
        string='Payment Lines',
    )

    # Payment type fields (shown when operation_type = payment)
    payment_direction = fields.Selection([
        ('inbound', 'Receive (Inbound)'),
        ('outbound', 'Send (Outbound)'),
    ], string='Payment Direction', default='inbound')

    # Sale: pricelist applied to the whole operation
    pricelist_id = fields.Many2one(
        'product.pricelist',
        string='Pricelist',
        tracking=True,
        help='Pricelist applied when creating sale orders from this operation.',
    )

    # Terms & Conditions at operation level (can be overridden per line)
    note = fields.Html(string='Terms and Conditions')

    # Documents
    document_ids = fields.Many2many(
        'ir.attachment',
        'intercompany_operation_attachment_rel',
        'operation_id', 'attachment_id',
        string='Documents',
    )
    document_count = fields.Integer(
        string='Documents',
        compute='_compute_document_count',
    )

    # Related documents
    sale_order_ids = fields.One2many('sale.order', 'intercompany_operation_id', string='Sale Orders')
    purchase_order_ids = fields.One2many('purchase.order', 'intercompany_operation_id', string='Purchase Orders')
    picking_ids = fields.One2many('stock.picking', 'intercompany_operation_id', string='Pickings')
    account_payment_ids = fields.One2many('account.payment', 'intercompany_operation_id', string='Payments')
    invoice_ids = fields.One2many('account.move', 'intercompany_operation_id', string='Invoices')

    # Landed cost documents
    landed_cost_ids = fields.One2many('stock.landed.cost', 'intercompany_operation_id', string='Landed Costs')

    # Linked intercompany.payment record (for payment type)
    intercompany_payment_id = fields.Many2one(
        'intercompany.payment',
        string='Payment Distribution',
        readonly=True,
        copy=False,
    )

    # Smart button counts
    sale_count = fields.Integer(compute='_compute_counts')
    purchase_count = fields.Integer(compute='_compute_counts')
    picking_count = fields.Integer(compute='_compute_counts')
    payment_count = fields.Integer(compute='_compute_counts')
    invoice_count = fields.Integer(compute='_compute_counts')
    order_count = fields.Integer(compute='_compute_counts')
    landed_cost_count = fields.Integer(compute='_compute_counts')

    amount_total = fields.Monetary(
        string='Total',
        compute='_compute_amount_total',
        currency_field='currency_id',
        store=True,
    )

    submitted_by = fields.Many2one(
        'res.users',
        string='Submitted By',
        readonly=True,
        copy=False,
        help='User who submitted this operation for approval.',
    )
    reject_reason = fields.Text(
        string='Rejection Reason',
        readonly=True,
        copy=False,
    )

    @api.depends('currency_id', 'operation_date', 'line_ids.company_id', 'payment_line_ids.company_id')
    def _compute_currency_rate(self):
        for rec in self:
            company = (rec.company_ids[:1] or rec.env.company)
            if rec.currency_id and company:
                rec.currency_rate = rec.currency_id._get_conversion_rate(
                    rec.currency_id, company.currency_id,
                    company, rec.operation_date or fields.Date.today(),
                )
            else:
                rec.currency_rate = 1.0

    @api.constrains('partner_id', 'line_ids', 'payment_line_ids')
    def _check_partner_not_same_as_line_company(self):
        for rec in self:
            if not rec.partner_id:
                continue
            # Find which company this partner belongs to (if any)
            partner_company = self.env['res.company'].sudo().search([
                ('partner_id', '=', rec.partner_id.id)
            ], limit=1)
            if not partner_company:
                continue  # partner is not a company, no conflict possible
            # Check against all line companies
            line_companies = rec.line_ids.mapped('company_id') | rec.payment_line_ids.mapped('company_id')
            for lc in line_companies:
                if lc == partner_company:
                    raise UserError(_(
                        'Company "%s" cannot be both the operating company on a line '
                        'and the partner of this operation.\n'
                        'You cannot buy from or sell to yourself.'
                    ) % lc.name)

    @api.onchange('partner_id')
    def _onchange_partner_intercompany_warning(self):
        if not self.partner_id:
            return
        partner_company = self.env['res.company'].sudo().search([
            ('partner_id', '=', self.partner_id.id)
        ], limit=1)
        if not partner_company:
            return
        line_companies = self.line_ids.mapped('company_id') | self.payment_line_ids.mapped('company_id')
        if partner_company in line_companies:
            return {
                'warning': {
                    'title': _('Invalid Partner'),
                    'message': _(
                        '"%s" is already selected as the company on one or more lines.\n'
                        'You cannot use the same company as both the partner and the operating company.'
                    ) % partner_company.name,
                }
            }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                op_type = vals.get('operation_type', 'sale')
                seq_code = {
                    'sale': 'intercompany.operation.sale',
                    'purchase': 'intercompany.operation.purchase',
                    'payment': 'intercompany.operation.payment',
                    'landed_cost': 'intercompany.operation.landed.cost',
                }.get(op_type, 'intercompany.operation.sale')
                vals['name'] = self.env['ir.sequence'].next_by_code(seq_code) or _('New')
        return super().create(vals_list)

    @api.depends('line_ids.company_id', 'payment_line_ids.company_id')
    def _compute_company_ids(self):
        for rec in self:
            if rec.operation_type == 'payment':
                rec.company_ids = rec.payment_line_ids.mapped('company_id')
            else:
                rec.company_ids = rec.line_ids.mapped('company_id')

    @api.depends('line_ids.subtotal', 'payment_line_ids.amount')
    def _compute_amount_total(self):
        for rec in self:
            if rec.operation_type == 'payment':
                rec.amount_total = sum(rec.payment_line_ids.mapped('amount'))
            else:
                rec.amount_total = sum(rec.line_ids.mapped('subtotal'))

    def _compute_counts(self):
        for rec in self:
            rec.sale_count = len(rec.sale_order_ids)
            rec.purchase_count = len(rec.purchase_order_ids)
            rec.picking_count = len(rec.picking_ids)
            rec.payment_count = len(rec.account_payment_ids)
            rec.invoice_count = len(rec.invoice_ids)
            rec.landed_cost_count = len(rec.landed_cost_ids)
            if rec.operation_type == 'sale':
                rec.order_count = rec.sale_count
            elif rec.operation_type == 'purchase':
                rec.order_count = rec.purchase_count
            else:
                rec.order_count = 0

    # ── APPROVAL NOTIFICATIONS ──────────────────────────────────────────────

    def _get_manager_users(self):
        return self.env['res.users'].search([
            ('groups_id', 'in', self.env.ref('intercompany_operation_modified.group_intercompany_manager').id),
        ])

    def _notify_managers_for_approval(self):
        """Schedule a To-Do activity for every manager and post a message
        in the chatter so managers are notified a record is waiting."""
        for rec in self:
            managers = rec._get_manager_users()
            if not managers:
                continue
            rec.message_post(
                body=_('%s submitted this record for approval.') % (rec.env.user.name),
                partner_ids=managers.mapped('partner_id').ids,
            )
            activity_type = rec.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            for manager in managers:
                rec.activity_schedule(
                    activity_type_id=activity_type.id if activity_type else False,
                    summary=_('Approval Required'),
                    note=_('%s is waiting for your approval.') % rec.display_name,
                    user_id=manager.id,
                )

    def _notify_submitter(self, message):
        """Notify the user who submitted the record about a decision."""
        for rec in self:
            if rec.submitted_by:
                rec.message_post(body=message, partner_ids=rec.submitted_by.partner_id.ids)
                rec.activity_feedback(['mail.mail_activity_data_todo'], user_id=self.env.user.id)

    def action_open_reject_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject with Reason'),
            'res_model': 'intercompany.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': 'intercompany.operation',
                'default_res_id': self.id,
            },
        }

    def _do_refuse(self, reason):
        """Manager-only: refuse/reset an approved operation back to draft, with a reason."""
        self.ensure_one()
        if self.state not in ('approved', 'to_approve'):
            raise UserError(_('Only approved or submitted operations can be refused.'))
        self.reject_reason = reason
        self.state = 'draft'
        self.message_post(body=_('Rejected by %s: %s') % (self.env.user.name, reason))
        self._notify_submitter(_('Your operation %s was rejected.\nReason: %s') % (self.display_name, reason))

    # ── SALE / PURCHASE FLOW ──────────────────────────────────────────────────

    def action_submit(self):
        """Submit operation for manager approval"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only draft operations can be submitted for approval.'))
        self.submitted_by = self.env.user
        self.reject_reason = False
        self.state = 'to_approve'
        self._notify_managers_for_approval()

    def action_submit_payment(self):
        """Submit payment-type operation for manager approval"""
        self.ensure_one()
        if self.operation_type != 'payment':
            raise UserError(_('This action is only for payment operations.'))
        if self.state != 'draft':
            raise UserError(_('Only draft operations can be submitted for approval.'))
        self.submitted_by = self.env.user
        self.reject_reason = False
        self.state = 'to_approve'
        self._notify_managers_for_approval()

    def action_approve(self):
        """Manager-only: approve operation before creating documents"""
        self.ensure_one()
        if self.state != 'to_approve':
            raise UserError(_('Only submitted operations can be approved. Please submit it first.'))
        self.state = 'approved'
        self._notify_submitter(_('Your operation %s was approved.') % self.display_name)

    def action_approve_payment(self):
        """Manager-only: approve payment-type operation"""
        self.ensure_one()
        if self.operation_type != 'payment':
            raise UserError(_('This action is only for payment operations.'))
        if self.state != 'to_approve':
            raise UserError(_('Only submitted operations can be approved. Please submit it first.'))
        self.state = 'approved'
        self._notify_submitter(_('Your operation %s was approved.') % self.display_name)

    def action_reset_payment_to_draft(self):
        """Reset a payment-type operation back to draft"""
        self.ensure_one()
        if self.operation_type != 'payment':
            raise UserError(_('This action is only for payment operations.'))
        if self.state not in ('approved', 'done'):
            raise UserError(_('Only approved or done payment operations can be reset to draft.'))
        pay_dists = self.env['intercompany.payment'].search([
            ('intercompany_operation_id', '=', self.id)
        ])
        for pd in pay_dists.filtered(lambda p: p.state == 'posted'):
            for payment in pd.payment_ids.filtered(lambda p: p.state == 'posted'):
                try:
                    payment.action_draft()
                except Exception:
                    pass
            pd.state = 'draft'
        self.state = 'draft'

    def _compute_document_count(self):
        for rec in self:
            rec.document_count = len(rec.document_ids)

    def action_view_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Documents',
            'res_model': 'ir.attachment',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.document_ids.ids)],
            'context': {
                'default_res_model': 'intercompany.operation',
                'default_res_id': self.id,
            },
        }

    @api.onchange('pricelist_id')
    def _onchange_pricelist_id(self):
        """When pricelist changes, recompute prices on all sale lines."""
        if self.operation_type != 'sale':
            return
        for line in self.line_ids:
            if line.product_id:
                line.price = line._get_price_from_product()

    def action_update_prices(self):
        """Button: recompute price + taxes on all lines from product/pricelist/UoM."""
        self.ensure_one()
        for line in self.line_ids:
            if not line.product_id:
                continue
            line.price = line._get_price_from_product()
            line.tax_ids = line._get_taxes_for_line()
        return True

    def action_create_documents(self):
        """Create Sale or Purchase Orders per company"""
        self.ensure_one()
        if self.operation_type == 'payment':
            return self.action_create_payment_distribution()

        if self.state != 'approved':
            raise UserError(_('Please get the operation approved by a manager before creating documents.'))

        if not self.line_ids:
            raise UserError(_('Please add operation lines first.'))

        if self.operation_type == 'sale':
            self._create_sale_orders()
            self.state = 'confirmed'
        elif self.operation_type == 'purchase':
            self._create_purchase_orders()
            self.state = 'confirmed'
        # landed_cost skips this step — goes directly to Create Invoice

    def _create_sale_orders(self):
        SaleOrder = self.env['sale.order']
        lines_by_company = {}
        for line in self.line_ids:
            lines_by_company.setdefault(line.company_id, []).append(line)

        for company, lines in lines_by_company.items():
            order_lines = [(0, 0, {
                'product_id': l.product_id.id,
                'product_uom_qty': l.qty,
                'product_uom': (l.product_uom_id or l.product_id.uom_id).id,
                'price_unit': l.price,
                'discount': l.discount,
                'name': l.note or l.product_id.name,
                'tax_id': [(6, 0, l.tax_ids.ids)] if l.tax_ids else [],
            }) for l in lines]

            vals = {
                'partner_id': self.partner_id.id,
                'date_order': self.operation_date,
                'currency_id': self.currency_id.id,
                'order_line': order_lines,
                'intercompany_operation_id': self.id,
                'company_id': company.id,
            }
            if self.pricelist_id:
                vals['pricelist_id'] = self.pricelist_id.id
            if self.payment_term_id:
                vals['payment_term_id'] = self.payment_term_id.id
            if self.note:
                vals['note'] = self.note
            company_lines = [l for l in lines if l.warehouse_id]
            if company_lines:
                vals['warehouse_id'] = company_lines[0].warehouse_id.id

            sale_order = SaleOrder.with_company(company).create(vals)
            sale_order.action_confirm()
            sale_order.picking_ids.write({'intercompany_operation_id': self.id})

    def _create_purchase_orders(self):
        PurchaseOrder = self.env['purchase.order']
        lines_by_company = {}
        for line in self.line_ids:
            lines_by_company.setdefault(line.company_id, []).append(line)

        for company, lines in lines_by_company.items():
            order_lines = [(0, 0, {
                'product_id': l.product_id.id,
                'product_qty': l.qty,
                'product_uom': (l.product_uom_id or l.product_id.uom_id).id,
                'price_unit': l.price,
                'discount': l.discount,
                'name': l.note or l.product_id.name,
                'taxes_id': [(6, 0, l.tax_ids.ids)] if l.tax_ids else [],
                'date_planned': self.operation_date,
            }) for l in lines]

            vals = {
                'partner_id': self.partner_id.id,
                'date_order': self.operation_date,
                'currency_id': self.currency_id.id,
                'order_line': order_lines,
                'intercompany_operation_id': self.id,
                'company_id': company.id,
            }
            if self.payment_term_id:
                vals['payment_term_id'] = self.payment_term_id.id
            if self.note:
                vals['notes'] = self.note
            company_lines = [l for l in lines if l.warehouse_id]
            if company_lines:
                wh = company_lines[0].warehouse_id
                picking_type = self.env['stock.picking.type'].search([
                    ('warehouse_id', '=', wh.id),
                    ('code', '=', 'incoming'),
                ], limit=1)
                if picking_type:
                    vals['picking_type_id'] = picking_type.id

            purchase_order = PurchaseOrder.with_company(company).create(vals)
            purchase_order.button_confirm()
            purchase_order.picking_ids.write({'intercompany_operation_id': self.id})

    def action_confirm_pickings(self):
        """Validate all stock pickings then move to pickings_confirmed"""
        self.ensure_one()
        for picking in self.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
            picking.action_confirm()
            picking.action_assign()
            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
            picking.button_validate()
        self.state = 'pickings_confirmed'

    def action_validate_pickings(self):
        return self.action_confirm_pickings()

    def action_create_invoices(self):
        """Create and post invoices from sale/purchase orders (or directly for landed_cost)."""
        self.ensure_one()
        invoices = self.env['account.move']

        if self.operation_type == 'sale':
            if self.state != 'pickings_confirmed':
                raise UserError(_('Please confirm pickings first.'))
            for order in self.sale_order_ids.filtered(lambda o: o.invoice_status == 'to invoice'):
                invoices |= order._create_invoices()
            invoices.write({'intercompany_operation_id': self.id, 'invoice_date': self.operation_date})
            for inv in invoices.filtered(lambda i: i.state == 'draft'):
                inv.action_post()
            self.state = 'done'

        elif self.operation_type == 'purchase':
            if self.state != 'pickings_confirmed':
                raise UserError(_('Please confirm pickings first.'))
            for order in self.purchase_order_ids.filtered(lambda o: o.state in ('purchase', 'done')):
                order.action_create_invoice()
                new_invoices = self.env['account.move'].search([
                    ('purchase_id', '=', order.id),
                    ('move_type', '=', 'in_invoice'),
                    ('state', '=', 'draft'),
                ])
                invoices |= new_invoices
            invoices.write({'intercompany_operation_id': self.id, 'invoice_date': self.operation_date})
            for inv in invoices.filtered(lambda i: i.state == 'draft'):
                inv.action_post()
            self.state = 'done'

        elif self.operation_type == 'landed_cost':
            if self.state != 'approved':
                raise UserError(_('Operation must be approved before creating invoices.'))
            if not self.line_ids:
                raise UserError(_('Please add operation lines first.'))

            # Group lines by company — create one vendor bill per company
            lines_by_company = {}
            for line in self.line_ids:
                lines_by_company.setdefault(line.company_id, []).append(line)

            for company, lines in lines_by_company.items():
                inv_lines = []
                for line in lines:
                    account = (
                        line.product_id.property_account_expense_id
                        or line.product_id.categ_id.property_account_expense_categ_id
                    )
                    inv_lines.append((0, 0, {
                        'product_id': line.product_id.id,
                        'name': line.product_id.name,
                        'quantity': line.qty,
                        'price_unit': line.price,
                        'product_uom_id': line.product_uom_id.id or line.product_id.uom_id.id,
                        'account_id': account.id if account else False,
                        'tax_ids': [(6, 0, line.tax_ids.ids)] if line.tax_ids else [],
                    }))
                bill = self.env['account.move'].with_company(company).create({
                    'move_type': 'in_invoice',
                    'partner_id': self.partner_id.id,
                    'invoice_date': self.operation_date,
                    'company_id': company.id,
                    'invoice_line_ids': inv_lines,
                    'intercompany_operation_id': self.id,
                })
                invoices |= bill

            for inv in invoices.filtered(lambda i: i.state == 'draft'):
                inv.action_post()

            self.state = 'lc_invoiced'

    def action_create_landed_cost(self):
        """Create stock.landed.cost records from the posted invoices."""
        self.ensure_one()
        if self.operation_type != 'landed_cost':
            raise UserError(_('This action is only for Landed Cost operations.'))
        if self.state != 'lc_invoiced':
            raise UserError(_('Please create the invoice first (Create Invoice step).'))

        posted_invoices = self.invoice_ids.filtered(lambda i: i.state == 'posted')
        if not posted_invoices:
            raise UserError(_('No posted invoices found. Please create invoices first.'))

        has_lc_field = 'landed_cost_ok' in self.env['product.product']._fields

        landed_costs = self.env['stock.landed.cost']
        for inv in posted_invoices:
            cost_lines = []
            for inv_line in inv.invoice_line_ids.filtered(lambda l: l.product_id):
                # Only include products flagged as Landed Cost
                if has_lc_field and not inv_line.product_id.landed_cost_ok:
                    continue
                cost_lines.append((0, 0, {
                    'product_id': inv_line.product_id.id,
                    'name': inv_line.name or inv_line.product_id.name,
                    'account_id': inv_line.account_id.id,
                    'price_unit': inv_line.price_subtotal,
                    'split_method': getattr(inv_line.product_id, 'split_method_landed_cost', 'equal') or 'equal',
                }))
            if not cost_lines:
                continue
            lc = self.env['stock.landed.cost'].with_company(inv.company_id).create({
                'vendor_bill_id': inv.id,
                'date': self.operation_date,
                'company_id': inv.company_id.id,
                'intercompany_operation_id': self.id,
                'cost_lines': cost_lines,
            })
            landed_costs |= lc

        if not landed_costs:
            raise UserError(_(
                'No Landed Cost products found in the invoices. '
                'Make sure the products are marked as "Can be a Landed Cost" (landed_cost_ok).'
            ))

        self.state = 'landed_cost_created'

        # اعمل الـ wizard record مسبقاً عشان الـ create() يشتغل ويملى الـ lines
        wizard = self.env['intercompany.landed.cost.validate.wizard'].create({
            'operation_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Validate Landed Costs'),
            'res_model': 'intercompany.landed.cost.validate.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }

    def action_open_landed_cost_validate_wizard(self):
        """Open the validate wizard for landed costs (from the Validate button)."""
        self.ensure_one()
        # اعمل الـ wizard record مسبقاً عشان الـ create() يشتغل ويملى الـ lines
        wizard = self.env['intercompany.landed.cost.validate.wizard'].create({
            'operation_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Validate Landed Costs'),
            'res_model': 'intercompany.landed.cost.validate.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }

    def action_view_landed_costs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Landed Costs'),
            'res_model': 'stock.landed.cost',
            'view_mode': 'list,form',
            'domain': [('intercompany_operation_id', '=', self.id)],
        }

    def action_create_payment_distribution(self):
        """Create a linked intercompany.payment from the payment lines
        ── PAYMENT FLOW ──────────────────────────────────────────────────────
        """
        self.ensure_one()
        if not self.payment_line_ids:
            raise UserError(_('Please add payment lines first.'))

        # Build intercompany.payment lines from our payment_line_ids
        pay_lines = [(0, 0, {
            'company_id': l.company_id.id,
            'journal_id': l.journal_id.id if l.journal_id else False,
            'amount': l.amount,
            'invoice_ids': [(6, 0, l.invoice_ids.ids)],
        }) for l in self.payment_line_ids]

        ip = self.env['intercompany.payment'].create({
            'partner_id': self.partner_id.id,
            'payment_type': self.payment_direction,
            'payment_date': self.operation_date,
            'currency_id': self.currency_id.id,
            'line_ids': pay_lines,
        })

        # Post payments immediately
        ip.action_post_payment()

        # Link payments back to this operation
        ip.payment_ids.write({'intercompany_operation_id': self.id})

        self.intercompany_payment_id = ip
        self.state = 'done'

    def action_view_payment_distribution(self):
        """Open the linked intercompany.payment"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Payment Distribution'),
            'res_model': 'intercompany.payment',
            'view_mode': 'form',
            'res_id': self.intercompany_payment_id.id,
        }

    # ── SMART BUTTONS ─────────────────────────────────────────────────────────

    def action_view_orders(self):
        self.ensure_one()
        if self.operation_type == 'sale':
            return {
                'type': 'ir.actions.act_window',
                'name': _('Sale Orders'),
                'res_model': 'sale.order',
                'view_mode': 'list,form',
                'domain': [('intercompany_operation_id', '=', self.id)],
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Purchase Orders'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('intercompany_operation_id', '=', self.id)],
        }

    def action_view_pickings(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pickings'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('intercompany_operation_id', '=', self.id)],
        }

    def action_view_payments(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Payments'),
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': [('intercompany_operation_id', '=', self.id)],
        }

    def action_view_invoices(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoices'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('intercompany_operation_id', '=', self.id)],
        }

    def action_cancel(self):
        for rec in self:
            # Block if any picking already done
            done_pickings = rec.picking_ids.filtered(lambda p: p.state == 'done')
            if done_pickings:
                picking_names = ', '.join(done_pickings.mapped('name'))
                raise UserError(_(
                    'Cannot cancel operation "%s".\n\n'
                    'The following stock transfers are already validated:\n%s\n\n'
                    'Please create a return/reverse transfer manually before cancelling.'
                ) % (rec.name, picking_names))

            # 1) Cancel pickings FIRST before orders
            for picking in rec.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')):
                try:
                    picking.action_cancel()
                except Exception:
                    picking._action_cancel()

            # 2) Cancel sale orders
            for order in rec.sale_order_ids.filtered(lambda o: o.state != 'cancel'):
                try:
                    order.action_cancel()
                except Exception as e:
                    raise UserError(_('Could not cancel Sale Order %s:\n%s') % (order.name, str(e)))

            # 3) Cancel purchase orders
            for order in rec.purchase_order_ids.filtered(lambda o: o.state != 'cancel'):
                try:
                    order.button_cancel()
                except Exception as e:
                    raise UserError(_('Could not cancel Purchase Order %s:\n%s') % (order.name, str(e)))

            # 4) Cancel posted invoices
            for inv in rec.invoice_ids.filtered(lambda i: i.state == 'posted'):
                try:
                    inv.button_draft()
                    inv.button_cancel()
                except Exception:
                    pass

            rec.state = 'cancelled'

    def action_draft(self):
        self.state = 'draft'

    def action_refuse(self):
        """Manager-only: opens the reject wizard to capture a reason."""
        return self.action_open_reject_wizard()

    @api.model
    def _cron_remind_pending_approvals(self):
        """Daily reminder: re-notify managers about operations still
        waiting for approval (state = to_approve)."""
        pending = self.search([('state', '=', 'to_approve')])
        for rec in pending:
            managers = rec._get_manager_users()
            if not managers:
                continue
            rec.message_post(
                body=_('Reminder: this operation has been waiting for approval since %s.')
                % (rec.write_date.strftime('%Y-%m-%d') if rec.write_date else ''),
                partner_ids=managers.mapped('partner_id').ids,
            )


class IntercompanyOperationLine(models.Model):
    _name = 'intercompany.operation.line'
    _description = 'Intercompany Operation Line'

    operation_id = fields.Many2one('intercompany.operation', ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True)

    product_domain = fields.Binary(
        compute='_compute_product_domain',
        help='Dynamic domain for product_id based on operation type.',
    )

    @api.depends('operation_id.operation_type')
    def _compute_product_domain(self):
        has_lc_field = 'landed_cost_ok' in self.env['product.product']._fields
        for line in self:
            op_type = line.operation_id.operation_type
            if op_type == 'landed_cost' and has_lc_field:
                line.product_domain = [('landed_cost_ok', '=', True)]
            elif op_type == 'sale':
                line.product_domain = [('sale_ok', '=', True)]
            elif op_type == 'purchase':
                line.product_domain = [('purchase_ok', '=', True)]
            else:
                line.product_domain = []

    company_id = fields.Many2one('res.company', string='Company', required=True)
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
        domain="[('company_id', '=', company_id)]",
    )
    product_uom_category_id = fields.Many2one(
        related='product_id.uom_id.category_id',
    )
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='UoM',
        domain="[('category_id', '=', product_uom_category_id)]",
        help="Unit of Measure used for this line. Defaults to the product's "
             "sales/purchase Unit of Measure and must stay in the same UoM "
             "category as the product.",
    )
    qty = fields.Float(string='Qty', default=1.0)
    price = fields.Float(string='Unit Price', digits='Product Price')
    discount = fields.Float(string='Disc.%', digits='Discount', default=0.0)
    tax_ids = fields.Many2many(
        'account.tax',
        string='Taxes',
        help='Taxes applied to this line when creating orders/invoices.',
        domain="[('type_tax_use', '=', operation_type == 'purchase' and 'purchase' or 'sale'), ('company_id', 'child_of', company_id)]",
    )

    operation_type = fields.Selection(
        related='operation_id.operation_type',
        store=False,
        string='Operation Type',
    )
    note = fields.Char(string='Description / Terms')
    subtotal = fields.Float(
        string='Subtotal',
        compute='_compute_subtotal',
        store=True,
    )
    currency_id = fields.Many2one(related='operation_id.currency_id')

    # Related fields used by the Reports (Products / Suppliers / Customers) — manager only
    partner_id = fields.Many2one(
        related='operation_id.partner_id', string='Partner', store=True)
    operation_type = fields.Selection(
        related='operation_id.operation_type', string='Operation Type', store=True)
    state = fields.Selection(
        related='operation_id.state', string='Status', store=True)
    operation_date = fields.Date(
        related='operation_id.operation_date', string='Operation Date', store=True)

    @api.depends('qty', 'price', 'discount')
    def _compute_subtotal(self):
        for rec in self:
            price_after_disc = rec.price * (1 - rec.discount / 100.0)
            rec.subtotal = rec.qty * price_after_disc

    # ── helpers ──────────────────────────────────────────────────────────────

    def _get_taxes_for_line(self):
        """Return taxes filtered by this line's company and operation type (sale/purchase)."""
        if not self.product_id:
            return self.env['account.tax']
        op_type = self.operation_id.operation_type if self.operation_id else 'sale'
        tax_use = 'sale' if op_type == 'sale' else 'purchase'
        company = self.company_id
        if not company:
            return self.env['account.tax']

        # جيب الضرائب من المنتج بالشركة المختارة
        product = self.product_id.with_company(company)
        taxes = product.taxes_id if op_type == 'sale' else product.supplier_taxes_id

        # لو مفيش ضرائب على الفرع، نصعد للشركة الأم
        if not taxes:
            check_company = company.parent_id
            while check_company:
                product_parent = self.product_id.with_company(check_company)
                taxes = product_parent.taxes_id if op_type == 'sale' else product_parent.supplier_taxes_id
                if taxes:
                    break
                check_company = check_company.parent_id

        # فلتر النوع بس — نقبل ضرائب الشركة الأم والفرع معاً
        company_ids = company.ids
        parent = company.parent_id
        while parent:
            company_ids.append(parent.id)
            parent = parent.parent_id

        taxes = taxes.filtered(
            lambda t: t.type_tax_use == tax_use
            and (not t.company_id or t.company_id.id in company_ids)
        )
        return taxes

    def _get_price_from_product(self):
        """Return unit price based on operation type, pricelist, UoM, company and supplierinfo."""
        if not self.product_id:
            return 0.0

        product = self.product_id
        op_type = self.operation_id.operation_type if self.operation_id else 'sale'
        pricelist = self.operation_id.pricelist_id if self.operation_id else False
        qty = self.qty or 1.0
        partner = self.operation_id.partner_id if self.operation_id else False
        uom = self.product_uom_id or product.uom_id
        company = self.company_id or self.env.company

        # product.with_company(company) هو الطريقة الصح عشان Odoo يقرأ
        # company-dependent fields (standard_price, lst_price, supplierinfo)
        # بتاعت الشركة المختارة على الـ line مش شركة اليوزر الحالية
        product_w_company = product.with_company(company)

        if op_type == 'sale':
            if pricelist:
                price = pricelist._get_product_price(product_w_company, qty, partner, uom=uom)
            else:
                price = product.uom_id._compute_price(product_w_company.lst_price, uom)
        elif op_type == 'purchase':
            if partner:
                seller = product_w_company._select_seller(
                    partner_id=partner,
                    quantity=qty,
                    uom_id=uom,
                )
                if seller:
                    price = seller.price
                    if seller.product_uom and seller.product_uom != uom:
                        price = seller.product_uom._compute_price(price, uom)
                    return price
            # لا يوجد supplierinfo - نرجع standard_price بتاع الشركة المختارة
            price = product.uom_id._compute_price(product_w_company.standard_price, uom)
        else:
            price = product.uom_id._compute_price(product_w_company.standard_price, uom)

        return price

    # ── onchange ─────────────────────────────────────────────────────────────

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if not self.product_id:
            return
        product = self.product_id

        # UoM → always reset to product default when product changes
        self.product_uom_id = product.uom_id

        # Description
        if not self.note:
            self.note = product.name

        # Price
        self.price = self._get_price_from_product()

        # Taxes
        self.tax_ids = self._get_taxes_for_line()

        # Reset discount
        self.discount = 0.0

    @api.constrains('company_id')
    def _check_line_company_not_same_as_partner(self):
        for line in self:
            if not line.company_id or not line.operation_id.partner_id:
                continue
            partner_company = self.env['res.company'].sudo().search([
                ('partner_id', '=', line.operation_id.partner_id.id)
            ], limit=1)
            if partner_company and partner_company == line.company_id:
                raise UserError(_(
                    'The company "%s" on this line is the same as the operation partner.\n'
                    'You cannot buy from or sell to yourself.'
                ) % line.company_id.name)

    @api.onchange('company_id')
    def _onchange_company_id(self):
        """Recompute price and taxes when company changes."""
        if self.product_id and self.company_id:
            self.price = self._get_price_from_product()
            self.tax_ids = self._get_taxes_for_line()
        # Warn if same as partner
        if self.company_id and self.operation_id.partner_id:
            partner_company = self.env['res.company'].sudo().search([
                ('partner_id', '=', self.operation_id.partner_id.id)
            ], limit=1)
            if partner_company and partner_company == self.company_id:
                return {
                    'warning': {
                        'title': _('Invalid Company'),
                        'message': _(
                            '"%s" is already the partner of this operation.\n'
                            'You cannot use the same company as both buyer/seller and partner.'
                        ) % self.company_id.name,
                    }
                }

    @api.onchange('product_uom_id')
    def _onchange_product_uom_id(self):
        """Recompute price when UoM changes (converts between UoMs)."""
        if self.product_id and self.product_uom_id:
            self.price = self._get_price_from_product()

    @api.onchange('qty')
    def _onchange_qty(self):
        """Recompute price when qty changes (pricelist qty breaks)."""
        op_type = self.operation_id.operation_type if self.operation_id else 'sale'
        if self.product_id and (
            (op_type == 'sale' and self.operation_id.pricelist_id)
            or op_type == 'purchase'
        ):
            self.price = self._get_price_from_product()

    @api.onchange('company_id')
    def _onchange_company_id(self):
        self.warehouse_id = False
        if self.product_id:
            self.tax_ids = self._get_taxes_for_line()


class IntercompanyOperationPaymentLine(models.Model):
    """Payment lines used when operation_type = payment"""
    _name = 'intercompany.operation.payment.line'
    _description = 'Intercompany Operation Payment Line'

    operation_id = fields.Many2one('intercompany.operation', ondelete='cascade')
    company_id = fields.Many2one('res.company', string='Company', required=True)
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal',
        domain="[('type', 'in', ['bank', 'cash']), ('company_id', '=', company_id)]",
    )
    amount = fields.Monetary(string='Amount', currency_field='currency_id')
    move_type_filter = fields.Selection([
        ('out_invoice', 'Customer Invoice'),
        ('in_invoice', 'Vendor Bill'),
    ], string='Invoice Type', compute='_compute_move_type_filter', store=True)
    invoice_ids = fields.Many2many(
        'account.move',
        string='Invoices to Reconcile',
        help='Optional: select open invoices/bills for this company & partner. '
             'On posting, the payment will be automatically reconciled against them. '
             'The oldest open invoice is pre-selected automatically when you pick a company; '
             'you can change it.',
        domain="[('company_id', '=', company_id), ('partner_id', '=', parent.partner_id),"
               " ('state', '=', 'posted'), ('payment_state', 'in', ['not_paid', 'partial']),"
               " ('move_type', '=', move_type_filter)]",
    )
    percentage = fields.Float(string='%', compute='_compute_percentage', store=True)
    currency_id = fields.Many2one(related='operation_id.currency_id')

    @api.depends('amount', 'operation_id.amount_total')
    def _compute_percentage(self):
        for rec in self:
            total = rec.operation_id.amount_total
            rec.percentage = (rec.amount / total * 100) if total else 0.0

    @api.depends('operation_id.payment_direction')
    def _compute_move_type_filter(self):
        # Receiving money (inbound) → sales invoices issued to the partner.
        # Sending money (outbound) → vendor bills issued by the partner.
        for rec in self:
            rec.move_type_filter = (
                'out_invoice' if rec.operation_id.payment_direction == 'inbound' else 'in_invoice'
            )

    @api.onchange('company_id')
    def _onchange_company_id(self):
        self.journal_id = False
        self._auto_select_invoice()

    def _auto_select_invoice(self):
        """Automatically pre-select the oldest open invoice/bill for this
        company & partner (user can still change or clear it manually)."""
        for rec in self:
            if rec.invoice_ids:
                continue  # don't override a manual choice
            if not rec.company_id or not rec.operation_id or not rec.operation_id.partner_id:
                continue
            move_type = 'out_invoice' if rec.operation_id.payment_direction == 'inbound' else 'in_invoice'
            oldest_invoice = rec.env['account.move'].search([
                ('company_id', '=', rec.company_id.id),
                ('partner_id', '=', rec.operation_id.partner_id.id),
                ('state', '=', 'posted'),
                ('payment_state', 'in', ['not_paid', 'partial']),
                ('move_type', '=', move_type),
            ], order='invoice_date_due asc, invoice_date asc, id asc', limit=1)
            if oldest_invoice:
                rec.invoice_ids = [(6, 0, [oldest_invoice.id])]


# Extend sale.order
class SaleOrder(models.Model):
    _inherit = 'sale.order'

    intercompany_operation_id = fields.Many2one(
        'intercompany.operation',
        string='Intercompany Operation',
        copy=False,
    )


# Extend purchase.order
class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    intercompany_operation_id = fields.Many2one(
        'intercompany.operation',
        string='Intercompany Operation',
        copy=False,
    )


# Extend stock.picking
class StockPicking(models.Model):
    _inherit = 'stock.picking'

    intercompany_operation_id = fields.Many2one(
        'intercompany.operation',
        string='Intercompany Operation',
        copy=False,
    )


# Extend account.payment
class AccountPayment(models.Model):
    _inherit = 'account.payment'

    intercompany_operation_id = fields.Many2one(
        'intercompany.operation',
        string='Intercompany Operation',
        copy=False,
    )
    intercompany_payment_id = fields.Many2one(
        'intercompany.payment',
        string='Intercompany Payment',
        copy=False,
    )


# Extend account.move
class AccountMove(models.Model):
    _inherit = 'account.move'

    intercompany_operation_id = fields.Many2one(
        'intercompany.operation',
        string='Intercompany Operation',
        copy=False,
    )

    # Landed cost: count of stock.landed.cost records created from this bill
    intercompany_landed_cost_ids = fields.One2many(
        'stock.landed.cost',
        'intercompany_vendor_bill_id',
        string='Intercompany Landed Costs',
    )
    intercompany_landed_cost_count = fields.Integer(
        compute='_compute_intercompany_landed_cost_count',
    )
    intercompany_show_landed_cost_button = fields.Boolean(
        compute='_compute_intercompany_show_landed_cost_button',
        help='Show Create Landed Cost button on posted vendor bills linked to intercompany ops.',
    )

    @api.depends('intercompany_landed_cost_ids')
    def _compute_intercompany_landed_cost_count(self):
        for rec in self:
            rec.intercompany_landed_cost_count = len(rec.intercompany_landed_cost_ids)

    @api.depends('invoice_line_ids.product_id', 'invoice_line_ids.product_id.type',
                 'move_type', 'state', 'intercompany_operation_id',
                 'intercompany_landed_cost_count')
    def _compute_intercompany_show_landed_cost_button(self):
        # Check once if landed_cost_ok field exists in product.product
        has_lc_field = 'landed_cost_ok' in self.env['product.product']._fields
        for rec in self:
            if rec.move_type != 'in_invoice' or rec.state != 'posted':
                rec.intercompany_show_landed_cost_button = False
                continue
            if not rec.intercompany_operation_id:
                rec.intercompany_show_landed_cost_button = False
                continue
            if rec.intercompany_landed_cost_count > 0:
                rec.intercompany_show_landed_cost_button = False
                continue
            if has_lc_field:
                has_service = any(
                    l.product_id and l.product_id.type == 'service'
                    and l.product_id.landed_cost_ok
                    for l in rec.invoice_line_ids
                )
            else:
                has_service = any(
                    l.product_id and l.product_id.type == 'service'
                    for l in rec.invoice_line_ids
                )
            rec.intercompany_show_landed_cost_button = has_service

    def action_intercompany_create_landed_cost(self):
        """Called from the vendor bill button.
        Creates a stock.landed.cost in the Intercompany Landed Cost menu."""
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_('Please post the invoice first.'))
        if not self.intercompany_operation_id:
            raise UserError(_('This invoice is not linked to an Intercompany Operation.'))

        cost_lines = []
        has_lc_field = 'landed_cost_ok' in self.env['product.product']._fields
        for line in self.invoice_line_ids.filtered(
                lambda l: l.product_id and l.product_id.type == 'service'):
            if has_lc_field and not line.product_id.landed_cost_ok:
                continue
            cost_lines.append((0, 0, {
                'product_id': line.product_id.id,
                'name': line.name or line.product_id.name,
                'account_id': line.account_id.id,
                'price_unit': line.price_subtotal,
                'split_method': getattr(line.product_id, 'split_method_landed_cost', 'equal') or 'equal',
            }))

        if not cost_lines:
            raise UserError(_(
                'No landed cost service products found in this invoice.\n'
                'Make sure the products are of type "Service" and have "Is a Landed Cost" checked.'
            ))

        # Link to existing landed_cost operation or create one
        operation = self.intercompany_operation_id
        if operation.operation_type != 'landed_cost':
            lc_operation = self.env['intercompany.operation'].create({
                'partner_id': operation.partner_id.id,
                'operation_type': 'landed_cost',
                'operation_date': self.invoice_date or fields.Date.today(),
                'currency_id': self.currency_id.id,
                'state': 'done',
            })
        else:
            lc_operation = operation

        lc = self.env['stock.landed.cost'].with_company(self.company_id).create({
            'vendor_bill_id': self.id,
            'date': self.invoice_date or fields.Date.today(),
            'company_id': self.company_id.id,
            'intercompany_operation_id': lc_operation.id,
            'intercompany_vendor_bill_id': self.id,
            'cost_lines': cost_lines,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': _('Landed Cost'),
            'res_model': 'stock.landed.cost',
            'view_mode': 'form',
            'res_id': lc.id,
        }

    def action_view_intercompany_landed_costs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Intercompany Landed Costs'),
            'res_model': 'stock.landed.cost',
            'view_mode': 'list,form',
            'domain': [('intercompany_vendor_bill_id', '=', self.id)],
        }
