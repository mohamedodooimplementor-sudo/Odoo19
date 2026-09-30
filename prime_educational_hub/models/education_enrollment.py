# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

from .education_config_helpers import get_default_currency, get_default_discount


class EducationEnrollment(models.Model):
    _name = 'education.enrollment'
    _description = 'Student Enrollment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'enrollment_date desc'

    student_id = fields.Many2one('education.student', string='Student', required=True, tracking=True)
    group_id = fields.Many2one('education.group', string='Group', required=True, tracking=True)
    enrollment_date = fields.Date(string='Enrollment Date', default=fields.Date.context_today, required=True)
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, required=True)

    # Fee plan and financials
    fee_plan_id = fields.Many2one('education.fee.plan', string='Fee Plan')
    billing_type = fields.Selection([
        ('lump_sum', 'Lump Sum / Installments'),
        ('per_session', 'Per Session (Session Package)'),
    ], string='Billing Type', default='lump_sum')
    session_count = fields.Integer(string='Sessions in Package')
    price_per_session = fields.Monetary(string='Price per Session', currency_field='currency_id')
    sessions_consumed = fields.Integer(string='Sessions Consumed', compute='_compute_session_billing', store=True)
    sessions_remaining = fields.Integer(string='Sessions Remaining', compute='_compute_session_billing', store=True)
    amount_consumed = fields.Monetary(string='Amount Consumed (Sessions Attended)',
                                       compute='_compute_session_billing', store=True, currency_field='currency_id')
    gross_fee = fields.Monetary(string='Gross Fee', currency_field='currency_id')
    discount_type = fields.Selection([
        ('fixed', 'Fixed Amount'),
        ('percent', 'Percentage'),
    ], string='Discount Type', default=lambda self: (
        get_default_discount(self.env)[0] if get_default_discount(self.env)[0] != 'none' else False))
    discount_value = fields.Float(string='Discount Value', default=lambda self: get_default_discount(self.env)[1])
    discount_amount = fields.Monetary(string='Discount Amount', compute='_compute_fees', store=True,
                                       currency_field='currency_id')
    net_fee = fields.Monetary(string='Net Fee', compute='_compute_fees', store=True, currency_field='currency_id')

    fee_ids = fields.One2many('education.fee', 'enrollment_id', string='Fees')
    fee_count = fields.Integer(string='Fees Count', compute='_compute_fee_count')
    payment_ids = fields.One2many('education.payment', 'enrollment_id', string='Payments')
    paid_amount = fields.Monetary(string='Paid Amount', compute='_compute_financials', store=True,
                                   currency_field='currency_id')
    refunded_amount = fields.Monetary(string='Refunded Amount', compute='_compute_financials', store=True,
                                       currency_field='currency_id')
    outstanding_amount = fields.Monetary(string='Outstanding Amount', compute='_compute_financials', store=True,
                                          currency_field='currency_id')

    currency_id = fields.Many2one('res.currency', string='Currency',
                                   default=lambda self: get_default_currency(self.env))
    notes = fields.Text(string='Notes')
    end_reason = fields.Text(string='Completion / Cancellation Reason',
                              help='Why this enrollment was completed, cancelled, or the student transferred out.')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    attendance_ids = fields.One2many('education.attendance', 'enrollment_id', string='Attendance Records')
    attendance_percentage = fields.Float(string='Attendance %', compute='_compute_attendance_stats', store=True)
    present_count = fields.Integer(string='Present', compute='_compute_attendance_stats', store=True)
    absent_count = fields.Integer(string='Absent', compute='_compute_attendance_stats', store=True)
    late_count = fields.Integer(string='Late', compute='_compute_attendance_stats', store=True)
    excused_count = fields.Integer(string='Excused', compute='_compute_attendance_stats', store=True)

    @api.depends('attendance_ids.status')
    def _compute_attendance_stats(self):
        exclude_excused = self.env['ir.config_parameter'].sudo().get_param(
            'prime_educational_hub.attendance_excused_excluded')
        for rec in self:
            lines = rec.attendance_ids
            rec.present_count = len(lines.filtered(lambda a: a.status == 'present'))
            rec.absent_count = len(lines.filtered(lambda a: a.status == 'absent'))
            rec.late_count = len(lines.filtered(lambda a: a.status == 'late'))
            rec.excused_count = len(lines.filtered(lambda a: a.status == 'excused'))
            total = len(lines) - (rec.excused_count if exclude_excused else 0)
            counted_present = rec.present_count + rec.late_count
            rec.attendance_percentage = (counted_present / total * 100.0) if total else 0.0

    @api.onchange('fee_plan_id')
    def _onchange_fee_plan_id(self):
        if self.fee_plan_id:
            plan = self.fee_plan_id
            self.billing_type = plan.billing_type
            if plan.billing_type == 'per_session':
                self.session_count = plan.session_count
                self.price_per_session = plan.price_per_session
                self.gross_fee = plan.session_count * plan.price_per_session
            else:
                self.gross_fee = plan.amount
            if plan.discount_policy != 'none':
                self.discount_type = plan.discount_policy
                self.discount_value = plan.discount_value

    @api.onchange('billing_type', 'session_count', 'price_per_session')
    def _onchange_session_billing_fields(self):
        if self.billing_type == 'per_session':
            self.gross_fee = (self.session_count or 0) * (self.price_per_session or 0.0)

    @api.depends('present_count', 'late_count', 'session_count', 'price_per_session', 'billing_type')
    def _compute_session_billing(self):
        for rec in self:
            consumed = rec.present_count + rec.late_count
            if rec.billing_type == 'per_session':
                rec.sessions_consumed = consumed
                rec.sessions_remaining = rec.session_count - consumed
                rec.amount_consumed = consumed * rec.price_per_session
            else:
                rec.sessions_consumed = 0
                rec.sessions_remaining = 0
                rec.amount_consumed = 0.0

    @api.onchange('group_id')
    def _onchange_group_id_fee_plan(self):
        if self.group_id and self.group_id.fee_plan_id and not self.fee_plan_id:
            self.fee_plan_id = self.group_id.fee_plan_id

    @api.depends('gross_fee', 'discount_type', 'discount_value')
    def _compute_fees(self):
        for rec in self:
            discount = 0.0
            if rec.discount_type == 'fixed':
                discount = rec.discount_value
            elif rec.discount_type == 'percent':
                discount = rec.gross_fee * (rec.discount_value / 100.0)
            discount = min(discount, rec.gross_fee) if rec.gross_fee else discount
            rec.discount_amount = discount
            rec.net_fee = rec.gross_fee - discount

    @api.depends('payment_ids.amount', 'payment_ids.state', 'net_fee',
                 'payment_ids.refund_ids.amount', 'payment_ids.refund_ids.state')
    def _compute_financials(self):
        for rec in self:
            confirmed_payments = rec.payment_ids.filtered(lambda p: p.state == 'confirmed')
            rec.paid_amount = sum(confirmed_payments.mapped('amount'))
            refunds = confirmed_payments.mapped('refund_ids').filtered(lambda r: r.state in ('approved', 'paid'))
            rec.refunded_amount = sum(refunds.mapped('amount'))
            rec.outstanding_amount = rec.net_fee - rec.paid_amount + rec.refunded_amount

    @api.constrains('student_id', 'group_id', 'state')
    def _check_duplicate_enrollment(self):
        for rec in self:
            if rec.state in ('draft', 'active'):
                domain = [
                    ('id', '!=', rec.id),
                    ('student_id', '=', rec.student_id.id),
                    ('group_id', '=', rec.group_id.id),
                    ('state', 'in', ('draft', 'active')),
                ]
                if self.search_count(domain):
                    raise ValidationError(_(
                        'Student "%s" already has an active/draft enrollment in group "%s".'
                    ) % (rec.student_id.name, rec.group_id.name))

    @api.constrains('start_date', 'end_date')
    @api.constrains('company_id', 'student_id', 'group_id')
    def _check_company_consistency(self):
        for rec in self:
            if rec.student_id and rec.student_id.company_id and rec.student_id.company_id != rec.company_id:
                raise ValidationError(_(
                    'Enrollment company must match the student\'s company (%s).') % rec.student_id.company_id.name)
            if rec.group_id and rec.group_id.company_id and rec.group_id.company_id != rec.company_id:
                raise ValidationError(_(
                    'Enrollment company must match the group\'s company (%s).') % rec.group_id.company_id.name)

    def _check_dates(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.start_date > rec.end_date:
                raise ValidationError(_('Enrollment start date cannot be after end date.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._resolve_billing_defaults(vals)
            group = self.env['education.group'].browse(vals.get('group_id'))
            if group and vals.get('state', 'draft') in ('draft', 'active'):
                self._check_capacity(group, force=self.env.context.get('force_enrollment'))
        return super().create(vals_list)

    def _resolve_billing_defaults(self, vals):
        """Server-side equivalent of the group_id/fee_plan_id onchange cascade.
        Onchange methods only fire inside the web form; an enrollment created
        via import, an API call, or any other server-side path would
        otherwise end up with no fee_plan_id/gross_fee at all, and
        _ensure_fee_record() would then silently create no charge for that
        student when the enrollment goes active. This makes the group's
        default fee plan (and its amount) apply regardless of how the
        enrollment record came to exist."""
        if not vals.get('fee_plan_id') and vals.get('group_id'):
            group = self.env['education.group'].browse(vals['group_id'])
            if group.fee_plan_id:
                vals['fee_plan_id'] = group.fee_plan_id.id
        if vals.get('fee_plan_id') and not vals.get('gross_fee'):
            plan = self.env['education.fee.plan'].browse(vals['fee_plan_id'])
            if plan.billing_type == 'per_session':
                vals.setdefault('billing_type', 'per_session')
                vals.setdefault('session_count', plan.session_count)
                vals.setdefault('price_per_session', plan.price_per_session)
                vals['gross_fee'] = plan.session_count * plan.price_per_session
            else:
                vals['gross_fee'] = plan.amount
            if plan.discount_policy != 'none' and not vals.get('discount_type'):
                vals['discount_type'] = plan.discount_policy
                vals['discount_value'] = plan.discount_value
        return vals

    def write(self, vals):
        if vals.get('state') == 'active':
            for rec in self:
                self._check_capacity(rec.group_id, force=self.env.context.get('force_enrollment'), exclude=rec)
        return super().write(vals)

    def _check_capacity(self, group, force=False, exclude=None):
        if not group or not group.capacity:
            return
        if force or self.env.user.has_group('prime_educational_hub.group_education_admin'):
            return
        domain = [('group_id', '=', group.id), ('state', '=', 'active')]
        if exclude:
            domain.append(('id', '!=', exclude.id))
        active_count = self.search_count(domain)
        if active_count >= group.capacity:
            raise ValidationError(_(
                'Group "%s" has reached its capacity (%s). '
                'Add the student to the Waiting List, or ask an Education Administrator to override.'
            ) % (group.name, group.capacity))

    def action_set_active(self):
        for rec in self:
            rec._check_capacity(rec.group_id, force=self.env.context.get('force_enrollment'), exclude=rec)
            rec._check_student_status(force=self.env.context.get('force_enrollment'))
        self.write({'state': 'active'})
        for rec in self:
            rec._ensure_fee_record()

    def _check_student_status(self, force=False):
        self.ensure_one()
        if force or self.env.user.has_group('prime_educational_hub.group_education_admin'):
            return
        if self.student_id.state != 'active':
            raise ValidationError(_(
                'Student "%s" is currently "%s" and cannot be actively enrolled. '
                'An Education Administrator can override this if needed.'
            ) % (self.student_id.name, dict(self.student_id._fields['state'].selection).get(self.student_id.state)))

    def _ensure_fee_record(self):
        """Create the underlying Fee (+ installments) the first time an
        enrollment becomes active, if one doesn't already exist and a
        gross fee has been set."""
        self.ensure_one()
        if self.fee_ids:
            return
        if not self.gross_fee:
            # Nothing to bill and _resolve_billing_defaults() found no group
            # fee plan to fall back on either - this student is being
            # activated with zero fees. That's valid for a genuinely free
            # enrollment, but it's exactly as likely to mean "the group has
            # no fee plan configured and nobody noticed" - so flag it loudly
            # instead of leaving it silent.
            self.message_post(body=_(
                'This enrollment was activated with no Gross Fee and no Fee Plan resolved from '
                'the group, so no Fee/Installments were created. If "%s" should be billed, set a '
                'Fee Plan on the group or a Gross Fee on this enrollment and use "Regenerate Fee".'
            ) % self.student_id.name)
            return
        fee = self.env['education.fee'].create({
            'student_id': self.student_id.id,
            'enrollment_id': self.id,
            'group_id': self.group_id.id,
            'fee_plan_id': self.fee_plan_id.id,
            'gross_amount': self.gross_fee,
            'discount_type': self.discount_type,
            'discount_value': self.discount_value,
            'currency_id': self.currency_id.id,
            'date': self.enrollment_date or fields.Date.context_today(self),
        })
        fee.action_confirm()

    def action_regenerate_fee(self):
        """Manual recovery for the case _ensure_fee_record() flagged: an
        enrollment went active with nothing to bill. Once a Gross Fee or
        Fee Plan has been set on the record, this (re)runs fee creation
        without requiring the enrollment to be deactivated and reactivated."""
        for rec in self:
            if rec.fee_ids:
                raise UserError(_(
                    'This enrollment already has a Fee record ("%s"). Cancel it first if it needs '
                    'to be regenerated, to keep the payment audit trail intact.'
                ) % rec.fee_ids[0].display_name)
            rec._ensure_fee_record()

    @api.depends('fee_ids')
    def _compute_fee_count(self):
        for rec in self:
            rec.fee_count = len(rec.fee_ids)

    def action_view_fee(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Fee'),
            'res_model': 'education.fee',
            'view_mode': 'list,form',
            'domain': [('enrollment_id', '=', self.id)],
            'context': {'default_enrollment_id': self.id},
        }

    def action_set_completed(self):
        self.write({'state': 'completed'})
        self.mapped('group_id')._notify_waitlist_of_available_seat()

    def action_set_cancelled(self):
        self.write({'state': 'cancelled'})
        self.mapped('group_id')._notify_waitlist_of_available_seat()
        # Mirror Group -> Sessions: cascade the cancellation down to the fee,
        # but only where it's still safe to -- a fee with payments allocated
        # against it is left alone (matches Fee.action_cancel's own guard),
        # so a cashier has to consciously handle the refund instead of it
        # silently disappearing.
        cancellable_fees = self.mapped('fee_ids').filtered(
            lambda f: f.state != 'cancelled' and not f.paid_amount)
        if cancellable_fees:
            cancellable_fees.action_cancel()
