# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EducationTeacherPayoutGenerateWizard(models.TransientModel):
    _name = 'education.teacher.payout.generate.wizard'
    _description = 'Generate Teacher Payouts'

    period_start = fields.Date(string='Period Start', required=True,
                                default=lambda self: fields.Date.context_today(self).replace(day=1))
    period_end = fields.Date(string='Period End', required=True,
                              default=lambda self: self._default_period_end())
    teacher_ids = fields.Many2many('education.teacher', string='Teachers (leave empty for all with a plan)',
                                    domain=[('compensation_type', '!=', 'none')])

    @api.model
    def _default_period_end(self):
        today = fields.Date.context_today(self)
        start_of_month = today.replace(day=1)
        next_month = (start_of_month + timedelta(days=32)).replace(day=1)
        return next_month - timedelta(days=1)

    def action_generate(self):
        self.ensure_one()
        if self.period_start > self.period_end:
            raise UserError(_('Period Start must be before Period End.'))
        payouts = self.env['education.teacher.payout']._generate_for_period(
            self.period_start, self.period_end, teacher_ids=self.teacher_ids.ids or None)
        if not payouts:
            raise UserError(_(
                'No new payouts were generated -- either no teacher has a compensation plan set '
                'up, or payouts for this exact period already exist.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Generated Payouts'),
            'res_model': 'education.teacher.payout',
            'view_mode': 'list,form',
            'domain': [('id', 'in', payouts.ids)],
        }
