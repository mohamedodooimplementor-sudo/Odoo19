# -*- coding: utf-8 -*-
from odoo.tests import tagged

from .common import EducationTestCommon


@tagged('post_install', '-at_install')
class TestTeacherStats(EducationTestCommon):

    def setUp(self):
        super().setUp()
        teacher_group = self.env.ref('prime_educational_hub.group_education_teacher')
        self.teacher_user = self.env['res.users'].create({
            'name': 'Test Teacher User', 'login': 'test_teacher_stats@example.com',
            'group_ids': [(6, 0, [teacher_group.id])],
        })
        self.substitute_user = self.env['res.users'].create({
            'name': 'Substitute Teacher User', 'login': 'test_substitute_stats@example.com',
            'group_ids': [(6, 0, [teacher_group.id])],
        })
        # The main teacher happens to have a System User (e.g. they take their
        # own attendance); the substitute is pure master data with no login,
        # which is the normal case for most teachers.
        self.teacher = self.env['education.teacher'].create({
            'name': 'Test Teacher', 'user_id': self.teacher_user.id,
        })
        self.substitute_teacher = self.env['education.teacher'].create({'name': 'Substitute Teacher'})
        self.group.teacher_id = self.teacher.id

    def test_teacher_does_not_require_a_system_user(self):
        self.assertFalse(self.substitute_teacher.user_id)
        self.assertFalse(self.substitute_teacher.has_system_access)
        self.assertTrue(self.teacher.has_system_access)

    def test_session_teacher_id_defaults_to_group_teacher(self):
        session = self.env['education.session'].create({'group_id': self.group.id, 'date': '2026-03-01'})
        self.assertEqual(session.teacher_id, self.teacher)

    def test_session_teacher_id_uses_substitute_when_set(self):
        session = self.env['education.session'].create({
            'group_id': self.group.id, 'date': '2026-03-02',
            'substitute_teacher_id': self.substitute_teacher.id,
        })
        self.assertEqual(session.teacher_id, self.substitute_teacher)

    def test_teacher_session_and_group_counts(self):
        self.env['education.session'].create({'group_id': self.group.id, 'date': '2026-03-03'})
        session2 = self.env['education.session'].create({'group_id': self.group.id, 'date': '2026-03-04'})
        session2.state = 'completed'

        self.assertEqual(self.teacher.group_count, 1)
        self.assertEqual(self.teacher.session_count, 2)
        self.assertEqual(self.teacher.session_completed_count, 1)

    def test_group_teacher_total_session_count_spans_all_their_groups(self):
        other_group = self.env['education.group'].create({
            'name': 'Other Group For Same Teacher', 'subject_id': self.subject.id, 'level_id': self.level.id,
            'academic_year_id': self.academic_year.id, 'capacity': 5, 'state': 'active',
            'teacher_id': self.teacher.id,
        })
        self.env['education.session'].create({'group_id': self.group.id, 'date': '2026-03-05'})
        self.env['education.session'].create({'group_id': other_group.id, 'date': '2026-03-06'})

        # This group only has 1 session of its own...
        self.assertEqual(self.group.session_count, 1)
        # ...but the teacher's total across both groups is 2.
        self.assertEqual(self.group.teacher_total_session_count, 2)
        self.assertEqual(other_group.teacher_total_session_count, 2)

    def test_res_users_smart_button_stats_reflect_linked_teacher(self):
        self.env['education.session'].create({'group_id': self.group.id, 'date': '2026-03-07'})
        self.assertEqual(self.teacher_user.education_teacher_id, self.teacher)
        self.assertTrue(self.teacher_user.education_is_teacher)
        self.assertEqual(self.teacher_user.education_group_count, 1)
        self.assertEqual(self.teacher_user.education_session_count, 1)

    def test_non_teacher_user_stats_are_empty(self):
        random_user = self.env['res.users'].create({
            'name': 'No Groups User', 'login': 'test_no_groups@example.com',
        })
        self.assertEqual(random_user.education_session_count, 0)
        self.assertFalse(random_user.education_is_teacher)
