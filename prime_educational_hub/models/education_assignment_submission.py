# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EducationAssignmentSubmission(models.Model):
    _name = 'education.assignment.submission'
    _description = 'Assignment Submission'
    _order = 'assignment_id, student_id'

    assignment_id = fields.Many2one('education.assignment', string='Assignment', required=True, ondelete='cascade')
    student_id = fields.Many2one('education.student', string='Student', required=True, ondelete='cascade')
    group_id = fields.Many2one(related='assignment_id.group_id', string='Group', store=True)
    due_date = fields.Date(related='assignment_id.due_date', string='Due Date', store=True)
    max_mark = fields.Float(related='assignment_id.max_mark', string='Max Mark', store=True)
    company_id = fields.Many2one(related='assignment_id.company_id', string='Company', store=True)
    submission_date = fields.Date(string='Submission Date')
    status = fields.Selection([
        ('pending', 'Pending'),
        ('submitted', 'Submitted'),
        ('late', 'Late'),
        ('not_submitted', 'Not Submitted'),
    ], string='Status', default='pending', required=True, tracking=True)
    mark = fields.Float(string='Mark')
    feedback = fields.Text(string='Feedback')
    attachment_ids = fields.Many2many('ir.attachment', 'education_submission_attachment_rel',
                                       'submission_id', 'attachment_id', string='Attachments')

    _sql_constraints = [
        ('assignment_student_uniq', 'unique(assignment_id, student_id)',
         'This student already has a submission record for this assignment.'),
    ]

    @api.onchange('submission_date')
    def _onchange_submission_date(self):
        if self.submission_date:
            if self.due_date and self.submission_date > self.due_date:
                self.status = 'late'
            else:
                self.status = 'submitted'

    @api.constrains('mark', 'max_mark')
    def _check_mark_range(self):
        for rec in self:
            if rec.mark and not (0 <= rec.mark <= rec.max_mark):
                raise ValidationError(_(
                    'Submission mark (%.2f) must be between 0 and the assignment max mark (%.2f).'
                ) % (rec.mark, rec.max_mark))
