# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EducationTeacherPayout(models.Model):
    _name = 'education.teacher.payout'
    _description = 'Teacher Payout'
    _inherit = ['mail.thread']
    _order = 'period_start desc, teacher_id'

    teacher_id = fields.Many2one('education.teacher', string='Teacher', required=True, tracking=True)
    period_start = fields.Date(string='Period Start', required=True, tracking=True)
    period_end = fields.Date(string='Period End', required=True, tracking=True)
    compensation_type = fields.Selection(related='teacher_id.compensation_type', string='Compensation Type', store=True)

    session_count = fields.Integer(string='Completed Sessions in Period', compute='_compute_payout', store=True)
    fees_collected = fields.Monetary(string='Fees Collected (Their Groups)', compute='_compute_payout', store=True)
    rate_used = fields.Monetary(string='Rate/Session Used', compute='_compute_payout', store=True)
    commission_percentage_used = fields.Float(string='% Used', compute='_compute_payout', store=True)
    amount = fields.Monetary(string='Payable Amount', compute='_compute_payout', store=True, tracking=True)

    currency_id = fields.Many2one('res.currency', string='Currency', default=lambda self: self.env.company.currency_id)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('paid', 'Paid'),
    ], string='Status', default='draft', tracking=True, required=True)
    payment_date = fields.Date(string='Payment Date', tracking=True)
    cash_account_id = fields.Many2one('education.cash.account', string='Paid From',
                                       default=lambda self: self._default_cash_account())
    notes = fields.Text(string='Notes')

    _sql_constraints = [
        ('teacher_period_uniq', 'unique(teacher_id, period_start, period_end)',
         'A payout for this teacher and period already exists.'),
    ]

    @api.model
    def _default_cash_account(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'prime_educational_hub.default_cash_account_id')
        return int(param) if param else False

    @api.depends('teacher_id', 'period_start', 'period_end', 'teacher_id.compensation_type',
                 'teacher_id.rate_per_session', 'teacher_id.commission_percentage', 'teacher_id.fixed_salary')
    def _compute_payout(self):
        Session = self.env['education.session'].sudo()
        Payment = self.env['education.payment'].sudo()
        for rec in self:
            teacher = rec.teacher_id
            sessions = Session
            fees = 0.0
            if teacher and rec.period_start and rec.period_end:
                sessions = Session.search([
                    ('teacher_id', '=', teacher.id),
                    ('date', '>=', rec.period_start), ('date', '<=', rec.period_end),
                    ('state', '=', 'completed'),
                ])
                if teacher.compensation_type == 'percentage' and teacher.group_ids:
                    payments = Payment.search([
                        ('state', '=', 'confirmed'),
                        ('payment_date', '>=', rec.period_start), ('payment_date', '<=', rec.period_end),
                        ('group_id', 'in', teacher.group_ids.ids),
                    ])
                    fees = sum(payments.mapped('amount'))
            rec.session_count = len(sessions)
            rec.fees_collected = fees
            rec.rate_used = teacher.rate_per_session if teacher else 0.0
            rec.commission_percentage_used = teacher.commission_percentage if teacher else 0.0

            if not teacher or teacher.compensation_type == 'none':
                rec.amount = 0.0
            elif teacher.compensation_type == 'per_session':
                rec.amount = rec.session_count * teacher.rate_per_session
            elif teacher.compensation_type == 'percentage':
                rec.amount = fees * (teacher.commission_percentage / 100.0)
            elif teacher.compensation_type == 'fixed':
                rec.amount = teacher.fixed_salary
            else:
                rec.amount = 0.0

    def action_confirm(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft payouts can be confirmed.'))
        self.write({'state': 'confirmed'})

    def action_mark_paid(self):
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('Only confirmed payouts can be marked as paid.'))
            if not rec.cash_account_id:
                raise UserError(_('Please set the "Paid From" cash/bank account before marking this payout paid.'))
        self.write({'state': 'paid', 'payment_date': fields.Date.context_today(self)})

    def action_reset_draft(self):
        for rec in self:
            if rec.state == 'paid':
                raise UserError(_('A paid payout cannot be reset to draft.'))
        self.write({'state': 'draft'})

    @api.model
    def _generate_for_period(self, period_start, period_end, teacher_ids=None):
        """Bulk-creates (or returns existing) payout records for every teacher
        with a compensation plan set up, for the given period. Skips teachers
        that already have a payout for that exact period."""
        Teacher = self.env['education.teacher']
        domain = [('compensation_type', '!=', 'none')]
        if teacher_ids:
            domain.append(('id', 'in', teacher_ids))
        teachers = Teacher.search(domain)
        created = self.browse()
        for teacher in teachers:
            existing = self.search([
                ('teacher_id', '=', teacher.id),
                ('period_start', '=', period_start), ('period_end', '=', period_end),
            ], limit=1)
            if existing:
                continue
            created |= self.create({
                'teacher_id': teacher.id, 'period_start': period_start, 'period_end': period_end,
            })
        return created
