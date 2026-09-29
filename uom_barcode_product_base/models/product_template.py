# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    uom_barcode_ids = fields.One2many(
        'product.uom.barcode',
        'product_tmpl_id',
        string='UoM Barcodes',
    )

    def action_print_uom_barcodes(self):
        self.ensure_one()
        return self.env.ref(
            'uom_barcode_product_base.action_report_product_uom_barcode'
        ).report_action(self)


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def get_uom_barcode(self, uom_id):
        """Get barcode for this product variant with given UoM."""
        barcode_rec = self.env['product.uom.barcode'].search([
            ('product_tmpl_id', '=', self.product_tmpl_id.id),
            ('uom_id', '=', uom_id),
        ], limit=1)
        return barcode_rec.barcode if barcode_rec else False
