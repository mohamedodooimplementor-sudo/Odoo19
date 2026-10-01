# -*- coding: utf-8 -*-
from odoo import _, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    tender_id = fields.Many2one(
        'tm.tender', string='Tender', copy=False, readonly=True, index=True, ondelete='set null')

    def action_confirm(self):
        res = super().action_confirm()
        for tender in self.mapped('tender_id').filtered(lambda t: t.state in ('approved', 'quotation')):
            tender.write({'state': 'won'})
            tender.message_post(body=_('Tender marked as Won: the quotation was confirmed.'))
        return res

    def action_view_tender(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'tm.tender',
            'res_id': self.tender_id.id,
            'view_mode': 'form',
        }
