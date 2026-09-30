# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

from .education_config_helpers import get_default_currency


class EducationPayment(models.Model):
    _name = 'education.payment'
    _description = 'Payment / Receipt'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'payment_date desc'

    receipt_number = fields.Char(string='Receipt Number', copy=False, readonly=True, default='New')
    student_id = fields.Many2one('education.student', string='Student', required=True, tracking=True)
    enrollment_id = fields.Many2one('education.enrollment', string='Enrollment',
                                     domain="[('student_id', '=', student_id)]")
    group_id = fields.Many2one(related='enrollment_id.group_id', string='Group', store=True)
    payment_date = fields.Date(string='Payment Date', default=fields.Date.context_today, required=True)
    amount = fields.Monetary(string='Amount', required=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency',
                                   default=lambda self: get_default_currency(self.env))
    payment_method_id = fields.Many2one('education.payment.method', string='Payment Method', required=True,
                                         default=lambda self: self._default_payment_method())
    reference = fields.Char(string='Reference')
    received_by = fields.Many2one('res.users', string='Received By', default=lambda self: self.env.user)
    notes = fields.Text(string='Notes')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed / Received'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, required=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    allocation_ids = fields.One2many('education.payment.allocation', 'payment_id', string='Allocations')
    refund_ids = fields.One2many('education.refund', 'payment_id', string='Refunds')
    refunded_amount = fields.Monetary(string='Refunded Amount', compute='_compute_refunded_amount',
                                       currency_field='currency_id')
    refundable_amount = fields.Monetary(string='Refundable Amount', compute='_compute_refunded_amount',
                                         currency_field='currency_id')
    unallocated_amount = fields.Monetary(string='Available Credit', compute='_compute_unallocated_amount',
                                          store=True, currency_field='currency_id',
                                          help='Portion of this payment not yet applied to any installment - '
                                               'e.g. an overpayment. Automatically consumed by future fees for '
                                               'the same student (see education.fee._apply_available_credit).')

    @api.depends('amount', 'state', 'allocation_ids.amount', 'refunded_amount')
    def _compute_unallocated_amount(self):
        for rec in self:
            if rec.state != 'confirmed':
                rec.unallocated_amount = 0.0
                continue
            allocated = sum(rec.allocation_ids.mapped('amount'))
            rec.unallocated_amount = max(rec.amount - allocated - rec.refunded_amount, 0.0)

    @api.depends('refund_ids.amount', 'refund_ids.state', 'amount')
    def _compute_refunded_amount(self):
        for rec in self:
            active_refunds = rec.refund_ids.filtered(lambda r: r.state in ('approved', 'paid'))
            rec.refunded_amount = sum(active_refunds.mapped('amount'))
            rec.refundable_amount = rec.amount - rec.refunded_amount

    @api.constrains('amount')
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('Payment amount must be positive.'))

    def _default_payment_method(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'prime_educational_hub.default_payment_method_id')
        return int(param) if param else False

    @api.constrains('company_id', 'currency_id', 'student_id', 'enrollment_id')
    def _check_company_currency_consistency(self):
        for rec in self:
            if rec.student_id and rec.student_id.company_id and rec.student_id.company_id != rec.company_id:
                raise ValidationError(_(
                    'Payment company must match the student\'s company (%s).') % rec.student_id.company_id.name)
            if rec.enrollment_id:
                if rec.enrollment_id.company_id and rec.enrollment_id.company_id != rec.company_id:
                    raise ValidationError(_(
                        'Payment company must match the enrollment\'s company (%s).'
                    ) % rec.enrollment_id.company_id.name)
                if rec.enrollment_id.currency_id and rec.currency_id != rec.enrollment_id.currency_id:
                    raise ValidationError(_(
                        'Payment currency (%s) does not match the enrollment\'s currency (%s). '
                        'A payment must use the same currency as the fee it is settling.'
                    ) % (rec.currency_id.name, rec.enrollment_id.currency_id.name))

    @api.constrains('student_id', 'enrollment_id')
    def _check_enrollment_belongs_to_student(self):
        # The hard guarantee that a payment can only ever fund the account of
        # the student it says it's for. _allocate_to_installments() trusts
        # student_id (and enrollment_id) completely when deciding which
        # installments to pay down, so if these two ever disagreed the money
        # could silently go unallocated (or, in a differently-shaped bug,
        # toward the wrong person's balance). The UI domain only guides the
        # picker; this is what actually stops it.
        for rec in self:
            if rec.enrollment_id and rec.enrollment_id.student_id != rec.student_id:
                raise ValidationError(_(
                    'This payment is set for student "%s" but its enrollment belongs to "%s". '
                    'A payment must always be linked to an enrollment of the same student.'
                ) % (rec.student_id.name, rec.enrollment_id.student_id.name))

    @api.constrains('reference', 'payment_method_id')
    def _check_reference_required(self):
        for rec in self:
            if rec.payment_method_id and rec.payment_method_id.requires_reference and not rec.reference:
                raise ValidationError(_(
                    'Payment method "%s" requires a reference number.'
                ) % rec.payment_method_id.name)

    @api.model_create_multi
    def create(self, vals_list):
        PaymentMethod = self.env['education.payment.method']
        for vals in vals_list:
            if vals.get('receipt_number', 'New') == 'New':
                method = PaymentMethod.browse(vals.get('payment_method_id')) if vals.get('payment_method_id') else None
                sequence = method.sequence_id if method and method.sequence_id else None
                if sequence:
                    vals['receipt_number'] = sequence.next_by_id() or 'New'
                else:
                    # No payment method chosen yet (or it has no sequence for some reason) --
                    # fall back to the one shared counter so numbering never breaks.
                    vals['receipt_number'] = self.env['ir.sequence'].next_by_code('education.payment') or 'New'
        return super().create(vals_list)

    def action_confirm(self):
        for rec in self:
            rec._check_overpayment()
            rec._allocate_to_installments()
        self.write({'state': 'confirmed'})

    def action_cancel(self):
        for rec in self:
            if rec.refunded_amount:
                raise ValidationError(_(
                    'Payment "%s" has refunds recorded against it and cannot be cancelled. '
                    'Cancel the refund(s) first.'
                ) % rec.receipt_number)
            rec._reverse_allocations()
        self.write({'state': 'cancelled'})

    # Fields that determine the financial meaning of a payment; once
    # confirmed, these must never change except through cancellation +
    # creating a brand-new corrected payment (preserves the audit trail).
    _LOCKED_AFTER_CONFIRM = {'amount', 'student_id', 'enrollment_id', 'currency_id',
                             'payment_method_id', 'payment_date'}

    def write(self, vals):
        if self._LOCKED_AFTER_CONFIRM.intersection(vals.keys()) and not self.env.context.get('allow_system_write'):
            for rec in self:
                if rec.state == 'confirmed':
                    raise ValidationError(_(
                        'Payment "%s" is confirmed. Amount, student, enrollment, currency, method and date '
                        'are locked once a receipt is confirmed. Cancel it and create a new corrected '
                        'payment instead, to preserve the audit trail.'
                    ) % rec.receipt_number)
        return super().write(vals)

    def _check_overpayment(self):
        self.ensure_one()
        if self.env.context.get('allow_overpayment'):
            return
        if self.env.user.has_group('prime_educational_hub.group_education_admin'):
            return
        if not self.enrollment_id:
            return
        enrollment = self.enrollment_id
        already_paid = sum(self.search([
            ('enrollment_id', '=', enrollment.id),
            ('state', '=', 'confirmed'),
            ('id', '!=', self.id),
        ]).mapped('amount'))
        if already_paid + self.amount > enrollment.net_fee:
            raise ValidationError(_(
                'This payment would exceed the outstanding fee for "%s" '
                '(Net Fee: %.2f, Already Paid: %.2f, This Payment: %.2f). '
                'An Education Administrator can override this using the overpayment option.'
            ) % (enrollment.student_id.name, enrollment.net_fee, already_paid, self.amount))

    def _allocate_to_installments(self):
        """FIFO allocation: oldest due-date outstanding installments first,
        scoped to this payment's enrollment if set, otherwise across all of
        the student's fees."""
        self.ensure_one()
        Installment = self.env['education.installment']
        Allocation = self.env['education.payment.allocation'].sudo()
        domain = [('student_id', '=', self.student_id.id), ('remaining_amount', '>', 0)]
        if self.enrollment_id:
            domain.append(('fee_id.enrollment_id', '=', self.enrollment_id.id))
        installments = Installment.search(domain, order='due_date asc')

        remaining = self.amount
        for inst in installments:
            if remaining <= 0:
                break
            to_apply = min(inst.remaining_amount, remaining)
            if to_apply <= 0:
                continue
            inst.with_context(allow_system_write=True).write({'paid_amount': inst.paid_amount + to_apply})
            Allocation.create({
                'payment_id': self.id,
                'installment_id': inst.id,
                'amount': to_apply,
            })
            remaining -= to_apply
        # Any leftover amount beyond outstanding installments is recorded as
        # a credit balance implicitly reflected in the enrollment's outstanding
        # calculation (Net - Paid + Refunded), per the standalone ledger design.

    def _reverse_allocations(self):
        self.ensure_one()
        for alloc in self.allocation_ids:
            alloc.installment_id.with_context(allow_system_write=True).write({
                'paid_amount': alloc.installment_id.paid_amount - alloc.amount,
            })
        self.allocation_ids.sudo().unlink()

    def _reverse_for_refund(self, amount):
        """Reverses up to `amount` from the installments this payment funded
        (most-recently-applied allocation first), so a refund un-pays the
        specific installments the original payment covered — instead of
        only adjusting a top-level enrollment total while the installment
        ledger silently stays 'paid'. Tracks per-allocation refunded_amount
        so multiple partial refunds on the same payment reconcile correctly.

        Returns a list of (allocation, amount_reversed) pairs describing
        exactly what was touched, so the caller (education.refund) can save
        a precise, per-allocation record and undo exactly this — and only
        this — reversal later if the refund itself gets cancelled."""
        self.ensure_one()
        remaining = amount
        breakdown = []
        for alloc in self.allocation_ids.sorted(key=lambda a: a.id, reverse=True):
            if remaining <= 0:
                break
            available = alloc.amount - alloc.refunded_amount
            if available <= 0:
                continue
            reduce_by = min(available, remaining)
            inst = alloc.installment_id
            inst.with_context(allow_system_write=True).write({
                'paid_amount': max(inst.paid_amount - reduce_by, 0.0),
            })
            alloc.sudo().write({'refunded_amount': alloc.refunded_amount + reduce_by})
            breakdown.append((alloc, reduce_by))
            remaining -= reduce_by
        return breakdown
