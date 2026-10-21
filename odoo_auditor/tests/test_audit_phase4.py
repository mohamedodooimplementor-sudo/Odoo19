from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAuditPhase4(TransactionCase):

    def _finding(self, **kw):
        vals = {'title': 'T', 'company_id': self.env.company.id, 'severity': 'medium',
                'fingerprint': 'FIN001|account.move,999999'}
        vals.update(kw)
        return self.env['odoo.auditor.finding'].create(vals)

    def test_ignore_future_creates_exclusion(self):
        rule = self.env.ref('odoo_auditor.rule_fin001')
        f = self._finding(rule_id=rule.id)
        f.action_triage()
        f._ignore_future('Known intercompany balance')
        self.assertEqual(f.state, 'rejected')
        self.assertTrue(self.env['odoo.auditor.exclusion'].search_count([('fingerprint', '=', f.fingerprint)]))

    def test_create_corrective_action_defaults(self):
        f = self._finding(recommendation='Fix it')
        act = f.action_create_corrective_action()
        self.assertEqual(act['context']['default_finding_id'], f.id)
        self.assertEqual(act['context']['default_description'], 'Fix it')

    def test_xlsx_export(self):
        f = self._finding()
        act = f.action_export_xlsx()
        self.assertIn('/web/content/', act['url'])

    def test_setup_wizard_applies_thresholds(self):
        wiz = self.env['odoo.auditor.setup.wizard'].create({'manual_entry_amount': 12345})
        wiz.action_apply()
        self.assertEqual(self.env.ref('odoo_auditor.rule_fin002').threshold_amount, 12345)

    def test_queue_and_background_processing(self):
        rule = self.env.ref('odoo_auditor.rule_fin001')
        run = self.env['odoo.auditor.run'].create({
            'audit_name': 'Q', 'company_id': self.env.company.id, 'rule_ids': [(6, 0, rule.ids)]})
        run.action_queue()
        self.assertEqual(run.state, 'queued')
        run.action_execute()  # same code path the cron uses (minus commits)
        self.assertEqual(run.state, 'done')
        self.assertEqual(run.progress, 100.0)

    def test_queue_requires_rules(self):
        run = self.env['odoo.auditor.run'].create({'audit_name': 'E', 'company_id': self.env.company.id})
        with self.assertRaises(UserError):
            run.action_queue()
