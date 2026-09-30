# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class ConstructionResourceAssignment(models.Model):
    _name = 'construction.resource.assignment'
    _description = 'Resource Assignment (Capacity Planning)'
    _order = 'date_from desc'

    resource_type = fields.Selection([
        ('employee',  'Employee'),
        ('equipment', 'Equipment'),
    ], string='Resource Type', required=True, default='employee')

    employee_id  = fields.Many2one('hr.employee', string='Employee')
    equipment_id = fields.Many2one('construction.equipment', string='Equipment')
    project_id   = fields.Many2one('construction.project', string='Project', required=True)
    company_id   = fields.Many2one(related='project_id.company_id', store=True)

    date_from = fields.Date(string='From', required=True)
    date_to   = fields.Date(string='To', required=True)
    allocation_percent = fields.Float(string='Allocation %', default=100.0,
                                       help='Percentage of this resource\'s time/capacity dedicated to this project.')
    notes = fields.Char(string='Notes')

    resource_display = fields.Char(string='Resource', compute='_compute_resource_display', store=True)

    @api.depends('resource_type', 'employee_id', 'equipment_id')
    def _compute_resource_display(self):
        for rec in self:
            if rec.resource_type == 'employee':
                rec.resource_display = rec.employee_id.name or ''
            else:
                rec.resource_display = rec.equipment_id.name or ''

    def _get_overlap_domain(self):
        self.ensure_one()
        domain = [
            ('id', '!=', self.id),
            ('resource_type', '=', self.resource_type),
            ('date_from', '<=', self.date_to),
            ('date_to', '>=', self.date_from),
        ]
        if self.resource_type == 'employee':
            domain.append(('employee_id', '=', self.employee_id.id))
        else:
            domain.append(('equipment_id', '=', self.equipment_id.id))
        return domain

    def is_overallocated(self):
        """Returns True if this resource's total allocation in the overlapping period exceeds 100%."""
        self.ensure_one()
        overlapping = self.search(self._get_overlap_domain())
        total = self.allocation_percent + sum(overlapping.mapped('allocation_percent'))
        return total > 100.0

    @api.model
    def get_overallocated_resources(self):
        """Utility for the dashboard: returns a list of currently over-allocated resources."""
        from datetime import date
        today = date.today()
        active = self.search([('date_from', '<=', today), ('date_to', '>=', today)])
        grouped = {}
        for rec in active:
            key = (rec.resource_type, rec.employee_id.id or rec.equipment_id.id)
            grouped.setdefault(key, []).append(rec)
        result = []
        for (rtype, res_id), recs in grouped.items():
            total = sum(r.allocation_percent for r in recs)
            if total > 100.0:
                result.append({
                    'resource_type': rtype,
                    'name': recs[0].resource_display,
                    'total_allocation': total,
                    'projects': [r.project_id.name for r in recs],
                })
        return result

    @api.model
    def get_leveling_suggestions(self):
        """Resource Leveling Assistant (MVP): scans all upcoming/current assignments and, for each
        pair of overlapping assignments of the same resource whose combined allocation exceeds
        100%, suggests pushing the later-starting assignment to begin right after the earlier one
        ends — the simplest fix that removes the conflict. This is a heuristic, not an optimizer:
        it doesn't consider project priority or critical-path impact, so review before applying."""
        from datetime import date, timedelta
        today = date.today()
        active = self.search([('date_to', '>=', today)])
        groups = {}
        for rec in active:
            key = (rec.resource_type, rec.employee_id.id, rec.equipment_id.id)
            groups.setdefault(key, []).append(rec)

        suggestions = []
        for key, recs in groups.items():
            recs = sorted(recs, key=lambda r: r.date_from)
            for i in range(len(recs)):
                for j in range(i + 1, len(recs)):
                    a, b = recs[i], recs[j]
                    overlap = a.date_from <= b.date_to and b.date_from <= a.date_to
                    if overlap and (a.allocation_percent + b.allocation_percent) > 100.0:
                        duration = (b.date_to - b.date_from).days
                        new_start = a.date_to + timedelta(days=1)
                        suggestions.append({
                            'assignment_id': b.id,
                            'resource_display': b.resource_display,
                            'project_id': b.project_id.id,
                            'current_date_from': b.date_from,
                            'current_date_to': b.date_to,
                            'conflict_with': '%s (%s to %s)' % (a.project_id.name, a.date_from, a.date_to),
                            'suggested_date_from': new_start,
                            'suggested_date_to': new_start + timedelta(days=duration),
                        })
        return suggestions

    def action_open_leveling_assistant(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Resource Leveling Assistant',
            'res_model': 'construction.resource.leveling.wizard',
            'view_mode': 'form',
            'target': 'new',
        }
