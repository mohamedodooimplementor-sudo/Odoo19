import hashlib
import json

from odoo import api, fields, models
from odoo.exceptions import UserError

IMMUTABLE = ('snapshot_json', 'snapshot_hash', 'collected_date', 'collected_by', 'snapshot_kind')


class AuditorEvidence(models.Model):
    _name = 'odoo.auditor.evidence'
    _description = 'Audit Evidence'
    _inherit = ['odoo.auditor.logged.mixin', 'mail.thread']
    _order = 'id desc'
    _log_fields = ('verification_status', 'confidentiality')

    name = fields.Char(required=True)
    evidence_type = fields.Selection([('snapshot', 'System snapshot (historical)'), ('document', 'Document'),
                                      ('confirmation', 'Confirmation'), ('observation', 'Observation'),
                                      ('interview', 'Interview / Inquiry'), ('other', 'Other')],
                                     default='document', required=True)
    snapshot_kind = fields.Selection([('historical', 'Historical snapshot - values at detection time'),
                                      ('manual', 'Manually provided')], default='manual', readonly=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    finding_id = fields.Many2one('odoo.auditor.finding', ondelete='restrict', index=True)
    run_id = fields.Many2one('odoo.auditor.run')
    plan_id = fields.Many2one('odoo.auditor.plan')
    workpaper_id = fields.Many2one('odoo.auditor.workpaper')
    source_document = fields.Char()
    description = fields.Text()
    snapshot_json = fields.Text(string='Observed Values', readonly=True,
                                help="Immutable. Not the current state of the business record.")
    snapshot_hash = fields.Char(string='SHA-256', readonly=True)
    hash_valid = fields.Boolean(compute='_compute_hash_valid')
    collected_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    collected_by = fields.Many2one('res.users', default=lambda s: s.env.user, readonly=True)
    attachment_ids = fields.Many2many('ir.attachment', string='Files')
    verification_status = fields.Selection([('pending', 'Pending'), ('verified', 'Verified'),
                                            ('rejected', 'Rejected')], default='pending', tracking=True)
    confidentiality = fields.Selection([('internal', 'Internal'), ('confidential', 'Confidential'),
                                        ('restricted', 'Restricted')], default='internal', required=True)

    @api.depends('snapshot_json', 'snapshot_hash')
    def _compute_hash_valid(self):
        for ev in self:
            ev.hash_valid = bool(ev.snapshot_json) and \
                hashlib.sha256(ev.snapshot_json.encode()).hexdigest() == ev.snapshot_hash

    @api.model
    def create_snapshot(self, finding, values, description):
        payload = json.dumps(values, default=str, sort_keys=True, ensure_ascii=False)
        return self.sudo().create({
            'name': self.env._("Snapshot for %s", finding.name), 'evidence_type': 'snapshot',
            'snapshot_kind': 'historical', 'finding_id': finding.id, 'company_id': finding.company_id.id,
            'run_id': finding.run_id.id, 'source_document': finding.source_name, 'description': description,
            'snapshot_json': payload, 'snapshot_hash': hashlib.sha256(payload.encode()).hexdigest(),
            'confidentiality': 'confidential' if finding.is_confidential else 'internal',
        })

    def write(self, vals):
        if any(f in vals for f in IMMUTABLE) and not self.env.context.get('module_uninstall'):
            raise UserError(self.env._("Evidence snapshots are immutable."))
        return super().write(vals)

    def unlink(self):
        raise UserError(self.env._("Evidence cannot be deleted."))

    def action_open_source(self):
        self.ensure_one()
        if not self.finding_id:
            raise UserError(self.env._("This evidence is not linked to a finding."))
        return self.finding_id.action_open_source()
