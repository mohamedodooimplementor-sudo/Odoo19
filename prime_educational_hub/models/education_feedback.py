# -*- coding: utf-8 -*-
from odoo import api, fields, models


class EducationFeedback(models.Model):
    _name = 'education.feedback'
    _description = 'Student Feedback / Satisfaction'
    _order = 'create_date desc'

    student_id = fields.Many2one('education.student', string='Student', required=True, ondelete='cascade')
    rating = fields.Selection([
        ('1', '1 - Very Dissatisfied'),
        ('2', '2 - Dissatisfied'),
        ('3', '3 - Neutral'),
        ('4', '4 - Satisfied'),
        ('5', '5 - Very Satisfied'),
    ], string='Rating', required=True)
    comment = fields.Text(string='Comment')
    context_label = fields.Char(string='Context', help='e.g. "End of Term 1" or an exam name - free text, '
                                                         'set by whoever/whatever prompted the feedback.')
    source = fields.Selection([
        ('portal', 'Student Portal'),
        ('manual', 'Entered by Staff'),
    ], string='Source', default='manual', required=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.model
    def get_average_rating(self, domain=None):
        """Simple helper for the dashboard/reporting: average rating (as a
        float out of 5) over the given domain, or all feedback if none."""
        records = self.search(domain or [])
        if not records:
            return 0.0
        return sum(int(r.rating) for r in records) / len(records)
