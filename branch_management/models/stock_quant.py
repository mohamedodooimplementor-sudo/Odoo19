# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    branch_id = fields.Many2one(
        'res.branch', string='Branch', related='warehouse_id.branch_id',
        store=True, index=True,
        help='Branch of this quant\'s Warehouse (via its Location). Used '
             'to isolate Physical Inventory / Inventory Adjustments per '
             'branch, and to default the Physical Inventory screen to the '
             "current user's own Branch.")

    @api.model
    def action_view_inventory(self):
        # Odoo builds this action dynamically (it isn't a plain
        # ir.actions.act_window record we could inherit through XML), so
        # the only way to default the "Physical Inventory" screen to the
        # current user's Branch is to extend the action dict here.
        action = super().action_view_inventory()
        branch = self.env.user.branch_id
        if branch:
            action.setdefault('context', {})
            # Many2one search defaults just need the record id: Odoo
            # applies it as [('branch_id', '=', value)] automatically.
            action['context']['search_default_branch_id'] = branch.id
        return action
