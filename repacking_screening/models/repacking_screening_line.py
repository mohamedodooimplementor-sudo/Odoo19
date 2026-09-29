# -*- coding: utf-8 -*-
from odoo import api, fields, models


class RepackingScreeningLine(models.Model):
    _name = 'repacking.screening.line'
    _description = 'Repacking & Screening Result Line'
    _order = 'sequence, id'

    operation_id = fields.Many2one(
        'repacking.screening.operation', string='Operation',
        required=True, ondelete='cascade')
    sequence = fields.Integer(string='#', default=10)

    operation_type = fields.Selection(
        related='operation_id.operation_type', store=True, readonly=True)

    product_id = fields.Many2one(
        'product.product', string='Product / Package', required=True,
        domain="[]")

    line_type = fields.Selection([
        ('good', 'Good'),
        ('waste', 'Waste'),
    ], string='Type', default='good',
        help='Used for Screening lines to classify the result as Good product or Waste.')

    uom_id = fields.Many2one(
        'uom.uom', string='UoM', required=True,
        default=lambda self: self.env.ref('uom.product_uom_kgm', raise_if_not_found=False))

    quantity = fields.Float(string='Quantity', required=True, digits='Product Unit of Measure')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id
