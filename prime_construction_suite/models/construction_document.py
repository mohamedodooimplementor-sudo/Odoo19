# -*- coding: utf-8 -*-
from odoo import models, fields


class ConstructionDocument(models.Model):
    _name = 'construction.document'
    _description = 'Project Document'
    _inherit = ['mail.thread']
    _rec_name = 'name'
    _order = 'date desc'

    name       = fields.Char(string='Document Name', required=True)
    project_id = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='project_id.company_id', store=True)

    category = fields.Selection([
        ('contract',    'Contract'),
        ('license',     'License / Permit'),
        ('drawing',     'Drawing'),
        ('photo',       'Site Photo'),
        ('certificate', 'Certificate'),
        ('guarantee',   'Guarantee Document'),
        ('insurance',   'Insurance Document'),
        ('correspondence', 'Correspondence'),
        ('other',       'Other'),
    ], string='Category', required=True, default='other')

    date       = fields.Date(string='Date', default=fields.Date.today)
    file       = fields.Binary(string='File', attachment=True)
    file_name  = fields.Char(string='File Name')
    notes      = fields.Text(string='Notes')
