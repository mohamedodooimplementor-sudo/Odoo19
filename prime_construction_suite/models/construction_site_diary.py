# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ConstructionSiteDiary(models.Model):
    _name = 'construction.site.diary'
    _description = 'Site Diary (Daily Site Report)'
    _inherit = ['mail.thread']
    _rec_name = 'display_name'
    _order = 'date desc'

    project_id = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    date       = fields.Date(string='Date', required=True, default=fields.Date.today)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    weather = fields.Selection([
        ('sunny',      'Sunny'),
        ('cloudy',     'Cloudy'),
        ('rainy',      'Rainy'),
        ('sandstorm',  'Sandstorm / Dust'),
        ('other',      'Other'),
    ], string='Weather', default='sunny')
    temperature_c = fields.Float(string='Temperature (°C)')

    workforce_count   = fields.Integer(string='Workers on Site')
    equipment_present_ids = fields.Many2many('construction.equipment', string='Equipment on Site')

    activities_summary = fields.Text(string='Work Performed Today')
    issues              = fields.Text(string='Issues / Delays / Remarks')

    reported_by = fields.Many2one('res.users', string='Reported By', default=lambda self: self.env.user)

    _sql_constraints = [
        ('project_date_unique', 'unique(project_id, date)', 'A site diary entry already exists for this project and date.'),
    ]

    @api.depends('project_id', 'date')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s - %s' % (rec.project_id.name, rec.date) if rec.project_id else str(rec.date)
