# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

VENDOR_TYPE_SEQUENCE_CODE = {
    'local': 'purchase.order.local',
    'foreign': 'purchase.order.foreign',
    'service': 'purchase.order.service',
}


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    allowed_branch_ids = fields.Many2many(
        'res.branch', compute='_compute_allowed_branch_ids',
        string='Allowed Branches')

    branch_id = fields.Many2one(
        'res.branch', string='Branch', tracking=True, required=True,
        domain="[('id', 'in', allowed_branch_ids)]")

    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Warehouse',
        domain="[('company_id', '=', company_id), "
               "'|', ('branch_id', '=', False), ('branch_id', '=', branch_id)]")

    purchase_journal_id = fields.Many2one(
        'account.journal', string='Purchase Journal',
        domain="[('type', '=', 'purchase'), ('company_id', '=', company_id), "
               "'|', ('branch_id', '=', False), ('branch_id', '=', branch_id)]")

    branch_analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Analytic Account')

    vendor_type = fields.Selection(
        related='partner_id.vendor_type', string='Vendor Type',
        store=True, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vendor_type = False
                partner_id = vals.get('partner_id')
                if partner_id:
                    vendor_type = self.env['res.partner'].browse(partner_id).vendor_type
                seq_code = VENDOR_TYPE_SEQUENCE_CODE.get(vendor_type)
                if seq_code:
                    vals['name'] = self.env['ir.sequence'].next_by_code(seq_code) or _('New')
        return super().create(vals_list)

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
                if 'picking_type_id' in fields_list:
                    picking_type = self.env['stock.picking.type'].search([
                        ('code', '=', 'incoming'),
                        ('warehouse_id', '=', branch.warehouse_id.id),
                    ], limit=1)
                    if picking_type:
                        res['picking_type_id'] = picking_type.id
            if 'purchase_journal_id' in fields_list and branch.purchase_journal_id:
                res['purchase_journal_id'] = branch.purchase_journal_id.id
            if 'branch_analytic_account_id' in fields_list and branch.analytic_account_id:
                res['branch_analytic_account_id'] = branch.analytic_account_id.id
        return res

    @api.onchange('branch_id')
    def _onchange_branch_id(self):
        if self.branch_id:
            if self.branch_id.warehouse_id:
                self.warehouse_id = self.branch_id.warehouse_id
                picking_type = self.env['stock.picking.type'].search([
                    ('code', '=', 'incoming'),
                    ('warehouse_id', '=', self.branch_id.warehouse_id.id),
                ], limit=1)
                if picking_type:
                    self.picking_type_id = picking_type
            if self.branch_id.purchase_journal_id:
                self.purchase_journal_id = self.branch_id.purchase_journal_id
            if self.branch_id.analytic_account_id:
                self.branch_analytic_account_id = self.branch_id.analytic_account_id

    def _prepare_invoice(self):
        invoice_vals = super()._prepare_invoice()
        if self.purchase_journal_id:
            invoice_vals['journal_id'] = self.purchase_journal_id.id
        if self.branch_id:
            invoice_vals['branch_id'] = self.branch_id.id
        return invoice_vals

    def _create_picking(self):
        res = super()._create_picking()
        for order in self:
            if order.branch_id:
                # sudo(): this is an internal linkage write done automatically
                # right after the picking is created, not something the
                # confirming user explicitly requested. The "Restricted to
                # Allowed Branches" rule requires branch_id to already be set
                # and match the user's allowed branches BEFORE it lets them
                # write to the record - but the picking has no branch yet at
                # this point, so a non-sudo write would always be blocked by
                # the very rule it's trying to satisfy.
                #
                # No "not p.branch_id" filter here on purpose: the order's
                # own branch is the authoritative source and must win even
                # if the picking already picked up a (possibly different)
                # default branch from its warehouse.
                order.picking_ids.sudo().write({'branch_id': order.branch_id.id})
        return res

    def action_create_invoice(self):
        result = super().action_create_invoice()
        for order in self:
            vals = {}
            if order.branch_id and order.purchase_journal_id:
                vals['journal_id'] = order.purchase_journal_id.id
            if order.branch_id:
                vals['branch_id'] = order.branch_id.id
            if vals:
                order.invoice_ids.write(vals)
        return result

    def write(self, vals):
        if 'branch_id' in vals:
            for order in self:
                if order.state in ('purchase', 'done') and order.branch_id.id != vals['branch_id']:
                    raise UserError(_(
                        "You cannot change the Branch of %(name)s because it is "
                        "already confirmed. Set it to RFQ first.", name=order.name))
        return super().write(vals)


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            branch_account = line.order_id.branch_analytic_account_id
            if branch_account and not line.analytic_distribution:
                line.analytic_distribution = {str(branch_account.id): 100}
        return lines
