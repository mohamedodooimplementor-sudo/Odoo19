# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase


class EducationTestCommon(TransactionCase):
    """Builds a minimal but complete academic structure (year, subject,
    level, group, guardian, student) that every other test module reuses,
    so each test file only needs to add the specifics for what it's
    actually testing."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.academic_year = cls.env['education.academic.year'].create({
            'name': 'Test Year 2026',
            'date_start': '2026-01-01',
            'date_end': '2026-12-31',
            'state': 'active',
        })
        cls.subject = cls.env['education.subject'].create({'name': 'Test Subject', 'code': 'TST'})
        cls.level = cls.env['education.level'].create({'name': 'Test Level'})
        cls.guardian = cls.env['education.guardian'].create({
            'name': 'Test Guardian', 'mobile': '+201001234567',
        })
        cls.student = cls.env['education.student'].create({
            'name': 'Test Student',
            'guardian_ids': [(6, 0, [cls.guardian.id])],
            'grade_level_id': cls.level.id,
        })
        cls.group = cls.env['education.group'].create({
            'name': 'Test Group A',
            'subject_id': cls.subject.id,
            'level_id': cls.level.id,
            'academic_year_id': cls.academic_year.id,
            'capacity': 2,
            'state': 'active',
        })
        cls.payment_method = cls.env['education.payment.method'].create({
            'name': 'Test Cash', 'code': 'test_cash',
        })
