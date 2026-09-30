# -*- coding: utf-8 -*-
from odoo import fields, models


class EducationPaymentAllocation(models.Model):
    _name = 'education.payment.allocation'
    _description = 'Payment to Installment Allocation (technical)'
    _order = 'payment_id, installment_id'

    payment_id = fields.Many2one('education.payment', string='Payment', required=True, ondelete='cascade')
    installment_id = fields.Many2one('education.installment', string='Installment', required=True, ondelete='cascade')
    amount = fields.Monetary(string='Allocated Amount', required=True, currency_field='currency_id')
    refunded_amount = fields.Monetary(string='Refunded Amount', default=0.0, currency_field='currency_id',
                                       help='How much of this allocation has already been reversed by a refund.')
    currency_id = fields.Many2one(related='payment_id.currency_id', string='Currency', store=True)
    company_id = fields.Many2one(related='payment_id.company_id', string='Company', store=True)
