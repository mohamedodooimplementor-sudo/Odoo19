# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ConstructionCostCode(models.Model):
    _name = 'construction.cost.code'
    _description = 'Cost Code (WBS)'
    _order = 'code'
    _rec_name = 'display_name'

    code        = fields.Char(string='Code', required=True)
    name        = fields.Char(string='Name', required=True)
    parent_id   = fields.Many2one('construction.cost.code', string='Parent Code', ondelete='restrict')
    child_ids   = fields.One2many('construction.cost.code', 'parent_id', string='Sub Codes')
    category = fields.Selection([
        ('civil',      'Civil'),
        ('electrical', 'Electrical'),
        ('mechanical', 'Mechanical'),
        ('finishing',  'Finishing'),
        ('plumbing',   'Plumbing'),
        ('hvac',       'HVAC'),
        ('overhead',   'Overhead'),
        ('other',      'Other'),
    ], string='Category', default='other')
    active      = fields.Boolean(default=True)
    display_name = fields.Char(compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'A cost code with this code already exists.'),
    ]

    @api.depends('code', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = '%s - %s' % (rec.code, rec.name) if rec.code else rec.name

