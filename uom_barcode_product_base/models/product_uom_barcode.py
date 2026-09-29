# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ProductUomBarcode(models.Model):
    _name = 'product.uom.barcode'
    _description = 'Product UoM Barcode'
    _rec_name = 'barcode'

    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
        ondelete='cascade',
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product Variant',
        ondelete='cascade',
        index=True,
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        required=True,
        ondelete='restrict',
    )
    uom_category_id = fields.Many2one(
        related='uom_id.category_id',
        string='UoM Category',
        store=True,
    )
    barcode = fields.Char(
        string='Barcode',
        required=True,
        copy=False,
        index=True,
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            'unique_product_uom_barcode',
            'UNIQUE(product_tmpl_id, uom_id)',
            'A barcode already exists for this product and unit of measure combination!'
        ),
        (
            'unique_barcode',
            'UNIQUE(barcode)',
            'This barcode already exists! Please use a unique barcode.'
        ),
    ]

    @api.constrains('uom_id', 'product_tmpl_id')
    def _check_uom_category(self):
        for rec in self:
            if rec.product_tmpl_id and rec.uom_id:
                product_uom_category = rec.product_tmpl_id.uom_id.category_id
                if rec.uom_id.category_id != product_uom_category:
                    raise ValidationError(_(
                        'The unit of measure "%s" must belong to the same category '
                        'as the product\'s unit of measure "%s".'
                    ) % (rec.uom_id.name, rec.product_tmpl_id.uom_id.name))

    def get_barcode_by_uom(self, product_id, uom_id):
        """Helper method to get barcode for a specific product/uom combination."""
        record = self.search([
            ('product_tmpl_id', '=', product_id),
            ('uom_id', '=', uom_id),
        ], limit=1)
        return record.barcode if record else False
