# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ConstructionKpiDefinition(models.Model):
    _name = 'construction.kpi.definition'
    _description = 'KPI Definition'
    _order = 'sequence, id'

    name     = fields.Char(required=True)
    code     = fields.Char(required=True, help='Short unique code, e.g. PHYS_COMPL, COST_VAR.')
    sequence = fields.Integer(default=10)
    active   = fields.Boolean(default=True)

    kpi_type = fields.Selection([
        ('physical_completion', 'Physical Completion %'),
        ('cost_variance',       'Cost Variance %'),
        ('schedule_variance',   'Schedule Variance (Days Late, Total)'),
        ('safety_incident_rate','Open Safety Incidents'),
        ('profit_margin',       'Profit Margin %'),
        ('manual',              'Manual Entry'),
    ], string='KPI Type', required=True, default='physical_completion')

    target_value = fields.Float(string='Target')
    unit         = fields.Char(default='%')
    description  = fields.Text()

    value_ids  = fields.One2many('construction.kpi.value', 'kpi_id', string='Recorded Values')

    _sql_constraints = [('code_unique', 'unique(code)', 'A KPI with this code already exists.')]

    def _compute_value_for_project(self, project):
        """Compute the current value of this KPI for a given project. Returns 0.0 for 'manual'
        KPIs — those are expected to be entered by hand via construction.kpi.value records."""
        self.ensure_one()
        if self.kpi_type == 'physical_completion':
            boq_lines = project.contract_id.boq_line_ids if project.contract_id else self.env['construction.boq.line']
            total = sum(boq_lines.mapped('total_price'))
            return (
                sum(l.total_price * l.physical_completion_percent for l in boq_lines) / total
                if total else 0.0)

        if self.kpi_type == 'cost_variance':
            contract_value = (project.contract_id.revised_contract_value
                               if project.contract_id else project.contract_value) or 0.0
            actual = sum(project.cost_ids.filtered(lambda c: c.state == 'approved').mapped('amount'))
            return ((contract_value - actual) / contract_value * 100) if contract_value else 0.0

        if self.kpi_type == 'schedule_variance':
            delayed = project.schedule_activity_ids.filtered(lambda a: a.delay_days > 0)
            return float(sum(delayed.mapped('delay_days')))

        if self.kpi_type == 'safety_incident_rate':
            return float(len(project.hse_incident_ids.filtered(lambda i: i.status == 'open')))

        if self.kpi_type == 'profit_margin':
            dash = self.env['construction.project.dashboard'].search(
                [('project_id', '=', project.id)], limit=1)
            if dash and dash.invoiced_amount:
                return (dash.invoiced_amount - dash.actual_cost) / dash.invoiced_amount * 100
            return 0.0

        return 0.0

    def action_snapshot_all_projects(self):
        """Compute and store a dated snapshot of each non-manual KPI's current value, for every
        active project. Run daily via a scheduled action, or manually from here."""
        Project = self.env['construction.project']
        Value = self.env['construction.kpi.value']
        projects = Project.search([('state', 'in', ('confirmed', 'running'))])
        for kpi in self.filtered(lambda k: k.kpi_type != 'manual'):
            for project in projects:
                value = kpi._compute_value_for_project(project)
                Value.create({'kpi_id': kpi.id, 'project_id': project.id, 'value': value})

    @api.model
    def _cron_snapshot_all_kpis(self):
        self.search([('active', '=', True)]).action_snapshot_all_projects()


class ConstructionKpiValue(models.Model):
    _name = 'construction.kpi.value'
    _description = 'KPI Snapshot Value'
    _order = 'date desc'

    kpi_id     = fields.Many2one('construction.kpi.definition', required=True, ondelete='cascade')
    kpi_type   = fields.Selection(related='kpi_id.kpi_type', store=True)
    unit       = fields.Char(related='kpi_id.unit')
    project_id = fields.Many2one('construction.project', required=True, ondelete='cascade')
    date       = fields.Date(default=fields.Date.today, required=True)
    value      = fields.Float(required=True)
    target_value = fields.Float(related='kpi_id.target_value')

    variance = fields.Float(compute='_compute_status', store=True)
    status = fields.Selection([
        ('on_track',  'On Track'),
        ('at_risk',   'At Risk'),
        ('off_track', 'Off Track'),
    ], compute='_compute_status', store=True)

    @api.depends('value', 'target_value')
    def _compute_status(self):
        for rec in self:
            rec.variance = rec.value - rec.target_value
            if not rec.target_value:
                rec.status = 'on_track'
                continue
            pct = rec.variance / abs(rec.target_value) * 100
            if pct >= -5:
                rec.status = 'on_track'
            elif pct >= -15:
                rec.status = 'at_risk'
            else:
                rec.status = 'off_track'
