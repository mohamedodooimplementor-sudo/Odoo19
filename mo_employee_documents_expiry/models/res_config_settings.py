# -*- coding: utf-8 -*-
###############################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2025-TODAY Cybrosys Technologies(<https://www.cybrosys.com>)
#    Author: Cybrosys Techno Solutions (odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
###############################################################################
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

REMINDER_CRON = 'mo_employee_documents_expiry.employee_data_reminder'
SUMMARY_CRON = 'mo_employee_documents_expiry.employee_data_weekly_summary'
INTERVAL_TYPES = [('minutes', 'Minutes'), ('hours', 'Hours'),
                  ('days', 'Days'), ('weeks', 'Weeks'),
                  ('months', 'Months')]


class ResConfigSettings(models.TransientModel):
    """Expiry reminder settings."""
    _inherit = 'res.config.settings'

    documents_reminder_days = fields.Char(
        string='Reminder Days',
        config_parameter='employee_documents_expiry.reminder_days',
        default='60,30,7,1,0',
        help="Days before the expiry date when a reminder is sent, "
             "separated by commas. Example: 60,30,7,1,0")
    documents_expired_repeat_days = fields.Integer(
        string='Repeat Expired Notice Every (days)',
        config_parameter='employee_documents_expiry.expired_repeat_days',
        default=7, help="0 = send the expired notice only once.")
    documents_escalation_days = fields.Integer(
        string='Escalate When Days Left <=',
        config_parameter='employee_documents_expiry.escalation_days',
        default=3,
        help="Notify the manager, department manager and HR managers when "
             "the document is still not renewed. 0 = disabled.")
    documents_summary_enabled = fields.Boolean(
        string='Weekly Summary Email',
        config_parameter='employee_documents_expiry.summary_enabled',
        default=True)
    documents_summary_days = fields.Integer(
        string='Summary Period (days)',
        config_parameter='employee_documents_expiry.summary_days',
        default=30)

    # Schedule of the scheduled actions (stored on the cron records)
    documents_cron_interval_number = fields.Integer(
        string='Reminders: Run Every', default=1)
    documents_cron_interval_type = fields.Selection(
        INTERVAL_TYPES, string='Reminders: Interval Unit', default='days')
    documents_cron_nextcall = fields.Datetime(
        string='Reminders: Next Run')
    documents_summary_cron_interval_number = fields.Integer(
        string='Summary: Run Every', default=1)
    documents_summary_cron_interval_type = fields.Selection(
        INTERVAL_TYPES, string='Summary: Interval Unit', default='weeks')
    documents_summary_cron_nextcall = fields.Datetime(
        string='Summary: Next Run')

    @api.model
    def get_values(self):
        res = super().get_values()
        for xmlid, prefix in ((REMINDER_CRON, 'documents_cron'),
                              (SUMMARY_CRON, 'documents_summary_cron')):
            cron = self.env.ref(xmlid, raise_if_not_found=False)
            if cron:
                res.update({
                    prefix + '_interval_number': cron.interval_number,
                    prefix + '_interval_type': cron.interval_type,
                    prefix + '_nextcall': cron.nextcall,
                })
        return res

    def set_values(self):
        super().set_values()
        for xmlid, prefix in ((REMINDER_CRON, 'documents_cron'),
                              (SUMMARY_CRON, 'documents_summary_cron')):
            cron = self.env.ref(xmlid, raise_if_not_found=False)
            if not cron:
                continue
            number = self[prefix + '_interval_number']
            if number < 1:
                raise ValidationError(
                    _("The scheduled action interval must be at least 1."))
            vals = {
                'interval_number': number,
                'interval_type': self[prefix + '_interval_type'],
            }
            nextcall = self[prefix + '_nextcall']
            if nextcall and nextcall != cron.nextcall:
                vals['nextcall'] = nextcall
            cron.sudo().write(vals)
