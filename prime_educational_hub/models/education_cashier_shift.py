# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .education_config_helpers import get_default_currency


class EducationCashierShift(models.Model):
    """One cashier's day on one cash/bank account: they declare an opening
    balance, work the day (payments/expenses/refunds/payouts/transfers all
    flow through the account as usual), then count the drawer and declare a
    closing balance. Any gap between what the books say should be there
    (expected) and what was actually counted (over/short) needs a
    supervisor's sign-off before the shift can close -- this is the P0
    'cash over/short with approval' + 'daily opening/closing balance' +
    'cashier handover' requirement in one connected workflow."""
    _name = 'education.cashier.shift'
    _description = 'Cashier Shift'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference', copy=False, readonly=True, default='New')
    cash_account_id = fields.Many2one('education.cash.account', string='Cash/Bank Account', required=True,
                                       tracking=True)
    cashier_id = fields.Many2one('res.users', string='Cashier', default=lambda self: self.env.user,
                                  required=True, tracking=True)
    date = fields.Date(string='Date', default=fields.Date.context_today, required=True, tracking=True)
    currency_id = fields.Many2one('res.currency', string='Currency',
                                   default=lambda self: get_default_currency(self.env))

    opening_datetime = fields.Datetime(string='Opened At', readonly=True)
    opening_balance = fields.Monetary(string='Opening Balance', currency_field='currency_id', tracking=True)

    closing_datetime = fields.Datetime(string='Closed At', readonly=True)
    counted_closing_balance = fields.Monetary(string='Counted Closing Balance', currency_field='currency_id',
                                               help='What the cashier physically counted in the drawer '
                                                    '(or confirmed as the bank balance) at close.')
    expected_closing_balance = fields.Monetary(string='Expected Closing Balance', compute='_compute_expected_balance',
                                                store=True, currency_field='currency_id',
                                                help='Opening balance + everything the books say moved through '
                                                     'this account on this date.')
    difference = fields.Monetary(string='Over / Short', compute='_compute_difference', store=True,
                                  currency_field='currency_id',
                                  help='Counted minus Expected. Positive = over (more cash than the books '
                                       'expect), negative = short (less than expected).')

    handed_over_to_id = fields.Many2one('res.users', string='Handed Over To',
                                         help='Who is taking over this drawer for the next shift, if anyone.')
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('pending_approval', 'Pending Approval (Over/Short)'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', tracking=True, required=True)

    _sql_constraints = [
        ('date_account_cashier_uniq', 'unique(cash_account_id, date, cashier_id)',
         'This cashier already has a shift for this account on this date.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('education.cashier.shift') or 'New'
        return super().create(vals_list)

    @api.depends('cash_account_id', 'date', 'opening_balance', 'state')
    def _compute_expected_balance(self):
        for rec in self:
            if rec.cash_account_id and rec.date:
                total_in, total_out = rec.cash_account_id._get_movement_totals(rec.date, rec.date)
                rec.expected_closing_balance = rec.opening_balance + total_in - total_out
            else:
                rec.expected_closing_balance = rec.opening_balance

    @api.depends('counted_closing_balance', 'expected_closing_balance')
    def _compute_difference(self):
        for rec in self:
            rec.difference = rec.counted_closing_balance - rec.expected_closing_balance

    def action_open(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only a draft shift can be opened.'))
            other_open = self.search([
                ('cash_account_id', '=', rec.cash_account_id.id),
                ('state', '=', 'open'),
                ('id', '!=', rec.id),
            ], limit=1)
            if other_open:
                raise ValidationError(_(
                    'Account "%s" already has an open shift (%s, cashier: %s). Close it before '
                    'opening a new one — two open shifts on the same drawer would double-count everything.'
                ) % (rec.cash_account_id.name, other_open.name, other_open.cashier_id.name))
        self.write({'state': 'open', 'opening_datetime': fields.Datetime.now()})

    def action_close(self):
        for rec in self:
            if rec.state != 'open':
                raise UserError(_('Only an open shift can be closed.'))
            if rec.counted_closing_balance is False or rec.counted_closing_balance is None:
                raise UserError(_('Enter the counted closing balance before closing the shift.'))
        for rec in self:
            rec.closing_datetime = fields.Datetime.now()
            if rec.currency_id.compare_amounts(rec.difference, 0.0) != 0:
                rec.state = 'pending_approval'
            else:
                rec.state = 'closed'

    def action_approve(self):
        for rec in self:
            if rec.state != 'pending_approval':
                raise UserError(_('Only a shift pending approval can be approved.'))
        self.write({'state': 'closed', 'approved_by': self.env.user.id})

    def action_reopen_for_recount(self):
        for rec in self:
            if rec.state not in ('pending_approval', 'closed'):
                raise UserError(_('Only a pending-approval or closed shift can be reopened for a recount.'))
        self.write({'state': 'open', 'closing_datetime': False, 'approved_by': False})
