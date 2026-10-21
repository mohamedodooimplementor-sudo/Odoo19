import json

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

DOMAIN_AREAS = [('financial', 'Financial & Accounting'), ('inventory', 'Inventory & Warehouse'),
                ('sales', 'Sales'), ('purchase', 'Purchase & Vendor'), ('hr', 'HR & Payroll'),
                ('manufacturing', 'Manufacturing'), ('access', 'Access & SoD'), ('other', 'Other')]
SEVERITIES = [('informational', 'Informational'), ('low', 'Low'), ('medium', 'Medium'),
              ('high', 'High'), ('critical', 'Critical')]
NATURES = [('verified_inconsistency', 'Verified inconsistency'), ('policy_exception', 'Policy exception'),
           ('risk_indicator', 'Risk indicator'), ('needs_investigation', 'Requires human investigation')]
RISK_CATEGORIES = [('financial', 'Financial'), ('operational', 'Operational'), ('compliance', 'Compliance'),
                   ('fraud', 'Fraud indicator'), ('data_quality', 'Data quality')]


class AuditorRule(models.Model):
    _name = 'odoo.auditor.rule'
    _description = 'Audit Rule'
    _inherit = ['odoo.auditor.logged.mixin', 'mail.thread']
    _order = 'domain_area, code'
    _log_fields = ('active', 'severity', 'threshold_amount', 'threshold_days', 'threshold_percent',
                   'frequency', 'extra_params', 'exclude_partner_ids', 'method_key')

    _code_uniq = models.Constraint('UNIQUE(code)', 'The rule code must be unique.')

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, copy=False, index=True, help="Stable rule code. Do not change once findings exist.")
    active = fields.Boolean(default=True)
    description = fields.Text(translate=True)
    domain_area = fields.Selection(DOMAIN_AREAS, required=True, default='financial')
    category = fields.Char(help="Free sub-category, e.g. Duplicates, Thresholds.")
    method_key = fields.Selection(selection='_selection_method_key', required=True,
                                  help="Predefined, controlled implementation. No user code is ever executed.")
    nature = fields.Selection(NATURES, required=True, default='needs_investigation')
    severity = fields.Selection(SEVERITIES, required=True, default='medium')
    risk_category = fields.Selection(RISK_CATEGORIES, default='operational')
    company_id = fields.Many2one('res.company', help="Leave empty to apply to all companies.")
    threshold_amount = fields.Float(help="Amount (company currency) or quantity, depending on the rule.")
    threshold_days = fields.Integer(help="Age / window in days, depending on the rule.")
    threshold_percent = fields.Float(help="Percentage threshold, depending on the rule.")
    extra_params = fields.Text(help="Optional JSON object with additional simple parameters.")
    exclude_partner_ids = fields.Many2many('res.partner', string='Excluded Partners')
    version = fields.Integer(string='Detection Logic Version', default=1)
    recommendation = fields.Text(translate=True)
    expected_evidence = fields.Text(translate=True)
    owner_id = fields.Many2one('res.users', string='Owner')
    department = fields.Char(string='Responsible Department')
    frequency = fields.Selection([('manual', 'Manual only'), ('daily', 'Daily'), ('weekly', 'Weekly'),
                                  ('monthly', 'Monthly')], default='manual', required=True)
    lookback_days = fields.Integer(default=90, help="Window for scheduled runs.")
    last_run = fields.Datetime(readonly=True)
    next_run = fields.Datetime(readonly=True)
    finding_ids = fields.One2many('odoo.auditor.finding', 'rule_id')
    finding_count = fields.Integer(compute='_compute_finding_count')
    effectiveness = fields.Selection([('untested', 'Not yet evaluated'), ('productive', 'Producing findings'),
                                      ('quiet', 'No findings')], compute='_compute_effectiveness')
    applicable_models = fields.Char(compute='_compute_meta')
    config_message = fields.Text(compute='_compute_meta', string='Configuration Validation')
    config_ok = fields.Boolean(compute='_compute_meta')

    @api.model
    def _selection_method_key(self):
        from .audit_engine import RULE_METHODS
        return [(k, v['label']) for k, v in sorted(RULE_METHODS.items())]

    @api.depends('finding_ids')
    def _compute_finding_count(self):
        data = dict(self.env['odoo.auditor.finding'].with_context(active_test=False)._read_group(
            [('rule_id', 'in', self.ids)], ['rule_id'], ['__count']))
        for rule in self:
            rule.finding_count = data.get(rule, 0)

    @api.depends('finding_count', 'last_run')
    def _compute_effectiveness(self):
        for rule in self:
            rule.effectiveness = 'untested' if not rule.last_run else (
                'productive' if rule.finding_count else 'quiet')

    @api.depends('method_key', 'threshold_amount', 'threshold_days', 'threshold_percent', 'extra_params')
    def _compute_meta(self):
        from .audit_engine import RULE_METHODS
        for rule in self:
            meta = RULE_METHODS.get(rule.method_key) or {}
            rule.applicable_models = ', '.join(meta.get('models', []))
            msgs = [self.env._("Required model not installed: %s", m)
                    for m in meta.get('models', []) if m not in self.env]
            for need in meta.get('needs', []):
                if not rule['threshold_' + need]:
                    msgs.append(self.env._("Threshold '%s' is required for this rule.", need))
            rule.config_ok = not msgs
            rule.config_message = '\n'.join(msgs) or self.env._("Configuration is valid.")

    @api.constrains('extra_params')
    def _check_extra_params(self):
        for rule in self.filtered('extra_params'):
            try:
                data = json.loads(rule.extra_params)
            except ValueError:
                raise ValidationError(self.env._("Extra parameters must be valid JSON."))
            if not isinstance(data, dict) or any(
                    not isinstance(v, (str, int, float, bool, list, type(None))) for v in data.values()):
                raise ValidationError(self.env._("Extra parameters must be a flat JSON object of simple values."))

    def get_params(self):
        self.ensure_one()
        return json.loads(self.extra_params) if self.extra_params else {}

    def _schedule_next(self):
        now = fields.Datetime.now()
        delta = {'daily': relativedelta(days=1), 'weekly': relativedelta(weeks=1),
                 'monthly': relativedelta(months=1)}
        for rule in self:
            rule.sudo().write({'last_run': now,
                               'next_run': now + delta[rule.frequency] if rule.frequency in delta else False})

    def action_view_findings(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': self.env._('Findings'),
                'res_model': 'odoo.auditor.finding', 'view_mode': 'list,form',
                'domain': [('rule_id', '=', self.id)], 'context': {'active_test': False}}
