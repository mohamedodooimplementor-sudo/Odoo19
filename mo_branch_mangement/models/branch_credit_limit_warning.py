# -*- coding: utf-8 -*-
from odoo import fields, models


class BranchCreditLimitWarning(models.TransientModel):
    _name = 'branch.credit.limit.warning'
    _description = 'Credit Limit Exceeded Warning'

    order_id = fields.Many2one('sale.order', string='Sales Order', required=True)
    partner_id = fields.Many2one(related='order_id.partner_id', string='Customer', readonly=True)
    branch_id = fields.Many2one(related='order_id.branch_id', string='Branch', readonly=True)
    currency_id = fields.Many2one(related='order_id.currency_id', readonly=True)

    customer_limit = fields.Monetary(string='Credit Limit (Customer)', readonly=True)
    customer_exposure = fields.Monetary(string='Exposure (Customer)', readonly=True)
    branch_limit = fields.Monetary(string='Credit Limit (Branch)', readonly=True)
    branch_exposure = fields.Monetary(string='Exposure (Branch)', readonly=True)

    def action_proceed(self):
        self.ensure_one()
        self.order_id.with_context(bypass_credit_limit=True).action_confirm()
        return {'type': 'ir.actions.act_window_close'}
