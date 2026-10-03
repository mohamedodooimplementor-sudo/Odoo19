# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    branch_ids = fields.One2many(
        'res.branch', 'company_id', string='Branches')
    branch_count = fields.Integer(
        string='Branch Count', compute='_compute_branch_count')

    def _compute_branch_count(self):
        for company in self:
            company.branch_count = self.env['res.branch'].search_count(
                [('company_id', '=', company.id)])
