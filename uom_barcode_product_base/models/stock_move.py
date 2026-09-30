# -*- coding: utf-8 -*-
from odoo import models, fields, api


class StockPicking(models.Model):
    _inherit = 'stock.picking'

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

            existing = self.move_ids_without_package.filtered(
                lambda m: m.product_id == product and m.product_uom == uom
            )
            if existing:
                existing[0].product_uom_qty += 1
            else:
                self.move_ids_without_package = [(0, 0, {
                    'name': product.name,
                    'product_id': product.id,
                    'product_uom': uom.id,
                    'product_uom_qty': 1,
                    'location_id': self.location_id.id,
                    'location_dest_id': self.location_dest_id.id,
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


class StockMove(models.Model):
    _inherit = 'stock.move'

    uom_barcode = fields.Char(
        string='Barcode (UoM)',
        store=True,
        copy=True,
    )

    def _get_uom_barcode_value(self):
        """جيب الباركود من جدول product.uom.barcode."""
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
        moves = super().create(vals_list)
        for move in moves:
            if not move.uom_barcode:
                move.uom_barcode = move._get_uom_barcode_value()
        return moves

    def write(self, vals):
        res = super().write(vals)
        if 'product_id' in vals or 'product_uom' in vals:
            for move in self:
                move.uom_barcode = move._get_uom_barcode_value()
        return res

    def _sync_move_line_barcodes(self):
        """بعد ما الـ move lines تتولد، حط فيها الباركود."""
        for move in self:
            if move.uom_barcode and move.move_line_ids:
                move.move_line_ids.filtered(
                    lambda l: not l.uom_barcode
                ).write({'uom_barcode': move.uom_barcode})

    def _action_assign(self):
        """Override لضمان نقل الباركود للـ move lines بعد الـ reservation."""
        res = super()._action_assign()
        self._sync_move_line_barcodes()
        return res


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    uom_barcode = fields.Char(
        string='Barcode (UoM)',
        store=True,
        copy=True,
    )

    def _get_uom_barcode_value(self):
        self.ensure_one()
        if self.move_id and self.move_id.uom_barcode:
            return self.move_id.uom_barcode
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
                line.uom_barcode = line._get_uom_barcode_value()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if 'product_id' in vals or 'product_uom_id' in vals or 'move_id' in vals:
            for line in self:
                line.uom_barcode = line._get_uom_barcode_value()
        return res
