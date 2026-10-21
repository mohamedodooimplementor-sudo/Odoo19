from datetime import timedelta

from odoo import api, fields, models


class RunAuditWizard(models.TransientModel):
    _name = 'odoo.auditor.run.wizard'
    _description = 'Run Audit Wizard'

    audit_name = fields.Char(required=True, default=lambda s: s.env._("Audit %s", fields.Date.today()))
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    date_from = fields.Date(required=True, default=lambda s: fields.Date.today() - timedelta(days=90))
    date_to = fields.Date(required=True, default=fields.Date.today)
    domain_area = fields.Selection([('all', 'All domains'), ('financial', 'Financial'), ('inventory', 'Inventory'),
                                    ('sales', 'Sales'), ('purchase', 'Purchase')], default='all')
    rule_ids = fields.Many2many('odoo.auditor.rule')
    execute_now = fields.Boolean(default=True)
    background = fields.Boolean(string='Run in background', default=True,
                                help='Recommended for large databases. The run form shows live progress.')

    @api.onchange('domain_area', 'company_id')
    def _onchange_domain(self):
        dom = [('company_id', 'in', (False, self.company_id.id))]
        if self.domain_area != 'all':
            dom.append(('domain_area', '=', self.domain_area))
        self.rule_ids = self.env['odoo.auditor.rule'].search(dom)

    def action_run(self):
        self.ensure_one()
        run = self.env['odoo.auditor.run'].create({
            'audit_name': self.audit_name, 'company_id': self.company_id.id, 'date_from': self.date_from,
            'date_to': self.date_to, 'rule_ids': [(6, 0, self.rule_ids.ids)],
            'audit_type': 'full' if self.domain_area == 'all' else self.domain_area,
        })
        if self.execute_now:
            run.action_queue() if self.background else run.action_execute()
        return {'type': 'ir.actions.act_window', 'res_model': 'odoo.auditor.run', 'res_id': run.id,
                'view_mode': 'form'}
