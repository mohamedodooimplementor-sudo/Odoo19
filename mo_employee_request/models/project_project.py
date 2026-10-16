# -*- coding: utf-8 -*-
from odoo import _, fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    er_location_id = fields.Many2one(
        'stock.location', string='Project Location', index=True,
        domain="[('usage', '=', 'internal'), ('er_is_general', '=', False)]",
        help="Stock location of the project. Employee request lines of this project take it "
             "automatically, stock is issued from it and the purchase receipts of the project "
             "are received into it.")

    def action_er_project_stock(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _("Project Stock: %s", self.display_name),
            'res_model': 'er.project.stock.report', 'view_mode': 'list,pivot',
            'domain': [('project_id', '=', self.id)],
        }

    def action_er_replace(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _("Replace Stock"),
            'res_model': 'er.project.replace', 'view_mode': 'form', 'target': 'new',
            'context': {'default_project_id': self.id},
        }

    def action_er_release_back(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _("Release Back"),
            'res_model': 'er.project.allocation', 'view_mode': 'form', 'target': 'current',
            'context': {'default_project_id': self.id, 'default_kind': 'release'},
        }
