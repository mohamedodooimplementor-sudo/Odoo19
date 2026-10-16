# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class StockLocation(models.Model):
    _inherit = 'stock.location'

    er_is_general = fields.Boolean(
        string='General Location', copy=False,
        help="Tick it for the shared (general) projects stock. Only these locations can be "
             "chosen as the General Projects Location in the settings, and they belong to no "
             "project.")
    er_project_id = fields.Many2one(
        'project.project', string='Project', copy=False,
        compute='_compute_er_project_id', inverse='_inverse_er_project_id',
        help="Project owning this location. It is the same link as the Project Location "
             "field of the project.")

    @api.depends('er_is_general')
    def _compute_er_project_id(self):
        Project = self.env['project.project'].sudo()
        for loc in self:
            loc.er_project_id = False if (loc.er_is_general or not loc.id) else Project.search(
                [('er_location_id', '=', loc.id)], limit=1)

    def _inverse_er_project_id(self):
        Project = self.env['project.project'].sudo().with_context(active_test=False)
        for loc in self:
            project = False if loc.er_is_general else loc.er_project_id
            # the location belongs to one project at most
            old = Project.search([('er_location_id', '=', loc.id)])
            (old - project).write({'er_location_id': False})
            if project and project.er_location_id != loc:
                project.write({'er_location_id': loc.id})

    @api.constrains('er_is_general')
    def _check_er_general_project(self):
        Project = self.env['project.project'].sudo().with_context(active_test=False)
        for loc in self.filtered('er_is_general'):
            if Project.search_count([('er_location_id', '=', loc.id)]):
                raise ValidationError(_(
                    "A general location cannot belong to a project. Remove the project first."))

    def write(self, vals):
        if vals.get('er_is_general'):
            # ticking General Location detaches the location from its project
            vals = {k: v for k, v in vals.items() if k != 'er_project_id'}
            self.env['project.project'].sudo().with_context(active_test=False).search(
                [('er_location_id', 'in', self.ids)]).write({'er_location_id': False})
        return super().write(vals)
