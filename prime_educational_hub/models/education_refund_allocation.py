# -*- coding: utf-8 -*-
from odoo import fields, models


class EducationRefundAllocation(models.Model):
    _name = 'education.refund.allocation'
    _description = 'Refund to Payment-Allocation Reversal (technical)'
    _order = 'refund_id, allocation_id'

    refund_id = fields.Many2one('education.refund', string='Refund', required=True, ondelete='cascade')
    allocation_id = fields.Many2one('education.payment.allocation', string='Original Allocation',
                                     required=True, ondelete='restrict')
    amount = fields.Monetary(string='Reversed Amount', required=True, currency_field='currency_id')
    currency_id = fields.Many2one(related='refund_id.currency_id', string='Currency', store=True)
    company_id = fields.Many2one(related='refund_id.company_id', string='Company', store=True)
