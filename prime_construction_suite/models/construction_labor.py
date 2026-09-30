# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class ConstructionLaborer(models.Model):
    _name = 'construction.laborer'
    _description = 'Daily Laborer'
    _rec_name = 'name'
    _order = 'name'

    name         = fields.Char(string='Full Name', required=True)
    national_id  = fields.Char(string='National ID')
    phone        = fields.Char(string='Phone')
    trade = fields.Selection([
        ('mason',        'Mason'),
        ('carpenter',    'Carpenter'),
        ('steel_fixer',  'Steel Fixer'),
        ('electrician',  'Electrician'),
        ('plumber',      'Plumber'),
        ('painter',      'Painter'),
        ('helper',       'Helper / General Labor'),
        ('operator',     'Equipment Operator'),
        ('other',        'Other'),
    ], string='Trade', required=True, default='helper')

    daily_rate = fields.Monetary(string='Standard Daily Rate', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    active     = fields.Boolean(default=True)

    attendance_ids = fields.One2many('construction.labor.attendance', 'laborer_id', string='Attendance Records')


class ConstructionLaborAttendance(models.Model):
    _name = 'construction.labor.attendance'
    _description = 'Daily Labor Attendance'
    _order = 'date desc'

    laborer_id = fields.Many2one('construction.laborer', string='Laborer', required=True)
    project_id = fields.Many2one('construction.project', string='Project', required=True)
    boq_line_id  = fields.Many2one('construction.boq.line', string='BOQ Item', domain="[('contract_id.project_id','=',project_id)]",
                                    help='Optional: attribute this labor cost to a specific BOQ item.')
    cost_code_id = fields.Many2one('construction.cost.code', string='Cost Code (WBS)')
    currency_id = fields.Many2one(related='laborer_id.currency_id', store=True)

    date   = fields.Date(string='Date', required=True, default=fields.Date.today)
    status = fields.Selection([
        ('present',  'Present'),
        ('absent',   'Absent'),
        ('half_day', 'Half Day'),
    ], string='Attendance', default='present', required=True)

    hours_worked    = fields.Float(string='Hours Worked', default=8.0)
    overtime_hours  = fields.Float(string='Overtime Hours')
    overtime_rate_multiplier = fields.Float(string='Overtime Multiplier', default=1.5)

    daily_rate      = fields.Monetary(string='Daily Rate Applied', currency_field='currency_id', compute='_compute_cost', store=True, readonly=False)
    advance_amount  = fields.Monetary(string='Advance Given', currency_field='currency_id')
    deduction_amount= fields.Monetary(string='Other Deductions', currency_field='currency_id')

    gross_cost = fields.Monetary(string='Gross Cost', currency_field='currency_id', compute='_compute_cost', store=True)
    net_cost   = fields.Monetary(string='Net Cost (after advances/deductions)', currency_field='currency_id',
                                  compute='_compute_cost', store=True)

    posted = fields.Boolean(string='Posted to Actual Cost', default=False, copy=False, readonly=True)
    notes  = fields.Char(string='Notes')

    @api.depends('status', 'hours_worked', 'overtime_hours', 'overtime_rate_multiplier',
                 'advance_amount', 'deduction_amount', 'laborer_id.daily_rate')
    def _compute_cost(self):
        for rec in self:
            if not rec.daily_rate:
                rec.daily_rate = rec.laborer_id.daily_rate
            base = 0.0
            if rec.status == 'present':
                base = rec.daily_rate
            elif rec.status == 'half_day':
                base = rec.daily_rate / 2
            hourly_equivalent = (rec.daily_rate / 8.0) if rec.daily_rate else 0.0
            overtime_pay = rec.overtime_hours * hourly_equivalent * rec.overtime_rate_multiplier
            rec.gross_cost = base + overtime_pay
            rec.net_cost = rec.gross_cost - rec.advance_amount - rec.deduction_amount

    def action_post_to_actual_cost(self):
        for rec in self.filtered(lambda r: not r.posted and r.gross_cost):
            self.env['construction.actual.cost'].create({
                'project_id': rec.project_id.id,
                'cost_type': 'labor',
                'boq_line_id': rec.boq_line_id.id if rec.boq_line_id else False,
                'cost_code_id': rec.cost_code_id.id if rec.cost_code_id else False,
                'description': _('Daily Labor: %s (%s)') % (rec.laborer_id.name, rec.date),
                'quantity': 1.0,
                'unit_price': rec.gross_cost,
                'date': rec.date,
            })
            rec.posted = True
