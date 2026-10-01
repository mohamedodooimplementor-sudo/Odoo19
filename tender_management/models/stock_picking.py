# -*- coding: utf-8 -*-
from odoo import fields, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    tm_tender_id = fields.Many2one('tm.tender', string='Tender', compute='_compute_tm_tender_id')

    def _compute_tm_tender_id(self):
        for picking in self:
            picking.tm_tender_id = picking.sudo().sale_id.tender_id

    def action_view_tm_tender(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'tm.tender',
            'res_id': self.tm_tender_id.id,
            'view_mode': 'form',
        }

    def _action_done(self):
        res = super()._action_done()
        tenders = self.sudo().mapped('sale_id.tender_id')
        if tenders:
            tenders._tm_sync_fulfillment()
        return res
