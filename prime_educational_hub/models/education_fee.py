# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

from .education_config_helpers import get_default_currency, get_discount_approval_threshold


class EducationFee(models.Model):
    _name = 'education.fee'
    _description = 'Student Fee / Charge'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc'

    student_id = fields.Many2one('education.student', string='Student', required=True, tracking=True)
    enrollment_id = fields.Many2one('education.enrollment', string='Enrollment',
                                     domain="[('student_id', '=', student_id)]")
    group_id = fields.Many2one('education.group', string='Group')
    fee_plan_id = fields.Many2one('education.fee.plan', string='Fee Plan')

    gross_amount = fields.Monetary(string='Gross Amount', required=True, currency_field='currency_id')
    discount_type = fields.Selection([
        ('fixed', 'Fixed Amount'),
        ('percent', 'Percentage'),
    ], string='Discount Type')
    discount_value = fields.Float(string='Discount Value')
    discount_amount = fields.Monetary(string='Discount Amount', compute='_compute_amounts', store=True,
                                       currency_field='currency_id')
    net_amount = fields.Monetary(string='Net Amount', compute='_compute_amounts', store=True,
                                  currency_field='currency_id')
    discount_percent = fields.Float(string='Discount %', compute='_compute_amounts', store=True,
                                     help='Discount amount as a percentage of the gross amount, used to '
                                          'decide whether this fee needs discount approval.')
    discount_needs_approval = fields.Boolean(string='Discount Needs Approval',
                                              compute='_compute_discount_needs_approval')
    discount_approved_by = fields.Many2one('res.users', string='Discount Approved By', readonly=True, copy=False)
    discount_approved_on = fields.Datetime(string='Discount Approved On', readonly=True, copy=False)
    currency_id = fields.Many2one('res.currency', string='Currency',
                                   default=lambda self: get_default_currency(self.env))
    date = fields.Date(string='Date', default=fields.Date.context_today, required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, required=True)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    installment_ids = fields.One2many('education.installment', 'fee_id', string='Installments')
    installment_count = fields.Integer(string='Installments Count', compute='_compute_installment_stats')
    paid_amount = fields.Monetary(string='Paid Amount', compute='_compute_installment_stats',
                                   currency_field='currency_id')
    outstanding_amount = fields.Monetary(string='Outstanding Amount', compute='_compute_installment_stats',
                                          currency_field='currency_id', store=True)

    @api.depends('gross_amount', 'discount_type', 'discount_value')
    def _compute_amounts(self):
        for rec in self:
            discount = 0.0
            if rec.discount_type == 'fixed':
                discount = rec.discount_value
            elif rec.discount_type == 'percent':
                discount = rec.gross_amount * (rec.discount_value / 100.0)
            discount = min(discount, rec.gross_amount) if rec.gross_amount else discount
            rec.discount_amount = discount
            rec.net_amount = rec.gross_amount - discount
            rec.discount_percent = (discount / rec.gross_amount * 100.0) if rec.gross_amount else 0.0

    @api.depends('discount_percent', 'discount_approved_by')
    def _compute_discount_needs_approval(self):
        threshold = get_discount_approval_threshold(self.env)
        for rec in self:
            rec.discount_needs_approval = (
                threshold > 0 and rec.discount_percent >= threshold and not rec.discount_approved_by
            )

    def action_approve_discount(self):
        if not (self.env.user.has_group('prime_educational_hub.group_education_admin')
                or self.env.user.has_group('prime_educational_hub.group_education_supervisor')):
            raise UserError(_('Only an Admin or Supervisor can approve a discount.'))
        for rec in self:
            if not rec.discount_needs_approval and rec.discount_approved_by:
                continue
            rec.write({
                'discount_approved_by': self.env.user.id,
                'discount_approved_on': fields.Datetime.now(),
            })
            rec.message_post(body=_(
                '%(discount).1f%% discount approved by %(user)s.'
            ) % {'discount': rec.discount_percent, 'user': self.env.user.name})

    @api.depends('installment_ids.paid_amount', 'installment_ids.amount')
    def _compute_installment_stats(self):
        for rec in self:
            lines = rec.installment_ids
            rec.installment_count = len(lines)
            rec.paid_amount = sum(lines.mapped('paid_amount'))
            rec.outstanding_amount = sum(lines.mapped('remaining_amount'))

    @api.constrains('company_id', 'currency_id', 'student_id', 'enrollment_id')
    def _check_company_currency_consistency(self):
        for rec in self:
            if rec.student_id and rec.student_id.company_id and rec.student_id.company_id != rec.company_id:
                raise ValidationError(_(
                    'Fee company must match the student\'s company (%s).') % rec.student_id.company_id.name)
            if rec.enrollment_id:
                if rec.enrollment_id.company_id and rec.enrollment_id.company_id != rec.company_id:
                    raise ValidationError(_(
                        'Fee company must match the enrollment\'s company (%s).'
                    ) % rec.enrollment_id.company_id.name)
                if rec.enrollment_id.currency_id and rec.currency_id != rec.enrollment_id.currency_id:
                    raise ValidationError(_(
                        'Fee currency (%s) does not match the linked enrollment\'s currency (%s).'
                    ) % (rec.currency_id.name, rec.enrollment_id.currency_id.name))

    @api.constrains('student_id', 'enrollment_id')
    def _check_enrollment_belongs_to_student(self):
        # This is the hard guarantee that the money on this fee is tied to the
        # right student's account: the UI domain on enrollment_id only guides
        # the picker, it does not stop a mismatched value coming in through an
        # import, an API call, or a write() bypassing the form.
        for rec in self:
            if rec.enrollment_id and rec.enrollment_id.student_id != rec.student_id:
                raise ValidationError(_(
                    'This fee is set for student "%s" but its enrollment belongs to "%s". '
                    'A fee must always be linked to an enrollment of the same student.'
                ) % (rec.student_id.name, rec.enrollment_id.student_id.name))

    def write(self, vals):
        if ('discount_type' in vals or 'discount_value' in vals) and \
                not ({'discount_approved_by', 'discount_approved_on'} & set(vals)):
            vals.setdefault('discount_approved_by', False)
            vals.setdefault('discount_approved_on', False)
        return super().write(vals)

    def action_confirm(self):
        blocked = self.filtered('discount_needs_approval')
        if blocked:
            raise ValidationError(_(
                'These fees have a discount of %(threshold).0f%% or more and need approval before they can '
                'be confirmed: %(names)s. Use "Approve Discount" first (requires the Supervisor/Admin group).'
            ) % {
                'threshold': get_discount_approval_threshold(self.env),
                'names': ', '.join(blocked.mapped('display_name')),
            })
        for rec in self:
            if not rec.installment_ids:
                rec._generate_installments()
            rec._apply_available_credit()
        self.write({'state': 'confirmed'})

    def action_cancel(self):
        for rec in self:
            if rec.paid_amount:
                raise ValidationError(_(
                    'Fee for "%s" has payments allocated against it and cannot be cancelled directly. '
                    'Cancel/refund the related payments first.'
                ) % rec.student_id.name)
        self.write({'state': 'cancelled'})
        self.mapped('installment_ids').unlink()

    def _generate_installments(self):
        self.ensure_one()
        Installment = self.env['education.installment'].sudo()
        plan = self.fee_plan_id
        count = plan.installment_count if plan and plan.installment_count > 0 else 1
        frequency = plan.frequency if plan else 'one_time'
        step_map = {
            'weekly': relativedelta(weeks=1),
            'monthly': relativedelta(months=1),
            'termly': relativedelta(months=3),
            'one_time': relativedelta(),
        }
        step = step_map.get(frequency, relativedelta())

        base_amount = round(self.net_amount / count, 2)
        remaining = self.net_amount
        vals_list = []
        for i in range(count):
            due_date = self.date + (step * i)
            amount = base_amount if i < count - 1 else round(remaining, 2)
            remaining -= amount
            vals_list.append({
                'fee_id': self.id,
                'student_id': self.student_id.id,
                'sequence': i + 1,
                'due_date': due_date,
                'amount': amount,
            })
        Installment.create(vals_list)

    def _apply_available_credit(self):
        """If this student has leftover credit sitting on earlier confirmed
        payments (an overpayment that had nothing left to allocate to at the
        time), automatically apply it to this fee's installments - oldest
        credit and oldest installment first. This closes the gap the
        standalone-ledger design left: outstanding_amount already *reflected*
        a credit as a negative balance, but nothing ever actually spent it
        against a new fee. Uses the same education.payment.allocation trail
        as a normal payment, so the audit trail (and any future refund
        reversal) works identically either way."""
        self.ensure_one()
        Payment = self.env['education.payment']
        Allocation = self.env['education.payment.allocation'].sudo()
        credit_payments = Payment.search([
            ('student_id', '=', self.student_id.id),
            ('state', '=', 'confirmed'),
            ('unallocated_amount', '>', 0),
        ], order='payment_date asc, id asc')
        if not credit_payments:
            return
        installments = self.installment_ids.filtered(lambda i: i.remaining_amount > 0).sorted('due_date')
        if not installments:
            return
        inst_index = 0
        for payment in credit_payments:
            credit = payment.unallocated_amount
            while credit > 0 and inst_index < len(installments):
                inst = installments[inst_index]
                to_apply = min(inst.remaining_amount, credit)
                if to_apply > 0:
                    inst.with_context(allow_system_write=True).write({'paid_amount': inst.paid_amount + to_apply})
                    Allocation.create({
                        'payment_id': payment.id,
                        'installment_id': inst.id,
                        'amount': to_apply,
                    })
                    credit -= to_apply
                if inst.remaining_amount <= 0:
                    inst_index += 1
            if inst_index >= len(installments):
                break

    def action_view_installments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Installments'),
            'res_model': 'education.installment',
            'view_mode': 'list,form',
            'domain': [('fee_id', '=', self.id)],
        }

    def unlink(self):
        for rec in self:
            if any(rec.installment_ids.mapped('paid_amount')):
                raise ValidationError(_(
                    'Fee for "%s" has payment history recorded against its installments and cannot be '
                    'deleted. Cancel it instead to preserve the audit trail.'
                ) % rec.student_id.name)
        return super().unlink()
