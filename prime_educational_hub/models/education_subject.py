# -*- coding: utf-8 -*-
from odoo import fields, models


class EducationSubject(models.Model):
    _name = 'education.subject'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Subject'
    _order = 'name'

    name = fields.Char(string='Subject Name', required=True)
    code = fields.Char(string='Code')
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)
    default_duration = fields.Float(string='Default Duration (Hours)', default=1.0)
    color = fields.Integer(string='Color Index')
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    group_count = fields.Integer(string='Groups Count', compute='_compute_counts')
    teacher_count = fields.Integer(string='Teachers Count', compute='_compute_counts')

    _sql_constraints = [
        ('code_uniq', 'unique(code, company_id)', 'Subject code must be unique per company.'),
    ]

    def _compute_counts(self):
        Group = self.env['education.group']
        Teacher = self.env['education.teacher']
        for rec in self:
            rec.group_count = Group.search_count([('subject_id', '=', rec.id)])
            rec.teacher_count = Teacher.search_count([('subject_ids', 'in', rec.id)])

    def action_view_groups(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'res_model': 'education.group', 'name': 'Groups',
            'view_mode': 'list,form', 'domain': [('subject_id', '=', self.id)],
            'context': {'default_subject_id': self.id},
        }

    def action_view_teachers(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'res_model': 'education.teacher', 'name': 'Teachers',
            'view_mode': 'list,form', 'domain': [('subject_ids', 'in', self.id)],
        }
