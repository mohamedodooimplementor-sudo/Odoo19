# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import EducationTestCommon


@tagged('post_install', '-at_install')
class TestDashboardTeacherWidgets(EducationTestCommon):

    def setUp(self):
        super().setUp()
        self.teacher = self.env['education.teacher'].create({'name': 'Dashboard Teacher'})
        self.group.teacher_id = self.teacher.id
        self.group.state = 'active'
        enrollment = self.env['education.enrollment'].create({
            'student_id': self.student.id, 'group_id': self.group.id,
        })
        enrollment.action_set_active()

    def test_dashboard_includes_teacher_activity_and_low_attendance_keys(self):
        session = self.env['education.session'].create({'group_id': self.group.id})
        session.action_take_attendance()
        session.attendance_ids.write({'status': 'absent'})

        data = self.env['education.dashboard'].get_dashboard_data()
        self.assertIn('teacher_activity', data)
        self.assertIn('low_attendance_groups', data)
        activity_names = [row['label'] for row in data['teacher_activity']]
        self.assertIn(self.teacher.name, activity_names)


@tagged('post_install', '-at_install')
class TestGuardianPortalAttendanceBreakdown(EducationTestCommon):

    def setUp(self):
        super().setUp()
        enrollment = self.env['education.enrollment'].create({
            'student_id': self.student.id, 'group_id': self.group.id,
        })
        enrollment.action_set_active()

    def test_portal_data_includes_attendance_breakdown(self):
        self.student.action_generate_portal_link()
        session1 = self.env['education.session'].create({'group_id': self.group.id, 'date': '2026-04-01'})
        session1.action_take_attendance()
        session1.attendance_ids.filtered(lambda a: a.student_id == self.student).write({'status': 'present'})

        session2 = self.env['education.session'].create({'group_id': self.group.id, 'date': '2026-04-02'})
        session2.action_take_attendance()
        session2.attendance_ids.filtered(lambda a: a.student_id == self.student).write({'status': 'absent'})

        data = self.env['education.student'].get_public_portal_data(self.student.portal_token)
        self.assertTrue(data['found'])
        self.assertEqual(data['attendance_breakdown']['present'], 1)
        self.assertEqual(data['attendance_breakdown']['absent'], 1)
