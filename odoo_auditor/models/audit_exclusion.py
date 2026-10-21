from odoo import fields, models


class AuditorExclusion(models.Model):
    """A finding fingerprint the audit team decided to ignore in future runs (documented reason)."""
    _name = 'odoo.auditor.exclusion'
    _description = 'Audit Exclusion'
    _inherit = ['odoo.auditor.logged.mixin']
    _order = 'id desc'
    _log_fields = ('active', 'reason')

    _fp_uniq = models.Constraint('UNIQUE(fingerprint, company_id)', 'This item is already excluded.')

    fingerprint = fields.Char(required=True, index=True, readonly=True)
    rule_id = fields.Many2one('odoo.auditor.rule', required=True, ondelete='cascade')
    company_id = fields.Many2one('res.company', required=True)
    source_name = fields.Char(string='Source Document', readonly=True)
    finding_id = fields.Many2one('odoo.auditor.finding', ondelete='set null', readonly=True)
    reason = fields.Text(required=True)
    active = fields.Boolean(default=True)
