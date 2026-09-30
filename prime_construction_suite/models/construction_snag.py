# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class ConstructionSnag(models.Model):
    _name = 'construction.snag'
    _description = 'Snagging Item (Defects List)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'description'
    _order = 'date_reported desc'

    name        = fields.Char(string='Reference', copy=False, readonly=True, default='New')
    project_id  = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    company_id  = fields.Many2one(related='project_id.company_id', store=True)

    description = fields.Char(string='Description', required=True)
    location    = fields.Char(string='Location / Area')
    category = fields.Selection([
        ('civil',      'Civil'),
        ('electrical', 'Electrical'),
        ('mechanical', 'Mechanical'),
        ('finishing',  'Finishing'),
        ('plumbing',   'Plumbing'),
        ('hvac',       'HVAC'),
        ('other',      'Other'),
    ], string='Category', default='other')

    priority = fields.Selection([
        ('low',    'Low'),
        ('normal', 'Normal'),
        ('high',   'High'),
        ('urgent', 'Urgent'),
    ], string='Priority', default='normal')

    stage = fields.Selection([
        ('pre_handover',  'Pre-Handover'),
        ('dlp',           'During DLP'),
    ], string='Stage', default='pre_handover', required=True)

    date_reported = fields.Date(string='Date Reported', required=True, default=fields.Date.today)
    reported_by   = fields.Many2one('res.users', string='Reported By', default=lambda self: self.env.user)
    date_closed   = fields.Date(string='Date Closed', copy=False)
    closed_by     = fields.Many2one('res.users', string='Closed By', copy=False, readonly=True)

    status = fields.Selection([
        ('open',        'Open'),
        ('in_progress', 'In Progress'),
        ('closed',      'Closed'),
    ], string='Status', default='open', tracking=True, required=True)

    notes = fields.Text(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.snag') or 'New'
        return super().create(vals_list)

    def action_start(self):  self.write({'status': 'in_progress'})
    def action_close(self):
        self.write({'status': 'closed', 'date_closed': fields.Date.today(), 'closed_by': self.env.user.id})
    def action_reopen(self):
        self.write({'status': 'open', 'date_closed': False, 'closed_by': False})
