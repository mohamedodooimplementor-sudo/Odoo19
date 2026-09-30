# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EducationTeacherLeaveRequest(models.Model):
    _name = 'education.teacher.leave.request'
    _description = 'Teacher Leave Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_from desc'

    teacher_id = fields.Many2one('education.teacher', string='Teacher', required=True, tracking=True)
    date_from = fields.Date(string='From', required=True, tracking=True)
    date_to = fields.Date(string='To', required=True, tracking=True)
    reason = fields.Text(string='Reason')
    state = fields.Selection([
        ('draft', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', tracking=True, required=True)
    decided_by = fields.Many2one('res.users', string='Decided By', readonly=True, copy=False)
    decision_note = fields.Text(string='Decision Note')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from > rec.date_to:
                raise UserError(_('"From" date must be on or before "To" date.'))

    def action_approve(self):
        if not (self.env.user.has_group('prime_educational_hub.group_education_admin')
                or self.env.user.has_group('prime_educational_hub.group_education_supervisor')):
            raise UserError(_('Only an Admin or Supervisor can decide on a leave request.'))
        self.write({'state': 'approved', 'decided_by': self.env.user.id})
        self._refresh_affected_session_warnings()

    def action_reject(self):
        if not (self.env.user.has_group('prime_educational_hub.group_education_admin')
                or self.env.user.has_group('prime_educational_hub.group_education_supervisor')):
            raise UserError(_('Only an Admin or Supervisor can decide on a leave request.'))
        self.write({'state': 'rejected', 'decided_by': self.env.user.id})
        self._refresh_affected_session_warnings()

    def _refresh_affected_session_warnings(self):
        """Immediately re-flags/un-flags teacher_on_leave_warning on this
        teacher's sessions in the leave date range, rather than waiting for
        the daily cron to catch up."""
        Session = self.env['education.session']
        for rec in self:
            sessions = Session.search([
                ('teacher_id', '=', rec.teacher_id.id),
                ('date', '>=', rec.date_from), ('date', '<=', rec.date_to),
            ])
            if sessions:
                sessions._compute_teacher_on_leave_warning()
