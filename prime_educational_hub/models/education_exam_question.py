# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EducationExamQuestion(models.Model):
    _name = 'education.exam.question'
    _description = 'Exam Question'
    _order = 'exam_id, sequence'

    exam_id = fields.Many2one('education.exam', string='Exam', required=True, ondelete='cascade')
    question_bank_id = fields.Many2one('education.question.bank', string='From Question Bank')
    sequence = fields.Integer(string='Sequence', default=10)
    question_text = fields.Text(string='Question Text', required=True)
    question_type = fields.Selection([
        ('mcq', 'Multiple Choice'),
        ('true_false', 'True / False'),
        ('short_answer', 'Short Answer'),
        ('essay', 'Essay'),
        ('practical', 'Practical'),
    ], string='Question Type', required=True, default='mcq')
    max_mark = fields.Float(string='Max Mark', required=True, default=1.0)
    weight = fields.Float(string='Weight', default=1.0)
    company_id = fields.Many2one(related='exam_id.company_id', string='Company', store=True)
    choices = fields.Text(string='Choices', help='One choice per line (for MCQ / True-False).')
    correct_answer = fields.Char(string='Correct Answer')

    @api.onchange('question_bank_id')
    def _onchange_question_bank_id(self):
        if self.question_bank_id:
            bank = self.question_bank_id
            self.question_text = bank.question_text
            self.question_type = bank.question_type
            self.max_mark = bank.default_max_mark
            self.choices = bank.choices
            self.correct_answer = bank.correct_answer

    @api.constrains('max_mark')
    def _check_max_mark_positive(self):
        for rec in self:
            if rec.max_mark <= 0:
                raise ValidationError(_('Question max mark must be positive.'))

    @api.constrains('exam_id')
    def _check_exam_editable(self):
        for rec in self:
            if rec.exam_id:
                rec.exam_id._check_edit_allowed()
