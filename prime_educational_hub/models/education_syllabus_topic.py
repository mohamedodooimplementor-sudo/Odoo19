# -*- coding: utf-8 -*-
from odoo import api, fields, models


class EducationSyllabusTopic(models.Model):
    _name = 'education.syllabus.topic'
    _description = 'Syllabus Topic'
    _order = 'subject_id, sequence, id'

    name = fields.Char(string='Topic', required=True)
    subject_id = fields.Many2one('education.subject', string='Subject', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    _sql_constraints = [
        ('name_subject_uniq', 'unique(name, subject_id)', 'This topic already exists for this subject.'),
    ]


class EducationGroupSyllabusMixin(models.Model):
    """Adds a live syllabus-coverage percentage to a group: how many of its
    subject's topics have been marked covered in at least one of its
    sessions, out of the subject's total topic count. Lets staff spot a
    group falling behind the plan before the exam, not after."""
    _inherit = 'education.group'

    syllabus_topic_count = fields.Integer(string='Total Syllabus Topics',
                                           compute='_compute_syllabus_coverage')
    syllabus_covered_count = fields.Integer(string='Topics Covered',
                                             compute='_compute_syllabus_coverage')
    syllabus_coverage_percent = fields.Float(string='Syllabus Coverage %',
                                              compute='_compute_syllabus_coverage')

    def _compute_syllabus_coverage(self):
        Topic = self.env['education.syllabus.topic']
        for rec in self:
            total_topics = Topic.search_count([('subject_id', '=', rec.subject_id.id)]) if rec.subject_id else 0
            covered = rec.session_ids.mapped('syllabus_topic_ids').filtered(
                lambda t: t.subject_id == rec.subject_id) if rec.subject_id else rec.env['education.syllabus.topic']
            rec.syllabus_topic_count = total_topics
            rec.syllabus_covered_count = len(covered)
            rec.syllabus_coverage_percent = (len(covered) / total_topics * 100.0) if total_topics else 0.0
