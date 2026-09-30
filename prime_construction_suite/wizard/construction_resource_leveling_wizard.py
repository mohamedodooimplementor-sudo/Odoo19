# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ConstructionResourceLevelingWizard(models.TransientModel):
    _name = 'construction.resource.leveling.wizard'
    _description = 'Resource Leveling Assistant'

    line_ids = fields.One2many('construction.resource.leveling.wizard.line', 'wizard_id', string='Suggestions')
    line_count = fields.Integer(compute='_compute_line_count')

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        suggestions = self.env['construction.resource.assignment'].get_leveling_suggestions()
        res['line_ids'] = [(0, 0, s) for s in suggestions]
        return res

    def action_apply_all(self):
        for line in self.line_ids:
            if line.assignment_id:
                line.assignment_id.write({
                    'date_from': line.suggested_date_from,
                    'date_to': line.suggested_date_to,
                })
        return {'type': 'ir.actions.act_window_close'}

    def action_refresh(self):
        self.line_ids.unlink()
        suggestions = self.env['construction.resource.assignment'].get_leveling_suggestions()
        self.line_ids = [(0, 0, s) for s in suggestions]
        return {
            'type': 'ir.actions.act_window',
            'name': 'Resource Leveling Assistant',
            'res_model': 'construction.resource.leveling.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class ConstructionResourceLevelingWizardLine(models.TransientModel):
    _name = 'construction.resource.leveling.wizard.line'
    _description = 'Resource Leveling Suggestion'

    wizard_id       = fields.Many2one('construction.resource.leveling.wizard', ondelete='cascade')
    assignment_id   = fields.Many2one('construction.resource.assignment', readonly=True)
    resource_display = fields.Char(string='Resource', readonly=True)
    project_id      = fields.Many2one('construction.project', readonly=True)
    current_date_from = fields.Date(string='Current From', readonly=True)
    current_date_to   = fields.Date(string='Current To', readonly=True)
    conflict_with     = fields.Char(string='Conflicts With', readonly=True)
    suggested_date_from = fields.Date(string='Suggested From', readonly=True)
    suggested_date_to   = fields.Date(string='Suggested To', readonly=True)
