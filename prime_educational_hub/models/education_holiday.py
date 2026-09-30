# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EducationHoliday(models.Model):
    _name = 'education.holiday'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Holiday / Excluded Date'
    _order = 'date_from'

    name = fields.Char(string='Name', required=True)
    date_from = fields.Date(string='From', required=True, default=fields.Date.context_today)
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    notes = fields.Text(string='Notes')

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from > rec.date_to:
                raise ValidationError(_('Holiday "%s": start date must be before or equal to end date.') % rec.name)

    @api.model
    def get_holiday_dates(self, date_from, date_to, company_id=None):
        """Returns a set of all individual dates covered by active holidays
        overlapping [date_from, date_to], for fast membership checks during
        session generation."""
        domain = [
            ('active', '=', True),
            ('date_from', '<=', date_to),
            ('date_to', '>=', date_from),
        ]
        if company_id:
            domain.append('|')
            domain.append(('company_id', '=', False))
            domain.append(('company_id', '=', company_id))
        holidays = self.search(domain)
        dates = set()
        for holiday in holidays:
            current = max(holiday.date_from, date_from)
            end = min(holiday.date_to, date_to)
            while current <= end:
                dates.add(current)
                current += timedelta(days=1)
        return dates
