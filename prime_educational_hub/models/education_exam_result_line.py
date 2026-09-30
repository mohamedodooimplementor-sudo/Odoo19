# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EducationExamResultLine(models.Model):
    _name = 'education.exam.result.line'
    _description = 'Exam Result Line (per-question mark)'
    _order = 'result_id, question_id'

    result_id = fields.Many2one('education.exam.result', string='Result', required=True, ondelete='cascade')
    question_id = fields.Many2one('education.exam.question', string='Question', required=True, ondelete='cascade')
    question_text = fields.Text(related='question_id.question_text', string='Question')
    max_mark = fields.Float(related='question_id.max_mark', string='Max Mark', store=True)
    mark_obtained = fields.Float(string='Mark Obtained', default=0.0)
    student_answer = fields.Text(string="Student's Answer")
    is_correct = fields.Boolean(string='Correct', compute='_compute_is_correct', store=True)

    _sql_constraints = [
        ('result_question_uniq', 'unique(result_id, question_id)',
         'This question already has a recorded mark for this result.'),
    ]

    @api.depends('mark_obtained', 'max_mark')
    def _compute_is_correct(self):
        for rec in self:
            rec.is_correct = rec.max_mark > 0 and rec.mark_obtained >= rec.max_mark

    @api.constrains('mark_obtained', 'max_mark')
    def _check_mark_range(self):
        for rec in self:
            if not (0 <= rec.mark_obtained <= rec.max_mark):
                raise ValidationError(_(
                    'Mark obtained (%.2f) must be between 0 and the question max mark (%.2f).'
                ) % (rec.mark_obtained, rec.max_mark))
