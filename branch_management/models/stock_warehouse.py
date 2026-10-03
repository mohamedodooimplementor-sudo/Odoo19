# -*- coding: utf-8 -*-
from odoo import fields, models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    branch_id = fields.Many2one(
        'res.branch', string='Branch',
        compute='_compute_branch_id', inverse='_inverse_branch_id',
        search='_search_branch_id', store=True,
        help='The Branch this warehouse belongs to. Kept in sync with the '
             "Branch's own Warehouse field (setting either one updates "
             'the other).')

    def _compute_branch_id(self):
        for warehouse in self:
            warehouse.branch_id = self.env['res.branch'].search(
                [('warehouse_id', '=', warehouse.id)], limit=1)

    def _inverse_branch_id(self):
        for warehouse in self:
            previous_branch = self.env['res.branch'].search(
                [('warehouse_id', '=', warehouse.id)], limit=1)
            if previous_branch and previous_branch != warehouse.branch_id:
                previous_branch.warehouse_id = False
            if warehouse.branch_id:
                warehouse.branch_id.warehouse_id = warehouse.id

    def _search_branch_id(self, operator, value):
        branches = self.env['res.branch'].search([('warehouse_id', operator, value)])
        return [('id', 'in', branches.mapped('warehouse_id').ids)]
