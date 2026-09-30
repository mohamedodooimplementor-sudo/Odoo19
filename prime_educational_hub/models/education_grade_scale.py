# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EducationGradeScale(models.Model):
    _name = 'education.grade.scale'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Grade Scale'
    _order = 'sequence, min_percentage desc'

    name = fields.Char(string='Name', required=True)
    min_percentage = fields.Float(string='Min %', required=True)
    max_percentage = fields.Float(string='Max %', required=True)
    grade = fields.Char(string='Grade', required=True, help='e.g. A, B+, Excellent')
    label = fields.Char(string='Label', help='e.g. Excellent, Very Good, Needs Improvement')
    sequence = fields.Integer(string='Sequence', default=10)
    pass_grade = fields.Boolean(string='Is Passing Grade', default=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.constrains('min_percentage', 'max_percentage')
    def _check_range(self):
        for rec in self:
            if rec.min_percentage >= rec.max_percentage:
                raise ValidationError(_('Grade Scale "%s": Min %% must be less than Max %%.') % rec.name)

    @api.constrains('min_percentage', 'max_percentage', 'active', 'company_id')
    def _check_no_overlap(self):
        for rec in self:
            if not rec.active:
                continue
            domain = [
                ('id', '!=', rec.id),
                ('active', '=', True),
                ('company_id', '=', rec.company_id.id),
                ('min_percentage', '<', rec.max_percentage),
                ('max_percentage', '>', rec.min_percentage),
            ]
            overlapping = self.search(domain, limit=1)
            if overlapping:
                raise ValidationError(_(
                    'Grade Scale "%s" (%.2f%%-%.2f%%) overlaps with "%s" (%.2f%%-%.2f%%).'
                ) % (rec.name, rec.min_percentage, rec.max_percentage,
                     overlapping.name, overlapping.min_percentage, overlapping.max_percentage))

    @api.model
    def get_grade_for_percentage(self, percentage, company_id=None):
        domain = [
            ('min_percentage', '<=', percentage),
            ('max_percentage', '>=', percentage),
            ('active', '=', True),
        ]
        if company_id:
            domain.append(('company_id', '=', company_id))
        return self.search(domain, limit=1)
