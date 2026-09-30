# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .education_config_helpers import get_default_currency, get_default_discount


class EducationFeePlan(models.Model):
    _name = 'education.fee.plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Fee Plan'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    subject_id = fields.Many2one('education.subject', string='Subject')
    group_id = fields.Many2one('education.group', string='Default For Group')
    billing_type = fields.Selection([
        ('lump_sum', 'Lump Sum / Installments'),
        ('per_session', 'Per Session (Session Package)'),
    ], string='Billing Type', default='lump_sum', required=True,
        help='Per Session: the student pays for a package of a fixed number of sessions at a '
             'fixed price each; as they attend, the system tracks sessions/amount consumed.')
    session_count = fields.Integer(string='Number of Sessions',
                                    help='Total sessions included in the package (Per Session billing only).')
    price_per_session = fields.Monetary(string='Price per Session', currency_field='currency_id',
                                         help='Price of a single session (Per Session billing only).')
    amount = fields.Monetary(string='Amount', required=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency',
                                   default=lambda self: get_default_currency(self.env))
    discount_policy = fields.Selection([
        ('none', 'No Discount'),
        ('fixed', 'Fixed Amount'),
        ('percent', 'Percentage'),
    ], string='Default Discount Policy', default=lambda self: get_default_discount(self.env)[0], required=True)
    discount_value = fields.Float(string='Default Discount Value',
                                   default=lambda self: get_default_discount(self.env)[1])
    installment_count = fields.Integer(string='Number of Installments', default=1)
    frequency = fields.Selection([
        ('one_time', 'One Time'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('termly', 'Termly (every 3 months)'),
    ], string='Installment Frequency', default='one_time', required=True)
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.onchange('billing_type', 'session_count', 'price_per_session')
    def _onchange_session_billing(self):
        if self.billing_type == 'per_session':
            self.amount = (self.session_count or 0) * (self.price_per_session or 0.0)

    @api.constrains('billing_type', 'session_count', 'price_per_session')
    def _check_session_billing(self):
        for rec in self:
            if rec.billing_type == 'per_session' and (rec.session_count <= 0 or rec.price_per_session <= 0):
                raise ValidationError(_(
                    'Fee Plan "%s": Number of Sessions and Price per Session must both be positive '
                    'for Per Session billing.') % rec.name)

    @api.constrains('installment_count')
    def _check_installment_count(self):
        for rec in self:
            if rec.installment_count < 1:
                raise ValidationError(_('Fee Plan "%s": number of installments must be at least 1.') % rec.name)

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('Fee Plan "%s": amount must be positive.') % rec.name)
