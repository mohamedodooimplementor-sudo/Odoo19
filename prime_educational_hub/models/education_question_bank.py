# -*- coding: utf-8 -*-
from odoo import fields, models


class EducationQuestionBank(models.Model):
    _name = 'education.question.bank'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Question Bank'
    _order = 'subject_id, sequence'

    name = fields.Char(string='Title', compute='_compute_name', store=True)
    sequence = fields.Integer(string='Sequence', default=10)
    subject_id = fields.Many2one('education.subject', string='Subject')
    level_id = fields.Many2one('education.level', string='Level')
    question_text = fields.Text(string='Question Text', required=True)
    question_type = fields.Selection([
        ('mcq', 'Multiple Choice'),
        ('true_false', 'True / False'),
        ('short_answer', 'Short Answer'),
        ('essay', 'Essay'),
        ('practical', 'Practical'),
    ], string='Question Type', required=True, default='mcq')
    default_max_mark = fields.Float(string='Default Max Mark', default=1.0)
    choices = fields.Text(string='Choices', help='One choice per line (for MCQ / True-False).')
    correct_answer = fields.Char(string='Correct Answer')
    notes = fields.Text(string='Notes')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    def _compute_name(self):
        for rec in self:
            text = (rec.question_text or '').strip().replace('\n', ' ')
            rec.name = (text[:60] + '…') if len(text) > 60 else (text or 'Question')
