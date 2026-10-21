from odoo import api, fields, models

LEVELS = [('1', '1 - Very low'), ('2', '2 - Low'), ('3', '3 - Medium'), ('4', '4 - High'), ('5', '5 - Very high')]
EFFECT = [('effective', 'Effective'), ('partial', 'Partially effective'), ('ineffective', 'Ineffective'),
          ('untested', 'Not tested')]
REDUCTION = {'effective': 0.7, 'partial': 0.4, 'ineffective': 0.0, 'untested': 0.0}


def rating(score):
    return 'low' if score <= 6 else 'medium' if score <= 12 else 'high' if score <= 19 else 'critical'


class AuditorControl(models.Model):
    _name = 'odoo.auditor.control'
    _description = 'Internal Control'
    _inherit = ['odoo.auditor.logged.mixin', 'mail.thread']
    _log_fields = ('design_effectiveness', 'operating_effectiveness', 'owner_id')

    name = fields.Char(required=True)
    code = fields.Char(required=True, copy=False)
    description = fields.Text()
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company)
    control_type = fields.Selection([('preventive', 'Preventive'), ('detective', 'Detective'),
                                     ('corrective', 'Corrective')], required=True, default='preventive')
    frequency = fields.Selection([('continuous', 'Continuous'), ('daily', 'Daily'), ('weekly', 'Weekly'),
                                  ('monthly', 'Monthly'), ('quarterly', 'Quarterly'), ('annual', 'Annual')],
                                 default='monthly')
    owner_id = fields.Many2one('res.users')
    design_effectiveness = fields.Selection(EFFECT, default='untested', tracking=True)
    operating_effectiveness = fields.Selection(EFFECT, default='untested', tracking=True)
    risk_reduction = fields.Float(compute='_compute_reduction', store=True,
                                  help="Weakest of design/operating effectiveness: effective 70%, partial 40%, "
                                       "otherwise 0%.")
    last_test_date = fields.Date()
    testing_history = fields.Text()
    rule_ids = fields.Many2many('odoo.auditor.rule', string='Linked Rules')
    risk_ids = fields.Many2many('odoo.auditor.risk', string='Mitigated Risks')

    _control_code_uniq = models.Constraint('UNIQUE(code)', 'The control code must be unique.')

    @api.depends('design_effectiveness', 'operating_effectiveness')
    def _compute_reduction(self):
        for c in self:
            c.risk_reduction = min(REDUCTION[c.design_effectiveness], REDUCTION[c.operating_effectiveness])


class AuditorRisk(models.Model):
    _name = 'odoo.auditor.risk'
    _description = 'Risk Register'
    _inherit = ['odoo.auditor.logged.mixin', 'mail.thread']
    _log_fields = ('likelihood', 'impact', 'control_ids')

    name = fields.Char(required=True)
    code = fields.Char(string='Risk ID', required=True, copy=False)
    category = fields.Selection([('financial', 'Financial'), ('operational', 'Operational'),
                                 ('compliance', 'Compliance'), ('fraud', 'Fraud'), ('it', 'IT / Access')],
                                default='operational')
    description = fields.Text()
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company)
    likelihood = fields.Selection(LEVELS, default='3', required=True)
    impact = fields.Selection(LEVELS, default='3', required=True)
    inherent_score = fields.Integer(compute='_compute_scores', store=True,
                                    help="Likelihood x Impact (1-25). Bands: <=6 low, <=12 medium, <=19 high, else critical.")
    inherent_rating = fields.Selection([('low', 'Low'), ('medium', 'Medium'), ('high', 'High'),
                                        ('critical', 'Critical')], compute='_compute_scores', store=True)
    control_ids = fields.Many2many('odoo.auditor.control', string='Existing Controls')
    residual_score = fields.Float(compute='_compute_scores', store=True,
                                  help="Inherent score x (1 - risk reduction of the strongest linked control).")
    residual_rating = fields.Selection([('low', 'Low'), ('medium', 'Medium'), ('high', 'High'),
                                        ('critical', 'Critical')], compute='_compute_scores', store=True)
    rule_ids = fields.Many2many('odoo.auditor.rule', string='Linked Rules')
    finding_ids = fields.Many2many('odoo.auditor.finding', string='Linked Findings')
    review_date = fields.Date()
    remediation_plan = fields.Text()

    _risk_code_uniq = models.Constraint('UNIQUE(code)', 'The risk ID must be unique.')

    @api.depends('likelihood', 'impact', 'control_ids.risk_reduction')
    def _compute_scores(self):
        for r in self:
            inherent = int(r.likelihood) * int(r.impact)
            best = max(r.control_ids.mapped('risk_reduction') or [0.0])
            residual = inherent * (1 - best)
            r.inherent_score, r.inherent_rating = inherent, rating(inherent)
            r.residual_score, r.residual_rating = residual, rating(residual)
