# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    er_epo_id = fields.Many2one('employee.purchase.order', string='Employee Purchase Order',
                                copy=False, index=True, readonly=True)


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    er_po_line_id = fields.Many2one('employee.purchase.order.line',
                                    string='Employee PO Line', copy=False, index=True)


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
