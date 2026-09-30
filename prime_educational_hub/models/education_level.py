# -*- coding: utf-8 -*-
from odoo import fields, models


class EducationLevel(models.Model):
    _name = 'education.level'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Grade / Level'
    _order = 'sequence, name'

    name = fields.Char(string='Level Name', required=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Description')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    _sql_constraints = [
        ('code_uniq', 'unique(code, company_id)', 'Level code must be unique per company.'),
    ]
