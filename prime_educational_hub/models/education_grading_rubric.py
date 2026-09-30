# -*- coding: utf-8 -*-
from odoo import api, fields, models


class EducationGradingRubric(models.Model):
    _name = 'education.grading.rubric'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Grading Rubric'
    _order = 'name'

    name = fields.Char(string='Rubric Name', required=True)
    subject_id = fields.Many2one('education.subject', string='Subject')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    criteria_ids = fields.One2many('education.grading.rubric.criteria', 'rubric_id', string='Criteria')
    total_max_mark = fields.Float(string='Total Max Mark', compute='_compute_total_max_mark')

    @api.depends('criteria_ids.max_mark')
    def _compute_total_max_mark(self):
        for rec in self:
            rec.total_max_mark = sum(rec.criteria_ids.mapped('max_mark'))


class EducationGradingRubricCriteria(models.Model):
    _name = 'education.grading.rubric.criteria'
    _description = 'Grading Rubric Criterion'
    _order = 'rubric_id, sequence'

    rubric_id = fields.Many2one('education.grading.rubric', string='Rubric', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    name = fields.Char(string='Criterion', required=True)
    description = fields.Text(string='Description')
    max_mark = fields.Float(string='Max Mark', default=1.0)
