# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .education_config_helpers import is_pin_required_for_checkin

_logger = logging.getLogger(__name__)


class EducationAttendance(models.Model):
    _name = 'education.attendance'
    _description = 'Attendance'
    _order = 'session_id, student_id'

    session_id = fields.Many2one('education.session', string='Session', required=True, ondelete='cascade')
    student_id = fields.Many2one('education.student', string='Student', required=True, ondelete='cascade')
    enrollment_id = fields.Many2one('education.enrollment', string='Enrollment')
    group_id = fields.Many2one(related='session_id.group_id', string='Group', store=True)
    subject_id = fields.Many2one(related='session_id.group_id.subject_id', string='Subject', store=True)
    session_date = fields.Date(related='session_id.date', string='Session Date', store=True)
    company_id = fields.Many2one(related='session_id.company_id', string='Company', store=True)
    status = fields.Selection([
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
        ('excused', 'Excused'),
    ], string='Status', default=lambda self: self._default_status(), required=True)
    check_in = fields.Datetime(string='Check In')
    check_out = fields.Datetime(string='Check Out')
    note = fields.Char(string='Note')
    registration_method = fields.Selection([
        ('manual', 'Manual'),
        ('qr', 'QR Self Check-in'),
        ('portal', 'Portal'),
    ], string='Registration Method', default='manual', required=True)
    ip_address = fields.Char(string='IP Address', copy=False)
    device_info = fields.Char(string='Device Info', copy=False)
    marked_by = fields.Many2one('res.users', string='Marked By', default=lambda self: self.env.user)
    marked_at = fields.Datetime(string='Marked At', default=fields.Datetime.now)

    previous_status = fields.Selection([
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
        ('excused', 'Excused'),
    ], string='Previous Status', readonly=True, copy=False)
    changed_by = fields.Many2one('res.users', string='Changed By', readonly=True, copy=False)
    changed_at = fields.Datetime(string='Changed At', readonly=True, copy=False)
    change_reason = fields.Char(string='Change Reason', copy=False,
                                 help='Fill this in together with a status change to record why '
                                      'a locked (completed session) attendance record was corrected.')

    _sql_constraints = [
        ('session_student_uniq', 'unique(session_id, student_id)',
         'Attendance already recorded for this student in this session.'),
    ]

    def _default_status(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'prime_educational_hub.default_attendance_status', 'present')

    @api.constrains('session_id', 'student_id')
    def _check_student_enrolled_in_group(self):
        for rec in self:
            if not rec.session_id or not rec.student_id:
                continue
            active_students = rec.session_id.group_id.enrollment_ids.filtered(
                lambda e: e.state == 'active').student_id
            if rec.student_id not in active_students:
                raise ValidationError(_(
                    'Student "%s" is not actively enrolled in the group "%s" for this session.'
                ) % (rec.student_id.name, rec.session_id.group_id.name))

    @api.constrains('check_in', 'session_id')
    def _check_check_in_matches_session_date(self):
        for rec in self:
            if rec.check_in and rec.session_id and rec.session_id.date:
                if rec.check_in.date() != rec.session_id.date:
                    raise ValidationError(_('Check-in date must match the session date.'))

    @api.model_create_multi
    def create(self, vals_list):
        is_privileged = self._is_privileged()
        allow_system = self.env.context.get('allow_system_write')
        for vals in vals_list:
            session = None
            if vals.get('session_id'):
                session = self.env['education.session'].browse(vals['session_id'])
            if not vals.get('enrollment_id') and session and vals.get('student_id'):
                enrollment = session.group_id.enrollment_ids.filtered(
                    lambda e: e.state == 'active' and e.student_id.id == vals['student_id'])
                if enrollment:
                    vals['enrollment_id'] = enrollment[0].id
            method = vals.get('registration_method', 'manual')
            if method not in ('qr', 'portal') and session and not is_privileged and not allow_system:
                if session.attendance_method == 'qr':
                    raise ValidationError(_(
                        'Session "%s" only accepts QR self check-in. Ask an Academic Supervisor or '
                        'Administrator to record attendance manually for it.'
                    ) % session.name)
            if method in ('qr', 'portal'):
                vals.setdefault('marked_by', False)
            else:
                vals.setdefault('marked_by', self.env.user.id)
            vals.setdefault('marked_at', fields.Datetime.now())
        return super().create(vals_list)

    def _is_privileged(self):
        return self.env.user.has_group('prime_educational_hub.group_education_admin') or \
            self.env.user.has_group('prime_educational_hub.group_education_supervisor')

    def write(self, vals):
        allow_system = self.env.context.get('allow_system_write')
        is_privileged = self._is_privileged()
        if not allow_system and not is_privileged:
            for rec in self:
                if rec.session_id.state == 'completed':
                    raise ValidationError(_(
                        'Session "%s" is completed and its attendance is locked. Ask an Academic '
                        'Supervisor or Administrator to reopen the session before correcting attendance.'
                    ) % rec.session_id.name)
                if rec.session_id.attendance_method == 'qr':
                    raise ValidationError(_(
                        'Session "%s" only accepts QR self check-in. Ask an Academic Supervisor or '
                        'Administrator to correct attendance for it.'
                    ) % rec.session_id.name)

        if 'status' in vals and not allow_system:
            audit_user = self.env.user.id
            audit_time = fields.Datetime.now()
            for rec in self:
                if rec.status != vals['status']:
                    super(EducationAttendance, rec).write(dict(
                        vals,
                        previous_status=rec.status,
                        changed_by=audit_user,
                        changed_at=audit_time,
                    ))
                else:
                    super(EducationAttendance, rec).write(vals)
            return True
        return super().write(vals)

    def unlink(self):
        if not self._is_privileged():
            for rec in self:
                if rec.session_id.state == 'completed':
                    raise ValidationError(_(
                        'Session "%s" is completed and its attendance is locked.'
                    ) % rec.session_id.name)
        return super().unlink()

    # ------------------------------------------------------------------
    # Public self check-in (QR / no Odoo user for the student)
    # ------------------------------------------------------------------
    @api.model
    def register_self_checkin(self, token, student_code, pin, ip_address=None, device_info=None):
        """Validates and, if everything checks out, creates the attendance
        record for a student self-checking in via the public QR/portal page.
        Always runs sudo() since the caller has no Odoo user at all.
        Returns a dict: {'ok': bool, 'error': str, ...}."""
        Session = self.env['education.session'].sudo()
        Student = self.env['education.student'].sudo()

        session = Session.search([('qr_token', '=', token)], limit=1) if token else Session
        if not session:
            return {'ok': False, 'error': 'invalid_qr'}
        if session.qr_token_expiry and fields.Datetime.now() > session.qr_token_expiry:
            return {'ok': False, 'error': 'qr_expired'}
        if session.attendance_method == 'manual':
            return {'ok': False, 'error': 'qr_disabled'}

        student_code = (student_code or '').strip()
        student = Student.search([
            ('student_code', '=', student_code),
            ('company_id', '=', session.company_id.id),
        ], limit=1) if student_code else Student
        if not student:
            return {'ok': False, 'error': 'student_not_found'}

        if student.attendance_pin_lock_active():
            return {'ok': False, 'error': 'pin_locked'}

        if is_pin_required_for_checkin(self.env):
            if not student.attendance_pin_set or not student.verify_attendance_pin(pin):
                student.register_pin_attempt(False)
                return {'ok': False, 'error': 'invalid_pin'}
            student.register_pin_attempt(True)

        active_students = session.group_id.enrollment_ids.filtered(
            lambda e: e.state == 'active').student_id
        if student not in active_students:
            return {'ok': False, 'error': 'not_enrolled'}

        if not session._is_attendance_window_open():
            return {'ok': False, 'error': 'window_closed'}

        existing = self.sudo().search([
            ('session_id', '=', session.id), ('student_id', '=', student.id),
        ], limit=1)
        if existing:
            return {'ok': False, 'error': 'already_registered'}

        now = fields.Datetime.now()
        status = session._compute_self_checkin_status(now)
        try:
            record = self.sudo().create({
                'session_id': session.id,
                'student_id': student.id,
                'status': status,
                'check_in': now,
                'registration_method': 'qr',
                'ip_address': ip_address,
                'device_info': (device_info or '')[:250],
            })
        except Exception:
            _logger.exception(
                'Prime Educational Hub: self check-in failed for student_code=%s, session=%s',
                student_code, session.id)
            return {'ok': False, 'error': 'registration_failed'}
        return {
            'ok': True,
            'student_name': student.name,
            'session_name': session.name,
            'group_name': session.group_id.name,
            'subject_name': session.group_id.subject_id.name or '',
            'status': status,
            'check_in': str(record.check_in),
        }
