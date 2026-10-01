# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError


@tagged('post_install', '-at_install')
class TestIntercompanyPayment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'Test IC Payment Partner'})
        cls.manager_group = cls.env.ref('intercompany_operation_modified.group_intercompany_manager')
        cls.manager = cls.env['res.users'].create({
            'name': 'IC Payment Manager',
            'login': 'ic_pay_manager_test',
            'email': 'ic_pay_manager_test@example.com',
            'groups_id': [(4, cls.manager_group.id)],
        })

    def _create_payment(self):
        return self.env['intercompany.payment'].create({
            'partner_id': self.partner.id,
            'payment_type': 'inbound',
        })

    def test_submit_sets_to_approve_and_tracks_submitter(self):
        pay = self._create_payment()
        self.assertEqual(pay.state, 'draft')
        pay.action_submit()
        self.assertEqual(pay.state, 'to_approve')
        self.assertEqual(pay.submitted_by, self.env.user)

    def test_approve_flow(self):
        pay = self._create_payment()
        pay.action_submit()
        pay.action_approve()
        self.assertEqual(pay.state, 'approved')

    def test_reject_with_reason_resets_to_draft(self):
        pay = self._create_payment()
        pay.action_submit()
        pay._do_refuse('Amounts do not match invoice')
        self.assertEqual(pay.state, 'draft')
        self.assertEqual(pay.reject_reason, 'Amounts do not match invoice')

    def test_reject_invalid_state_raises(self):
        pay = self._create_payment()
        # still draft, cannot reject
        with self.assertRaises(UserError):
            pay._do_refuse('Some reason')

    def test_post_payment_without_lines_raises(self):
        pay = self._create_payment()
        with self.assertRaises(UserError):
            pay.action_post_payment()

    def test_cron_pending_approval_reminder_runs(self):
        pay = self._create_payment()
        pay.action_submit()
        # Should not raise, even with managers present
        self.env['intercompany.payment']._cron_remind_pending_approvals()
