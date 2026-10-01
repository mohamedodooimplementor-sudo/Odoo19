# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestIntercompanyOperation(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Test IC Partner'})
        cls.manager_group = cls.env.ref('intercompany_operation_modified.group_intercompany_manager')
        cls.manager = cls.env['res.users'].create({
            'name': 'IC Manager',
            'login': 'ic_manager_test',
            'email': 'ic_manager_test@example.com',
            'groups_id': [(4, cls.manager_group.id)],
        })

    def _create_operation(self):
        return self.env['intercompany.operation'].create({
            'partner_id': self.partner.id,
            'operation_type': 'sale',
        })

    def test_submit_sets_to_approve_and_tracks_submitter(self):
        op = self._create_operation()
        self.assertEqual(op.state, 'draft')
        op.action_submit()
        self.assertEqual(op.state, 'to_approve')
        self.assertEqual(op.submitted_by, self.env.user)

    def test_submit_twice_raises(self):
        op = self._create_operation()
        op.action_submit()
        with self.assertRaises(UserError):
            op.action_submit()

    def test_approve_flow(self):
        op = self._create_operation()
        op.action_submit()
        op.action_approve()
        self.assertEqual(op.state, 'approved')

    def test_reject_with_reason_resets_to_draft(self):
        op = self._create_operation()
        op.action_submit()
        op._do_refuse('Missing supporting documents')
        self.assertEqual(op.state, 'draft')
        self.assertEqual(op.reject_reason, 'Missing supporting documents')

    def test_reject_without_reason_raises(self):
        op = self._create_operation()
        op.action_submit()
        wizard = self.env['intercompany.reject.wizard'].create({
            'res_model': 'intercompany.operation',
            'res_id': op.id,
            'reason': '   ',
        })
        with self.assertRaises(UserError):
            wizard.action_confirm_reject()

    def test_reject_wizard_full_flow(self):
        op = self._create_operation()
        op.action_submit()
        wizard = self.env['intercompany.reject.wizard'].create({
            'res_model': 'intercompany.operation',
            'res_id': op.id,
            'reason': 'Wrong amount',
        })
        wizard.action_confirm_reject()
        self.assertEqual(op.state, 'draft')
        self.assertEqual(op.reject_reason, 'Wrong amount')

    def test_cron_pending_approval_reminder_runs(self):
        op = self._create_operation()
        op.action_submit()
        # Should not raise, even with managers present
        self.env['intercompany.operation']._cron_remind_pending_approvals()
