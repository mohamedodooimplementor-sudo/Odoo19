# -*- coding: utf-8 -*-
from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    tender_id = fields.Many2one(
        'tm.tender', string='Tender', copy=False, readonly=True, index=True, ondelete='set null')

    def action_view_tm_tender(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'tm.tender',
            'res_id': self.tender_id.id,
            'view_mode': 'form',
        }
