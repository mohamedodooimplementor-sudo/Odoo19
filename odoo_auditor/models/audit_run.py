from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class AuditorRun(models.Model):
    _name = 'odoo.auditor.run'
    _description = 'Audit Run'
    _inherit = ['odoo.auditor.logged.mixin', 'mail.thread']
    _order = 'id desc'
    _log_fields = ('state',)

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    audit_name = fields.Char(required=True)
    audit_type = fields.Selection([('full', 'Full / Multi-domain'), ('financial', 'Financial'),
                                   ('inventory', 'Inventory'), ('sales', 'Sales'), ('purchase', 'Purchase'),
                                   ('custom', 'Custom rule selection')], default='custom', required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    date_from = fields.Date(required=True, default=lambda s: fields.Date.today() - timedelta(days=90))
    date_to = fields.Date(required=True, default=fields.Date.today)
    start_datetime = fields.Datetime(readonly=True)
    end_datetime = fields.Datetime(readonly=True)
    duration = fields.Float(compute='_compute_duration', help="Seconds")
    user_id = fields.Many2one('res.users', string='Initiated by', default=lambda s: s.env.user, readonly=True)
    mode = fields.Selection([('manual', 'Manual'), ('scheduled', 'Scheduled'), ('event', 'Event-triggered')],
                            default='manual', required=True)
    rule_ids = fields.Many2many('odoo.auditor.rule', string='Selected Rules')
    domains_covered = fields.Char(compute='_compute_domains', store=True)
    state = fields.Selection([('draft', 'Draft'), ('queued', 'Queued'), ('running', 'Running'), ('done', 'Done'), ('failed', 'Failed')],
                             default='draft', required=True, tracking=True)
    records_inspected = fields.Integer(readonly=True)
    finding_ids = fields.One2many('odoo.auditor.finding', 'run_id')
    finding_count = fields.Integer(compute='_compute_counts')
    critical_count = fields.Integer(compute='_compute_counts')
    high_count = fields.Integer(compute='_compute_counts')
    medium_count = fields.Integer(compute='_compute_counts')
    low_count = fields.Integer(compute='_compute_counts')
    message_log = fields.Text(string='Errors & Warnings', readonly=True)
    config_snapshot = fields.Text(readonly=True)
    rule_versions = fields.Text(readonly=True)
    summary = fields.Text(readonly=True)
    progress = fields.Float(readonly=True, copy=False)
    current_rule = fields.Char(readonly=True, copy=False)

    @api.depends('start_datetime', 'end_datetime')
    def _compute_duration(self):
        for run in self:
            run.duration = (run.end_datetime - run.start_datetime).total_seconds() \
                if run.start_datetime and run.end_datetime else 0.0

    @api.depends('rule_ids.domain_area')
    def _compute_domains(self):
        for run in self:
            run.domains_covered = ', '.join(sorted(set(run.rule_ids.mapped('domain_area'))))

    @api.depends('finding_ids.severity')
    def _compute_counts(self):
        for run in self:
            sev = run.finding_ids.mapped('severity')
            run.finding_count = len(sev)
            for s in ('critical', 'high', 'medium', 'low'):
                run[s + '_count'] = sev.count(s)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('odoo.auditor.run') or 'New'
        return super().create(vals_list)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for run in self:
            if run.date_from > run.date_to:
                raise UserError(self.env._("'Date from' must not be after 'Date to'."))

    def _add_message(self, level, rule, text):
        line = "[%s] %s: %s" % (level.upper(), rule.code, text)
        self.message_log = ((self.message_log or '') + line + '\n')

    def _update_progress(self, done, total, code):
        self.sudo().write({'progress': (done * 100.0 / total) if total else 100.0, 'current_rule': code or False})
        if self.env.context.get('auditor_commit_progress'):
            self.env.cr.commit()  # background mode only: lets the form show live progress

    def action_queue(self):
        """Run in the background (cron). The form shows progress; the user can keep working."""
        for run in self:
            if not run.rule_ids:
                raise UserError(self.env._("Select at least one rule."))
            run.write({'state': 'queued', 'progress': 0.0})
        cron = self.env.ref('odoo_auditor.cron_process_queue', raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()
        return True

    def action_execute(self):
        """Run (or safely retry) the audit. Findings are de-duplicated by fingerprint, so retrying is idempotent."""
        for run in self:
            if run.state == 'running':
                raise UserError(self.env._("This run is already executing."))
            # Session-level advisory lock: survives progress commits; always released in `finally`.
            key = 7_100_000 + run.company_id.id
            self.env.cr.execute("SELECT pg_try_advisory_lock(%s)", [key])
            if not self.env.cr.fetchone()[0]:
                raise UserError(self.env._("Another audit is currently running for this company."))
            try:
                run._do_execute()
            finally:
                self.env.cr.execute("SELECT pg_advisory_unlock(%s)", [key])
        return True

    def _do_execute(self):
        self.ensure_one()
        run = self
        if not run.rule_ids:
            raise UserError(self.env._("Select at least one rule."))
        run.write({
            'state': 'running', 'start_datetime': fields.Datetime.now(), 'end_datetime': False,
            'message_log': False, 'progress': 0.0,
            'config_snapshot': str({r.code: {'severity': r.severity, 'amount': r.threshold_amount,
                                              'days': r.threshold_days, 'percent': r.threshold_percent,
                                              'params': r.extra_params, 'excluded_partners': r.exclude_partner_ids.ids}
                                    for r in run.rule_ids}),
            'rule_versions': ', '.join("%s v%s" % (r.code, r.version) for r in run.rule_ids),
        })
        try:
            inspected = self.env['odoo.auditor.engine'].execute_run(run)
        except Exception as exc:  # noqa: BLE001
            run.write({'state': 'failed', 'end_datetime': fields.Datetime.now(), 'message_log': str(exc)})
            return
        run.rule_ids._schedule_next()
        run.write({'state': 'done', 'end_datetime': fields.Datetime.now(), 'records_inspected': inspected,
                   'progress': 100.0, 'current_rule': False})
        run.summary = self.env._(
            "%(n)s findings (critical %(c)s, high %(h)s, medium %(m)s, low %(l)s) from %(i)s records inspected.",
            n=run.finding_count, c=run.critical_count, h=run.high_count, m=run.medium_count,
            l=run.low_count, i=inspected)
        tmpl = self.env.ref('odoo_auditor.mail_template_run_summary', raise_if_not_found=False)
        if tmpl and run.mode == 'scheduled' and run.user_id.email:
            try:
                tmpl.sudo().send_mail(run.id)
            except Exception:  # noqa: BLE001 - mail problems must never fail an audit
                pass

    def action_export_xlsx(self):
        from .audit_export import build_findings_xlsx, download_action
        self.ensure_one()
        return download_action(build_findings_xlsx(self.env, self.finding_ids, run=self))

    @api.model
    def cron_process_queue(self):
        for run in self.search([('state', '=', 'queued')], order='id'):
            try:
                run.with_context(auditor_commit_progress=True).action_execute()
            except UserError:
                continue
            self.env.cr.commit()

    def action_view_findings(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': self.env._('Findings'),
                'res_model': 'odoo.auditor.finding', 'view_mode': 'list,form',
                'domain': [('run_id', '=', self.id)]}

    @api.model
    def cron_run_scheduled(self):
        today = fields.Datetime.now()
        rules = self.env['odoo.auditor.rule'].search([
            ('frequency', '!=', 'manual'), '|', ('next_run', '=', False), ('next_run', '<=', today)])
        for company in self.env['res.company'].search([]):
            due = rules.filtered(lambda r: not r.company_id or r.company_id == company)
            if not due:
                continue
            lookback = max(due.mapped('lookback_days') or [90])
            run = self.with_company(company).create({
                'audit_name': self.env._("Scheduled audit %s", fields.Date.today()),
                'company_id': company.id, 'mode': 'scheduled', 'audit_type': 'custom',
                'date_from': fields.Date.today() - timedelta(days=lookback), 'date_to': fields.Date.today(),
                'rule_ids': [(6, 0, due.ids)],
            })
            try:
                run.action_execute()
            except UserError:
                continue  # another run holds the lock; retry on next cron tick
            self.env.cr.commit()
