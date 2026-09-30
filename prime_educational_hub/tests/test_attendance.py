# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import EducationTestCommon


@tagged('post_install', '-at_install')
class TestAttendance(EducationTestCommon):

    def setUp(self):
        super().setUp()
        self.enrollment = self.env['education.enrollment'].create({
            'student_id': self.student.id, 'group_id': self.group.id,
        })
        self.enrollment.action_set_active()
        self.session = self.env['education.session'].create({
            'group_id': self.group.id, 'date': '2026-02-01',
        })

    def test_take_attendance_creates_one_line_per_active_student(self):
        self.session.action_take_attendance()
        self.assertEqual(len(self.session.attendance_ids), 1)
        self.assertEqual(self.session.attendance_ids.student_id, self.student)

    def test_duplicate_attendance_blocked(self):
        Attendance = self.env['education.attendance']
        Attendance.create({
            'session_id': self.session.id, 'student_id': self.student.id, 'status': 'present',
        })
        with self.assertRaises(Exception):
            # SQL unique constraint -> IntegrityError, wrapped by Odoo
            Attendance.create({
                'session_id': self.session.id, 'student_id': self.student.id, 'status': 'absent',
            })

    def test_attendance_locked_after_session_completed(self):
        self.session.action_take_attendance()
        self.session.action_complete()
        with self.assertRaises(ValidationError):
            self.session.attendance_ids.write({'status': 'absent'})

    def test_attendance_percentage_reflects_status(self):
        self.session.action_take_attendance()
        self.session.attendance_ids.write({'status': 'present'})
        self.assertAlmostEqual(self.enrollment.attendance_percentage, 100.0)

        session2 = self.env['education.session'].create({'group_id': self.group.id, 'date': '2026-02-02'})
        session2.action_take_attendance()
        session2.attendance_ids.write({'status': 'absent'})
        self.assertAlmostEqual(self.enrollment.attendance_percentage, 50.0)

    def test_qr_only_session_blocks_manual_creation_for_regular_user(self):
        self.session.attendance_method = 'qr'
        with self.assertRaises(Exception):
            self.env['education.attendance'].create({
                'session_id': self.session.id, 'student_id': self.student.id,
                'status': 'present', 'registration_method': 'manual',
            })

    def test_manual_only_session_blocks_qr_self_checkin(self):
        self.session.attendance_method = 'manual'
        now = fields.Datetime.now()
        self.session.write({'date': now.date(), 'start_datetime': now, 'end_datetime': now + timedelta(hours=1)})
        self.session.action_generate_attendance_qr()
        result = self.env['education.attendance'].register_self_checkin(
            token=self.session.qr_token, student_code=self.student.student_code, pin='0000',
        )
        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'qr_disabled')

    def test_pin_lockout_after_failed_attempts(self):
        now = fields.Datetime.now()
        self.session.write({'date': now.date(), 'start_datetime': now, 'end_datetime': now + timedelta(hours=1)})
        self.session.action_generate_attendance_qr()
        self.student.action_generate_attendance_pin()
        Attendance = self.env['education.attendance']
        for _i in range(self.student.ATTENDANCE_PIN_MAX_ATTEMPTS):
            result = Attendance.register_self_checkin(
                token=self.session.qr_token, student_code=self.student.student_code, pin='9999',
            )
            self.assertEqual(result['error'], 'invalid_pin')
        self.assertTrue(self.student.attendance_pin_lock_active())
        locked_result = Attendance.register_self_checkin(
            token=self.session.qr_token, student_code=self.student.student_code, pin='9999',
        )
        self.assertEqual(locked_result['error'], 'pin_locked')

    def test_manual_override_records_audit_trail(self):
        self.session.action_take_attendance()
        line = self.session.attendance_ids
        line.write({'status': 'absent'})
        self.assertEqual(line.previous_status, 'present')
        self.assertEqual(line.changed_by, self.env.user)
        self.assertTrue(line.changed_at)

    def test_cron_auto_locks_session_after_it_ends(self):
        now = fields.Datetime.now()
        self.session.write({
            'date': (now - timedelta(hours=2)).date(),
            'start_datetime': now - timedelta(hours=2),
            'end_datetime': now - timedelta(hours=1),
        })
        self.session.action_take_attendance()
        self.env['education.session']._cron_auto_mark_absent()
        self.assertEqual(self.session.state, 'completed')
        with self.assertRaises(ValidationError):
            self.session.attendance_ids.write({'status': 'present'})
