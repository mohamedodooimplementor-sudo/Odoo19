# -*- coding: utf-8 -*-
from urllib.parse import quote

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class EducationAssignment(models.Model):
    _name = 'education.assignment'
    _description = 'Assignment / Homework'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'due_date desc'

    title = fields.Char(string='Title', required=True, tracking=True)
    group_id = fields.Many2one('education.group', string='Group', required=True, tracking=True)
    subject_id = fields.Many2one('education.subject', string='Subject', tracking=True)
    assigned_date = fields.Date(string='Assigned Date', default=fields.Date.context_today, required=True)
    due_date = fields.Date(string='Due Date', required=True, tracking=True)
    description = fields.Text(string='Description')
    attachment_ids = fields.Many2many('ir.attachment', 'education_assignment_attachment_rel',
                                       'assignment_id', 'attachment_id', string='Attachments')
    max_mark = fields.Float(string='Max Mark', default=10.0)
    rubric_id = fields.Many2one('education.grading.rubric', string='Grading Rubric')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', tracking=True, required=True)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    submission_ids = fields.One2many('education.assignment.submission', 'assignment_id', string='Submissions')
    submission_count = fields.Integer(string='Students Count', compute='_compute_submission_stats')
    submitted_count = fields.Integer(string='Submitted', compute='_compute_submission_stats')
    completion_percentage = fields.Float(string='Completion %', compute='_compute_submission_stats')
    average_mark = fields.Float(string='Average Mark', compute='_compute_submission_stats')

    @api.onchange('group_id')
    def _onchange_group_id(self):
        if self.group_id and self.group_id.subject_id:
            self.subject_id = self.group_id.subject_id

    @api.depends('submission_ids.status', 'submission_ids.mark')
    def _compute_submission_stats(self):
        for rec in self:
            lines = rec.submission_ids
            rec.submission_count = len(lines)
            submitted = lines.filtered(lambda s: s.status in ('submitted', 'late'))
            rec.submitted_count = len(submitted)
            rec.completion_percentage = (len(submitted) / len(lines) * 100.0) if lines else 0.0
            rec.average_mark = (sum(submitted.mapped('mark')) / len(submitted)) if submitted else 0.0

    @api.constrains('assigned_date', 'due_date')
    def _check_dates(self):
        for rec in self:
            if rec.assigned_date and rec.due_date and rec.assigned_date > rec.due_date:
                raise ValidationError(_('Assignment "%s": assigned date cannot be after the due date.') % rec.title)

    def action_publish(self):
        self.write({'state': 'published'})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_reset_to_draft(self):
        self.write({'state': 'draft'})

    def action_view_submissions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Submissions'),
            'res_model': 'education.assignment.submission',
            'view_mode': 'list,form',
            'domain': [('assignment_id', '=', self.id)],
            'context': {'default_assignment_id': self.id},
        }

    def action_generate_submissions_for_group(self):
        """Create a 'pending' submission line for every actively enrolled
        student who doesn't already have one for this assignment."""
        self.ensure_one()
        Submission = self.env['education.assignment.submission']
        existing_student_ids = self.submission_ids.student_id.ids
        active_students = self.group_id.enrollment_ids.filtered(lambda e: e.state == 'active').student_id
        to_create = [
            {'assignment_id': self.id, 'student_id': student.id, 'status': 'pending'}
            for student in active_students if student.id not in existing_student_ids
        ]
        if to_create:
            Submission.create(to_create)
        return self.action_view_submissions()

    def action_mark_overdue_as_not_submitted(self):
        """Convert any still-pending submissions past the due date to 'not_submitted'."""
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.due_date and rec.due_date < today:
                rec.submission_ids.filtered(lambda s: s.status == 'pending').write({'status': 'not_submitted'})

    def action_send_whatsapp_reminders(self):
        """Opens a WhatsApp chat for every student who hasn't submitted yet,
        one browser tab per guardian — a lightweight bulk-reminder tool with
        zero API/integration setup, matching the existing per-student
        WhatsApp reminder pattern used for fee collection."""
        self.ensure_one()
        pending = self.submission_ids.filtered(lambda s: s.status == 'pending')
        if not pending:
            raise UserError(_('No pending submissions to remind — everyone has already submitted.'))
        urls = []
        for sub in pending:
            number = sub.student_id._get_whatsapp_number()
            if not number:
                continue
            message = _(
                'Dear guardian of %(student)s,\n\n'
                'Reminder: the assignment "%(title)s" is due on %(due)s and has not been submitted yet.\n\n'
                'Thank you.'
            ) % {'student': sub.student_id.name, 'title': self.title, 'due': self.due_date}
            urls.append('https://wa.me/%s?text=%s' % (number, quote(message)))
        if not urls:
            raise UserError(_('None of the pending students have a WhatsApp/mobile number on file.'))
        # Open the first one directly; log the rest as clickable links in the
        # chatter since browsers block multiple auto-opened popups.
        if len(urls) > 1:
            links_html = ''.join(
                '<li><a href="%s" target="_blank">Reminder link %d</a></li>' % (u, i + 2)
                for i, u in enumerate(urls[1:])
            )
            self.message_post(body=_(
                'Prepared %d WhatsApp reminder(s) for pending submissions. The first opened automatically; '
                'click the rest below:<ul>%s</ul>'
            ) % (len(urls), links_html))
        return {'type': 'ir.actions.act_url', 'url': urls[0], 'target': 'new'}
