# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .education_config_helpers import get_default_currency


class EducationExpense(models.Model):
    """Money going OUT of the center for operating costs (rent, utilities,
    salaries, supplies, maintenance, marketing...) — the counterpart to
    education.payment (money coming IN). Together with education.payment,
    education.refund and education.teacher.payout, this feeds the Income
    Statement and Cash Book reports, forming a self-contained accounting
    system with no dependency on Odoo's Accounting app."""
    _name = 'education.expense'
    _description = 'Expense'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'expense_date desc'

    name = fields.Char(string='Reference', copy=False, readonly=True, default='New')
    expense_date = fields.Date(string='Date', default=fields.Date.context_today, required=True, tracking=True)
    category_id = fields.Many2one('education.expense.category', string='Category', required=True, tracking=True)
    description = fields.Char(string='Description', required=True)
    payee = fields.Char(string='Paid To', help='Vendor, supplier, or person this expense was paid to.')
    amount = fields.Monetary(string='Amount', required=True, currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one('res.currency', string='Currency',
                                   default=lambda self: get_default_currency(self.env))
    cash_account_id = fields.Many2one('education.cash.account', string='Paid From',
                                       default=lambda self: self._default_cash_account())
    reference = fields.Char(string='Invoice / Reference No.')
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
    requested_by = fields.Many2one('res.users', string='Requested By', default=lambda self: self.env.user)
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True)
    paid_by = fields.Many2one('res.users', string='Paid By', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, required=True)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.model
    def _default_cash_account(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'prime_educational_hub.default_cash_account_id')
        return int(param) if param else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('education.expense') or 'New'
        return super().create(vals_list)

    @api.constrains('amount')
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('Expense amount must be positive.'))

    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise ValidationError(_('Only draft expenses can be submitted.'))
        self.write({'state': 'submitted'})

    def action_approve(self):
        for rec in self:
            if rec.state != 'submitted':
                raise ValidationError(_('Only submitted expenses can be approved.'))
        self.write({'state': 'approved', 'approved_by': self.env.user.id})

    def action_reject(self):
        for rec in self:
            if rec.state not in ('submitted', 'approved'):
                raise ValidationError(_('Only submitted or approved expenses can be rejected.'))
        self.write({'state': 'rejected'})

    def action_mark_paid(self):
        for rec in self:
            if rec.state != 'approved':
                raise ValidationError(_('Only approved expenses can be marked as paid.'))
            if not rec.cash_account_id:
                raise ValidationError(_('Please set the "Paid From" cash/bank account before marking this paid.'))
        self.write({'state': 'paid', 'paid_by': self.env.user.id})

    def action_reset_to_draft(self):
        self.write({
            'state': 'draft',
            'approved_by': False,
            'paid_by': False,
        })

    def action_cancel(self):
        for rec in self:
            if rec.state == 'paid':
                raise ValidationError(_('A paid expense cannot be cancelled directly - contact an administrator.'))
        self.write({'state': 'cancelled'})
