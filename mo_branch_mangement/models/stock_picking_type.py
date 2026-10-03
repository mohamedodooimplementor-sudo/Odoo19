# -*- coding: utf-8 -*-
from odoo import fields, models


class StockPickingType(models.Model):
    _inherit = 'stock.picking.type'

    branch_id = fields.Many2one(
        'res.branch', string='Branch', related='warehouse_id.branch_id',
        store=True, readonly=True,
        help='Branch of this Operation Type\'s Warehouse. Used to hide '
             "Operation Types (and therefore the ability to create/see "
             "Receipts, Deliveries, Internal Transfers...) belonging to a "
             "warehouse of another branch from a branch-restricted user.")
