# -*- coding: utf-8 -*-
from odoo import models, fields, api


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    uom_barcode = fields.Char(
        string='Barcode (UoM)',
        store=True,
        copy=True,
    )

    def _get_uom_barcode(self):
        self.ensure_one()
        if not self.product_id or not self.product_uom_id:
            return False
        rec = self.env['product.uom.barcode'].search([
            ('product_tmpl_id', '=', self.product_id.product_tmpl_id.id),
            ('uom_id', '=', self.product_uom_id.id),
        ], limit=1)
        return rec.barcode if rec else False

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            if not line.uom_barcode:
                line.uom_barcode = line._get_uom_barcode()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if 'product_id' in vals or 'product_uom_id' in vals:
            for line in self:
                line.uom_barcode = line._get_uom_barcode()
        return res
