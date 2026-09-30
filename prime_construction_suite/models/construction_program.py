# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ConstructionProgram(models.Model):
    _name = 'construction.program'
    _description = 'Program / Portfolio Group'
    _rec_name = 'name'

    name        = fields.Char(string='Program Name', required=True)
    manager_id  = fields.Many2one('res.users', string='Program Manager')
    description = fields.Text(string='Description')
    project_ids = fields.One2many('construction.project', 'program_id', string='Projects')
    project_count = fields.Integer(compute='_compute_project_count')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    total_contract_value = fields.Monetary(string='Total Contract Value', currency_field='currency_id',
                                            compute='_compute_project_count')

    @api.depends('project_ids')
    def _compute_project_count(self):
        for rec in self:
            rec.project_count = len(rec.project_ids)
            rec.total_contract_value = sum(rec.project_ids.mapped('contract_value'))

    def action_view_projects(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': 'Projects',
            'res_model': 'construction.project', 'view_mode': 'kanban,list,form',
            'domain': [('program_id', '=', self.id)],
            'context': {'default_program_id': self.id},
        }
