# -*- coding: utf-8 -*-
from odoo import fields, models

from .education_config_helpers import get_default_currency


class EducationCashAccount(models.Model):
    """A 'drawer' the center's money actually sits in — a cash box or a bank
    account. Every education.payment (via its payment method), education.expense,
    education.refund and education.teacher.payout can point to one of these, so
    the module can show a real running balance per drawer — a mini treasury,
    without any dependency on Odoo's Accounting app."""
    _name = 'education.cash.account'
    _description = 'Cash / Bank Account'
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True)
    account_type = fields.Selection([
        ('cash', 'Cash'),
        ('bank', 'Bank'),
    ], string='Type', default='cash', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    bank_name = fields.Char(string='Bank Name')
    account_number = fields.Char(string='Account / IBAN Number')
    opening_balance = fields.Monetary(string='Opening Balance', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency',
                                   default=lambda self: get_default_currency(self.env))
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    notes = fields.Text(string='Notes')

    total_in = fields.Monetary(string='Total In', compute='_compute_balance', currency_field='currency_id')
    total_out = fields.Monetary(string='Total Out', compute='_compute_balance', currency_field='currency_id')
    current_balance = fields.Monetary(string='Current Balance', compute='_compute_balance',
                                       currency_field='currency_id')
    payment_method_count = fields.Integer(string='Payment Methods Count', compute='_compute_payment_method_count')

    def _compute_payment_method_count(self):
        PaymentMethod = self.env['education.payment.method']
        for rec in self:
            rec.payment_method_count = PaymentMethod.search_count([('cash_account_id', '=', rec.id)])

    def action_view_payment_methods(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'res_model': 'education.payment.method', 'name': 'Payment Methods',
            'view_mode': 'list,form', 'domain': [('cash_account_id', '=', self.id)],
            'context': {'default_cash_account_id': self.id},
        }

    def _compute_balance(self):
        for rec in self:
            total_in, total_out = rec._get_movement_totals()
            rec.total_in = total_in
            rec.total_out = total_out
            rec.current_balance = rec.opening_balance + total_in - total_out

    def _get_movement_totals(self, date_from=None, date_to=None):
        """Returns (total_in, total_out) for this account, optionally
        restricted to a date range. Shared by the balance compute and by the
        Cash Book / Treasury reports so the two never drift apart."""
        self.ensure_one()
        Payment = self.env['education.payment']
        Expense = self.env['education.expense']
        Refund = self.env['education.refund']
        Payout = self.env['education.teacher.payout']
        Transfer = self.env['education.cash.transfer']

        pay_domain = [('payment_method_id.cash_account_id', '=', self.id), ('state', '=', 'confirmed')]
        exp_domain = [('cash_account_id', '=', self.id), ('state', '=', 'paid')]
        ref_domain = [('cash_account_id', '=', self.id), ('state', '=', 'paid')]
        out_domain = [('cash_account_id', '=', self.id), ('state', '=', 'paid')]
        transfer_in_domain = [('to_account_id', '=', self.id), ('state', '=', 'confirmed')]
        transfer_out_domain = [('from_account_id', '=', self.id), ('state', '=', 'confirmed')]

        date_field_domain = lambda field, d_from, d_to: (
            ([(field, '>=', d_from)] if d_from else []) + ([(field, '<=', d_to)] if d_to else [])
        )
        pay_domain += date_field_domain('payment_date', date_from, date_to)
        exp_domain += date_field_domain('expense_date', date_from, date_to)
        ref_domain += date_field_domain('refund_date', date_from, date_to)
        out_domain += date_field_domain('payment_date', date_from, date_to)
        transfer_in_domain += date_field_domain('date', date_from, date_to)
        transfer_out_domain += date_field_domain('date', date_from, date_to)

        total_in = (
            sum(Payment.search(pay_domain).mapped('amount'))
            + sum(Transfer.search(transfer_in_domain).mapped('amount'))
        )
        total_out = (
            sum(Expense.search(exp_domain).mapped('amount'))
            + sum(Refund.search(ref_domain).mapped('amount'))
            + sum(Payout.search(out_domain).mapped('amount'))
            + sum(Transfer.search(transfer_out_domain).mapped('amount'))
        )
        return total_in, total_out

    def get_ledger_lines(self, date_from=None, date_to=None):
        """Returns a chronological list of dicts — one per money movement —
        for this account, used by the Cash Book report. Each dict has: date,
        description, in_amount, out_amount."""
        self.ensure_one()
        Payment = self.env['education.payment']
        Expense = self.env['education.expense']
        Refund = self.env['education.refund']
        Payout = self.env['education.teacher.payout']

        date_field_domain = lambda field, d_from, d_to: (
            ([(field, '>=', d_from)] if d_from else []) + ([(field, '<=', d_to)] if d_to else [])
        )

        lines = []
        payments = Payment.search(
            [('payment_method_id.cash_account_id', '=', self.id), ('state', '=', 'confirmed')]
            + date_field_domain('payment_date', date_from, date_to))
        for p in payments:
            lines.append({
                'date': p.payment_date, 'doc': p.receipt_number,
                'description': 'Payment - %s' % p.student_id.name,
                'in_amount': p.amount, 'out_amount': 0.0,
            })

        expenses = Expense.search(
            [('cash_account_id', '=', self.id), ('state', '=', 'paid')]
            + date_field_domain('expense_date', date_from, date_to))
        for e in expenses:
            lines.append({
                'date': e.expense_date, 'doc': e.name,
                'description': 'Expense - %s' % (e.category_id.name or ''),
                'in_amount': 0.0, 'out_amount': e.amount,
            })

        refunds = Refund.search(
            [('cash_account_id', '=', self.id), ('state', '=', 'paid')]
            + date_field_domain('refund_date', date_from, date_to))
        for r in refunds:
            lines.append({
                'date': r.refund_date, 'doc': r.refund_number,
                'description': 'Refund - %s' % r.student_id.name,
                'in_amount': 0.0, 'out_amount': r.amount,
            })

        payouts = Payout.search(
            [('cash_account_id', '=', self.id), ('state', '=', 'paid')]
            + date_field_domain('payment_date', date_from, date_to))
        for pay in payouts:
            lines.append({
                'date': pay.payment_date, 'doc': pay.teacher_id.name,
                'description': 'Teacher Payout - %s' % pay.teacher_id.name,
                'in_amount': 0.0, 'out_amount': pay.amount,
            })

        Transfer = self.env['education.cash.transfer']
        transfers_in = Transfer.search(
            [('to_account_id', '=', self.id), ('state', '=', 'confirmed')]
            + date_field_domain('date', date_from, date_to))
        for t in transfers_in:
            lines.append({
                'date': t.date, 'doc': t.name,
                'description': 'Transfer in - from %s' % t.from_account_id.name,
                'in_amount': t.amount, 'out_amount': 0.0,
            })
        transfers_out = Transfer.search(
            [('from_account_id', '=', self.id), ('state', '=', 'confirmed')]
            + date_field_domain('date', date_from, date_to))
        for t in transfers_out:
            lines.append({
                'date': t.date, 'doc': t.name,
                'description': 'Transfer out - to %s' % t.to_account_id.name,
                'in_amount': 0.0, 'out_amount': t.amount,
            })

        lines.sort(key=lambda l: l['date'] or fields.Date.today())
        return lines
