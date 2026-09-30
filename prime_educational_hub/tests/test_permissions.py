# -*- coding: utf-8 -*-
from odoo.exceptions import ValidationError, UserError
from odoo.tests import tagged

from .common import EducationTestCommon


@tagged('post_install', '-at_install')
class TestPermissions(EducationTestCommon):

    def setUp(self):
        super().setUp()
        teacher_group = self.env.ref('prime_educational_hub.group_education_teacher')
        self.teacher_user = self.env['res.users'].create({
            'name': 'Test Teacher', 'login': 'test_teacher_perms@example.com',
            'group_ids': [(6, 0, [teacher_group.id])],
        })
        self.other_teacher_user = self.env['res.users'].create({
            'name': 'Other Teacher', 'login': 'other_teacher_perms@example.com',
            'group_ids': [(6, 0, [teacher_group.id])],
        })
        # Teachers are master data (education.teacher) and only optionally linked
        # to a System User -- these two happen to have one, so permission
        # scoping can be exercised via with_user().
        self.teacher = self.env['education.teacher'].create({
            'name': 'Test Teacher', 'user_id': self.teacher_user.id,
        })
        self.other_teacher = self.env['education.teacher'].create({
            'name': 'Other Teacher', 'user_id': self.other_teacher_user.id,
        })
        self.group.teacher_id = self.teacher.id

        self.other_group = self.env['education.group'].create({
            'name': 'Other Group', 'subject_id': self.subject.id, 'level_id': self.level.id,
            'academic_year_id': self.academic_year.id, 'capacity': 5, 'state': 'active',
            'teacher_id': self.other_teacher.id,
        })

    def test_teacher_only_sees_own_group(self):
        groups_seen = self.env['education.group'].with_user(self.teacher_user).search([])
        self.assertIn(self.group, groups_seen)
        self.assertNotIn(self.other_group, groups_seen,
                          "Teacher must not see a group taught by someone else")

    def test_teacher_only_sees_students_in_own_group(self):
        enrollment = self.env['education.enrollment'].create({
            'student_id': self.student.id, 'group_id': self.other_group.id,
        })
        enrollment.action_set_active()
        students_seen = self.env['education.student'].with_user(self.teacher_user).search([])
        self.assertNotIn(self.student, students_seen,
                          "Teacher must not see a student only enrolled in another teacher's group")

    def test_admin_sees_all_groups_despite_teacher_rule(self):
        admin_group = self.env.ref('prime_educational_hub.group_education_admin')
        admin_user = self.env['res.users'].create({
            'name': 'Test Admin', 'login': 'test_admin_perms@example.com',
            'group_ids': [(6, 0, [admin_group.id])],
        })
        groups_seen = self.env['education.group'].with_user(admin_user).search([])
        self.assertIn(self.group, groups_seen)
        self.assertIn(self.other_group, groups_seen,
                       "Admin must see every group regardless of the teacher-scoping rule")

    def test_teacher_can_exist_without_any_system_user(self):
        """Most teachers are master data only -- no Odoo login required."""
        teacher = self.env['education.teacher'].create({'name': 'No Login Teacher'})
        self.assertFalse(teacher.user_id)
        self.assertFalse(teacher.has_system_access)
        group = self.env['education.group'].create({
            'name': 'No Login Teacher Group', 'subject_id': self.subject.id, 'level_id': self.level.id,
            'academic_year_id': self.academic_year.id, 'capacity': 5, 'state': 'active',
            'teacher_id': teacher.id,
        })
        self.assertEqual(group.teacher_id, teacher)


@tagged('post_install', '-at_install')
class TestCertificateLocking(EducationTestCommon):

    def test_issued_certificate_content_is_locked(self):
        cert = self.env['education.certificate'].create({
            'student_id': self.student.id, 'subject_id': self.subject.id,
        })
        cert.action_issue()
        with self.assertRaises(ValidationError):
            cert.write({'final_grade': 'A'})

    def test_revoke_requires_reason(self):
        cert = self.env['education.certificate'].create({
            'student_id': self.student.id, 'subject_id': self.subject.id,
        })
        cert.action_issue()
        with self.assertRaises(UserError):
            cert.action_revoke(reason=None)

    def test_revoke_with_reason_succeeds(self):
        cert = self.env['education.certificate'].create({
            'student_id': self.student.id, 'subject_id': self.subject.id,
        })
        cert.action_issue()
        cert.action_revoke(reason='Printing error')
        self.assertEqual(cert.state, 'revoked')
        self.assertEqual(cert.revoke_reason, 'Printing error')


@tagged('post_install', '-at_install')
class TestConcurrencyStyle(EducationTestCommon):
    """A true multi-connection race condition can't be reproduced inside a
    single TransactionCase, but this at least proves the capacity guard
    still rejects a second enrollment for the last seat even when it's
    attempted immediately after the first one commits within the same
    transaction — the realistic worst case the ORM-level check needs to
    catch once the DB-level lock from a real concurrent transaction would
    also apply."""

    def test_last_seat_cannot_be_double_booked(self):
        self.group.capacity = 1
        s1 = self.env['education.student'].create({'name': 'Seat Taker 1'})
        s2 = self.env['education.student'].create({'name': 'Seat Taker 2'})
        Enrollment = self.env['education.enrollment']

        e1 = Enrollment.create({'student_id': s1.id, 'group_id': self.group.id})
        e1.action_set_active()

        e2 = Enrollment.create({'student_id': s2.id, 'group_id': self.group.id})
        with self.assertRaises(ValidationError):
            e2.action_set_active()
