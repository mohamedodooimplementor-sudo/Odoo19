from odoo import api, fields, models
from odoo.exceptions import UserError

from .audit_rule import NATURES, SEVERITIES

STATES = [('new', 'New'), ('triaged', 'Triaged'), ('investigating', 'Under Investigation'),
          ('awaiting_response', 'Awaiting Management Response'), ('action_required', 'Action Required'),
          ('pending_verification', 'Pending Verification'), ('closed', 'Closed'),
          ('rejected', 'Rejected (Duplicate / False Positive)'), ('reopened', 'Reopened')]
OPEN_STATES = {'new', 'triaged', 'investigating', 'awaiting_response', 'action_required',
               'pending_verification', 'reopened'}
TRANSITIONS = {
    'triaged': {'new', 'reopened'},
    'investigating': {'triaged', 'reopened'},
    'awaiting_response': {'investigating'},
    'action_required': {'awaiting_response'},
    'pending_verification': {'action_required'},
    'closed': {'pending_verification'},
    'rejected': OPEN_STATES,
    'reopened': {'closed'},
}
SEVERITY_WEIGHT = {'informational': 5, 'low': 25, 'medium': 50, 'high': 75, 'critical': 95}
NATURE_FACTOR = {'verified_inconsistency': 1.0, 'policy_exception': 0.9,
                 'risk_indicator': 0.7, 'needs_investigation': 0.6}


class AuditorFinding(models.Model):
    _name = 'odoo.auditor.finding'
    _description = 'Audit Finding'
    _inherit = ['odoo.auditor.logged.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'risk_score desc, id desc'
    _log_fields = ('state', 'severity', 'assigned_user_id', 'process_owner_id', 'due_date', 'root_cause',
                   'recommendation', 'management_response', 'resolution_notes', 'active', 'is_confidential')

    name = fields.Char(string='Finding No.', readonly=True, copy=False, default='New')
    title = fields.Char(required=True, tracking=True)
    description = fields.Text()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', required=True, index=True)
    rule_id = fields.Many2one('odoo.auditor.rule', index=True, ondelete='restrict')
    rule_code = fields.Char(related='rule_id.code', store=True)
    domain_area = fields.Selection(related='rule_id.domain_area', store=True)
    run_id = fields.Many2one('odoo.auditor.run', string='Detected in Run', index=True)
    last_run_id = fields.Many2one('odoo.auditor.run', string='Last Detected in Run')
    fingerprint = fields.Char(index=True, copy=False)
    source_model = fields.Char()
    source_res_id = fields.Integer()
    source_name = fields.Char(string='Source Document')
    source_date = fields.Date(string='Source Document Date')
    partner_id = fields.Many2one('res.partner')
    product_name = fields.Char(string='Related Product')
    product_res_id = fields.Integer(string='Product ID')
    detection_date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    severity = fields.Selection(SEVERITIES, required=True, default='medium', tracking=True)
    nature = fields.Selection(NATURES, required=True, default='needs_investigation')
    risk_score = fields.Integer(compute='_compute_risk_score', store=True,
                                help="Severity weight (informational 5, low 25, medium 50, high 75, critical 95) "
                                     "multiplied by a nature factor (verified 1.0, policy exception 0.9, "
                                     "risk indicator 0.7, needs investigation 0.6).")
    estimated_impact = fields.Monetary(currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    validation_status = fields.Selection([('unvalidated', 'Unvalidated'), ('confirmed', 'Confirmed'),
                                          ('false_positive', 'False positive')], default='unvalidated')
    expected_condition = fields.Text()
    actual_condition = fields.Text()
    evidence_ids = fields.One2many('odoo.auditor.evidence', 'finding_id')
    evidence_count = fields.Integer(compute='_compute_evidence_count')
    state = fields.Selection(STATES, default='new', required=True, tracking=True, index=True, copy=False)
    assigned_user_id = fields.Many2one('res.users', string='Assigned Auditor', tracking=True)
    process_owner_id = fields.Many2one('res.users', string='Process Owner', tracking=True)
    department = fields.Char()
    root_cause = fields.Text()
    recommendation = fields.Text()
    management_response = fields.Text()
    action_ids = fields.One2many('odoo.auditor.action', 'finding_id')
    action_count = fields.Integer(compute='_compute_action_count')
    due_date = fields.Date(tracking=True)
    resolution_notes = fields.Text()
    related_finding_ids = fields.Many2many('odoo.auditor.finding', 'odoo_auditor_finding_rel', 'a_id', 'b_id')
    reopened_count = fields.Integer(readonly=True, copy=False)
    last_verified_date = fields.Date(readonly=True)
    closed_by = fields.Many2one('res.users', readonly=True, copy=False)
    closed_date = fields.Datetime(readonly=True, copy=False)
    closure_note = fields.Text(readonly=True, copy=False)
    rejection_justification = fields.Text(readonly=True, copy=False)
    rejected_by = fields.Many2one('res.users', readonly=True, copy=False)
    is_confidential = fields.Boolean(string='Confidential (HR / Payroll)', default=False)

    @api.depends('severity', 'nature')
    def _compute_risk_score(self):
        for f in self:
            f.risk_score = round(SEVERITY_WEIGHT.get(f.severity, 0) * NATURE_FACTOR.get(f.nature, 1))

    @api.depends('evidence_ids')
    def _compute_evidence_count(self):
        for f in self:
            f.evidence_count = len(f.evidence_ids)

    @api.depends('action_ids')
    def _compute_action_count(self):
        for f in self:
            f.action_count = len(f.action_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('odoo.auditor.finding') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        if 'state' in vals and not self.env.context.get('auditor_transition'):
            raise UserError(self.env._("The state can only be changed through the workflow buttons."))
        return super().write(vals)

    def unlink(self):
        for rec in self:
            self.env['odoo.auditor.log'].log('unlink_blocked', rec)
        raise UserError(self.env._("Findings cannot be deleted. Archive them instead."))

    # ------------------------------------------------------------- workflow
    def _transition(self, new_state, **extra):
        for rec in self:
            if rec.state not in TRANSITIONS[new_state]:
                raise UserError(self.env._("Transition from '%(a)s' to '%(b)s' is not allowed.",
                                           a=dict(STATES)[rec.state], b=dict(STATES)[new_state]))
        self.with_context(auditor_transition=True).write(dict(extra, state=new_state))

    def _check_manager(self):
        if not self.env.user.has_group('odoo_auditor.group_auditor_manager'):
            raise UserError(self.env._("Only an Audit Manager can perform this operation."))

    def action_triage(self):
        self._transition('triaged')
        for rec in self.filtered(lambda r: not r.assigned_user_id):
            rec.assigned_user_id = self.env.user

    def action_investigate(self):
        self._transition('investigating')

    def action_request_response(self):
        self._transition('awaiting_response')

    def action_require_action(self):
        self._transition('action_required')

    def action_pending_verification(self):
        for rec in self:
            if not rec.action_ids and rec.severity in ('high', 'critical'):
                raise UserError(self.env._("High / critical findings need at least one corrective action."))
            if any(a.state not in ('completed', 'verified', 'cancelled') for a in rec.action_ids):
                raise UserError(self.env._("All corrective actions must be completed first."))
        self._transition('pending_verification')

    def _close(self, note):
        self._check_manager()
        for rec in self:
            if rec.severity in ('high', 'critical'):
                blockers = rec.action_ids.mapped('responsible_user_id') | rec.process_owner_id
                if self.env.user in blockers:
                    raise UserError(self.env._(
                        "Segregation of duties: the process owner / action owner cannot close a "
                        "high or critical finding."))
                if any(a.state not in ('verified', 'cancelled') for a in rec.action_ids):
                    raise UserError(self.env._("High / critical findings require verified corrective actions."))
        self._transition('closed', closed_by=self.env.uid, closed_date=fields.Datetime.now(),
                         closure_note=note, last_verified_date=fields.Date.today())

    def _reject(self, justification):
        self._check_manager()
        if not (justification or '').strip():
            raise UserError(self.env._("A documented justification is required."))
        self._transition('rejected', rejection_justification=justification, rejected_by=self.env.uid,
                         validation_status='false_positive')

    def action_reopen(self):
        self._check_manager()
        for rec in self:
            self._reopen_one(rec, self.env._("Reopened manually."))

    def _reopen_one(self, rec, why):
        rec._transition('reopened', reopened_count=rec.reopened_count + 1, closed_by=False, closed_date=False)
        rec.message_post(body=why)

    def _reopen_recurrence(self, run):
        for rec in self:
            self._reopen_one(rec.sudo(), self.env._("Condition detected again by run %s - finding reopened.", run.name))

    def action_open_resolution_wizard(self):
        mode = self.env.context.get('resolution_mode', 'close')
        return {'type': 'ir.actions.act_window', 'res_model': 'odoo.auditor.finding.resolution.wizard',
                'view_mode': 'form', 'target': 'new',
                'context': {'default_finding_id': self.id, 'default_mode': mode}}

    def action_create_corrective_action(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'odoo.auditor.action', 'view_mode': 'form',
                'target': 'current', 'context': {
                    'default_finding_id': self.id, 'default_title': self.title,
                    'default_description': self.recommendation or self.title,
                    'default_root_cause': self.root_cause,
                    'default_responsible_user_id': (self.process_owner_id or self.assigned_user_id or self.env.user).id,
                    'default_deadline': self.due_date or fields.Date.add(fields.Date.today(), days=14)}}

    def _ignore_future(self, justification):
        """Reject the finding and register a documented exclusion so the condition is not reported again."""
        self._reject(justification)
        Excl = self.env['odoo.auditor.exclusion'].sudo().with_context(active_test=False)
        for rec in self.filtered('fingerprint'):
            existing = Excl.search([('fingerprint', '=', rec.fingerprint), ('company_id', '=', rec.company_id.id)], limit=1)
            vals = {'reason': justification, 'active': True, 'finding_id': rec.id, 'source_name': rec.source_name}
            if existing:
                existing.write(vals)
            else:
                Excl.create(dict(vals, fingerprint=rec.fingerprint, rule_id=rec.rule_id.id, company_id=rec.company_id.id))

    def action_export_xlsx(self):
        from .audit_export import build_findings_xlsx, download_action
        return download_action(build_findings_xlsx(self.env, self))

    def action_open_source(self):
        self.ensure_one()
        if not self.source_model or self.source_model not in self.env:
            raise UserError(self.env._("The source record is not available."))
        return {'type': 'ir.actions.act_window', 'res_model': self.source_model, 'res_id': self.source_res_id,
                'view_mode': 'form', 'target': 'current'}

    def action_view_evidence(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': self.env._('Evidence'),
                'res_model': 'odoo.auditor.evidence', 'view_mode': 'list,form',
                'domain': [('finding_id', '=', self.id)], 'context': {'default_finding_id': self.id}}

    def action_view_actions(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': self.env._('Corrective Actions'),
                'res_model': 'odoo.auditor.action', 'view_mode': 'list,form',
                'domain': [('finding_id', '=', self.id)], 'context': {'default_finding_id': self.id}}

    @api.model
    def get_dashboard_data(self):
        """KPIs for the OWL dashboard. Runs as the current user, so record rules (incl. confidentiality) apply."""
        open_dom = [('state', 'not in', ('closed', 'rejected'))]
        by_sev = dict(self._read_group(open_dom, ['severity'], ['__count']))
        by_dom = dict(self._read_group(open_dom, ['domain_area'], ['__count']))
        by_state = dict(self._read_group([], ['state'], ['__count']))
        top_rules = self._read_group(open_dom, ['rule_id'], ['__count'], order='__count desc', limit=5)
        runs = self.env['odoo.auditor.run'].search_read(
            [], ['name', 'audit_name', 'state', 'finding_count', 'start_datetime'], limit=5, order='id desc')
        return {
            'open_total': sum(by_sev.values()),
            'severity': {k: by_sev.get(k, 0) for k, _v in SEVERITIES},
            'domains': [{'key': k or 'other', 'count': v} for k, v in by_dom.items()],
            'states': {k: by_state.get(k, 0) for k, _v in STATES},
            'overdue_actions': self.env['odoo.auditor.action'].search_count([('is_overdue', '=', True)]),
            'top_rules': [{'id': r.id, 'name': r.display_name, 'count': c} for r, c in top_rules if r],
            'runs': runs,
        }
