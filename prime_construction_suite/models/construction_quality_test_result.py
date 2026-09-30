# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ConstructionQualityTestResult(models.Model):
    _name = 'construction.quality.test.result'
    _description = 'Quality Test Result'
    _inherit = ['mail.thread']
    _order = 'test_date desc, id desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default='New')
    project_id  = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    company_id  = fields.Many2one(related='project_id.company_id', store=True)
    boq_line_id = fields.Many2one('construction.boq.line', string='Related BOQ Item',
                                   domain="[('project_id','=',project_id)]")
    inspection_id = fields.Many2one('construction.quality.inspection', string='Related Inspection')

    test_type = fields.Selection([
        ('concrete', 'Concrete (Cube/Cylinder Strength)'),
        ('soil',     'Soil Compaction'),
        ('steel',    'Steel / Rebar'),
        ('welding',  'Welding'),
        ('other',    'Other'),
    ], default='concrete', required=True)
    test_name = fields.Char(string='Test Name', required=True)
    lab_id = fields.Many2one('res.partner', string='Testing Laboratory')

    sample_date = fields.Date(string='Sample Date')
    test_date   = fields.Date(string='Test Date', default=fields.Date.today, required=True)

    spec_value   = fields.Float(string='Specification Value')
    actual_value = fields.Float(string='Actual Value')
    uom_label    = fields.Char(string='Unit', help='e.g. MPa, %, mm')

    result = fields.Selection([
        ('pending', 'Pending'),
        ('pass',    'Pass'),
        ('fail',    'Fail'),
    ], default='pending', required=True, tracking=True)

    certificate = fields.Binary(string='Certificate / Report')
    certificate_filename = fields.Char(string='Certificate Filename')
    notes = fields.Text(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.quality.test.result') or 'New'
        return super().create(vals_list)

    @api.onchange('spec_value', 'actual_value')
    def _onchange_values(self):
        if self.spec_value and self.actual_value:
            self.result = 'pass' if self.actual_value >= self.spec_value else 'fail'
