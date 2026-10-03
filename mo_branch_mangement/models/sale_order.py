# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    allowed_branch_ids = fields.Many2many(
        'res.branch', compute='_compute_allowed_branch_ids',
        string='Allowed Branches')

    branch_id = fields.Many2one(
        'res.branch', string='Branch', tracking=True, required=True,
        domain="[('id', 'in', allowed_branch_ids)]")

    sale_journal_id = fields.Many2one(
        'account.journal', string='Sales Journal',
        domain="[('type', '=', 'sale'), ('company_id', '=', company_id), "
               "'|', ('branch_id', '=', False), ('branch_id', '=', branch_id)]")

    branch_analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Analytic Account')

    credit_limit_message = fields.Text(compute='_compute_credit_limit_message')
    credit_limit_exceeded = fields.Boolean(compute='_compute_credit_limit_message')

    @api.depends('partner_id', 'branch_id', 'amount_total')
    def _compute_credit_limit_message(self):
        for order in self:
            message = False
            exceeded = False
            if order.branch_id or order.partner_id:
                data = order._get_credit_limit_data()
                # Branch checked first: if the branch itself is over its limit,
                # that's shown regardless of the customer's own standing.
                if order.branch_id and data['branch_limit'] and (
                        data['branch_exposure'] + order.amount_total) > data['branch_limit']:
                    message = _(
                        "Branch '%(branch)s' has exceeded its credit limit: "
                        "current exposure %(exposure)s, limit %(limit)s.",
                        branch=order.branch_id.name,
                        exposure=data['branch_exposure'],
                        limit=data['branch_limit'])
                    exceeded = True
                elif data['customer_limit'] and (
                        data['customer_exposure'] + order.amount_total) > data['customer_limit']:
                    message = _(
                        "Customer '%(partner)s' has exceeded their credit limit: "
                        "current balance due %(exposure)s, limit %(limit)s.",
                        partner=order.partner_id.name,
                        exposure=data['customer_exposure'],
                        limit=data['customer_limit'])
                    exceeded = True
            order.credit_limit_message = message
            order.credit_limit_exceeded = exceeded

    @api.depends_context('uid')
    def _compute_allowed_branch_ids(self):
        allowed = self.env.user.get_allowed_branches()
        for order in self:
            order.allowed_branch_ids = allowed

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        branch = self.env.user.branch_id
        if branch and 'branch_id' in fields_list and not res.get('branch_id'):
            res['branch_id'] = branch.id
            if 'warehouse_id' in fields_list and branch.warehouse_id:
                res['warehouse_id'] = branch.warehouse_id.id
            if 'sale_journal_id' in fields_list and branch.sale_journal_id:
                res['sale_journal_id'] = branch.sale_journal_id.id
            if 'branch_analytic_account_id' in fields_list and branch.analytic_account_id:
                res['branch_analytic_account_id'] = branch.analytic_account_id.id
        return res

    @api.onchange('branch_id')
    def _onchange_branch_id(self):
        if self.branch_id:
            if self.branch_id.warehouse_id:
                self.warehouse_id = self.branch_id.warehouse_id
            if self.branch_id.sale_journal_id:
                self.sale_journal_id = self.branch_id.sale_journal_id
            if self.branch_id.analytic_account_id:
                self.branch_analytic_account_id = self.branch_id.analytic_account_id

    def write(self, vals):
        if 'branch_id' in vals:
            for order in self:
                if order.state in ('sale', 'done') and order.branch_id.id != vals['branch_id']:
                    raise UserError(_(
                        "You cannot change the Branch of %(name)s because it is "
                        "already confirmed. Set it to quotation first.", name=order.name))
        return super().write(vals)

    def _action_launch_stock_rule(self, previous_product_uom_qty=False):
        res = super()._action_launch_stock_rule(previous_product_uom_qty=previous_product_uom_qty)
        for order in self:
            if order.branch_id:
                # sudo(): see purchase_order.py's _create_picking for why
                # this needs sudo (chicken-and-egg with the branch rule) and
                # why there's no "not p.branch_id" filter (the order's own
                # branch is authoritative, overriding the warehouse-based
                # default the picking may already have).
                order.picking_ids.sudo().write({'branch_id': order.branch_id.id})
        return res

    def _prepare_invoice(self):
        invoice_vals = super()._prepare_invoice()
        if self.sale_journal_id:
            invoice_vals['journal_id'] = self.sale_journal_id.id
        if self.branch_id:
            invoice_vals['branch_id'] = self.branch_id.id
        return invoice_vals

    def _create_invoices(self, grouped=False, final=False, date=None):
        moves = super()._create_invoices(grouped=grouped, final=final, date=date)
        for order in self:
            vals = {}
            if order.branch_id and order.sale_journal_id:
                vals['journal_id'] = order.sale_journal_id.id
            if order.branch_id:
                vals['branch_id'] = order.branch_id.id
            if vals:
                invoices = order.invoice_ids.filtered(lambda m: m.id in moves.ids)
                invoices.write(vals)
        return moves

    # ------------------------------------------------------------------
    # Credit limit check (customer + branch level)
    # ------------------------------------------------------------------
    def _get_credit_limit_data(self):
        self.ensure_one()
        partner = self.partner_id.commercial_partner_id
        branch = self.branch_id

        # Confirmed orders not yet (fully) invoiced don't show up in posted
        # invoice residuals, but they still represent a real commitment, so
        # count them too - otherwise a customer/branch could stack several
        # large un-invoiced orders and blow past the limit unnoticed.
        pending_domain = [
            ('state', 'in', ('sale', 'done')),
            ('invoice_status', 'not in', ('invoiced', 'upselling')),
            ('id', '!=', self.id),
        ]
        branch_pending = 0.0
        if branch:
            branch_orders = self.env['sale.order'].search(
                pending_domain + [('branch_id', '=', branch.id)])
            branch_pending = sum(branch_orders.mapped('amount_total'))

        customer_pending = 0.0
        if partner:
            customer_orders = self.env['sale.order'].search(
                pending_domain + [('partner_id', '=', self.partner_id.id)])
            customer_pending = sum(customer_orders.mapped('amount_total'))

        return {
            'customer_limit': 0.0 if partner.no_credit_limit else partner.partner_credit_limit,
            'customer_exposure': partner.credit + customer_pending,
            'branch_limit': 0.0 if (not branch or branch.no_credit_limit) else branch.credit_limit,
            'branch_exposure': (branch.branch_exposure if branch else 0.0) + branch_pending,
        }

    def _is_credit_limit_exceeded(self, data):
        self.ensure_one()
        if self.branch_id and data['branch_limit'] and (
                data['branch_exposure'] + self.amount_total) > data['branch_limit']:
            return True
        if data['customer_limit'] and (
                data['customer_exposure'] + self.amount_total) > data['customer_limit']:
            return True
        return False

    def action_confirm(self):
        if len(self) == 1 and not self.env.context.get('bypass_credit_limit'):
            data = self._get_credit_limit_data()
            if self._is_credit_limit_exceeded(data):
                return {
                    'name': 'Credit Limit Exceeded',
                    'type': 'ir.actions.act_window',
                    'res_model': 'branch.credit.limit.warning',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {
                        'default_order_id': self.id,
                        'default_customer_limit': data['customer_limit'],
                        'default_customer_exposure': data['customer_exposure'],
                        'default_branch_limit': data['branch_limit'],
                        'default_branch_exposure': data['branch_exposure'],
                    },
                }
        return super().action_confirm()


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            branch_account = line.order_id.branch_analytic_account_id
            if branch_account and not line.analytic_distribution:
                line.analytic_distribution = {str(branch_account.id): 100}
        return lines
