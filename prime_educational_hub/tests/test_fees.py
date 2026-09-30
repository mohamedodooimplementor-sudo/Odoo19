# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import EducationTestCommon


@tagged('post_install', '-at_install')
class TestFees(EducationTestCommon):

    def setUp(self):
        super().setUp()
        self.enrollment = self.env['education.enrollment'].create({
            'student_id': self.student.id, 'group_id': self.group.id, 'gross_fee': 1000.0,
        })
        self.enrollment.action_set_active()
        self.fee = self.enrollment.fee_ids[0]
        self.installment = self.fee.installment_ids[0]

    def test_payment_confirmation_allocates_to_installment(self):
        payment = self.env['education.payment'].create({
            'student_id': self.student.id, 'enrollment_id': self.enrollment.id,
            'amount': 400.0, 'payment_method_id': self.payment_method.id,
        })
        payment.action_confirm()
        self.assertAlmostEqual(self.installment.paid_amount, 400.0)
        self.assertAlmostEqual(self.enrollment.paid_amount, 400.0)
        self.assertAlmostEqual(self.enrollment.outstanding_amount, 600.0)

    def test_confirmed_payment_amount_is_locked(self):
        payment = self.env['education.payment'].create({
            'student_id': self.student.id, 'enrollment_id': self.enrollment.id,
            'amount': 400.0, 'payment_method_id': self.payment_method.id,
        })
        payment.action_confirm()
        with self.assertRaises(ValidationError):
            payment.write({'amount': 999.0})

    def test_installment_paid_amount_cannot_be_edited_directly(self):
        with self.assertRaises(ValidationError):
            self.installment.write({'paid_amount': 500.0})

    def test_overpayment_blocked_for_non_admin_without_override(self):
        cashier_group = self.env.ref('prime_educational_hub.group_education_cashier')
        cashier_user = self.env['res.users'].create({
            'name': 'Test Cashier', 'login': 'test_cashier_fees@example.com',
            'group_ids': [(6, 0, [cashier_group.id])],
        })
        payment = self.env['education.payment'].with_user(cashier_user).create({
            'student_id': self.student.id, 'enrollment_id': self.enrollment.id,
            'amount': 1500.0, 'payment_method_id': self.payment_method.id,
        })
        with self.assertRaises(ValidationError):
            payment.with_user(cashier_user).action_confirm()

    def test_refund_reverses_installment_paid_amount(self):
        payment = self.env['education.payment'].create({
            'student_id': self.student.id, 'enrollment_id': self.enrollment.id,
            'amount': 400.0, 'payment_method_id': self.payment_method.id,
        })
        payment.action_confirm()
        self.assertAlmostEqual(self.installment.paid_amount, 400.0)

        refund = self.env['education.refund'].create({
            'student_id': self.student.id, 'payment_id': payment.id,
            'amount': 150.0, 'reason': 'Test refund',
        })
        refund.action_approve()
        self.installment.invalidate_recordset(['paid_amount'])
        self.assertAlmostEqual(self.installment.paid_amount, 250.0,
                                msg='Refund should reverse exactly what it refunded from the installment')
        self.assertAlmostEqual(self.enrollment.outstanding_amount, 750.0)

    def test_refund_cannot_exceed_payment_amount(self):
        payment = self.env['education.payment'].create({
            'student_id': self.student.id, 'enrollment_id': self.enrollment.id,
            'amount': 400.0, 'payment_method_id': self.payment_method.id,
        })
        payment.action_confirm()
        with self.assertRaises(ValidationError):
            self.env['education.refund'].create({
                'student_id': self.student.id, 'payment_id': payment.id,
                'amount': 500.0, 'reason': 'Too much',
            })

    def test_refund_requires_reason(self):
        payment = self.env['education.payment'].create({
            'student_id': self.student.id, 'enrollment_id': self.enrollment.id,
            'amount': 400.0, 'payment_method_id': self.payment_method.id,
        })
        payment.action_confirm()
        with self.assertRaises(Exception):
            self.env['education.refund'].create({
                'student_id': self.student.id, 'payment_id': payment.id, 'amount': 100.0,
            })
