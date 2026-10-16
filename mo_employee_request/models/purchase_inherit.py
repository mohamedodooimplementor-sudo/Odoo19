# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    er_epo_id = fields.Many2one('employee.purchase.order', string='Employee Purchase Order',
                                copy=False, index=True, readonly=True)
    # location the purchase is received into (the project's location)
    er_location_id = fields.Many2one('stock.location', string='Receive In Location',
                                     copy=False, index=True)

    def _get_destination_location(self):
        self.ensure_one()
        if self.er_location_id:
            return self.er_location_id.id
        return super()._get_destination_location()


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    er_po_line_id = fields.Many2one('employee.purchase.order.line',
                                    string='Employee PO Line', copy=False, index=True)
    er_location_id = fields.Many2one('stock.location', string='Receive In Location',
                                     copy=False)

    def _prepare_stock_move_vals(self, *args, **kwargs):
        # carry the analytic distribution of the PO line to the receipt's stock move
        vals = super()._prepare_stock_move_vals(*args, **kwargs)
        if self.analytic_distribution:
            vals['analytic_distribution'] = self.analytic_distribution
        # receive into the location of the line (the project's location)
        location = self.er_location_id or self.order_id.er_location_id
        if location:
            vals['location_dest_id'] = location.id
            if 'location_final_id' in self.env['stock.move']._fields:
                vals['location_final_id'] = location.id
        return vals


class AccountMove(models.Model):
    _inherit = 'account.move'

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        epos = moves.sudo().invoice_line_ids.purchase_line_id.er_po_line_id.order_id
        if epos:
            epos._refresh_state()
        return moves

    def action_post(self):
        res = super().action_post()
        epos = self.sudo().invoice_line_ids.purchase_line_id.er_po_line_id.order_id
        if epos:
            epos._refresh_state()
        return res

    def button_cancel(self):
        res = super().button_cancel()
        epos = self.sudo().invoice_line_ids.purchase_line_id.er_po_line_id.order_id
        if epos:
            epos._refresh_state()
        return res
