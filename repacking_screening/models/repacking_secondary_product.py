# -*- coding: utf-8 -*-
from odoo import api, fields, models


class RepackingSecondaryProduct(models.Model):
    _name = 'repacking.secondary.product'
    _description = 'Repacking Secondary / Byproduct Line'
    _order = 'sequence, id'

    operation_id = fields.Many2one(
        'repacking.screening.operation', required=True, ondelete='cascade')
    sequence = fields.Integer(string='#', default=10)

    product_id = fields.Many2one(
        'product.product', string='Secondary Product', required=True)
    uom_id = fields.Many2one(
        'uom.uom', string='UoM', required=True)
    quantity = fields.Float(
        string='Quantity', required=True, digits='Product Unit of Measure')
    cost_percentage = fields.Float(
        string='Cost %', digits=(6, 2),
        help='Percentage of total production cost (input + packaging) '
             'allocated to this secondary product.')

    location_id = fields.Many2one(
        'stock.location', string='Store In',
        domain="[('usage','=','internal')]",
        help='Warehouse/location this secondary/byproduct is stored (added) to '
             'once produced. Leave empty to use the operation\'s '
             'Manufacturing Location.')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id
