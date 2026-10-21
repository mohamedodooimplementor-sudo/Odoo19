from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAuditWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group_user = cls.env.ref('odoo_auditor.group_auditor_user')
        group_mgr = cls.env.ref('odoo_auditor.group_auditor_manager')
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        cls.auditor = Users.create({'name': 'Aud', 'login': 'aud_t', 'email': 'a@t.com',
                                    'group_ids': [(6, 0, [group_user.id])]})
        cls.manager = Users.create({'name': 'Mgr', 'login': 'mgr_t', 'email': 'm@t.com',
                                    'group_ids': [(6, 0, [group_mgr.id])]})
        cls.owner = Users.create({'name': 'Own', 'login': 'own_t', 'email': 'o@t.com',
                                  'group_ids': [(6, 0, [group_mgr.id])]})
        cls.finding = cls.env['odoo.auditor.finding'].create({
            'title': 'T', 'company_id': cls.env.company.id, 'severity': 'high'})

    def test_direct_state_change_blocked(self):
        with self.assertRaises(UserError):
            self.finding.write({'state': 'closed'})

    def test_invalid_transition_blocked(self):
        with self.assertRaises(UserError):
            self.finding.action_investigate()  # must be triaged first

    def test_full_flow_and_sod(self):
        f = self.finding.with_user(self.auditor)
        f.action_triage()
        f.action_investigate()
        f.action_request_response()
        f.action_require_action()
        with self.assertRaises(UserError):   # high severity needs an action
            f.action_pending_verification()
        action = self.env['odoo.auditor.action'].create({
            'title': 'Fix', 'finding_id': f.id, 'description': 'd', 'deadline': '2030-01-01',
            'responsible_user_id': self.owner.id})
        action.write({'completion_notes': 'done'})
        action.with_user(self.owner).action_complete()
        with self.assertRaises(UserError):   # owner cannot verify own action
            action.with_user(self.owner).action_verify()
        action.with_user(self.manager).action_verify()
        f.action_pending_verification()
        with self.assertRaises(UserError):   # plain auditor cannot close
            f.action_open_resolution_wizard() and f._close('x')
        self.finding.with_user(self.manager)._close('verified')
        self.assertEqual(self.finding.state, 'closed')

    def test_reject_requires_justification(self):
        with self.assertRaises(UserError):
            self.finding.with_user(self.manager)._reject('  ')

    def test_log_is_protected(self):
        log = self.env['odoo.auditor.log'].search([], limit=1)
        self.assertTrue(log)
        with self.assertRaises(UserError):
            log.write({'reason': 'x'})
        with self.assertRaises(UserError):
            log.unlink()

    def test_finding_cannot_be_deleted(self):
        with self.assertRaises(UserError):
            self.finding.unlink()
