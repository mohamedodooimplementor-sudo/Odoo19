# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IntercompanyReturn(models.Model):
    _name = 'intercompany.return'
    _description = 'Intercompany Sales / Purchase Return'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Return No.', required=True, copy=False, readonly=True,
        default=lambda self: _('New'),
    )
    return_type = fields.Selection([
        ('sale', 'Sales Return'),
        ('purchase', 'Purchase Return'),
    ], string='Return Type', required=True, default='sale', tracking=True)

    partner_id = fields.Many2one('res.partner', string='Customer/Vendor', required=True, tracking=True)

    # ── ORDER SOURCE MODE ────────────────────────────────────────────────────
    order_source = fields.Selection([
        ('individual', 'Individual Orders'),
        ('operation', 'Grouped Operation'),
    ], string='Order Source', default='individual', required=True,
       readonly="state != 'draft'", tracking=True)

    # Individual orders (multiple)
    sale_order_ids = fields.Many2many(
        'sale.order', 'intercompany_return_sale_order_rel',
        'return_id', 'order_id',
        string='Sale Orders', tracking=True,
        domain="[('partner_id', '=', partner_id), ('state', '=', 'sale')]",
    )
    purchase_order_ids = fields.Many2many(
        'purchase.order', 'intercompany_return_purchase_order_rel',
        'return_id', 'order_id',
        string='Purchase Orders', tracking=True,
        domain="[('partner_id', '=', partner_id), ('state', '=', 'purchase')]",
    )

    # Grouped operation
    operation_id = fields.Many2one(
        'intercompany.operation', string='Intercompany Operation', tracking=True,
        domain="[('partner_id', '=', partner_id), ('state', '=', 'done'), ('operation_type', '=', return_type)]",
    )

    company_id = fields.Many2one('res.company', string='Company', compute='_compute_company_id', store=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('to_approve', 'To Approve'),
        ('approved', 'Approved'),
        ('confirmed', 'Submitted'),
        ('returned', 'Returned'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
        ('refused', 'Refused'),
    ], string='Status', default='draft', tracking=True)

    submitted_by = fields.Many2one('res.users', string='Submitted By', readonly=True, copy=False)
    reject_reason = fields.Text(string='Rejection Reason', readonly=True, copy=False)

    # Original pickings belonging to the chosen orders
    order_picking_ids = fields.One2many(
        'stock.picking', compute='_compute_order_picking_ids', string='Order Pickings',
    )
    # Product/quantity breakdown of those pickings, shown directly on the form
    # so the user can see what's available to return before opening the wizard.
    return_move_ids = fields.One2many(
        'stock.move', compute='_compute_return_move_ids', string='Products Available to Return',
    )
    # Pickings created by this return
    return_picking_ids = fields.One2many(
        'stock.picking', 'intercompany_return_id', string='Return Pickings',
    )
    invoice_ids = fields.One2many(
        'account.move', 'intercompany_return_id', string='Return Invoices',
    )

    picking_count = fields.Integer(compute='_compute_counts')
    return_picking_count = fields.Integer(compute='_compute_counts')
    invoice_count = fields.Integer(compute='_compute_counts')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                seq_code = {
                    'sale': 'intercompany.return.sale',
                    'purchase': 'intercompany.return.purchase',
                }.get(vals.get('return_type', 'sale'), 'intercompany.return.sale')
                vals['name'] = self.env['ir.sequence'].next_by_code(seq_code) or _('New')
        return super().create(vals_list)

    @api.constrains('partner_id', 'company_id')
    def _check_partner_not_same_company(self):
        for rec in self:
            if not rec.partner_id or not rec.company_id:
                continue
            # Check if the partner is linked to the same company
            partner_company = self.env['res.company'].sudo().search([
                ('partner_id', '=', rec.partner_id.id)
            ], limit=1)
            if partner_company and partner_company == rec.company_id:
                raise UserError(_(
                    'The customer/vendor "%s" cannot be the same company as the one '
                    'processing this return (%s).\n'
                    'Intercompany returns must be between two different companies.'
                ) % (rec.partner_id.name, rec.company_id.name))

    @api.onchange('partner_id')
    def _onchange_partner_same_company_warning(self):
        if not self.partner_id:
            return
        partner_company = self.env['res.company'].sudo().search([
            ('partner_id', '=', self.partner_id.id)
        ], limit=1)
        current_company = self.env.company
        if partner_company and partner_company == current_company:
            return {
                'warning': {
                    'title': _('Invalid Partner'),
                    'message': _(
                        'The selected partner "%s" is the same company you are working in (%s).\n'
                        'Please select a partner from a different company.'
                    ) % (self.partner_id.name, current_company.name),
                }
            }

    @api.depends('return_type', 'sale_order_ids.company_id', 'purchase_order_ids.company_id',
                 'operation_id.company_ids', 'order_source')
    def _compute_company_id(self):
        for rec in self:
            if rec.order_source == 'operation' and rec.operation_id:
                rec.company_id = rec.operation_id.company_ids[:1]
            elif rec.return_type == 'sale' and rec.sale_order_ids:
                rec.company_id = rec.sale_order_ids[0].company_id
            elif rec.return_type == 'purchase' and rec.purchase_order_ids:
                rec.company_id = rec.purchase_order_ids[0].company_id
            else:
                rec.company_id = False

    def _get_source_orders(self):
        """Return all source orders (sale or purchase) for this return."""
        self.ensure_one()
        if self.order_source == 'operation' and self.operation_id:
            if self.return_type == 'sale':
                return self.operation_id.sale_order_ids
            else:
                return self.operation_id.purchase_order_ids
        else:
            if self.return_type == 'sale':
                return self.sale_order_ids
            else:
                return self.purchase_order_ids

    @api.depends('sale_order_ids.picking_ids', 'purchase_order_ids.picking_ids',
                 'operation_id', 'return_type', 'order_source')
    def _compute_order_picking_ids(self):
        for rec in self:
            orders = rec._get_source_orders() if rec.id else self.env['sale.order']
            all_pickings = self.env['stock.picking']
            for order in orders:
                all_pickings |= order.picking_ids.filtered(
                    lambda p: p.state == 'done'
                    and not p.is_return_replacement          # مش استبدال
                    and not p.intercompany_return_id         # مش return picking
                )
            rec.order_picking_ids = all_pickings

    @api.depends('order_picking_ids', 'order_picking_ids.move_ids', 'order_picking_ids.move_ids.state')
    def _compute_return_move_ids(self):
        for rec in self:
            rec.return_move_ids = rec.order_picking_ids.mapped('move_ids').filtered(
                lambda m: m.state == 'done'
            )

    def _compute_counts(self):
        for rec in self:
            rec.picking_count = len(rec.order_picking_ids)
            rec.return_picking_count = len(rec.return_picking_ids)
            rec.invoice_count = len(rec.invoice_ids)

    @api.onchange('return_type', 'partner_id', 'order_source')
    def _onchange_reset_orders(self):
        self.sale_order_ids = False
        self.purchase_order_ids = False
        self.operation_id = False

    # ── APPROVAL CYCLE ───────────────────────────────────────────────────────

    def _get_manager_users(self):
        return self.env['res.users'].search([
            ('groups_id', 'in', self.env.ref('intercompany_operation_modified.group_intercompany_manager').id),
        ])

    def _notify_managers_for_approval(self):
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        for rec in self:
            # Clean up any stale "To Do" activities left over from a previous
            # submit/refuse cycle, otherwise the same manager can end up with
            # more than one open activity on this record.
            if activity_type:
                stale = self.env['mail.activity'].search([
                    ('res_model', '=', rec._name),
                    ('res_id', '=', rec.id),
                    ('activity_type_id', '=', activity_type.id),
                ])
                stale.unlink()

            managers = rec._get_manager_users()
            if not managers:
                continue
            rec.message_post(
                body=_('%s submitted this return for approval.') % (rec.env.user.name),
                partner_ids=managers.mapped('partner_id').ids,
            )
            for manager in managers:
                rec.activity_schedule(
                    activity_type_id=activity_type.id if activity_type else False,
                    summary=_('Approval Required'),
                    note=_('%s is waiting for your approval.') % rec.display_name,
                    user_id=manager.id,
                )

    def _notify_submitter(self, message):
        for rec in self:
            if rec.submitted_by:
                rec.message_post(body=message, partner_ids=rec.submitted_by.partner_id.ids)
                activities = self.env['mail.activity'].search([
                    ('res_model', '=', rec._name),
                    ('res_id', '=', rec.id),
                    ('activity_type_id', '=', self.env.ref('mail.mail_activity_data_todo').id),
                    ('user_id', '=', self.env.user.id),
                ])
                for activity in activities:
                    activity.action_feedback()

    def action_open_reject_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject with Reason'),
            'res_model': 'intercompany.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': 'intercompany.return',
                'default_res_id': self.id,
            },
        }

    def _do_refuse(self, reason):
        self.ensure_one()
        if self.state not in ('approved', 'to_approve'):
            raise UserError(_('Only approved or submitted returns can be refused.'))
        self.reject_reason = reason
        self.state = 'refused'
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        if activity_type:
            self.env['mail.activity'].search([
                ('res_model', '=', self._name),
                ('res_id', '=', self.id),
                ('activity_type_id', '=', activity_type.id),
            ]).unlink()
        self.message_post(body=_('Refused by %s: %s') % (self.env.user.name, reason))
        self._notify_submitter(_('Your return %s was refused.\nReason: %s') % (self.display_name, reason))

    def action_refuse(self):
        """Manager only: refuse with reason."""
        return self.action_open_reject_wizard()

    def action_submit(self):
        """Submit the return for manager approval."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only draft returns can be submitted for approval.'))
        orders = self._get_source_orders()
        if not orders:
            raise UserError(_('Please select at least one order first.'))
        self.submitted_by = self.env.user
        self.reject_reason = False
        self.state = 'to_approve'
        self._notify_managers_for_approval()

    def action_approve(self):
        """Manager only: approve."""
        self.ensure_one()
        if self.state != 'to_approve':
            raise UserError(_('Only submitted returns can be approved.'))
        self.state = 'approved'
        self._notify_submitter(_('Your return %s was approved.') % self.display_name)

    def action_confirm(self):
        """After approval: confirm to unlock return wizard."""
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_('Please get the return approved first.'))
        if not self.order_picking_ids:
            raise UserError(_('There are no done stock pickings on the selected orders to return.'))
        self.state = 'confirmed'

    def action_draft(self):
        self.state = 'draft'
        self.reject_reason = False

    def action_cancel(self):
        """Manager only: cancel at any stage before done."""
        if self.state == 'done':
            raise UserError(_('Cannot cancel a completed return.'))
        self.state = 'cancelled'
        self.message_post(body=_('Cancelled by %s.') % self.env.user.name)

    # ── RETURN WIZARD ─────────────────────────────────────────────────────────

    def action_open_return_wizard(self):
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(_('Please confirm the return first.'))
        if not self.order_picking_ids:
            raise UserError(_('No pickings available to return.'))

        # Build flat move lines directly linked to wizard (not nested)
        flat_move_line_vals = []
        for picking in self.order_picking_ids:
            for m in picking.move_ids.filtered(lambda m: m.state == 'done'):
                returned = sum(
                    m.returned_move_ids.filtered(lambda r: r.state == 'done').mapped('quantity')
                )
                max_qty = max(0.0, m.quantity - returned)
                if max_qty <= 0:
                    continue  # skip fully returned moves
                flat_move_line_vals.append((0, 0, {
                    'picking_id': picking.id,
                    'move_id': m.id,
                    'product_id': m.product_id.id,
                    'original_qty': m.quantity,
                    'return_qty': max_qty,
                }))

        if not flat_move_line_vals:
            raise UserError(_('All products from these pickings have already been fully returned.'))

        wizard = self.env['intercompany.return.picking.wizard'].create({
            'return_id': self.id,
            'flat_move_line_ids': flat_move_line_vals,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Return Pickings'),
            'res_model': 'intercompany.return.picking.wizard',
            'view_mode': 'form',
            'target': 'new',
            'res_id': wizard.id,
        }

    def action_view_order_pickings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pickings'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.order_picking_ids.ids)],
        }

    def action_view_return_pickings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Return Pickings'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.return_picking_ids.ids)],
        }

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Return Invoices'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.invoice_ids.ids)],
        }

    # ── RETURN INVOICES ───────────────────────────────────────────────────────

    def _get_net_return_qty_by_product(self):
        """
        Returns a dict {product_id: net_returned_qty_in_base_uom}
        = returned qty - replaced qty (net amount that needs a credit note).
        """
        # 1. Returned qty (real returns only)
        return_pickings = self.return_picking_ids.filtered(
            lambda p: p.state == 'done' and not p.is_return_replacement
        )
        returned_base = {}
        for picking in return_pickings:
            for move in picking.move_ids.filtered(lambda m: m.state == 'done'):
                pid = move.product_id.id
                qty_base = move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)
                returned_base[pid] = returned_base.get(pid, 0.0) + qty_base

        # 2. Replaced qty (replacement pickings)
        replacement_pickings = self.return_picking_ids.filtered(
            lambda p: p.state == 'done' and p.is_return_replacement
        )
        replaced_base = {}
        for picking in replacement_pickings:
            for move in picking.move_ids.filtered(lambda m: m.state == 'done'):
                pid = move.product_id.id
                qty_base = move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)
                replaced_base[pid] = replaced_base.get(pid, 0.0) + qty_base

        # 3. Net = returned - replaced (only positive = needs credit note)
        net = {}
        for pid, ret_qty in returned_base.items():
            net_qty = ret_qty - replaced_base.get(pid, 0.0)
            if net_qty > 0.001:  # tolerance
                net[pid] = net_qty
        return net

    def _get_returned_qty_by_product(self):
        """
        Returns a dict {product_id: {'qty_base': float, 'uom': uom}}
        Only real return pickings, excluding replacements.
        """
        return_pickings = self.return_picking_ids.filtered(
            lambda p: p.state == 'done' and not p.is_return_replacement
        )
        returned_qty = {}
        for picking in return_pickings:
            for move in picking.move_ids.filtered(lambda m: m.state == 'done'):
                pid = move.product_id.id
                if pid not in returned_qty:
                    returned_qty[pid] = {'qty_base': 0.0, 'uom': move.product_uom}
                qty_base = move.product_uom._compute_quantity(move.quantity, move.product_id.uom_id)
                returned_qty[pid]['qty_base'] += qty_base
                returned_qty[pid]['uom'] = move.product_uom
        return returned_qty

    def _get_returned_qty_by_product_for_order(self, order):
        """
        Returns {product_id: net_returned_qty_in_base_uom} for a specific source order only.
        Matches return pickings to this order via ic_sale_order_id / ic_purchase_order_id
        or via origin_returned_move_id → picking → order link.
        """
        # Collect done pickings that belong to this specific order
        if hasattr(order, 'picking_ids'):
            order_pickings = order.picking_ids.filtered(lambda p: p.state == 'done')
        else:
            order_pickings = self.env['stock.picking']

        # Also include pickings linked via ic_ fields
        if order._name == 'sale.order':
            extra = self.env['stock.picking'].search([
                ('ic_sale_order_id', '=', order.id),
                ('state', '=', 'done'),
            ])
        else:
            extra = self.env['stock.picking'].search([
                ('ic_purchase_order_id', '=', order.id),
                ('state', '=', 'done'),
            ])
        order_pickings |= extra

        # Moves that were originally from this order's pickings
        order_move_ids = order_pickings.mapped('move_ids').filtered(
            lambda m: m.state == 'done'
        ).ids

        # Filter return_picking_ids to only those that returned moves from this order
        return_pickings = self.return_picking_ids.filtered(
            lambda p: p.state == 'done' and not p.is_return_replacement
        )
        replacement_pickings = self.return_picking_ids.filtered(
            lambda p: p.state == 'done' and p.is_return_replacement
        )

        returned_base = {}
        for picking in return_pickings:
            for move in picking.move_ids.filtered(lambda m: m.state == 'done'):
                origin_move = move.origin_returned_move_id
                if origin_move and origin_move.id in order_move_ids:
                    pid = move.product_id.id
                    qty_base = move.product_uom._compute_quantity(
                        move.quantity, move.product_id.uom_id
                    )
                    returned_base[pid] = returned_base.get(pid, 0.0) + qty_base

        replaced_base = {}
        for picking in replacement_pickings:
            for move in picking.move_ids.filtered(lambda m: m.state == 'done'):
                origin_move = move.origin_returned_move_id
                if origin_move and origin_move.id in order_move_ids:
                    pid = move.product_id.id
                    qty_base = move.product_uom._compute_quantity(
                        move.quantity, move.product_id.uom_id
                    )
                    replaced_base[pid] = replaced_base.get(pid, 0.0) + qty_base

        net = {}
        for pid, ret_qty in returned_base.items():
            net_qty = ret_qty - replaced_base.get(pid, 0.0)
            if net_qty > 0.001:
                net[pid] = net_qty
        return net

    def _create_credit_note_for_invoice(self, inv, returned_qty_by_product):
        """
        Create and post a credit note for `inv`, adjusting quantities to
        `returned_qty_by_product` {product_id: qty_in_base_uom}.
        Returns the new account.move or empty recordset.
        """
        reversal = self.env['account.move.reversal'].with_context(
            active_model='account.move', active_ids=inv.ids,
        ).create({
            'reason': _('Return %s') % self.name,
            'journal_id': inv.journal_id.id,
        })
        result = reversal.reverse_moves()

        new_move = self.env['account.move']
        if isinstance(result, dict):
            res_id = result.get('res_id')
            if res_id:
                new_move = self.env['account.move'].browse(res_id).filtered(
                    lambda m: m.state == 'draft'
                )
            if not new_move:
                domain = result.get('domain')
                if domain:
                    new_move = self.env['account.move'].search(
                        domain + [('state', '=', 'draft')]
                    )[:1]

        if not new_move:
            inv.invalidate_recordset()
            if hasattr(inv, 'reversal_move_ids'):
                new_move = inv.reversal_move_ids.filtered(lambda m: m.state == 'draft')[:1]
            elif hasattr(inv, 'reversal_move_id'):
                new_move = inv.reversal_move_id.filtered(lambda m: m.state == 'draft')[:1]

        if not new_move:
            return self.env['account.move']

        new_move.intercompany_return_id = self.id

        if new_move.state == 'draft':
            lines_to_remove = self.env['account.move.line']

            # Determine the correct tax type based on return_type
            # sale return → credit note → use 'sale' taxes
            # purchase return → vendor credit note → use 'purchase' taxes
            expected_tax_type = 'sale' if self.return_type == 'sale' else 'purchase'

            for line in new_move.invoice_line_ids:
                product = line.product_id
                if not product:
                    lines_to_remove |= line
                    continue
                net_base = returned_qty_by_product.get(product.id, 0.0)
                if net_base <= 0:
                    lines_to_remove |= line
                else:
                    invoice_uom = line.product_uom_id or product.uom_id
                    ret_qty_in_invoice_uom = product.uom_id._compute_quantity(
                        net_base, invoice_uom
                    )
                    # Fix taxes: filter to only the correct type (sale/purchase)
                    correct_taxes = line.tax_ids.filtered(
                        lambda t: t.type_tax_use == expected_tax_type
                    )
                    # If no taxes of correct type, fetch from product
                    if not correct_taxes and product:
                        if expected_tax_type == 'sale':
                            correct_taxes = product.taxes_id.filtered(
                                lambda t: t.type_tax_use == 'sale' and
                                t.company_id == new_move.company_id
                            )
                        else:
                            correct_taxes = product.supplier_taxes_id.filtered(
                                lambda t: t.type_tax_use == 'purchase' and
                                t.company_id == new_move.company_id
                            )
                    line.with_context(check_move_validity=False).write({
                        'quantity': ret_qty_in_invoice_uom,
                        'tax_ids': [(6, 0, correct_taxes.ids)],
                    })

            if lines_to_remove:
                lines_to_remove.unlink()

            if new_move.invoice_line_ids:
                new_move.action_post()
                return new_move
            else:
                new_move.button_cancel()
                new_move.unlink()

        return self.env['account.move']

    def action_create_return_invoices(self):
        """Create credit-note invoices for the actually returned quantities only.
        One credit note per original invoice, with quantities scoped to that
        invoice's source order — so two orders of 10 units each produce two
        credit notes of 10, not one credit note of 20.
        """
        self.ensure_one()
        if self.state != 'returned':
            raise UserError(_('Please process the stock return first.'))

        orders = self._get_source_orders()

        # Global check: is there anything net-returned at all?
        global_net_qty = self._get_net_return_qty_by_product()
        if not global_net_qty:
            self.state = 'done'
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Invoice Needed'),
                    'message': _('All returned products have been replaced. No credit note is required.'),
                    'type': 'success',
                }
            }

        new_moves = self.env['account.move']

        for order in orders:
            # Qty returned that belongs to THIS order only
            order_net_qty = self._get_returned_qty_by_product_for_order(order)
            if not order_net_qty:
                continue  # nothing returned from this order

            posted_invoices = order.invoice_ids.filtered(lambda m: m.state == 'posted')
            if not posted_invoices:
                continue

            for inv in posted_invoices:
                new_move = self._create_credit_note_for_invoice(inv, order_net_qty)
                if new_move:
                    new_moves |= new_move

        if not new_moves:
            raise UserError(_(
                'No invoice lines matched the returned products. '
                'Please check the return pickings.'
            ))

        self.state = 'done'
        return {
            'type': 'ir.actions.act_window',
            'name': _('Return Invoices'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', new_moves.ids)],
        }


# Extend stock.move so the return form can show, per product, how much is
# already returned and how much can still be returned — without opening the wizard.
class StockMove(models.Model):
    _inherit = 'stock.move'

    ic_already_returned_qty = fields.Float(
        string='Already Returned', compute='_compute_ic_return_info',
    )
    ic_max_return_qty = fields.Float(
        string='Max. Returnable', compute='_compute_ic_return_info',
    )

    def _compute_ic_return_info(self):
        for move in self:
            returned = sum(
                move.returned_move_ids.filtered(lambda m: m.state == 'done').mapped('quantity')
            )
            move.ic_already_returned_qty = returned
            move.ic_max_return_qty = max(0.0, move.quantity - returned)


# Extend stock.picking and account.move to link back to the return record
class StockPicking(models.Model):
    _inherit = 'stock.picking'

    intercompany_return_id = fields.Many2one(
        'intercompany.return', string='Intercompany Return', copy=False,
    )
    is_return_replacement = fields.Boolean(
        string='Is Return Replacement', default=False, copy=False,
    )
    # Fields to manually link replacement/return pickings to original orders
    # (because purchase_id/sale_id are computed from move lines and can't be set directly)
    ic_purchase_order_id = fields.Many2one(
        'purchase.order', string='Linked Purchase Order', copy=False, index=True,
    )
    ic_sale_order_id = fields.Many2one(
        'sale.order', string='Linked Sale Order', copy=False, index=True,
    )


class AccountMove(models.Model):
    _inherit = 'account.move'

    intercompany_return_id = fields.Many2one(
        'intercompany.return', string='Intercompany Return', copy=False,
    )


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    def _get_all_picking_ids(self):
        """Returns all pickings linked to this purchase order (original + returns), excluding empty drafts."""
        self.ensure_one()
        direct = self.picking_ids
        extra = self.env['stock.picking'].search([
            ('ic_purchase_order_id', '=', self.id),
            ('state', 'not in', ['draft', 'cancel']),
        ])
        all_picks = direct | extra
        # استبعاد الـ draft pickings الفاضية (مفيهاش moves)
        return all_picks.filtered(
            lambda p: p.state != 'draft' or p.move_ids
        )

    def _compute_picking(self):
        super()._compute_picking()
        for order in self:
            order.picking_count = len(order._get_all_picking_ids())

    def action_view_picking(self):
        result = super().action_view_picking()
        all_pickings = self._get_all_picking_ids()
        if 'domain' in result:
            result['domain'] = [('id', 'in', all_pickings.ids)]
        if len(all_pickings) == 1:
            result['res_id'] = all_pickings.id
            result['view_mode'] = 'form,list'
        elif len(all_pickings) > 1:
            result.pop('res_id', None)
            result['view_mode'] = 'list,form'
        return result


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _get_all_delivery_ids(self):
        """Returns all deliveries linked to this sale order (original + returns), excluding empty drafts."""
        self.ensure_one()
        direct = self.picking_ids
        extra = self.env['stock.picking'].search([
            ('ic_sale_order_id', '=', self.id),
            ('state', 'not in', ['draft', 'cancel']),
        ])
        all_picks = direct | extra
        # استبعاد الـ draft pickings الفاضية (مفيهاش moves)
        return all_picks.filtered(
            lambda p: p.state != 'draft' or p.move_ids
        )

    def _compute_picking_ids(self):
        super()._compute_picking_ids()
        for order in self:
            order.delivery_count = len(order._get_all_delivery_ids())

    def action_view_delivery(self):
        all_pickings = self._get_all_delivery_ids()
        action = self.env['ir.actions.act_window']._for_xml_id('stock.action_picking_tree_all')
        action['domain'] = [('id', 'in', all_pickings.ids)]
        action.pop('res_id', None)
        action['view_mode'] = 'list,form'
        action['views'] = [(False, 'list'), (False, 'form')]
        action['context'] = dict(self.env.context)
        return action
