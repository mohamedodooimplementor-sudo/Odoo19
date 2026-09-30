# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import EducationTestCommon


@tagged('post_install', '-at_install')
class TestPerSessionBilling(EducationTestCommon):

    def test_fee_plan_amount_auto_computes_for_per_session(self):
        plan = self.env['education.fee.plan'].create({
            'name': 'Per Session Plan', 'billing_type': 'per_session',
            'session_count': 10, 'price_per_session': 50.0, 'amount': 1.0,
        })
        plan._onchange_session_billing()
        self.assertEqual(plan.amount, 500.0)

    def test_fee_plan_requires_positive_session_fields(self):
        with self.assertRaises(ValidationError):
            self.env['education.fee.plan'].create({
                'name': 'Bad Per Session Plan', 'billing_type': 'per_session',
                'session_count': 0, 'price_per_session': 0.0, 'amount': 100.0,
            })

    def test_enrollment_onchange_copies_session_fields_from_plan(self):
        plan = self.env['education.fee.plan'].create({
            'name': 'Per Session Plan 2', 'billing_type': 'per_session',
            'session_count': 8, 'price_per_session': 40.0, 'amount': 320.0,
        })
        enrollment = self.env['education.enrollment'].new({
            'student_id': self.student.id, 'group_id': self.group.id, 'fee_plan_id': plan.id,
        })
        enrollment._onchange_fee_plan_id()
        self.assertEqual(enrollment.billing_type, 'per_session')
        self.assertEqual(enrollment.session_count, 8)
        self.assertEqual(enrollment.price_per_session, 40.0)
        self.assertEqual(enrollment.gross_fee, 320.0)

    def test_sessions_consumed_tracks_attendance_automatically(self):
        enrollment = self.env['education.enrollment'].create({
            'student_id': self.student.id, 'group_id': self.group.id,
            'billing_type': 'per_session', 'session_count': 5, 'price_per_session': 60.0,
            'gross_fee': 300.0,
        })
        enrollment.action_set_active()
        self.assertEqual(enrollment.sessions_consumed, 0)
        self.assertEqual(enrollment.sessions_remaining, 5)
        self.assertEqual(enrollment.amount_consumed, 0.0)

        session1 = self.env['education.session'].create({'group_id': self.group.id, 'date': '2026-04-01'})
        session1.action_take_attendance()
        session1.attendance_ids.write({'status': 'present'})

        self.assertEqual(enrollment.sessions_consumed, 1)
        self.assertEqual(enrollment.sessions_remaining, 4)
        self.assertEqual(enrollment.amount_consumed, 60.0)

        session2 = self.env['education.session'].create({'group_id': self.group.id, 'date': '2026-04-02'})
        session2.action_take_attendance()
        session2.attendance_ids.write({'status': 'late'})

        self.assertEqual(enrollment.sessions_consumed, 2)
        self.assertEqual(enrollment.sessions_remaining, 3)
        self.assertEqual(enrollment.amount_consumed, 120.0)

    def test_absent_does_not_consume_a_session(self):
        enrollment = self.env['education.enrollment'].create({
            'student_id': self.student.id, 'group_id': self.group.id,
            'billing_type': 'per_session', 'session_count': 5, 'price_per_session': 60.0,
            'gross_fee': 300.0,
        })
        enrollment.action_set_active()
        session = self.env['education.session'].create({'group_id': self.group.id, 'date': '2026-04-03'})
        session.action_take_attendance()
        session.attendance_ids.write({'status': 'absent'})
        self.assertEqual(enrollment.sessions_consumed, 0)
        self.assertEqual(enrollment.sessions_remaining, 5)

    def test_lump_sum_enrollment_has_zero_session_metering(self):
        enrollment = self.env['education.enrollment'].create({
            'student_id': self.student.id, 'group_id': self.group.id, 'gross_fee': 1000.0,
        })
        enrollment.action_set_active()
        session = self.env['education.session'].create({'group_id': self.group.id, 'date': '2026-04-04'})
        session.action_take_attendance()
        session.attendance_ids.write({'status': 'present'})
        self.assertEqual(enrollment.billing_type, 'lump_sum')
        self.assertEqual(enrollment.sessions_consumed, 0)
        self.assertEqual(enrollment.sessions_remaining, 0)
        self.assertEqual(enrollment.amount_consumed, 0.0)

    def test_per_session_fee_generation_uses_package_total(self):
        enrollment = self.env['education.enrollment'].create({
            'student_id': self.student.id, 'group_id': self.group.id,
            'billing_type': 'per_session', 'session_count': 4, 'price_per_session': 75.0,
            'gross_fee': 300.0,
        })
        enrollment.action_set_active()
        self.assertTrue(enrollment.fee_ids)
        self.assertEqual(enrollment.fee_ids[0].net_amount, 300.0)
