# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .education_config_helpers import has_multi_branch


class EducationRoom(models.Model):
    """A physical classroom/hall. Sessions, group default rooms, and weekly
    schedule slots all point here instead of a free-text name, so the center
    can see at a glance which rooms are free right now and which are busy."""
    _name = 'education.room'
    _description = 'Room / Classroom'
    _order = 'sequence, name'

    name = fields.Char(string='Room Name', required=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(string='Sequence', default=10)
    branch_id = fields.Many2one('education.branch', string='Branch', domain="[('company_id', '=', company_id)]")
    show_branch_field = fields.Boolean(compute='_compute_show_branch_field')
    capacity = fields.Integer(string='Capacity', help='Maximum number of students this room can seat.')
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')
    color = fields.Integer(string='Color Index')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    status = fields.Selection([
        ('free', 'Free'),
        ('occupied', 'Occupied'),
    ], string='Status Now', compute='_compute_status', store=True,
        help='Whether a session is running in this room right now. Refreshed every '
             '5 minutes by a scheduled job, and immediately whenever a session in this '
             'room is created, changed or cancelled.')
    current_session_id = fields.Many2one('education.session', string='Current Session',
                                          compute='_compute_status', store=True)
    today_session_count = fields.Integer(string="Today's Sessions", compute='_compute_status', store=True)
    next_session_id = fields.Many2one('education.session', string='Next Session Today',
                                       compute='_compute_status', store=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code, company_id)', 'Room code must be unique per company.'),
    ]

    def _compute_show_branch_field(self):
        show = has_multi_branch(self.env)
        for rec in self:
            rec.show_branch_field = show

    @api.constrains('branch_id')
    def _check_branch_required(self):
        if has_multi_branch(self.env):
            for rec in self:
                if not rec.branch_id:
                    raise ValidationError(_('Branch is required once more than one branch is configured.'))

    def _compute_status(self):
        Session = self.env['education.session']
        now = fields.Datetime.now()
        today = fields.Date.context_today(self)
        for rec in self:
            today_sessions = Session.search([
                ('room_id', '=', rec.id), ('date', '=', today), ('state', '!=', 'cancelled'),
            ], order='start_datetime')
            rec.today_session_count = len(today_sessions)
            current = today_sessions.filtered(
                lambda s: s.start_datetime and s.end_datetime and s.start_datetime <= now <= s.end_datetime)
            rec.current_session_id = current[:1]
            rec.status = 'occupied' if current else 'free'
            upcoming = today_sessions.filtered(lambda s: s.start_datetime and s.start_datetime > now)
            rec.next_session_id = upcoming[:1]

    def action_view_today_sessions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Today\'s Sessions - %s') % self.name,
            'res_model': 'education.session',
            'view_mode': 'list,form',
            'domain': [('room_id', '=', self.id), ('date', '=', fields.Date.context_today(self))],
            'context': {'default_room_id': self.id},
        }

    def _cron_refresh_room_status(self):
        """Runs every 5 minutes: force-recomputes the stored Free/Occupied
        status of every active room, the same way the overdue-installment
        cron force-recomputes installment.state — status/current_session_id/
        next_session_id depend on 'now', which no @api.depends() can express,
        so a scheduled recompute is what keeps the Room dashboard (grouped by
        this field into Free/Occupied columns) accurate."""
        rooms = self.search([])
        if rooms:
            rooms._compute_status()
