# -*- coding: utf-8 -*-
from odoo import api, models


class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    @api.model_create_multi
    def create(self, vals_list):
        partials = super().create(vals_list)
        moves = (partials.debit_move_id.move_id | partials.credit_move_id.move_id).sudo()
        orders = moves.filtered(lambda m: m.move_type == 'out_invoice') \
            .invoice_line_ids.sale_line_ids.order_id
        tenders = orders.tender_id
        if tenders:
            tenders._tm_sync_fulfillment()
        return partials
