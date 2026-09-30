# -*- coding: utf-8 -*-
import io
import uuid
from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class EducationSession(models.Model):
    _name = 'education.session'
    _description = 'Class Session'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, start_datetime desc'

    name = fields.Char(string='Name', compute='_compute_name', store=True)
    sequence = fields.Integer(string='Sequence', default=10)
    group_id = fields.Many2one('education.group', string='Group', required=True, tracking=True, ondelete='cascade')
    date = fields.Date(string='Date', required=True, tracking=True, default=fields.Date.context_today)
    start_datetime = fields.Datetime(string='Start')
    end_datetime = fields.Datetime(string='End')
    room_id = fields.Many2one('education.room', string='Room')
    cancellation_reason = fields.Char(string='Cancellation Reason', copy=False)
    teacher_on_leave_warning = fields.Boolean(
        string='Teacher On Leave', compute='_compute_teacher_on_leave_warning', store=True,
        help='The assigned teacher has an approved leave request covering this date. Shown as a '
             'warning rather than blocked outright, so bulk session auto-generation for other '
             'teachers/groups never fails because of one person\'s day off — reassign a substitute '
             'or reschedule this specific session instead. Stored so it can be filtered/searched on; '
             'refreshed automatically when the session\'s own teacher/date change, and by a daily '
             'cron for the case a leave request gets approved/rejected after the session already '
             'existed.')
    substitute_teacher_id = fields.Many2one('education.teacher', string='Substitute Teacher',
                                             help='Optional stand-in for this specific session only -- '
                                                  "does not change the group's permanent teacher.")
    teacher_id = fields.Many2one(
        'education.teacher', string='Teacher', compute='_compute_teacher_id', store=True, index=True,
        help='Effective teacher for this session: the Substitute Teacher if one is set, '
             "otherwise the group's permanent teacher. Stored so sessions can be filtered "
             'and grouped by teacher directly.')
    topic = fields.Char(string='Topic')
    syllabus_topic_ids = fields.Many2many('education.syllabus.topic', string='Syllabus Topics Covered',
                                           domain="[('subject_id', '=', subject_id)]")
    subject_id = fields.Many2one(related='group_id.subject_id', string='Subject', store=True)
    homework_text = fields.Text(string='Homework')
    state = fields.Selection([
        ('planned', 'Planned'),
        ('open', 'Open'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='planned', tracking=True, required=True)
    notes = fields.Text(string='Notes')
    is_makeup = fields.Boolean(string='Make-up / Exceptional Session', default=False,
                                help='Manually created session outside the regular weekly schedule.')
    company_id = fields.Many2one(related='group_id.company_id', string='Company', store=True)

    attendance_ids = fields.One2many('education.attendance', 'session_id', string='Attendance')
    attendance_taken = fields.Boolean(string='Attendance Taken', compute='_compute_attendance_stats', store=True)
    present_count = fields.Integer(string='Present', compute='_compute_attendance_stats', store=True)
    absent_count = fields.Integer(string='Absent', compute='_compute_attendance_stats', store=True)
    late_count = fields.Integer(string='Late', compute='_compute_attendance_stats', store=True)
    excused_count = fields.Integer(string='Excused', compute='_compute_attendance_stats', store=True)
    attendance_percentage = fields.Float(string='Attendance %', compute='_compute_attendance_stats', store=True)

    # --- QR Self-Attendance --------------------------------------------
    qr_token = fields.Char(string='Attendance QR Token', copy=False, readonly=True)
    qr_token_expiry = fields.Datetime(string='QR Valid Until', copy=False, readonly=True)
    qr_image = fields.Binary(string='Attendance QR Code', copy=False, readonly=True, attachment=True)
    attendance_url = fields.Char(string='Attendance Link', compute='_compute_attendance_url')
    attendance_open_before_minutes = fields.Integer(
        string='Open Before Start (min)', default=15,
        help='Students can start scanning/checking in this many minutes before the session start time.')
    attendance_close_after_minutes = fields.Integer(
        string='Close After Start (min)', default=30,
        help='Self check-in closes this many minutes after the session start time.')
    late_after_minutes = fields.Integer(
        string='Late After (min)', default=15,
        help="Students checking in more than this many minutes after start are marked 'Late' instead of 'Present'.")
    attendance_window_open = fields.Datetime(string='Window Opens', compute='_compute_attendance_window', store=True)
    attendance_window_close = fields.Datetime(string='Window Closes', compute='_compute_attendance_window', store=True)
    attendance_method = fields.Selection([
        ('manual', 'Manual Only'),
        ('qr', 'QR Only'),
        ('both', 'Both'),
    ], string='Attendance Method', default='both', required=True, tracking=True,
        help='Manual Only: the teacher records attendance; students cannot self check-in via QR.\n'
             'QR Only: students self check-in via QR; only an Academic Supervisor/Administrator can '
             'add or correct attendance manually.\n'
             'Both: students can self check-in via QR and the teacher can also record/correct manually.')

    _sql_constraints = [
        ('group_date_uniq', 'unique(group_id, date, sequence)',
         'A session with the same sequence already exists for this group on this date.'),
        ('qr_token_uniq', 'unique(qr_token)', 'QR token must be unique.'),
    ]

    @api.depends('group_id', 'date')
    def _compute_name(self):
        for rec in self:
            if rec.group_id and rec.date:
                rec.name = _('%s - %s') % (rec.group_id.name, rec.date)
            else:
                rec.name = _('New Session')

    @api.depends('group_id.teacher_id', 'substitute_teacher_id')
    def _compute_teacher_id(self):
        for rec in self:
            rec.teacher_id = rec.substitute_teacher_id or rec.group_id.teacher_id
        exclude_excused = self.env['ir.config_parameter'].sudo().get_param(
            'prime_educational_hub.attendance_excused_excluded')
        for rec in self:
            lines = rec.attendance_ids
            rec.attendance_taken = bool(lines)
            rec.present_count = len(lines.filtered(lambda a: a.status == 'present'))
            rec.absent_count = len(lines.filtered(lambda a: a.status == 'absent'))
            rec.late_count = len(lines.filtered(lambda a: a.status == 'late'))
            rec.excused_count = len(lines.filtered(lambda a: a.status == 'excused'))
            total = len(lines) - (rec.excused_count if exclude_excused else 0)
            counted_present = rec.present_count + rec.late_count
            rec.attendance_percentage = (counted_present / total * 100.0) if total else 0.0

    @api.depends('qr_token')
    def _compute_attendance_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for rec in self:
            rec.attendance_url = '%s/education/attendance?token=%s' % (base_url, rec.qr_token) \
                if rec.qr_token else False

    @api.depends('start_datetime', 'attendance_open_before_minutes', 'attendance_close_after_minutes')
    def _compute_attendance_window(self):
        for rec in self:
            if rec.start_datetime:
                rec.attendance_window_open = rec.start_datetime - timedelta(
                    minutes=rec.attendance_open_before_minutes or 0)
                rec.attendance_window_close = rec.start_datetime + timedelta(
                    minutes=rec.attendance_close_after_minutes or 0)
            else:
                rec.attendance_window_open = False
                rec.attendance_window_close = False

    def _generate_qr_png(self, value, size=300):
        """Renders a QR code to PNG bytes using the 'qrcode' library (pure
        Python, built on Pillow — which Odoo already depends on for image
        fields, so no heavyweight extra runtime is introduced)."""
        try:
            import qrcode
        except ImportError:
            raise UserError(_(
                "The 'qrcode' Python package is required to generate Attendance QR codes. "
                "Install it on the server with: pip install qrcode"))
        qr = qrcode.QRCode(border=1)
        qr.add_data(value)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white').convert('RGB')
        img = img.resize((size, size))
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    def action_generate_attendance_qr(self):
        """(Re)generates a fresh, time-limited QR token for self check-in.
        Old printed/displayed QR codes stop working immediately once a new
        one is generated, and the token itself expires when the check-in
        window closes — this prevents a screenshotted QR from being reused
        later or shared outside the classroom."""
        import base64
        for rec in self:
            if not rec.start_datetime:
                raise UserError(_('Set the session Start time before generating an Attendance QR code.'))
            if rec.state not in ('planned', 'open'):
                raise UserError(_('Attendance QR codes can only be generated for a Planned or Open session.'))
            rec.qr_token = uuid.uuid4().hex
            rec.qr_token_expiry = rec.attendance_window_close or (
                rec.start_datetime + timedelta(minutes=rec.attendance_close_after_minutes or 30))
            png_bytes = rec._generate_qr_png(rec.attendance_url)
            rec.qr_image = base64.b64encode(png_bytes)
            sent_count = rec._send_qr_email_to_group()
            rec.message_post(body=_(
                'Attendance QR (re)generated (token: %s). Valid from %s to %s. Emailed to %s '
                'student(s) who have an email address on file.'
            ) % (rec.qr_token, rec.attendance_window_open, rec.attendance_window_close, sent_count))
        if len(self) == 1:
            # Auto-download the QR image immediately, on the very same click that
            # generated it -- Odoo's generic binary-field content route already
            # serves this file; we just ask for it with download=true.
            return {
                'type': 'ir.actions.act_url',
                'url': '/web/content/education.session/%s/qr_image?download=true&filename=attendance_qr_%s.png' % (
                    self.id, self.id),
                'target': 'self',
            }

    def _send_qr_email_to_group(self):
        """Emails this session's QR code image + check-in link to every
        actively enrolled student (falling back to their first guardian's
        email if the student has none on file). Silently skips students
        with no email address available at all -- this is a convenience
        on top of, not a replacement for, showing the QR in class."""
        self.ensure_one()
        if not self.qr_token or not self.attendance_url:
            return 0
        Attachment = self.env['ir.attachment'].sudo()
        Mail = self.env['mail.mail'].sudo()
        active_enrollments = self.group_id.enrollment_ids.filtered(lambda e: e.state == 'active')
        sent_count = 0
        for enrollment in active_enrollments:
            student = enrollment.student_id
            to_email = student.email or (student.guardian_ids[:1].email or False)
            if not to_email:
                continue
            attachment = Attachment.create({
                'name': 'attendance_qr_session_%s.png' % self.id,
                'type': 'binary',
                'datas': self.qr_image,
                'res_model': 'education.session',
                'res_id': self.id,
            })
            body = Markup(
                '<p>%s</p><p>%s: <a href="%s">%s</a></p><p style="color:#888;font-size:12px;">%s</p>'
            ) % (
                _('Hi %s, here is your check-in QR code / link for today\'s session (%s - %s).') % (
                    student.name, self.group_id.name, self.date),
                _('Check-in Link'), self.attendance_url, self.attendance_url,
                _('This link/QR is only valid for this specific session and expires once the '
                  'attendance window closes.'),
            )
            Mail.create({
                'subject': _('Attendance QR Code -- %s (%s)') % (self.group_id.name, self.date),
                'body_html': body,
                'email_to': to_email,
                'attachment_ids': [(6, 0, [attachment.id])],
            }).send()
            sent_count += 1
        return sent_count

    def action_revoke_attendance_qr(self):
        self.write({'qr_token': False, 'qr_token_expiry': False, 'qr_image': False})

    def _is_attendance_window_open(self, at_datetime=None):
        self.ensure_one()
        if self.state not in ('planned', 'open'):
            return False
        now = at_datetime or fields.Datetime.now()
        if not self.attendance_window_open or not self.attendance_window_close:
            return False
        return self.attendance_window_open <= now <= self.attendance_window_close

    def _compute_self_checkin_status(self, at_datetime=None):
        """Present vs Late, based on how far after the session start the
        student is checking in."""
        self.ensure_one()
        now = at_datetime or fields.Datetime.now()
        late_at = self.start_datetime + timedelta(minutes=self.late_after_minutes or 0)
        return 'late' if now > late_at else 'present'

    @api.constrains('start_datetime', 'end_datetime')
    def _check_datetimes(self):
        for rec in self:
            if rec.start_datetime and rec.end_datetime and rec.start_datetime >= rec.end_datetime:
                raise ValidationError(_('Session end time must be after start time.'))

    @api.constrains('group_id', 'date', 'start_datetime', 'end_datetime', 'state', 'room_id')
    def _check_teacher_and_room_conflicts(self):
        for rec in self:
            if rec.state == 'cancelled' or not rec.start_datetime or not rec.end_datetime:
                continue

            overlap_domain = [
                ('id', '!=', rec.id),
                ('date', '=', rec.date),
                ('state', '!=', 'cancelled'),
                ('start_datetime', '<', rec.end_datetime),
                ('end_datetime', '>', rec.start_datetime),
            ]

            # Group conflict: same group shouldn't have two overlapping sessions
            group_conflicts = self.search(overlap_domain + [('group_id', '=', rec.group_id.id)])
            if group_conflicts:
                raise ValidationError(_(
                    'Group "%s" already has another overlapping session ("%s") on %s.'
                ) % (rec.group_id.name, group_conflicts[0].name, rec.date))

            # Teacher conflict: same effective teacher, overlapping time, different group
            # (substitute teacher takes precedence over the group's permanent teacher --
            # already resolved into the stored teacher_id field).
            if rec.teacher_id:
                teacher_domain = overlap_domain + [('teacher_id', '=', rec.teacher_id.id)]
                teacher_conflicts = self.search(teacher_domain)
                if teacher_conflicts:
                    raise ValidationError(_(
                        'Teacher "%s" already has another session ("%s") overlapping this time slot on %s.'
                    ) % (rec.teacher_id.name, teacher_conflicts[0].name, rec.date))

            # Room conflict: same room, overlapping time
            if rec.room_id:
                room_conflicts = self.search(overlap_domain + [('room_id', '=', rec.room_id.id)])
                if room_conflicts:
                    raise ValidationError(_(
                        'Room "%s" is already booked for another session ("%s") overlapping this time slot on %s.'
                    ) % (rec.room_id.name, room_conflicts[0].name, rec.date))

    @api.depends('teacher_id', 'date')
    def _compute_teacher_on_leave_warning(self):
        LeaveRequest = self.env['education.teacher.leave.request']
        for rec in self:
            rec.teacher_on_leave_warning = bool(rec.teacher_id and rec.date and LeaveRequest.search_count([
                ('teacher_id', '=', rec.teacher_id.id),
                ('state', '=', 'approved'),
                ('date_from', '<=', rec.date),
                ('date_to', '>=', rec.date),
            ]))

    def _cron_refresh_teacher_leave_warnings(self):
        """Runs daily: re-checks teacher_on_leave_warning for every
        upcoming, non-cancelled session. Needed because the field only
        auto-recomputes off the SESSION's own fields (teacher/date) --  if
        a leave request gets approved or rejected afterwards, nothing on
        the session itself changes to trigger a recompute, so this cron is
        what catches it."""
        sessions = self.search([
            ('date', '>=', fields.Date.context_today(self)),
            ('state', 'not in', ('completed', 'cancelled')),
        ])
        if sessions:
            sessions._compute_teacher_on_leave_warning()

    def action_open(self):
        self.write({'state': 'open'})

    def action_complete(self):
        self.write({'state': 'completed'})

    def action_reopen(self):
        """Controlled reopening of a completed session so attendance can be
        corrected — restricted to Supervisor/Administrator (see the
        write-lock on education.attendance)."""
        is_privileged = self.env.user.has_group('prime_educational_hub.group_education_admin') or \
            self.env.user.has_group('prime_educational_hub.group_education_supervisor')
        if not is_privileged:
            raise UserError(_(
                'Only an Academic Supervisor or Administrator can reopen a completed session.'))
        self.write({'state': 'open'})

    def action_cancel(self):
        """Direct cancel with no reason (kept for backward-compat / bulk
        actions). Prefer action_open_cancel_wizard from the UI, which
        requires a reason and logs it to chatter."""
        self.write({'state': 'cancelled'})

    def action_open_cancel_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'education.session.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'name': _('Cancel Session'),
            'context': {'default_session_id': self.id},
        }

    def action_reset_to_planned(self):
        self.write({'state': 'planned'})

    def action_open_quick_checkin(self):
        """Opens the PIN-free, code-only quick check-in wizard for staff
        already logged into Odoo -- see education.session.quick_checkin.wizard
        for why it skips the PIN the public QR page requires."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'education.session.quick_checkin.wizard',
            'view_mode': 'form',
            'target': 'new',
            'name': _('Quick Check-in -- %s') % self.group_id.name,
            'context': {'default_session_id': self.id},
        }

    def action_take_attendance(self):
        """Create one attendance line (default: Present) per actively enrolled
        student in the session's group, skipping students who already have a line."""
        self.ensure_one()
        Attendance = self.env['education.attendance']
        existing_student_ids = self.attendance_ids.student_id.ids
        active_enrollments = self.group_id.enrollment_ids.filtered(lambda e: e.state == 'active')
        default_status = self.env['ir.config_parameter'].sudo().get_param(
            'prime_educational_hub.default_attendance_status', 'present')
        to_create = []
        for enrollment in active_enrollments:
            if enrollment.student_id.id not in existing_student_ids:
                to_create.append({
                    'session_id': self.id,
                    'student_id': enrollment.student_id.id,
                    'enrollment_id': enrollment.id,
                    'status': default_status,
                })
        if to_create:
            Attendance.create(to_create)
        if self.state == 'planned':
            self.state = 'open'
        return {
            'type': 'ir.actions.act_window',
            'name': _('Attendance'),
            'res_model': 'education.attendance',
            'view_mode': 'list',
            'domain': [('session_id', '=', self.id)],
            'context': {'default_session_id': self.id},
        }

    def action_mark_all_present(self):
        for rec in self:
            rec.attendance_ids.write({'status': 'present'})

    def action_mark_all_absent(self):
        for rec in self:
            rec.attendance_ids.write({'status': 'absent'})

    def action_reset_attendance(self):
        for rec in self:
            rec.attendance_ids.unlink()

    @api.model
    def _cron_auto_mark_absent(self):
        """After a session's attendance window has closed, any actively
        enrolled student who never checked in (QR, portal, or manual) is
        automatically recorded as Absent. Runs frequently (every 15 min) so
        the dashboard reflects reality soon after each session ends."""
        Attendance = self.env['education.attendance']
        now = fields.Datetime.now()
        sessions = self.search([
            ('state', 'in', ('planned', 'open')),
            ('start_datetime', '!=', False),
        ])
        for session in sessions:
            close_at = session.attendance_window_close or session.end_datetime
            if not close_at or close_at > now:
                continue
            existing_student_ids = session.attendance_ids.student_id.ids
            active_enrollments = session.group_id.enrollment_ids.filtered(lambda e: e.state == 'active')
            to_create = []
            for enrollment in active_enrollments:
                if enrollment.student_id.id not in existing_student_ids:
                    to_create.append({
                        'session_id': session.id,
                        'student_id': enrollment.student_id.id,
                        'enrollment_id': enrollment.id,
                        'status': 'absent',
                        'registration_method': 'manual',
                    })
            if to_create:
                Attendance.with_context(allow_system_write=True).create(to_create)
            if session.state == 'planned':
                session.state = 'open'
            # Automatic lock: once the session itself has actually ended
            # (not just the early self-check-in window), attendance for it
            # is frozen -- only a Supervisor/Administrator can reopen it.
            lock_at = session.end_datetime or close_at
            if lock_at and now >= lock_at:
                # Auto check-out: anyone still Present/Late with no check-out time
                # gets one stamped with the session's actual end time.
                checkout_lines = session.attendance_ids.filtered(
                    lambda a: a.status in ('present', 'late') and not a.check_out)
                if checkout_lines:
                    checkout_lines.with_context(allow_system_write=True).write({'check_out': lock_at})
                session.write({'state': 'completed'})

    def unlink(self):
        for rec in self:
            if rec.attendance_taken:
                raise ValidationError(_(
                    'Session "%s" already has attendance recorded and cannot be deleted. '
                    'Cancel it instead to preserve the audit trail.'
                ) % rec.name)
        return super().unlink()
