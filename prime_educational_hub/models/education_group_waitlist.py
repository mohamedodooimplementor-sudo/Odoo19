# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EducationGroupWaitlist(models.Model):
    _name = 'education.group.waitlist'
    _description = 'Group Waiting List'
    _inherit = ['mail.thread']
    _order = 'priority desc, request_date, id'

    student_id = fields.Many2one('education.student', string='Student', required=True, tracking=True)
    group_id = fields.Many2one('education.group', string='Group', required=True, tracking=True)
    request_date = fields.Date(string='Request Date', default=fields.Date.context_today, required=True)
    priority = fields.Selection([
        ('0', 'Normal'),
        ('1', 'High'),
        ('2', 'Urgent'),
    ], string='Priority', default='0')
    state = fields.Selection([
        ('waiting', 'Waiting'),
        ('enrolled', 'Enrolled'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='waiting', tracking=True, required=True)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one(related='group_id.company_id', string='Company', store=True)

    _sql_constraints = [
        ('student_group_waiting_uniq', 'unique(student_id, group_id, state)',
         'This student is already on the waiting list for this group (per status).'),
    ]

    def action_enroll_now(self):
        """Convert a waiting-list entry into an active enrollment, bypassing the
        capacity check once a seat has actually freed up (or with an override)."""
        self.ensure_one()
        if self.state != 'waiting':
            raise ValidationError(_('Only waiting entries can be enrolled.'))
        enrollment = self.env['education.enrollment'].with_context(force_enrollment=True).create({
            'student_id': self.student_id.id,
            'group_id': self.group_id.id,
            'state': 'active',
        })
        self.write({'state': 'enrolled'})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Enrollment'),
            'res_model': 'education.enrollment',
            'view_mode': 'form',
            'res_id': enrollment.id,
        }

    def action_cancel(self):
        self.write({'state': 'cancelled'})
