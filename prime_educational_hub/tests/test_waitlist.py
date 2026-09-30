# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import EducationTestCommon


@tagged('post_install', '-at_install')
class TestWaitlist(EducationTestCommon):

    def setUp(self):
        super().setUp()
        self.group.capacity = 1
        self.student_a = self.env['education.student'].create({'name': 'Seat Holder'})
        self.student_b = self.env['education.student'].create({'name': 'Waiting Student'})
        Enrollment = self.env['education.enrollment']
        self.enrollment_a = Enrollment.create({'student_id': self.student_a.id, 'group_id': self.group.id})
        self.enrollment_a.action_set_active()
        self.waitlist_entry = self.env['education.group.waitlist'].create({
            'student_id': self.student_b.id, 'group_id': self.group.id,
        })

    def test_manual_mode_only_notifies_does_not_enroll(self):
        self.assertFalse(self.group.auto_promote_waitlist)
        self.enrollment_a.action_set_cancelled()
        self.assertEqual(self.waitlist_entry.state, 'waiting',
                          'Without auto-promote, the waiting entry must stay waiting until staff acts.')
        enrolled = self.env['education.enrollment'].search([
            ('student_id', '=', self.student_b.id), ('group_id', '=', self.group.id),
        ])
        self.assertFalse(enrolled)

    def test_auto_promote_enrolls_top_candidate_automatically(self):
        self.group.auto_promote_waitlist = True
        self.enrollment_a.action_set_cancelled()
        self.assertEqual(self.waitlist_entry.state, 'enrolled')
        enrolled = self.env['education.enrollment'].search([
            ('student_id', '=', self.student_b.id), ('group_id', '=', self.group.id),
        ])
        self.assertTrue(enrolled)
        self.assertEqual(enrolled.state, 'active')

    def test_auto_promote_respects_priority_order(self):
        self.group.auto_promote_waitlist = True
        student_c = self.env['education.student'].create({'name': 'Urgent Waiting Student'})
        urgent_entry = self.env['education.group.waitlist'].create({
            'student_id': student_c.id, 'group_id': self.group.id, 'priority': '2',
        })
        self.enrollment_a.action_set_cancelled()
        self.assertEqual(urgent_entry.state, 'enrolled')
        self.assertEqual(self.waitlist_entry.state, 'waiting')
