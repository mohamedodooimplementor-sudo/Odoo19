# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .education_config_helpers import float_to_time_parts


class EducationGroupSchedule(models.Model):
    _name = 'education.group.schedule'
    _description = 'Group Weekly Schedule'
    _order = 'group_id, weekday, start_time'

    group_id = fields.Many2one('education.group', string='Group', required=True, ondelete='cascade')
    weekday = fields.Selection([
        ('0', 'Monday'),
        ('1', 'Tuesday'),
        ('2', 'Wednesday'),
        ('3', 'Thursday'),
        ('4', 'Friday'),
        ('5', 'Saturday'),
        ('6', 'Sunday'),
    ], string='Weekday', required=True)
    start_time = fields.Float(string='Start Time', required=True, help='Time in 24h float format, e.g. 14.5 = 14:30')
    end_time = fields.Float(string='End Time', required=True)
    room_id = fields.Many2one('education.room', string='Room')
    effective_from = fields.Date(string='Effective From')
    effective_to = fields.Date(string='Effective To')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(related='group_id.company_id', string='Company', store=True)
    time_range_label = fields.Char(string='Time', compute='_compute_time_range_label',
                                    help='12-hour AM/PM display of Start - End, so the time is never '
                                         'ambiguous at a glance.')

    def _compute_time_range_label(self):
        for rec in self:
            rec.time_range_label = '%s - %s' % (
                self._float_time_to_ampm(rec.start_time), self._float_time_to_ampm(rec.end_time))

    @api.model
    def _float_time_to_ampm(self, value):
        """Formats a float-hours value (e.g. 14.5) as '2:30 PM'."""
        hour, minute = float_to_time_parts(value)
        period = 'AM' if hour < 12 else 'PM'
        hour_12 = hour % 12 or 12
        return '%d:%02d %s' % (hour_12, minute, period)

    @api.constrains('start_time', 'end_time')
    def _check_times(self):
        for rec in self:
            if rec.start_time >= rec.end_time:
                raise ValidationError(_('Schedule end time must be after start time.'))

    @api.constrains('effective_from', 'effective_to')
    def _check_effective_dates(self):
        for rec in self:
            if rec.effective_from and rec.effective_to and rec.effective_from > rec.effective_to:
                raise ValidationError(_('"Effective From" date must be before "Effective To" date.'))
