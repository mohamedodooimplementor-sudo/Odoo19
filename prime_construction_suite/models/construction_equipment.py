# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class ConstructionEquipment(models.Model):
    _name = 'construction.equipment'
    _description = 'Construction Equipment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'name'

    name        = fields.Char(string='Equipment Name', required=True)
    code        = fields.Char(string='Asset Code', required=True, copy=False)
    equipment_type = fields.Selection([
        ('excavator', 'Excavator'),
        ('loader',    'Loader'),
        ('crane',     'Crane / Hoist'),
        ('truck',     'Truck'),
        ('generator', 'Generator'),
        ('compactor', 'Compactor'),
        ('mixer',     'Concrete Mixer'),
        ('pump',      'Pump'),
        ('other',     'Other'),
    ], string='Type', required=True, default='excavator')

    plate_number   = fields.Char(string='Plate / Serial No.')
    ownership_type = fields.Selection([('owned', 'Owned'), ('rented', 'Rented')], default='owned', required=True)
    supplier_id    = fields.Many2one('res.partner', string='Rental Supplier', domain=[('is_company', '=', True)])

    company_id  = fields.Many2one('res.company', default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', store=True)

    hourly_rate      = fields.Monetary(string='Cost per Hour', currency_field='currency_id',
                                        help='Owned equipment: internal cost rate. Rented: rental rate per hour.')
    fuel_price       = fields.Monetary(string='Fuel Price per Liter', currency_field='currency_id')

    current_project_id = fields.Many2one('construction.project', string='Currently Assigned To')

    status = fields.Selection([
        ('available',   'Available'),
        ('in_use',      'In Use'),
        ('maintenance', 'Under Maintenance'),
        ('breakdown',   'Breakdown'),
    ], string='Status', default='available', tracking=True, required=True)

    usage_ids       = fields.One2many('construction.equipment.usage', 'equipment_id', string='Usage Logs')
    maintenance_ids = fields.One2many('construction.equipment.maintenance', 'equipment_id', string='Maintenance Records')
    breakdown_ids   = fields.One2many('construction.equipment.breakdown', 'equipment_id', string='Breakdowns')

    total_hours_operated = fields.Float(string='Total Hours Operated', compute='_compute_totals', store=True)
    total_fuel_cost       = fields.Monetary(string='Total Fuel Cost', currency_field='currency_id', compute='_compute_totals', store=True)
    total_maintenance_cost = fields.Monetary(string='Total Maintenance Cost', currency_field='currency_id', compute='_compute_totals', store=True)
    open_breakdown_count   = fields.Integer(compute='_compute_totals')

    @api.depends('usage_ids.hours_operated', 'usage_ids.fuel_cost',
                 'maintenance_ids.cost', 'breakdown_ids.status')
    def _compute_totals(self):
        for rec in self:
            rec.total_hours_operated  = sum(rec.usage_ids.mapped('hours_operated'))
            rec.total_fuel_cost        = sum(rec.usage_ids.mapped('fuel_cost'))
            rec.total_maintenance_cost = sum(rec.maintenance_ids.mapped('cost'))
            rec.open_breakdown_count   = len(rec.breakdown_ids.filtered(lambda b: b.status != 'resolved'))

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'An equipment with this asset code already exists.'),
    ]

    def action_view_breakdowns(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': 'Breakdowns',
            'res_model': 'construction.equipment.breakdown', 'view_mode': 'list,form',
            'domain': [('equipment_id', '=', self.id)],
            'context': {'default_equipment_id': self.id},
        }


class ConstructionEquipmentUsage(models.Model):
    _name = 'construction.equipment.usage'
    _description = 'Equipment Usage Log'
    _order = 'date desc'

    equipment_id = fields.Many2one('construction.equipment', required=True, ondelete='cascade')
    project_id   = fields.Many2one('construction.project', string='Project', required=True)
    currency_id  = fields.Many2one(related='equipment_id.currency_id', store=True)

    date            = fields.Date(string='Date', required=True, default=fields.Date.today)
    hours_operated  = fields.Float(string='Hours Operated', required=True)
    fuel_liters     = fields.Float(string='Fuel Consumed (L)')
    fuel_cost       = fields.Monetary(string='Fuel Cost', currency_field='currency_id', compute='_compute_costs', store=True)
    equipment_cost  = fields.Monetary(string='Equipment Cost (Hourly)', currency_field='currency_id', compute='_compute_costs', store=True)
    total_cost      = fields.Monetary(string='Total Cost', currency_field='currency_id', compute='_compute_costs', store=True)

    operator_name = fields.Char(string='Operator')
    posted        = fields.Boolean(string='Posted to Actual Cost', default=False, copy=False, readonly=True)
    notes         = fields.Char(string='Notes')

    @api.depends('hours_operated', 'fuel_liters', 'equipment_id.hourly_rate', 'equipment_id.fuel_price')
    def _compute_costs(self):
        for rec in self:
            rec.equipment_cost = rec.hours_operated * (rec.equipment_id.hourly_rate or 0.0)
            rec.fuel_cost      = rec.fuel_liters * (rec.equipment_id.fuel_price or 0.0)
            rec.total_cost     = rec.equipment_cost + rec.fuel_cost

    def action_post_to_actual_cost(self):
        for rec in self.filtered(lambda r: not r.posted):
            self.env['construction.actual.cost'].create({
                'project_id': rec.project_id.id,
                'cost_type': 'equipment',
                'description': _('Equipment Usage: %s (%s hrs)') % (rec.equipment_id.name, rec.hours_operated),
                'quantity': 1.0,
                'unit_price': rec.total_cost,
                'date': rec.date,
            })
            rec.posted = True


class ConstructionEquipmentMaintenance(models.Model):
    _name = 'construction.equipment.maintenance'
    _description = 'Equipment Maintenance Record'
    _order = 'date desc'

    equipment_id = fields.Many2one('construction.equipment', required=True, ondelete='cascade')
    currency_id  = fields.Many2one(related='equipment_id.currency_id', store=True)

    maintenance_type = fields.Selection([
        ('routine',     'Routine Service'),
        ('repair',      'Repair'),
        ('inspection',  'Inspection'),
    ], string='Type', default='routine', required=True)

    date          = fields.Date(string='Date', required=True, default=fields.Date.today)
    description   = fields.Char(string='Description', required=True)
    cost          = fields.Monetary(string='Cost', currency_field='currency_id')
    performed_by  = fields.Char(string='Performed By')
    next_due_date = fields.Date(string='Next Due Date')
    state = fields.Selection([('scheduled', 'Scheduled'), ('done', 'Done')], default='done', required=True)

    def _cron_remind_maintenance_due(self):
        from datetime import date, timedelta
        today = date.today()
        soon = today + timedelta(days=7)
        due = self.search([('next_due_date', '<=', soon), ('next_due_date', '>=', today), ('state', '=', 'done')])
        for rec in due:
            equipment = rec.equipment_id
            already = equipment.activity_ids.filtered(lambda a: a.summary == _('Equipment Maintenance Due'))
            if already:
                continue
            equipment.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('Equipment Maintenance Due'),
                note=_('Equipment %s is due for maintenance on %s.') % (equipment.name, rec.next_due_date),
            )


class ConstructionEquipmentBreakdown(models.Model):
    _name = 'construction.equipment.breakdown'
    _description = 'Equipment Breakdown / Fault Log'
    _order = 'date_reported desc'

    equipment_id  = fields.Many2one('construction.equipment', required=True, ondelete='cascade')
    project_id    = fields.Many2one('construction.project', string='Project (at time of fault)')
    date_reported = fields.Date(string='Date Reported', required=True, default=fields.Date.today)
    description   = fields.Char(string='Fault Description', required=True)
    date_resolved = fields.Date(string='Date Resolved')
    downtime_hours = fields.Float(string='Downtime (Hours)')
    status = fields.Selection([
        ('open',       'Open'),
        ('in_repair',  'In Repair'),
        ('resolved',   'Resolved'),
    ], string='Status', default='open', required=True, tracking=True)
    notes = fields.Text(string='Notes')

    def action_resolve(self):
        self.write({'status': 'resolved', 'date_resolved': fields.Date.today()})
