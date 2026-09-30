# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .education_config_helpers import get_default_currency


class EducationCashTransfer(models.Model):
    """An internal movement of money between two of the center's own
    cash/bank accounts -- e.g. depositing the day's cash takings into the
    bank, or moving float between two branches' drawers. Deliberately
    separate from education.expense/education.payment: this never touches
    revenue or costs, it just relocates money the center already has, so
    it must never show up as income or an expense in the P&L."""
    _name = 'education.cash.transfer'
    _description = 'Internal Cash/Bank Transfer'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference', copy=False, readonly=True, default='New')
    date = fields.Date(string='Date', default=fields.Date.context_today, required=True, tracking=True)
    from_account_id = fields.Many2one('education.cash.account', string='From Account',
                                       required=True, tracking=True)
    to_account_id = fields.Many2one('education.cash.account', string='To Account',
                                     required=True, tracking=True)
    amount = fields.Monetary(string='Amount', required=True, currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one('res.currency', string='Currency',
                                   default=lambda self: get_default_currency(self.env))
    reference = fields.Char(string='Reference / Note')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, required=True)
    requested_by = fields.Many2one('res.users', string='Requested By', default=lambda self: self.env.user)
    confirmed_by = fields.Many2one('res.users', string='Confirmed By', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('education.cash.transfer') or 'New'
        return super().create(vals_list)

    @api.constrains('from_account_id', 'to_account_id')
    def _check_different_accounts(self):
        for rec in self:
            if rec.from_account_id and rec.from_account_id == rec.to_account_id:
                raise ValidationError(_('The "From" and "To" accounts must be different.'))

    @api.constrains('amount')
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('Transfer amount must be positive.'))

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError(_('Only draft transfers can be confirmed.'))
        self.write({'state': 'confirmed', 'confirmed_by': self.env.user.id})

    def action_cancel(self):
        for rec in self:
            if rec.state == 'confirmed':
                raise ValidationError(_(
                    'A confirmed transfer cannot be cancelled directly, to keep the treasury audit '
                    'trail intact — record an equal-and-opposite transfer back instead if it was a mistake.'
                ))
        self.write({'state': 'cancelled'})

    def action_reset_to_draft(self):
        for rec in self:
            if rec.state == 'confirmed':
                raise ValidationError(_('A confirmed transfer cannot be reset to draft.'))
        self.write({'state': 'draft'})
