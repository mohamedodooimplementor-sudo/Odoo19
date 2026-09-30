# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ConstructionActivity(models.Model):
    _name = 'construction.activity'
    _description = 'Project Schedule Activity'
    _order = 'project_id, sequence, date_start'

    name       = fields.Char(string='Activity', required=True)
    project_id = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    sequence   = fields.Integer(string='Sequence', default=10)

    date_start = fields.Date(string='Planned Start', required=True)
    date_end   = fields.Date(string='Planned End', required=True)
    duration_days = fields.Integer(string='Duration (Days)', compute='_compute_duration', store=True)

    actual_date_start = fields.Date(string='Actual Start')
    actual_date_end   = fields.Date(string='Actual End')
    delay_days = fields.Integer(string='Delay (Days)', compute='_compute_delay', store=True,
                                 help='Actual End - Planned End. Positive = late, negative/zero = on time or early.')
    delay_responsibility = fields.Selection([
        ('contractor',    'Contractor'),
        ('client',        'Client'),
        ('subcontractor', 'Subcontractor'),
        ('force_majeure', 'Force Majeure / External'),
        ('not_applicable','Not Applicable'),
    ], string='Delay Responsibility')
    delay_notes = fields.Text(string='Delay Notes')

    @api.depends('date_end', 'actual_date_end')
    def _compute_delay(self):
        for rec in self:
            if rec.actual_date_end and rec.date_end:
                rec.delay_days = (rec.actual_date_end - rec.date_end).days
            else:
                rec.delay_days = 0

    progress   = fields.Float(string='Progress %', default=0.0)
    responsible_id = fields.Many2one('res.users', string='Responsible')

    predecessor_ids = fields.Many2many(
        'construction.activity', 'construction_activity_dependency_rel',
        'activity_id', 'predecessor_id', string='Predecessors',
        domain="[('project_id','=',project_id),('id','!=',id)]")

    is_milestone = fields.Boolean(string='Milestone')
    color        = fields.Integer(string='Color', compute='_compute_color')

    # ── Baseline Schedule (snapshot of the originally committed plan) ──
    baseline_start = fields.Date(string='Baseline Start', readonly=True, copy=False)
    baseline_end   = fields.Date(string='Baseline End', readonly=True, copy=False)
    baseline_variance_days = fields.Integer(
        string='Baseline Variance (Days)', compute='_compute_baseline_variance', store=True,
        help='Planned End - Baseline End. Positive = the plan has slipped since baseline was set.')

    @api.depends('date_end', 'baseline_end')
    def _compute_baseline_variance(self):
        for rec in self:
            rec.baseline_variance_days = (
                (rec.date_end - rec.baseline_end).days if rec.date_end and rec.baseline_end else 0)

    # ── Critical Path Method (CPM) — computed via Project > Compute Critical Path ──
    calc_early_start  = fields.Date(string='Early Start (Calc.)', readonly=True, copy=False)
    calc_early_finish = fields.Date(string='Early Finish (Calc.)', readonly=True, copy=False)
    calc_late_start   = fields.Date(string='Late Start (Calc.)', readonly=True, copy=False)
    calc_late_finish  = fields.Date(string='Late Finish (Calc.)', readonly=True, copy=False)
    total_float = fields.Integer(string='Total Float (Days)', readonly=True, copy=False)
    is_critical = fields.Boolean(string='Critical Path', readonly=True, copy=False)

    @api.depends('date_start', 'date_end')
    def _compute_duration(self):
        for rec in self:
            rec.duration_days = (rec.date_end - rec.date_start).days + 1 if rec.date_start and rec.date_end else 0

    @api.depends('progress')
    def _compute_color(self):
        for rec in self:
            if rec.progress >= 100:
                rec.color = 1   # green-ish index used client-side
            elif rec.progress > 0:
                rec.color = 2   # amber
            else:
                rec.color = 0   # blue/default

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_start > rec.date_end:
                raise ValidationError(_('Activity start date must be before its end date.'))
