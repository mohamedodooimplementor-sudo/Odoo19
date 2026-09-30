# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EducationRefund(models.Model):
    _name = 'education.refund'
    _description = 'Refund'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'refund_date desc'

    refund_number = fields.Char(string='Refund Number', copy=False, readonly=True, default='New')
    student_id = fields.Many2one('education.student', string='Student', required=True, tracking=True)
    payment_id = fields.Many2one('education.payment', string='Original Payment', required=True, tracking=True,
                                  domain="[('student_id', '=', student_id), ('state', '=', 'confirmed')]")
    refund_date = fields.Date(string='Refund Date', default=fields.Date.context_today, required=True)
    amount = fields.Monetary(string='Amount', required=True, currency_field='currency_id')
    currency_id = fields.Many2one(related='payment_id.currency_id', string='Currency', store=True)
    reason = fields.Text(string='Reason')
    approved_by = fields.Many2one('res.users', string='Approved By')
    cash_account_id = fields.Many2one('education.cash.account', string='Paid From',
                                       default=lambda self: self._default_cash_account())
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, required=True)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    refund_line_ids = fields.One2many('education.refund.allocation', 'refund_id', string='Reversed Allocations')

    @api.model
    def _default_cash_account(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'prime_educational_hub.default_cash_account_id')
        return int(param) if param else False

    @api.constrains('amount')
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('Refund amount must be positive.'))

    @api.constrains('student_id', 'payment_id')
    def _check_payment_belongs_to_student(self):
        # Same rationale as Fee/Payment: the picker's UI domain is not a
        # server-side guarantee. _reverse_for_refund() always reverses the
        # allocations of rec.payment_id itself, so a mismatch here wouldn't
        # misdirect money — but it would make the refund's own student_id
        # (used for display, portal history, and reports) wrong. Blocking it
        # here keeps every money record's "whose account is this" honest.
        for rec in self:
            if rec.payment_id and rec.payment_id.student_id != rec.student_id:
                raise ValidationError(_(
                    'This refund is set for student "%s" but the original payment "%s" belongs to "%s".'
                ) % (rec.student_id.name, rec.payment_id.receipt_number, rec.payment_id.student_id.name))

    @api.constrains('amount', 'payment_id', 'state')
    def _check_within_refundable_balance(self):
        for rec in self:
            if rec.state == 'cancelled' or not rec.payment_id:
                continue
            other_refunds = self.search([
                ('payment_id', '=', rec.payment_id.id),
                ('id', '!=', rec.id),
                ('state', 'in', ('approved', 'paid')),
            ])
            already_refunded = sum(other_refunds.mapped('amount'))
            if rec.amount + already_refunded > rec.payment_id.amount:
                raise ValidationError(_(
                    'Refund of %.2f exceeds the refundable balance of payment "%s" '
                    '(Payment Amount: %.2f, Already Refunded: %.2f).'
                ) % (rec.amount, rec.payment_id.receipt_number, rec.payment_id.amount, already_refunded))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('refund_number', 'New') == 'New':
                vals['refund_number'] = self.env['ir.sequence'].next_by_code('education.refund') or 'New'
        return super().create(vals_list)

    def action_approve(self):
        RefundAllocation = self.env['education.refund.allocation'].sudo()
        for rec in self:
            rec.write({'state': 'approved', 'approved_by': self.env.user.id})
            breakdown = rec.payment_id._reverse_for_refund(rec.amount)
            for alloc, reversed_amount in breakdown:
                RefundAllocation.create({
                    'refund_id': rec.id,
                    'allocation_id': alloc.id,
                    'amount': reversed_amount,
                })

    def action_mark_paid(self):
        for rec in self:
            if not rec.cash_account_id:
                raise ValidationError(_(
                    'Please set the "Paid From" cash/bank account before marking this refund paid.'))
        self.write({'state': 'paid'})

    def action_cancel(self):
        for rec in self:
            if rec.state == 'approved' and rec.refund_line_ids:
                # Undo exactly what this refund reversed (and only this refund's
                # share) — other refunds' reversals on the same payment are
                # untouched since each has its own refund_line_ids records.
                for line in rec.refund_line_ids:
                    alloc = line.allocation_id
                    inst = alloc.installment_id
                    inst.with_context(allow_system_write=True).write({
                        'paid_amount': inst.paid_amount + line.amount,
                    })
                    alloc.sudo().write({'refunded_amount': alloc.refunded_amount - line.amount})
                rec.refund_line_ids.sudo().unlink()
        self.write({'state': 'cancelled'})
