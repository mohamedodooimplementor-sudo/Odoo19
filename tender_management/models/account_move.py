# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    tm_tender_id = fields.Many2one('tm.tender', string='Tender', compute='_compute_tm_tender_id')

    def _compute_tm_tender_id(self):
        for move in self:
            orders = move.sudo().invoice_line_ids.sale_line_ids.order_id
            move.tm_tender_id = orders.tender_id[:1]

    def action_view_tm_tender(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'tm.tender',
            'res_id': self.tm_tender_id.id,
            'view_mode': 'form',
        }

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        orders = posted.sudo().filtered(lambda m: m.move_type == 'out_invoice') \
            .invoice_line_ids.sale_line_ids.order_id
        tenders = orders.tender_id
        if tenders:
            tenders._tm_sync_fulfillment()
        return posted
