# -*- coding: utf-8 -*-
from odoo import api, fields, models


class RepackingPackagingLine(models.Model):
    _name = 'repacking.packaging.line'
    _description = 'Repacking Packaging Material Line'
    _order = 'sequence, id'

    operation_id = fields.Many2one(
        'repacking.screening.operation', required=True, ondelete='cascade')
    sequence = fields.Integer(string='#', default=10)

    product_id = fields.Many2one(
        'product.product', string='Packaging Material', required=True)
    uom_id = fields.Many2one(
        'uom.uom', string='UoM', required=True)
    quantity = fields.Float(
        string='Quantity', required=True, digits='Product Unit of Measure')

    location_id = fields.Many2one(
        'stock.location', string='Withdraw From',
        domain="[('usage','=','internal')]",
        help='Warehouse/location this packaging material is withdrawn (pulled) '
             'from. Leave empty to use the operation\'s Source Location.')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id
