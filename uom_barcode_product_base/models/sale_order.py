# -*- coding: utf-8 -*-
from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    barcode_scan_input = fields.Char(
        string='Scan Barcode',
        store=False,
        help='Scan barcode to add product with correct UoM',
    )

    @api.onchange('barcode_scan_input')
    def _onchange_barcode_scan_input(self):
        if not self.barcode_scan_input:
            return

        barcode = self.barcode_scan_input.strip()
        uom_barcode_rec = self.env['product.uom.barcode'].search([
            ('barcode', '=', barcode),
            ('active', '=', True),
        ], limit=1)

        if uom_barcode_rec:
            product = uom_barcode_rec.product_tmpl_id.product_variant_ids[:1]
            uom = uom_barcode_rec.uom_id

            existing_line = self.order_line.filtered(
                lambda l: l.product_id == product and l.product_uom == uom
            )
            if existing_line:
                existing_line[0].product_uom_qty += 1
            else:
                self.order_line = [(0, 0, {
                    'product_id': product.id,
                    'product_uom': uom.id,
                    'product_uom_qty': 1,
                    'uom_barcode': barcode,
                })]

            self.barcode_scan_input = False
            return {
                'warning': {
                    'title': 'Done',
                    'message': f'Added {product.name} - {uom.name}',
                }
            }
        else:
            return {
                'warning': {
                    'title': 'Barcode Not Found',
                    'message': f'No product found with barcode: {barcode}',
                }
            }

    def action_confirm(self):
        """بعد تأكيد الأمر وإنشاء الـ moves، انقل الباركود لكل move."""
        res = super().action_confirm()
        for order in self:
            for line in order.order_line:
                if line.uom_barcode:
                    # ابحث عن الـ stock moves المرتبطة بالسطر ده
                    moves = line.move_ids.filtered(
                        lambda m: m.state not in ('done', 'cancel')
                    )
                    moves.write({'uom_barcode': line.uom_barcode})
        return res


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    uom_barcode = fields.Char(
        string='Barcode (UoM)',
        store=True,
        copy=True,
    )

    def _get_uom_barcode_value(self):
        self.ensure_one()
        if not self.product_id or not self.product_uom:
            return False
        rec = self.env['product.uom.barcode'].search([
            ('product_tmpl_id', '=', self.product_id.product_tmpl_id.id),
            ('uom_id', '=', self.product_uom.id),
        ], limit=1)
        return rec.barcode if rec else False

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            if not line.uom_barcode:
                line.uom_barcode = line._get_uom_barcode_value()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if 'product_id' in vals or 'product_uom' in vals:
            for line in self:
                line.uom_barcode = line._get_uom_barcode_value()
        return res
