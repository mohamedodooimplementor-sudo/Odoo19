# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields, models, _
from odoo.exceptions import UserError


class EducationSessionGenerateWizard(models.TransientModel):
    _name = 'education.session.generate.wizard'
    _description = 'Generate Sessions from Schedule'

    group_id = fields.Many2one('education.group', string='Group', required=True)
    date_from = fields.Date(string='From', required=True, default=fields.Date.context_today)
    date_to = fields.Date(string='To', required=True,
                           default=lambda self: fields.Date.context_today(self) + timedelta(days=30))
    skip_existing = fields.Boolean(string='Skip Dates With Existing Sessions', default=True)

    def action_generate(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('"From" date must be before "To" date.'))
        if not self.group_id.schedule_ids.filtered('active'):
            raise UserError(_('This group has no active weekly schedule lines to generate sessions from.'))

        sessions = self.group_id._generate_sessions_from_schedule(
            self.date_from, self.date_to, skip_existing=self.skip_existing)
        if not sessions:
            raise UserError(_('No new sessions were generated. They may already exist for the selected range.'))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated Sessions'),
            'res_model': 'education.session',
            'view_mode': 'list,form,calendar',
            'domain': [('id', 'in', sessions.ids)],
        }
