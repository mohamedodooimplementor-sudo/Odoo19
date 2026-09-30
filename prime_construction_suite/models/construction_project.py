# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class ConstructionProject(models.Model):
    _name = 'construction.project'
    _description = 'Construction Project'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'date_start desc, id desc'

    name = fields.Char(string='Project Name', required=True, tracking=True)
    code = fields.Char(string='Project Code', readonly=True, copy=False, default='New')
    description = fields.Html(string='Description')

    client_id = fields.Many2one('res.partner', string='Client', required=True, tracking=True)
    project_manager_id = fields.Many2one('res.users', string='Project Manager',
                                          default=lambda self: self.env.user, tracking=True)
    site_engineer_id = fields.Many2one('hr.employee', string='Site Engineer')
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                  default=lambda self: self.env.company)

    site_address = fields.Char(string='Site Address')
    date_start   = fields.Date(string='Start Date', required=True, tracking=True)
    date_end     = fields.Date(string='Planned End Date', required=True, tracking=True)
    date_actual_end = fields.Date(string='Actual End Date', tracking=True)
    duration_days = fields.Integer(string='Duration (Days)', compute='_compute_duration', store=True)

    state = fields.Selection([
        ('draft',     'Draft'),
        ('confirmed', 'Confirmed'),
        ('running',   'In Progress'),
        ('done',      'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, required=True)

    currency_id     = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    contract_value  = fields.Monetary(string='Contract Value', currency_field='currency_id', tracking=True)
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account', copy=False)
    site_location_id = fields.Many2one(
        'stock.location', string='Site Stock Location', copy=False,
        help='Child stock location representing materials physically on this project site '
             '(as opposed to the main warehouse). Created automatically the first time it is needed.')

    # ── Earned Value Management (EVM) ──
    evm_bac = fields.Monetary(string='BAC (Budget at Completion)', currency_field='currency_id',
                               compute='_compute_evm')
    evm_pv = fields.Monetary(string='PV (Planned Value)', currency_field='currency_id', compute='_compute_evm',
                              help='Budgeted cost of work scheduled to date (linear distribution '
                                   'of BAC across the project timeline).')
    evm_ev = fields.Monetary(string='EV (Earned Value)', currency_field='currency_id', compute='_compute_evm',
                              help='BAC x physical completion %, from approved Measurement Sheets.')
    evm_ac = fields.Monetary(string='AC (Actual Cost)', currency_field='currency_id', compute='_compute_evm')
    evm_cpi = fields.Float(string='CPI (Cost Performance Index)', compute='_compute_evm',
                            help='EV / AC. Above 1.0 = under budget. Below 1.0 = over budget.')
    evm_spi = fields.Float(string='SPI (Schedule Performance Index)', compute='_compute_evm',
                            help='EV / PV. Above 1.0 = ahead of schedule. Below 1.0 = behind schedule.')
    evm_cv = fields.Monetary(string='CV (Cost Variance)', currency_field='currency_id', compute='_compute_evm')
    evm_sv = fields.Monetary(string='SV (Schedule Variance)', currency_field='currency_id', compute='_compute_evm')
    evm_eac = fields.Monetary(string='EAC (Estimate at Completion)', currency_field='currency_id',
                               compute='_compute_evm', help='BAC / CPI — projected final cost if the current '
                                                             'cost performance trend continues.')
    evm_etc = fields.Monetary(string='ETC (Estimate to Complete)', currency_field='currency_id', compute='_compute_evm')
    evm_vac = fields.Monetary(string='VAC (Variance at Completion)', currency_field='currency_id', compute='_compute_evm')

    def _compute_evm(self):
        today = fields.Date.context_today(self)
        for rec in self:
            bac = (rec.contract_id.revised_contract_value if rec.contract_id else rec.contract_value) or 0.0

            if rec.date_start and rec.date_end and rec.date_end > rec.date_start:
                total_days = (rec.date_end - rec.date_start).days
                elapsed_days = max(min((today - rec.date_start).days, total_days), 0)
                pv = bac * (elapsed_days / total_days) if total_days else 0.0
            else:
                pv = 0.0

            boq_lines = rec.contract_id.boq_line_ids if rec.contract_id else self.env['construction.boq.line']
            boq_value = sum(boq_lines.mapped('total_price'))
            physical_pct = (
                sum(l.total_price * l.physical_completion_percent for l in boq_lines) / boq_value
                if boq_value else 0.0)
            ev = bac * (physical_pct / 100.0)

            ac = sum(rec.cost_ids.filtered(lambda c: c.state == 'approved').mapped('amount'))

            cpi = (ev / ac) if ac else 0.0
            spi = (ev / pv) if pv else 0.0
            cv = ev - ac
            sv = ev - pv
            eac = (bac / cpi) if cpi else bac
            etc = eac - ac
            vac = bac - eac

            rec.evm_bac, rec.evm_pv, rec.evm_ev, rec.evm_ac = bac, pv, ev, ac
            rec.evm_cpi, rec.evm_spi = cpi, spi
            rec.evm_cv, rec.evm_sv = cv, sv
            rec.evm_eac, rec.evm_etc, rec.evm_vac = eac, etc, vac

    def _get_or_create_site_location(self):
        self.ensure_one()
        if self.site_location_id:
            return self.site_location_id
        parent = self.env['stock.warehouse'].search(
            [('company_id', '=', self.company_id.id)], limit=1).lot_stock_id
        if not parent:
            parent = self.env.ref('stock.stock_location_stock', raise_if_not_found=False)
        location = self.env['stock.location'].create({
            'name': 'Site - %s' % self.name,
            'location_id': parent.id if parent else False,
            'usage': 'internal',
            'company_id': self.company_id.id,
        })
        self.site_location_id = location.id
        return location

    contract_id    = fields.Many2one('construction.contract', string='Contract', copy=False)
    contract_count = fields.Integer(compute='_compute_contract_count')
    program_id     = fields.Many2one('construction.program', string='Program / Portfolio')
    progress_percent = fields.Float(string='Progress %', compute='_compute_progress', store=True)

    dlp_months    = fields.Integer(string='Defects Liability Period (Months)', default=12)
    dlp_end_date  = fields.Date(string='DLP End Date', compute='_compute_dlp', store=True)
    dlp_state = fields.Selection([
        ('not_started', 'Not Started'),
        ('active',      'Active'),
        ('expired',     'Expired'),
    ], string='DLP Status', compute='_compute_dlp', store=True)

    snag_ids        = fields.One2many('construction.snag', 'project_id', string='Snagging Items')
    guarantee_ids   = fields.One2many('construction.guarantee', 'project_id', string='Bank Guarantees')
    insurance_ids   = fields.One2many('construction.insurance', 'project_id', string='Insurance Policies')
    document_ids    = fields.One2many('construction.document', 'project_id', string='Documents')
    schedule_activity_ids = fields.One2many('construction.activity', 'project_id', string='Schedule Activities')
    cost_ids        = fields.One2many('construction.actual.cost', 'project_id', string='Actual Costs')
    risk_ids        = fields.One2many('construction.risk', 'project_id', string='Risks')
    site_diary_ids  = fields.One2many('construction.site.diary', 'project_id', string='Site Diary Entries')
    hse_incident_ids = fields.One2many('construction.hse.incident', 'project_id', string='Site Incidents')
    hse_permit_ids   = fields.One2many('construction.hse.permit', 'project_id', string='Work Permits')
    labor_attendance_ids = fields.One2many('construction.labor.attendance', 'project_id', string='Labor Attendance')
    drawing_ids     = fields.One2many('construction.drawing', 'project_id', string='Drawings')
    tender_ids      = fields.One2many('construction.tender', 'project_id', string='Tenders')
    high_risk_count       = fields.Integer(compute='_compute_hse_counts')
    open_incident_count   = fields.Integer(compute='_compute_hse_counts')

    @api.depends('risk_ids.risk_level', 'risk_ids.status', 'hse_incident_ids.status')
    def _compute_hse_counts(self):
        for rec in self:
            rec.high_risk_count = len(rec.risk_ids.filtered(lambda r: r.risk_level == 'high' and r.status == 'open'))
            rec.open_incident_count = len(rec.hse_incident_ids.filtered(lambda i: i.status == 'open'))

    material_request_count = fields.Integer(compute='_compute_procurement_quality_counts')
    rfq_count = fields.Integer(compute='_compute_procurement_quality_counts')
    ncr_open_count = fields.Integer(compute='_compute_procurement_quality_counts')

    def _compute_procurement_quality_counts(self):
        for rec in self:
            rec.material_request_count = self.env['construction.material.request'].search_count(
                [('project_id', '=', rec.id)])
            rec.rfq_count = self.env['construction.rfq'].search_count([('project_id', '=', rec.id)])
            rec.ncr_open_count = self.env['construction.quality.ncr'].search_count(
                [('project_id', '=', rec.id), ('state', '!=', 'closed')])

    def action_view_material_requests(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'Material Requests',
                'res_model': 'construction.material.request', 'view_mode': 'list,form',
                'domain': [('project_id', '=', self.id)], 'context': {'default_project_id': self.id}}

    def action_view_rfqs(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'RFQs',
                'res_model': 'construction.rfq', 'view_mode': 'list,form',
                'domain': [('project_id', '=', self.id)], 'context': {'default_project_id': self.id}}

    def action_view_ncrs(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': 'NCRs',
                'res_model': 'construction.quality.ncr', 'view_mode': 'list,form',
                'domain': [('project_id', '=', self.id)], 'context': {'default_project_id': self.id}}
    snag_open_count = fields.Integer(compute='_compute_extra_counts')
    guarantee_count = fields.Integer(compute='_compute_extra_counts')
    insurance_count = fields.Integer(compute='_compute_extra_counts')

    @api.depends('snag_ids.status', 'guarantee_ids', 'insurance_ids')
    def _compute_extra_counts(self):
        for rec in self:
            rec.snag_open_count = len(rec.snag_ids.filtered(lambda s: s.status != 'closed'))
            rec.guarantee_count = len(rec.guarantee_ids)
            rec.insurance_count = len(rec.insurance_ids)

    @api.depends('date_actual_end', 'dlp_months')
    def _compute_dlp(self):
        from datetime import date
        from dateutil.relativedelta import relativedelta
        today = date.today()
        for rec in self:
            if not rec.date_actual_end:
                rec.dlp_end_date = False
                rec.dlp_state = 'not_started'
                continue
            rec.dlp_end_date = rec.date_actual_end + relativedelta(months=rec.dlp_months or 0)
            rec.dlp_state = 'expired' if rec.dlp_end_date and rec.dlp_end_date < today else 'active'

    budget_at_completion = fields.Monetary(string='Budget at Completion (BAC)', currency_field='currency_id',
                                            compute='_compute_evm', store=True)
    planned_value        = fields.Monetary(string='Planned Value (PV)', currency_field='currency_id',
                                            compute='_compute_evm', store=True,
                                            help='BAC x % of project schedule elapsed — the value of work that should have been done by now.')
    earned_value         = fields.Monetary(string='Earned Value (EV)', currency_field='currency_id',
                                            compute='_compute_evm', store=True,
                                            help='Total value of physically completed BOQ quantities, regardless of billing status.')
    actual_cost_total     = fields.Monetary(string='Actual Cost (AC)', currency_field='currency_id',
                                             compute='_compute_evm', store=True)
    cost_performance_index     = fields.Float(string='CPI', compute='_compute_evm', store=True,
                                               help='EV / AC. Above 1.0 = under budget for work completed. Below 1.0 = over budget.')
    schedule_performance_index = fields.Float(string='SPI', compute='_compute_evm', store=True,
                                               help='EV / PV. Above 1.0 = ahead of schedule. Below 1.0 = behind schedule.')

    @api.depends('contract_value', 'progress_percent', 'contract_id.boq_line_ids.executed_value')
    def _compute_evm(self):
        for rec in self:
            rec.budget_at_completion = rec.contract_value
            rec.planned_value = rec.contract_value * (rec.progress_percent or 0.0) / 100

            boq_lines = rec.contract_id.boq_line_ids if rec.contract_id else self.env['construction.boq.line']
            rec.earned_value = sum(boq_lines.mapped('executed_value'))

            costs = self.env['construction.actual.cost'].search([
                ('project_id', '=', rec.id), ('state', '=', 'approved')])
            rec.actual_cost_total = sum(costs.mapped('amount'))

            rec.cost_performance_index = (rec.earned_value / rec.actual_cost_total) if rec.actual_cost_total else 0.0
            rec.schedule_performance_index = (rec.earned_value / rec.planned_value) if rec.planned_value else 0.0

    @api.depends('date_start', 'date_end')
    def _compute_duration(self):
        for rec in self:
            if rec.date_start and rec.date_end:
                rec.duration_days = (rec.date_end - rec.date_start).days
            else:
                rec.duration_days = 0

    @api.depends('contract_id')
    def _compute_contract_count(self):
        for rec in self:
            rec.contract_count = 1 if rec.contract_id else 0

    @api.depends('date_start', 'date_end', 'date_actual_end', 'state')
    def _compute_progress(self):
        from datetime import date
        today = date.today()
        for rec in self:
            if rec.state == 'done':
                rec.progress_percent = 100.0
            elif rec.state in ('draft', 'confirmed'):
                rec.progress_percent = 0.0
            elif rec.date_start and rec.date_end:
                total = (rec.date_end - rec.date_start).days
                rec.progress_percent = min(round((today - rec.date_start).days / total * 100, 2), 99.0) if total > 0 else 0.0
            else:
                rec.progress_percent = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', 'New') == 'New':
                vals['code'] = self.env['ir.sequence'].next_by_code('construction.project') or 'New'
            if not vals.get('analytic_account_id'):
                plan = self.env['account.analytic.plan'].search([], limit=1)
                analytic = self.env['account.analytic.account'].create({
                    'name': vals.get('name', ''),
                    'company_id': vals.get('company_id', self.env.company.id),
                    'plan_id': plan.id if plan else False,
                })
                vals['analytic_account_id'] = analytic.id
        return super().create(vals_list)

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_start > rec.date_end:
                raise ValidationError(_('Start date cannot be after end date!'))

    def action_confirm(self):   self.write({'state': 'confirmed'})
    def action_start(self):     self.write({'state': 'running'})
    def action_cancel(self):    self.write({'state': 'cancelled'})
    def action_reset_draft(self): self.write({'state': 'draft'})

    def action_set_baseline(self):
        """Snapshot the current Planned Start/End of every schedule activity as its Baseline,
        so future slippage can be measured against this committed plan. Safe to re-run — only
        activities without an existing baseline are captured, protecting the original snapshot."""
        for project in self:
            activities = project.schedule_activity_ids.filtered(lambda a: not a.baseline_start)
            for act in activities:
                act.write({'baseline_start': act.date_start, 'baseline_end': act.date_end})

    def action_compute_cpm(self):
        """Compute the Critical Path (CPM): early/late start & finish and total float for every
        schedule activity, using planned durations and Finish-to-Start Predecessor dependencies
        (0 lag). Activities with zero float are on the critical path. This computes an idealized
        schedule from the network logic — it does not overwrite the Planned Start/End dates you
        already entered."""
        from datetime import timedelta
        for project in self:
            activities = project.schedule_activity_ids
            if not activities:
                raise UserError(_('There are no schedule activities to compute for %s.') % project.name)

            by_id = {a.id: a for a in activities}
            preds = {a.id: set(a.predecessor_ids.ids) & set(by_id.keys()) for a in activities}
            succs = {aid: set() for aid in by_id}
            for aid, pset in preds.items():
                for p in pset:
                    succs[p].add(aid)
            duration = {aid: max(by_id[aid].duration_days, 1) for aid in by_id}

            # Kahn's topological sort
            remaining_preds = {aid: set(p) for aid, p in preds.items()}
            queue = [aid for aid, p in remaining_preds.items() if not p]
            topo_order = []
            while queue:
                aid = queue.pop(0)
                topo_order.append(aid)
                for s in succs[aid]:
                    remaining_preds[s].discard(aid)
                    if not remaining_preds[s] and s not in topo_order and s not in queue:
                        queue.append(s)
            if len(topo_order) < len(by_id):
                raise UserError(_(
                    'Could not compute the Critical Path for %s: a circular dependency was '
                    'detected between activities. Please review the Predecessors.') % project.name)

            starts = [by_id[aid].date_start for aid in by_id if by_id[aid].date_start]
            project_start = min(starts) if starts else fields.Date.context_today(self)

            early_start, early_finish = {}, {}
            for aid in topo_order:
                rel_preds = preds[aid]
                es = max((early_finish[p] for p in rel_preds), default=project_start)
                ef = es + timedelta(days=duration[aid])
                early_start[aid], early_finish[aid] = es, ef

            project_finish = max(early_finish.values())

            late_start, late_finish = {}, {}
            for aid in reversed(topo_order):
                rel_succs = succs[aid]
                lf = min((late_start[s] for s in rel_succs), default=project_finish)
                ls = lf - timedelta(days=duration[aid])
                late_finish[aid], late_start[aid] = lf, ls

            for aid, act in by_id.items():
                total_float = (late_start[aid] - early_start[aid]).days
                act.write({
                    'calc_early_start':  early_start[aid],
                    'calc_early_finish': early_finish[aid],
                    'calc_late_start':   late_start[aid],
                    'calc_late_finish':  late_finish[aid],
                    'total_float': total_float,
                    'is_critical': total_float <= 0,
                })

    def action_done(self):
        from datetime import date
        self.write({'state': 'done', 'date_actual_end': date.today(), 'progress_percent': 100.0})

    def action_view_contract(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Project Contract'),
            'res_model': 'construction.contract',
            'view_mode': 'form',
            'res_id': self.contract_id.id if self.contract_id else False,
            'context': {'default_project_id': self.id},
        }

    def action_view_snags(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Snagging List'),
            'res_model': 'construction.snag', 'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_view_guarantees(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Bank Guarantees'),
            'res_model': 'construction.guarantee', 'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_view_insurance(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Insurance Policies'),
            'res_model': 'construction.insurance', 'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_view_risks(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Risk Register'),
            'res_model': 'construction.risk', 'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_view_incidents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Site Incidents'),
            'res_model': 'construction.hse.incident', 'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_view_drawings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Drawings'),
            'res_model': 'construction.drawing', 'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_view_tenders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Tenders'),
            'res_model': 'construction.tender', 'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def _cron_check_dlp_expiry(self):
        """Remind the project manager 30 days before the Defects Liability Period ends."""
        from datetime import date, timedelta
        today = date.today()
        soon = today + timedelta(days=30)
        candidates = self.search([('dlp_state', '=', 'active'), ('dlp_end_date', '<=', soon), ('dlp_end_date', '>=', today)])
        for rec in candidates:
            already = rec.activity_ids.filtered(lambda a: a.summary == _('DLP Ending Soon'))
            if already:
                continue
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('DLP Ending Soon'),
                note=_('The Defects Liability Period for project %s ends on %s. Please review open snags before it closes.')
                     % (rec.name, rec.dlp_end_date),
                user_id=rec.project_manager_id.id or self.env.user.id,
            )
