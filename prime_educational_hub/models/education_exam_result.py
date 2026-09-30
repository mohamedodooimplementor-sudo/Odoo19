# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class EducationExamResult(models.Model):
    _name = 'education.exam.result'
    _description = 'Exam Result'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'exam_id, rank'

    exam_id = fields.Many2one('education.exam', string='Exam', required=True, ondelete='cascade', tracking=True)
    student_id = fields.Many2one('education.student', string='Student', required=True, tracking=True)
    group_id = fields.Many2one(related='exam_id.group_id', string='Group', store=True)
    company_id = fields.Many2one(related='exam_id.company_id', string='Company', store=True)
    mark = fields.Float(string='Mark', required=True, default=0.0, tracking=True)
    max_mark = fields.Float(related='exam_id.max_mark', string='Max Mark', store=True)
    percentage = fields.Float(string='Percentage', compute='_compute_percentage', store=True)
    grade = fields.Char(string='Grade', compute='_compute_grade', store=True)
    passed = fields.Boolean(string='Passed', compute='_compute_passed', store=True)
    rank = fields.Integer(string='Rank', default=0, copy=False)
    teacher_comment = fields.Text(string='Teacher Comment')
    line_ids = fields.One2many('education.exam.result.line', 'result_id', string='Question-Level Marks')
    line_marks_total = fields.Float(string='Sum of Question Marks', compute='_compute_line_marks_total')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
    ], string='Status', default='draft', tracking=True, required=True)

    _sql_constraints = [
        ('exam_student_uniq', 'unique(exam_id, student_id)',
         'This student already has a result recorded for this exam.'),
    ]

    @api.depends('mark', 'max_mark')
    def _compute_percentage(self):
        for rec in self:
            rec.percentage = (rec.mark / rec.max_mark * 100.0) if rec.max_mark else 0.0

    @api.depends('percentage')
    def _compute_grade(self):
        GradeScale = self.env['education.grade.scale']
        for rec in self:
            scale = GradeScale.get_grade_for_percentage(rec.percentage, rec.exam_id.company_id.id)
            rec.grade = scale.grade if scale else False

    @api.depends('mark', 'exam_id.pass_mark')
    def _compute_passed(self):
        for rec in self:
            rec.passed = rec.mark >= rec.exam_id.pass_mark if rec.exam_id else False

    @api.constrains('mark', 'max_mark')
    def _check_mark_range(self):
        for rec in self:
            if not (0 <= rec.mark <= rec.max_mark):
                raise ValidationError(_(
                    'Result for "%s": mark (%.2f) must be between 0 and the exam max mark (%.2f).'
                ) % (rec.student_id.name, rec.mark, rec.max_mark))

    def _check_edit_allowed(self):
        is_privileged = self.env.user.has_group('prime_educational_hub.group_education_admin') or \
            self.env.user.has_group('prime_educational_hub.group_education_supervisor')
        for rec in self:
            if (rec.state == 'confirmed' or rec.exam_id.state == 'closed') and not is_privileged:
                raise ValidationError(_(
                    'This result is confirmed or the exam is closed. '
                    'Only an Academic Supervisor or Administrator can modify it.'
                ))

    def write(self, vals):
        protected_fields = {'mark', 'teacher_comment', 'student_id'}
        if protected_fields.intersection(vals.keys()) and 'state' not in vals:
            self._check_edit_allowed()
        res = super().write(vals)
        self._recompute_ranks_for_exams(self.exam_id)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self._recompute_ranks_for_exams(records.exam_id)
        return records

    def unlink(self):
        exams = self.exam_id
        res = super().unlink()
        self._recompute_ranks_for_exams(exams)
        return res

    def _recompute_ranks_for_exams(self, exams):
        for exam in exams:
            results = self.search([('exam_id', '=', exam.id)], order='percentage desc')
            tie_mode = exam.tie_break_mode
            last_percentage = None
            current_rank = 0
            for index, rec in enumerate(results, start=1):
                if tie_mode == 'sequential':
                    new_rank = index
                else:
                    if last_percentage is None or rec.percentage != last_percentage:
                        current_rank = index
                    new_rank = current_rank
                    last_percentage = rec.percentage
                if rec.rank != new_rank:
                    self.env.cr.execute(
                        'UPDATE education_exam_result SET rank = %s WHERE id = %s', (new_rank, rec.id)
                    )
            results.invalidate_recordset(['rank'])

    @api.depends('line_ids.mark_obtained')
    def _compute_line_marks_total(self):
        for rec in self:
            rec.line_marks_total = sum(rec.line_ids.mapped('mark_obtained'))

    def action_sync_mark_from_questions(self):
        """Copies the sum of per-question marks into the overall `mark`
        field. Optional — exams without question-level breakdown keep
        entering `mark` directly."""
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('This result has no question-level marks recorded yet.'))
            rec.write({'mark': rec.line_marks_total})

    def action_generate_question_lines(self):
        """Creates one result line per question on the exam, defaulted to 0,
        for teachers who want to grade question-by-question."""
        Line = self.env['education.exam.result.line']
        for rec in self:
            existing_question_ids = rec.line_ids.question_id.ids
            to_create = [
                {'result_id': rec.id, 'question_id': q.id, 'mark_obtained': 0.0}
                for q in rec.exam_id.question_ids if q.id not in existing_question_ids
            ]
            if to_create:
                Line.create(to_create)

    def action_confirm(self):
        self.write({'state': 'confirmed'})

    def action_reset_to_draft(self):
        self._check_edit_allowed()
        self.write({'state': 'draft'})
