# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

from .education_config_helpers import float_to_time_parts, get_school_timezone


class EducationGroup(models.Model):
    _name = 'education.group'
    _description = 'Teaching Group'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'image.mixin']
    _order = 'name'

    is_published = fields.Boolean(
        string='Published on Booking Site', default=False, tracking=True,
        help='When on, this group appears on the public course-booking pages '
             '(Prime Educational Hub ▸ Configuration ▸ your own /courses site) so visitors '
             'can view it and book a seat online.')
    website_description = fields.Html(
        string='Public Description', translate=True,
        help='Public marketing copy shown on the course booking site. Separate from the '
             'internal Notes field below, which staff-only users see.')

    def action_toggle_publish(self):
        for rec in self:
            rec.is_published = not rec.is_published

    name = fields.Char(string='Group Name', required=True, tracking=True)
    code = fields.Char(string='Code', copy=False, readonly=True, default='New', tracking=True)
    subject_id = fields.Many2one('education.subject', string='Subject', required=True, tracking=True)
    level_id = fields.Many2one('education.level', string='Level')
    academic_year_id = fields.Many2one('education.academic.year', string='Academic Year',
                                        required=True, tracking=True,
                                        default=lambda self: self._default_academic_year())
    term_id = fields.Many2one('education.term', string='Term',
                               domain="[('academic_year_id', '=', academic_year_id)]")
    capacity = fields.Integer(string='Capacity', default=15, tracking=True)
    current_student_count = fields.Integer(string='Current Students', compute='_compute_current_student_count',
                                            store=True)
    seats_available = fields.Integer(string='Seats Available', compute='_compute_current_student_count', store=True)

    fee_plan_id = fields.Many2one('education.fee.plan', string='Default Fee Plan')

    room_id = fields.Many2one('education.room', string='Default Room')
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('closed', 'Closed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, required=True)
    teacher_id = fields.Many2one('education.teacher', string='Teacher', tracking=True)
    notes = fields.Text(string='Notes')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    schedule_ids = fields.One2many('education.group.schedule', 'group_id', string='Schedules')
    schedule_count = fields.Integer(string='Schedules Count', compute='_compute_schedule_count')
    enrollment_ids = fields.One2many('education.enrollment', 'group_id', string='Enrollments')
    waitlist_ids = fields.One2many('education.group.waitlist', 'group_id', string='Waiting List')
    waitlist_count = fields.Integer(string='Waiting List Count', compute='_compute_waitlist_count', store=True)
    auto_promote_waitlist = fields.Boolean(
        string='Auto-Promote Waiting List', default=False,
        help='If enabled, the next waiting-list candidate is automatically enrolled as soon as '
             'a seat frees up (e.g. another student is cancelled/completed). If disabled (default), '
             'staff only gets a chatter notification and enrolls the candidate manually after '
             'confirming interest and paperwork.')
    session_ids = fields.One2many('education.session', 'group_id', string='Sessions')
    session_count = fields.Integer(string='Sessions Count', compute='_compute_session_count')
    teacher_total_session_count = fields.Integer(
        string="Teacher's Total Sessions", compute='_compute_teacher_total_session_count',
        help="Total sessions taught by this group's teacher across ALL of their groups "
             '(not just this one) -- either as the permanent teacher or as a substitute.')
    average_attendance_percentage = fields.Float(string='Average Attendance %',
                                                  compute='_compute_average_attendance', store=True)
    exam_ids = fields.One2many('education.exam', 'group_id', string='Exams')
    exam_count = fields.Integer(string='Exams Count', compute='_compute_exam_count')
    assignment_ids = fields.One2many('education.assignment', 'group_id', string='Assignments')
    assignment_count = fields.Integer(string='Assignments Count', compute='_compute_assignment_count')
    total_outstanding = fields.Monetary(string='Total Outstanding', compute='_compute_financial_stats',
                                         currency_field='currency_id', store=True)
    total_collected = fields.Monetary(string='Total Collected', compute='_compute_financial_stats',
                                        currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency',
                                   default=lambda self: self.env.company.currency_id)

    _sql_constraints = [
        ('code_uniq', 'unique(code, company_id)', 'Group code must be unique per company.'),
    ]

    def _default_academic_year(self):
        param = self.env['ir.config_parameter'].sudo().get_param(
            'prime_educational_hub.default_academic_year_id')
        return int(param) if param else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == 'New':
                vals['code'] = self.env['ir.sequence'].next_by_code('education.group') or 'New'
        return super().create(vals_list)

    @api.depends('enrollment_ids.state', 'capacity')
    def _compute_current_student_count(self):
        for rec in self:
            active_enrollments = rec.enrollment_ids.filtered(lambda e: e.state == 'active')
            rec.current_student_count = len(active_enrollments)
            rec.seats_available = max(rec.capacity - len(active_enrollments), 0)

    @api.depends('waitlist_ids.state')
    def _compute_waitlist_count(self):
        for rec in self:
            rec.waitlist_count = len(rec.waitlist_ids.filtered(lambda w: w.state == 'waiting'))

    @api.depends('session_ids')
    def _compute_session_count(self):
        for rec in self:
            rec.session_count = len(rec.session_ids)

    @api.depends('teacher_id')
    def _compute_teacher_total_session_count(self):
        # sudo(): this is a cross-group figure about the teacher, not about
        # records this group's own access rules would otherwise expose.
        Session = self.env['education.session'].sudo()
        for rec in self:
            rec.teacher_total_session_count = Session.search_count(
                [('teacher_id', '=', rec.teacher_id.id)]) if rec.teacher_id else 0

    @api.depends('enrollment_ids.attendance_percentage', 'enrollment_ids.state')
    def _compute_average_attendance(self):
        for rec in self:
            active = rec.enrollment_ids.filtered(lambda e: e.state == 'active')
            rec.average_attendance_percentage = (
                sum(active.mapped('attendance_percentage')) / len(active) if active else 0.0
            )

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.start_date > rec.end_date:
                raise ValidationError(_('Group "%s": start date cannot be after end date.') % rec.name)

    def action_set_active(self):
        self.write({'state': 'active'})

    def action_set_closed(self):
        self.write({'state': 'closed'})

    def action_set_cancelled(self):
        self.write({'state': 'cancelled'})
        sessions_to_cancel = self.env['education.session'].search([
            ('group_id', 'in', self.ids), ('state', 'in', ('planned', 'open')),
        ])
        if sessions_to_cancel:
            sessions_to_cancel.action_cancel()

    @api.depends('schedule_ids')
    def _compute_schedule_count(self):
        for rec in self:
            rec.schedule_count = len(rec.schedule_ids)

    def action_view_schedules(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Schedules'),
            'res_model': 'education.group.schedule',
            'view_mode': 'list,form',
            'domain': [('group_id', '=', self.id)],
            'context': {'default_group_id': self.id},
        }

    def action_view_enrollments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Enrollments'),
            'res_model': 'education.enrollment',
            'view_mode': 'list,form',
            'domain': [('group_id', '=', self.id)],
            'context': {'default_group_id': self.id},
        }

    def action_view_waitlist(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Waiting List'),
            'res_model': 'education.group.waitlist',
            'view_mode': 'list,form',
            'domain': [('group_id', '=', self.id)],
            'context': {'default_group_id': self.id},
        }

    def action_enroll_next_waitlist_candidate(self):
        self.ensure_one()
        if self.seats_available <= 0:
            raise UserError(_('This group has no available seats.'))
        next_candidate = self.waitlist_ids.filtered(lambda w: w.state == 'waiting').sorted(
            key=lambda w: (w.priority, w.request_date), reverse=True)[:1]
        if not next_candidate:
            raise UserError(_('There is no one on the waiting list for this group.'))
        return next_candidate.action_enroll_now()

    def _notify_waitlist_of_available_seat(self):
        """Called when an active enrollment is cancelled/completed, freeing a
        seat. By default just posts a chatter note, since staff usually want
        to confirm the next candidate is still interested and has completed
        registration paperwork first -- unless the group has opted in to
        auto_promote_waitlist, in which case the top candidate is enrolled
        automatically."""
        for rec in self:
            waiting = rec.waitlist_ids.filtered(lambda w: w.state == 'waiting')
            if rec.seats_available > 0 and waiting:
                top = waiting.sorted(key=lambda w: (w.priority, w.request_date), reverse=True)[0]
                if rec.auto_promote_waitlist:
                    top.action_enroll_now()
                    rec.message_post(body=_(
                        'A seat became available and %s was automatically enrolled from the '
                        'waiting list (Auto-Promote Waiting List is enabled for this group).'
                    ) % top.student_id.name)
                else:
                    rec.message_post(body=_(
                        'A seat just became available. Next candidate on the waiting list: %s. '
                        'Use "Enroll Next Candidate" to confirm.'
                    ) % top.student_id.name)

    def action_view_sessions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sessions'),
            'res_model': 'education.session',
            'view_mode': 'list,form,calendar',
            'domain': [('group_id', '=', self.id)],
            'context': {'default_group_id': self.id},
        }

    def action_view_teacher_sessions(self):
        """Opens ALL sessions taught by this group's teacher, across every
        group they teach -- not just this one (see action_view_sessions
        for that)."""
        self.ensure_one()
        if not self.teacher_id:
            raise UserError(_('This group has no teacher assigned yet.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sessions -- %s') % self.teacher_id.name,
            'res_model': 'education.session',
            'view_mode': 'list,calendar,form',
            'domain': [('teacher_id', '=', self.teacher_id.id)],
            'context': {'search_default_group_by_group': 1},
        }

    @api.depends('exam_ids')
    def _compute_exam_count(self):
        for rec in self:
            rec.exam_count = len(rec.exam_ids)

    @api.depends('assignment_ids')
    def _compute_assignment_count(self):
        for rec in self:
            rec.assignment_count = len(rec.assignment_ids)

    @api.depends('enrollment_ids.outstanding_amount', 'enrollment_ids.paid_amount', 'enrollment_ids.state')
    def _compute_financial_stats(self):
        for rec in self:
            active = rec.enrollment_ids.filtered(lambda e: e.state == 'active')
            rec.total_outstanding = sum(active.mapped('outstanding_amount'))
            rec.total_collected = sum(active.mapped('paid_amount'))

    def action_view_assignments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Assignments'),
            'res_model': 'education.assignment',
            'view_mode': 'list,form',
            'domain': [('group_id', '=', self.id)],
            'context': {'default_group_id': self.id},
        }

    def action_view_exams(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Exams'),
            'res_model': 'education.exam',
            'view_mode': 'list,form',
            'domain': [('group_id', '=', self.id)],
            'context': {'default_group_id': self.id},
        }

    def action_generate_sessions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generate Sessions from Schedule'),
            'res_model': 'education.session.generate.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_group_id': self.id},
        }

    def _generate_sessions_from_schedule(self, date_from, date_to, skip_existing=True):
        """Creates education.session records for this group between date_from
        and date_to (inclusive) for every day that matches one of its active
        weekly schedule lines — skipping holidays, dates outside the group's
        own start/end date, and (optionally) dates that already have a
        session. Returns the created sessions (possibly empty).

        This is the single source of truth for "turn a weekly schedule into
        actual sessions" — used by both the manual Generate Sessions wizard
        and the daily auto-generation cron, so the two can never drift apart.
        """
        self.ensure_one()
        schedules = self.schedule_ids.filtered('active')
        if not schedules or date_from > date_to:
            return self.env['education.session']

        # Group schedule times (e.g. 14.5 = "2:30 PM") are wall-clock times in
        # the school's own timezone -- NOT UTC. Odoo's Datetime fields always
        # store UTC, so every generated start/end must be explicitly localized
        # here and converted, or sessions end up shifted by the timezone
        # offset (e.g. a 2:30 PM class saved as if 2:30 PM were already UTC,
        # showing as 4:30/5:30 PM to everyone once Odoo renders it back in
        # local time). This uses one school-wide timezone (Settings, falling
        # back to the acting user's) rather than each user's own tz, since a
        # cron running as an admin with no personal tz set would otherwise
        # silently generate sessions in UTC even when everyone else is in
        # Cairo/Riyadh/etc.
        tz = pytz.timezone(get_school_timezone(self.env))

        existing_dates = set(self.env['education.session'].search([
            ('group_id', '=', self.id),
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ]).mapped('date'))
        holiday_dates = self.env['education.holiday'].get_holiday_dates(date_from, date_to, self.company_id.id)

        to_create = []
        current = date_from
        while current <= date_to:
            if current in holiday_dates:
                current += timedelta(days=1)
                continue
            if self.start_date and current < self.start_date:
                current += timedelta(days=1)
                continue
            if self.end_date and current > self.end_date:
                current += timedelta(days=1)
                continue
            weekday = str(current.weekday())  # Monday=0 ... Sunday=6, matches our selection
            for sched in schedules:
                if sched.weekday != weekday:
                    continue
                if sched.effective_from and current < sched.effective_from:
                    continue
                if sched.effective_to and current > sched.effective_to:
                    continue
                if skip_existing and current in existing_dates:
                    continue
                start_h, start_m = float_to_time_parts(sched.start_time)
                end_h, end_m = float_to_time_parts(sched.end_time)
                start_local = tz.localize(datetime.combine(current, datetime.min.time()).replace(
                    hour=start_h, minute=start_m))
                end_local = tz.localize(datetime.combine(current, datetime.min.time()).replace(
                    hour=end_h, minute=end_m))
                to_create.append({
                    'group_id': self.id,
                    'date': current,
                    'start_datetime': start_local.astimezone(pytz.UTC).replace(tzinfo=None),
                    'end_datetime': end_local.astimezone(pytz.UTC).replace(tzinfo=None),
                    'room_id': (sched.room_id or self.room_id).id or False,
                    'state': 'planned',
                })
            current += timedelta(days=1)

        return self.env['education.session'].create(to_create) if to_create else self.env['education.session']
