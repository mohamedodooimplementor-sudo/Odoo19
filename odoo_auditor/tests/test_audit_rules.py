from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAuditRules(TransactionCase):

    def test_rule_codes_unique(self):
        with self.assertRaises(Exception), self.cr.savepoint():
            self.env['odoo.auditor.rule'].create({
                'name': 'dup', 'code': 'FIN001', 'method_key': 'FIN001'})

    def test_extra_params_validation(self):
        rule = self.env.ref('odoo_auditor.rule_fin001')
        with self.assertRaises(ValidationError):
            rule.extra_params = 'not json'
        with self.assertRaises(ValidationError):
            rule.extra_params = '{"a": {"nested": 1}}'

    def test_evidence_snapshot_immutable_and_hashed(self):
        finding = self.env['odoo.auditor.finding'].create({'title': 'E', 'company_id': self.env.company.id})
        ev = self.env['odoo.auditor.evidence'].create_snapshot(finding, {'a': 1}, 'd')
        self.assertTrue(ev.hash_valid)
        with self.assertRaises(Exception):
            ev.write({'snapshot_json': '{}'})

    def test_run_skips_missing_models_and_is_idempotent(self):
        rules = self.env['odoo.auditor.rule'].search([])
        run = self.env['odoo.auditor.run'].create({
            'audit_name': 'T', 'company_id': self.env.company.id, 'rule_ids': [(6, 0, rules.ids)]})
        run.action_execute()
        self.assertEqual(run.state, 'done')
        count = len(self.env['odoo.auditor.finding'].search([]))
        run.action_execute()  # retry must not duplicate findings
        self.assertEqual(count, len(self.env['odoo.auditor.finding'].search([])))

    def test_duplicate_vendor_bill_rule(self):
        if 'account.move' not in self.env:
            self.skipTest('account not installed')
        partner = self.env['res.partner'].create({'name': 'V'})
        vals = {'move_type': 'in_invoice', 'partner_id': partner.id, 'ref': 'INV-1',
                'invoice_date': '2026-01-10', 'date': '2026-01-10',
                'invoice_line_ids': [(0, 0, {'name': 'x', 'quantity': 1, 'price_unit': 100})]}
        self.env['account.move'].create([vals, dict(vals)])
        run = self.env['odoo.auditor.run'].create({
            'audit_name': 'D', 'company_id': self.env.company.id, 'date_from': '2026-01-01',
            'date_to': '2026-01-31', 'rule_ids': [(6, 0, self.env.ref('odoo_auditor.rule_fin003').ids)]})
        run.action_execute()
        self.assertEqual(run.finding_count, 1)

    def test_no_rule_errors_on_this_database(self):
        """Runs every active rule; any ERROR in the log reveals a field/API mismatch on this Odoo version."""
        rules = self.env['odoo.auditor.rule'].search([])
        run = self.env['odoo.auditor.run'].create({
            'audit_name': 'All', 'company_id': self.env.company.id, 'rule_ids': [(6, 0, rules.ids)]})
        run.action_execute()
        self.assertNotIn('[ERROR]', run.message_log or '', run.message_log)

    def test_dashboard_data(self):
        data = self.env['odoo.auditor.finding'].get_dashboard_data()
        for key in ('open_total', 'severity', 'domains', 'overdue_actions', 'top_rules', 'runs'):
            self.assertIn(key, data)
