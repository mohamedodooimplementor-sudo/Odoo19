# -*- coding: utf-8 -*-
from odoo import models, fields, _


class ChangeOrderRejectWizard(models.TransientModel):
    _name = 'construction.change.order.reject.wizard'
    _description = 'Reject Change Order Wizard'

    change_order_id  = fields.Many2one('construction.change.order', string='Change Order')
    rejection_reason = fields.Text(string='Rejection Reason', required=True)

    def action_confirm_reject(self):
        self.ensure_one()
        self.change_order_id.write({'state': 'rejected', 'rejection_reason': self.rejection_reason})
        self.change_order_id.message_post(
            body=_('Change Order rejected. Reason: %s') % self.rejection_reason,
            subtype_xmlid='mail.mt_note',
        )
