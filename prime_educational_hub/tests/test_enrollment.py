# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import EducationTestCommon


@tagged('post_install', '-at_install')
class TestEnrollment(EducationTestCommon):

    def _make_student(self, name):
        return self.env['education.student'].create({'name': name})

    def test_capacity_limit_blocks_overflow(self):
        """Group capacity is 2 — a 3rd active enrollment must be rejected."""
        s1, s2, s3 = self._make_student('S1'), self._make_student('S2'), self._make_student('S3')
        Enrollment = self.env['education.enrollment']

        e1 = Enrollment.create({'student_id': s1.id, 'group_id': self.group.id})
        e1.action_set_active()
        e2 = Enrollment.create({'student_id': s2.id, 'group_id': self.group.id})
        e2.action_set_active()

        e3 = Enrollment.create({'student_id': s3.id, 'group_id': self.group.id})
        with self.assertRaises(ValidationError):
            e3.action_set_active()

    def test_capacity_override_by_admin_context(self):
        """The force_enrollment context flag bypasses the capacity check
        (used by the waitlist 'Enroll Now' action)."""
        s1, s2, s3 = self._make_student('S1'), self._make_student('S2'), self._make_student('S3')
        Enrollment = self.env['education.enrollment']
        for s in (s1, s2):
            e = Enrollment.create({'student_id': s.id, 'group_id': self.group.id})
            e.action_set_active()

        e3 = Enrollment.with_context(force_enrollment=True).create({
            'student_id': s3.id, 'group_id': self.group.id,
        })
        e3.with_context(force_enrollment=True).action_set_active()
        self.assertEqual(e3.state, 'active')

    def test_duplicate_active_enrollment_blocked(self):
        student = self._make_student('Dup Student')
        Enrollment = self.env['education.enrollment']
        e1 = Enrollment.create({'student_id': student.id, 'group_id': self.group.id})
        e1.action_set_active()
        with self.assertRaises(ValidationError):
            Enrollment.create({'student_id': student.id, 'group_id': self.group.id})

    def test_suspended_student_cannot_be_activated(self):
        student = self._make_student('Suspended Student')
        student.state = 'suspended'
        enrollment = self.env['education.enrollment'].create({
            'student_id': student.id, 'group_id': self.group.id,
        })
        with self.assertRaises(ValidationError):
            enrollment.action_set_active()

    def test_fee_and_installments_generated_on_activation(self):
        student = self._make_student('Fee Student')
        enrollment = self.env['education.enrollment'].create({
            'student_id': student.id, 'group_id': self.group.id,
            'gross_fee': 1000.0,
        })
        enrollment.action_set_active()
        self.assertTrue(enrollment.fee_ids, 'Activating an enrollment with a gross fee should create a Fee record')
        self.assertTrue(enrollment.fee_ids.installment_ids, 'A Fee should have at least one installment')
        self.assertAlmostEqual(enrollment.net_fee, 1000.0)
        self.assertAlmostEqual(enrollment.outstanding_amount, 1000.0)
