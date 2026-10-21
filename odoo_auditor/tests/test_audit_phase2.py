from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAuditPhase2(TransactionCase):

    def test_checklist_completion(self):
        c = self.env['odoo.auditor.checklist'].create({'name': 'P', 'kind': 'year_end'})
        with self.assertRaises(UserError):
            c.action_complete()
        c.action_generate_lines()
        self.assertTrue(len(c.line_ids) > 10)
        c.line_ids.write({'done': True})
        c.action_complete()
        self.assertEqual(c.state, 'done')

    def test_access_review_requires_decisions(self):
        rev = self.env['odoo.auditor.access.review'].create({'name': 'R'})
        rev.action_generate()
        if rev.line_ids:
            with self.assertRaises(UserError):
                rev.action_complete()
        else:
            rev.action_complete()
            self.assertEqual(rev.state, 'done')

    def test_sod_rule_with_custom_pair(self):
        rule = self.env.ref('odoo_auditor.rule_sod001')
        rule.extra_params = '{"pairs": [["base.group_user", "base.group_system"]]}'
        run = self.env['odoo.auditor.run'].create({
            'audit_name': 'SoD', 'company_id': self.env.company.id, 'rule_ids': [(6, 0, rule.ids)]})
        run.action_execute()
        self.assertEqual(run.state, 'done')
        self.assertTrue(run.finding_count >= 1)  # admin holds both groups

    def test_hr_findings_are_confidential(self):
        if 'hr.employee' not in self.env:
            self.skipTest('hr not installed')
        self.env['hr.employee'].create([{'name': 'A', 'identification_id': 'X1'}, {'name': 'B', 'identification_id': 'X1'}])
        rule = self.env.ref('odoo_auditor.rule_hr001')
        run = self.env['odoo.auditor.run'].create({
            'audit_name': 'HR', 'company_id': self.env.company.id, 'rule_ids': [(6, 0, rule.ids)]})
        run.action_execute()
        self.assertTrue(run.finding_ids.mapped('is_confidential'))
