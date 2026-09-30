# -*- coding: utf-8 -*-
import logging
from datetime import timedelta
from urllib.parse import quote

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

from .education_config_helpers import get_late_penalty_config, get_early_discount_config

_logger = logging.getLogger(__name__)


class EducationInstallment(models.Model):
    _name = 'education.installment'
    _description = 'Fee Installment'
    _order = 'fee_id, sequence'

    fee_id = fields.Many2one('education.fee', string='Fee', required=True, ondelete='cascade')
    student_id = fields.Many2one('education.student', string='Student', related='fee_id.student_id', store=True)
    sequence = fields.Integer(string='Sequence', default=10)
    due_date = fields.Date(string='Due Date', required=True)
    amount = fields.Monetary(string='Amount', required=True, currency_field='currency_id')
    paid_amount = fields.Monetary(string='Paid Amount', default=0.0, currency_field='currency_id')
    penalty_amount = fields.Monetary(string='Late Penalty', default=0.0, currency_field='currency_id',
                                      readonly=True, copy=False,
                                      help='Late penalty locked in once, by the daily late-penalty cron, '
                                           'after the configured grace period past the due date.')
    penalty_applied_on = fields.Date(string='Penalty Applied On', readonly=True, copy=False)
    early_discount_amount = fields.Monetary(string='Early Settlement Discount', default=0.0,
                                             currency_field='currency_id', readonly=True, copy=False,
                                             help='Discount applied via "Apply Early Settlement Discount" '
                                                  'when this installment is settled well ahead of its due date.')
    early_discount_applied_on = fields.Date(string='Early Discount Applied On', readonly=True, copy=False)
    remaining_amount = fields.Monetary(string='Remaining Amount', compute='_compute_remaining', store=True,
                                        currency_field='currency_id')
    currency_id = fields.Many2one(related='fee_id.currency_id', string='Currency', store=True)
    company_id = fields.Many2one(related='fee_id.company_id', string='Company', store=True)
    state = fields.Selection([
        ('unpaid', 'Unpaid'),
        ('partial', 'Partial'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
    ], string='Status', compute='_compute_state', store=True)
    notes = fields.Text(string='Notes')

    @api.depends('amount', 'paid_amount', 'penalty_amount', 'early_discount_amount')
    def _compute_remaining(self):
        for rec in self:
            rec.remaining_amount = rec.amount + rec.penalty_amount - rec.early_discount_amount - rec.paid_amount

    @api.depends('amount', 'paid_amount', 'due_date', 'penalty_amount', 'early_discount_amount')
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for rec in self:
            effective_total = rec.amount + rec.penalty_amount - rec.early_discount_amount
            if rec.paid_amount <= 0:
                rec.state = 'overdue' if (rec.due_date and rec.due_date < today) else 'unpaid'
            elif rec.paid_amount < effective_total:
                rec.state = 'partial'
            else:
                rec.state = 'paid'

    @api.constrains('amount')
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('Installment amount must be positive.'))

    # paid_amount must only ever move through the payment allocation/reversal
    # engine (education.payment._allocate_to_installments /
    # _reverse_allocations, and the refund reconciliation logic), never by a
    # direct user edit — otherwise the ledger no longer reconciles with the
    # payments that supposedly fund it.
    def write(self, vals):
        if 'paid_amount' in vals and not self.env.context.get('allow_system_write'):
            raise ValidationError(_(
                'Installment "paid_amount" is system-controlled and can only change through '
                'confirming, cancelling or refunding a Payment — it cannot be edited directly.'
            ))
        return super().write(vals)

    def unlink(self):
        for rec in self:
            if rec.paid_amount:
                raise ValidationError(_(
                    'Installment #%s for "%s" has payments allocated against it and cannot be deleted.'
                ) % (rec.sequence, rec.student_id.name))
        return super().unlink()

    @api.model
    def _cron_apply_late_penalties(self):
        """Daily job: lock in a late penalty (once) on every unpaid/partial
        installment that has been overdue for longer than the configured
        grace period. Applied once via penalty_applied_on so re-running the
        cron never stacks a second penalty onto the same installment."""
        penalty_type, value, grace_days = get_late_penalty_config(self.env)
        if penalty_type == 'none' or value <= 0:
            return
        today = fields.Date.context_today(self)
        cutoff = today - timedelta(days=grace_days)
        candidates = self.search([
            ('state', 'in', ('unpaid', 'partial', 'overdue')),
            ('due_date', '<=', cutoff),
            ('penalty_amount', '=', 0.0),
        ])
        for inst in candidates:
            base = inst.remaining_amount
            if base <= 0:
                continue
            penalty = value if penalty_type == 'fixed' else base * (value / 100.0)
            inst.write({'penalty_amount': penalty, 'penalty_applied_on': today})
        if candidates:
            _logger.info('Education: applied late penalty to %d installment(s).', len(candidates))

    def action_apply_early_discount(self):
        """Manual action (typically used by a cashier at the payment desk):
        grants the configured early-settlement discount if this installment
        is being settled far enough ahead of its due date, and hasn't
        already had the discount (or a payment) applied."""
        discount_type, value, days_before = get_early_discount_config(self.env)
        if discount_type == 'none' or value <= 0:
            raise UserError(_('No early-settlement discount is configured (Settings > Education).'))
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.paid_amount:
                raise UserError(_(
                    'Installment #%s already has a payment applied - the early-settlement discount '
                    'only applies before any payment is recorded.') % rec.sequence)
            if rec.early_discount_amount:
                raise UserError(_('The early-settlement discount was already applied to installment #%s.')
                                 % rec.sequence)
            if not rec.due_date or (rec.due_date - today).days < days_before:
                raise UserError(_(
                    'Installment #%(seq)s is due on %(due)s, which is fewer than %(days)d days away - '
                    'it no longer qualifies for the early-settlement discount.'
                ) % {'seq': rec.sequence, 'due': rec.due_date, 'days': days_before})
            base = rec.remaining_amount
            discount = value if discount_type == 'fixed' else base * (value / 100.0)
            discount = min(discount, base)
            rec.write({'early_discount_amount': discount, 'early_discount_applied_on': today})
            rec.message_post(body=_('Early-settlement discount of %.2f applied.') % discount)

    def action_send_whatsapp_reminder(self):
        self.ensure_one()
        number = self.student_id._get_whatsapp_number()
        if not number:
            raise UserError(_(
                'No WhatsApp/mobile number found for this student or their guardians.'))
        message = _(
            'Dear guardian of %(student)s,\n\n'
            'Installment #%(seq)s (due %(due)s) has a remaining balance of %(amount)s %(currency)s.\n\n'
            'Kindly settle it at your earliest convenience. Thank you.'
        ) % {
            'student': self.student_id.name, 'seq': self.sequence, 'due': self.due_date,
            'amount': '%.2f' % self.remaining_amount, 'currency': self.currency_id.name or '',
        }
        url = 'https://wa.me/%s?text=%s' % (number, quote(message))
        return {'type': 'ir.actions.act_url', 'url': url, 'target': 'new'}
