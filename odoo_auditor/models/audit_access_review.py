from odoo import api, fields, models
from odoo.exceptions import UserError


class AuditorAccessReview(models.Model):
    _name = 'odoo.auditor.access.review'
    _description = 'Access Review (Segregation of Duties)'
    _inherit = ['odoo.auditor.logged.mixin', 'mail.thread']
    _log_fields = ('state',)

    name = fields.Char(required=True, default=lambda s: s.env._("Access review %s", fields.Date.today()))
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    review_date = fields.Date(default=fields.Date.today)
    reviewer_id = fields.Many2one('res.users', default=lambda s: s.env.user)
    state = fields.Selection([('draft', 'Draft'), ('in_review', 'In Review'), ('done', 'Completed')],
                             default='draft', tracking=True)
    line_ids = fields.One2many('odoo.auditor.access.review.line', 'review_id')
    note = fields.Text()

    def action_generate(self):
        """Snapshot users holding conflicting rights. Never changes anybody's access."""
        from .audit_engine import DEFAULT_SOD_PAIRS
        for rev in self:
            if rev.state != 'draft':
                raise UserError(self.env._("Lines can only be generated in draft."))
            rule = self.env.ref('odoo_auditor.rule_sod001', raise_if_not_found=False)
            pairs = (rule and rule.get_params().get('pairs')) or DEFAULT_SOD_PAIRS
            result, _n = self.env['odoo.auditor.engine']._sod_conflicts(rev.company_id, pairs)
            rev.line_ids.unlink()
            self.env['odoo.auditor.access.review.line'].create([{
                'review_id': rev.id, 'user_id': u.id,
                'conflicts': '\n'.join(' + '.join(p) for p in hits)} for u, hits in result.items()])
            rev.state = 'in_review'

    def action_complete(self):
        for rev in self:
            if any(l.decision == 'pending' for l in rev.line_ids):
                raise UserError(self.env._("Record a decision on every line first."))
            if any(l.decision in ('keep', 'escalate') and not l.justification for l in rev.line_ids):
                raise UserError(self.env._("Keeping or escalating a conflict requires a justification."))
            rev.state = 'done'


class AuditorAccessReviewLine(models.Model):
    _name = 'odoo.auditor.access.review.line'
    _description = 'Access Review Line'

    review_id = fields.Many2one('odoo.auditor.access.review', required=True, ondelete='cascade')
    user_id = fields.Many2one('res.users', required=True)
    conflicts = fields.Text(readonly=True)
    decision = fields.Selection([('pending', 'Pending'), ('keep', 'Keep (compensating control)'),
                                 ('revoke', 'Request revocation'), ('escalate', 'Escalate')], default='pending')
    justification = fields.Text()
