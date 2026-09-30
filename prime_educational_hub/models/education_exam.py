# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class EducationExam(models.Model):
    _name = 'education.exam'
    _description = 'Exam'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'exam_date desc'

    name = fields.Char(string='Name', required=True, tracking=True)
    code = fields.Char(string='Code', copy=False)
    subject_id = fields.Many2one('education.subject', string='Subject', required=True, tracking=True)
    group_id = fields.Many2one('education.group', string='Group', required=True, tracking=True)
    academic_year_id = fields.Many2one('education.academic.year', string='Academic Year')
    term_id = fields.Many2one('education.term', string='Term',
                               domain="[('academic_year_id', '=', academic_year_id)]")
    exam_date = fields.Date(string='Exam Date', tracking=True)
    duration_minutes = fields.Integer(string='Duration (Minutes)', default=60)
    max_mark = fields.Float(string='Max Mark', required=True, default=100.0, tracking=True)
    pass_mark = fields.Float(string='Pass Mark', required=True, default=50.0, tracking=True)
    exam_type = fields.Selection([
        ('quiz', 'Quiz'),
        ('midterm', 'Midterm'),
        ('final', 'Final'),
        ('practical', 'Practical'),
        ('oral', 'Oral'),
        ('other', 'Other'),
    ], string='Exam Type', default='quiz', required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', tracking=True, required=True)
    tie_break_mode = fields.Selection([
        ('same_rank', 'Same Rank for Ties (1,2,2,4)'),
        ('sequential', 'Sequential Rank (1,2,3,4)'),
    ], string='Tie Break Rule', default=lambda self: self._default_tie_break_mode(), required=True)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    question_ids = fields.One2many('education.exam.question', 'exam_id', string='Questions')
    question_count = fields.Integer(string='Questions Count', compute='_compute_question_count')
    question_marks_total = fields.Float(string='Questions Total Marks', compute='_compute_question_count')

    result_ids = fields.One2many('education.exam.result', 'exam_id', string='Results')
    result_count = fields.Integer(string='Results Count', compute='_compute_result_stats')
    average_percentage = fields.Float(string='Average %', compute='_compute_result_stats')
    pass_rate = fields.Float(string='Pass Rate %', compute='_compute_result_stats')

    _sql_constraints = [
        ('code_uniq', 'unique(code, company_id)', 'Exam code must be unique per company.'),
    ]

    def _default_tie_break_mode(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'prime_educational_hub.default_exam_tie_break_mode', 'same_rank')

    @api.depends('question_ids.max_mark')
    def _compute_question_count(self):
        for rec in self:
            rec.question_count = len(rec.question_ids)
            rec.question_marks_total = sum(rec.question_ids.mapped('max_mark'))

    @api.depends('result_ids.percentage', 'result_ids.passed')
    def _compute_result_stats(self):
        for rec in self:
            results = rec.result_ids
            rec.result_count = len(results)
            rec.average_percentage = (sum(results.mapped('percentage')) / len(results)) if results else 0.0
            rec.pass_rate = (len(results.filtered('passed')) / len(results) * 100.0) if results else 0.0

    @api.constrains('max_mark')
    def _check_max_mark_positive(self):
        for rec in self:
            if rec.max_mark <= 0:
                raise ValidationError(_('Exam "%s": Max Mark must be positive.') % rec.name)

    @api.constrains('pass_mark', 'max_mark')
    def _check_pass_mark(self):
        for rec in self:
            if not (0 <= rec.pass_mark <= rec.max_mark):
                raise ValidationError(_(
                    'Exam "%s": Pass Mark must be between 0 and the Max Mark (%.2f).'
                ) % (rec.name, rec.max_mark))

    def _check_edit_allowed(self):
        """Published/closed exams are protected from casual editing."""
        is_privileged = self.env.user.has_group('prime_educational_hub.group_education_admin') or \
            self.env.user.has_group('prime_educational_hub.group_education_supervisor')
        for rec in self:
            if rec.state != 'draft' and not is_privileged:
                raise ValidationError(_(
                    'Exam "%s" is %s and can only be modified by an Academic Supervisor or Administrator.'
                ) % (rec.name, rec.state))

    def write(self, vals):
        protected_fields = {'subject_id', 'group_id', 'max_mark', 'pass_mark', 'exam_date', 'exam_type'}
        if protected_fields.intersection(vals.keys()):
            self._check_edit_allowed()
        return super().write(vals)

    def action_publish(self):
        for rec in self:
            if rec.question_ids and abs(rec.question_marks_total - rec.max_mark) > 0.001:
                raise UserError(_(
                    'Exam "%s": the sum of question marks (%.2f) must equal the Exam Max Mark (%.2f) before publishing.'
                ) % (rec.name, rec.question_marks_total, rec.max_mark))
        self.write({'state': 'published'})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_reset_to_draft(self):
        self._check_edit_allowed()
        self.write({'state': 'draft'})

    def action_view_questions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Questions'),
            'res_model': 'education.exam.question',
            'view_mode': 'list,form',
            'domain': [('exam_id', '=', self.id)],
            'context': {'default_exam_id': self.id},
        }

    def action_view_results(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Results'),
            'res_model': 'education.exam.result',
            'view_mode': 'list,form',
            'domain': [('exam_id', '=', self.id)],
            'context': {'default_exam_id': self.id},
        }

    def action_generate_results_for_group(self):
        """Create a draft result line for every actively enrolled student who
        doesn't already have one for this exam."""
        self.ensure_one()
        Result = self.env['education.exam.result']
        existing_student_ids = self.result_ids.student_id.ids
        active_students = self.group_id.enrollment_ids.filtered(lambda e: e.state == 'active').student_id
        to_create = [
            {'exam_id': self.id, 'student_id': student.id, 'mark': 0.0}
            for student in active_students if student.id not in existing_student_ids
        ]
        if to_create:
            Result.create(to_create)
        return self.action_view_results()
