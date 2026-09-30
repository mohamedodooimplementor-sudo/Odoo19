# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import EducationTestCommon


@tagged('post_install', '-at_install')
class TestTeacherPayout(EducationTestCommon):

    def setUp(self):
        super().setUp()
        self.teacher = self.env['education.teacher'].create({'name': 'Payout Teacher'})
        self.group.teacher_id = self.teacher.id

    def _completed_session(self, date):
        session = self.env['education.session'].create({'group_id': self.group.id, 'date': date})
        session.state = 'completed'
        return session

    def test_per_session_payout_amount(self):
        self.teacher.write({'compensation_type': 'per_session', 'rate_per_session': 50.0})
        self._completed_session('2026-04-01')
        self._completed_session('2026-04-02')
        payout = self.env['education.teacher.payout'].create({
            'teacher_id': self.teacher.id, 'period_start': '2026-04-01', 'period_end': '2026-04-30',
        })
        self.assertEqual(payout.session_count, 2)
        self.assertEqual(payout.amount, 100.0)

    def test_fixed_salary_payout_amount(self):
        self.teacher.write({'compensation_type': 'fixed', 'fixed_salary': 3000.0})
        payout = self.env['education.teacher.payout'].create({
            'teacher_id': self.teacher.id, 'period_start': '2026-04-01', 'period_end': '2026-04-30',
        })
        self.assertEqual(payout.amount, 3000.0)

    def test_percentage_payout_amount(self):
        self.teacher.write({'compensation_type': 'percentage', 'commission_percentage': 10.0})
        enrollment = self.env['education.enrollment'].create({
            'student_id': self.student.id, 'group_id': self.group.id,
        })
        enrollment.action_set_active()
        payment = self.env['education.payment'].create({
            'student_id': self.student.id, 'enrollment_id': enrollment.id,
            'amount': 1000.0, 'payment_date': '2026-04-15',
        })
        payment.action_confirm()
        payout = self.env['education.teacher.payout'].create({
            'teacher_id': self.teacher.id, 'period_start': '2026-04-01', 'period_end': '2026-04-30',
        })
        self.assertEqual(payout.fees_collected, 1000.0)
        self.assertEqual(payout.amount, 100.0)

    def test_none_compensation_gives_zero(self):
        payout = self.env['education.teacher.payout'].create({
            'teacher_id': self.teacher.id, 'period_start': '2026-04-01', 'period_end': '2026-04-30',
        })
        self.assertEqual(payout.amount, 0.0)

    def test_duplicate_period_blocked(self):
        self.env['education.teacher.payout'].create({
            'teacher_id': self.teacher.id, 'period_start': '2026-04-01', 'period_end': '2026-04-30',
        })
        with self.assertRaises(Exception):
            self.env['education.teacher.payout'].create({
                'teacher_id': self.teacher.id, 'period_start': '2026-04-01', 'period_end': '2026-04-30',
            })

    def test_state_workflow(self):
        payout = self.env['education.teacher.payout'].create({
            'teacher_id': self.teacher.id, 'period_start': '2026-04-01', 'period_end': '2026-04-30',
        })
        payout.action_confirm()
        self.assertEqual(payout.state, 'confirmed')
        payout.action_mark_paid()
        self.assertEqual(payout.state, 'paid')
        self.assertTrue(payout.payment_date)

    def test_generate_for_period_skips_no_plan_and_duplicates(self):
        self.teacher.write({'compensation_type': 'fixed', 'fixed_salary': 1000.0})
        no_plan_teacher = self.env['education.teacher'].create({'name': 'No Plan Teacher'})
        Payout = self.env['education.teacher.payout']
        created = Payout._generate_for_period('2026-05-01', '2026-05-31')
        self.assertIn(self.teacher, created.mapped('teacher_id'))
        self.assertNotIn(no_plan_teacher, created.mapped('teacher_id'))
        # Running again for the same period should not duplicate.
        created_again = Payout._generate_for_period('2026-05-01', '2026-05-31')
        self.assertFalse(created_again)

    def test_performance_report_pdf_generates(self):
        self._completed_session('2026-04-03')
        pdf_bytes = self.teacher.get_performance_report_pdf()
        self.assertTrue(pdf_bytes)
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
