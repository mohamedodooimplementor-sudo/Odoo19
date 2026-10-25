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
import logging
from datetime import timedelta

from markupsafe import Markup, escape

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

PARAM = 'employee_documents_expiry.'
DEFAULT_REMINDER_DAYS = '60,30,7,1,0'
ACTIVITY_TYPE = 'mo_employee_documents_expiry.mail_activity_type_document_expiry'
REMINDER_TEMPLATE = 'mo_employee_documents_expiry.mail_template_document_expiry'


class HrEmployeeDocument(models.Model):
    """Employee documents with staged expiry reminders (email, Odoo inbox
    notification and activities), escalation and renewal."""
    _name = 'hr.employee.document'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'HR Employee Documents'
    _order = 'expiry_date, id'

    name = fields.Char(string='Document Number', required=True, copy=False,
                       help="Enter Document Number")
    document_id = fields.Many2one('employee.checklist',
                                  string='Document',
                                  required=True,
                                  help="Choose Employee Checklist for"
                                       " Employee Document")
    description = fields.Text(string='Description', copy=False,
                              help="Description for Employee Document")
    expiry_date = fields.Date(string='Expiry Date', copy=False,
                              help="Choose Expiry Date for Employee Document")
    employee_id = fields.Many2one('hr.employee', copy=False, string="Employee",
                                  help="Choose Employee for Employee Document")
    department_id = fields.Many2one(
        'hr.department', related='employee_id.department_id', store=True,
        string='Department')
    doc_attachment_ids = fields.Many2many('ir.attachment',
                                          'doc_attach_ids',
                                          'doc_id', 'attach_id3',
                                          string="Attachment",
                                          help='You can attach the copy'
                                               'of your document',
                                          copy=False)
    issue_date = fields.Date(string='Issue Date',
                             default=fields.Date.context_today, copy=False,
                             help="Choose Issue Date for Employee Document")
    active = fields.Boolean(default=True,
                            help="Renewed documents are archived.")
    previous_document_id = fields.Many2one(
        'hr.employee.document', string='Renewed From', copy=False,
        readonly=True)
    notify_user_ids = fields.Many2many(
        'res.users', 'hr_employee_document_notify_user_rel',
        'document_id', 'user_id', string='Notify Users',
        domain=[('share', '=', False)], copy=False,
        help="Users who will receive the Odoo notification and the activity "
             "for this document. If empty, the employee, his manager and "
             "the HR managers are notified.")
    state = fields.Selection(
        [('valid', 'Valid'), ('expiring', 'Expiring Soon'),
         ('expired', 'Expired')],
        string='Status', compute='_compute_state', store=True,
        help="Refreshed every day by the scheduled action.")
    days_left = fields.Integer(string='Days Left', compute='_compute_days_left')
    # Technical fields used by the reminder engine
    reminder_stage = fields.Integer(default=-1, copy=False, readonly=True)
    last_expired_notice = fields.Date(copy=False, readonly=True)
    escalated = fields.Boolean(copy=False, readonly=True)

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    @api.model
    def _get_param(self, key, default):
        return self.env['ir.config_parameter'].sudo().get_param(
            PARAM + key, default)

    @api.model
    def _get_int_param(self, key, default):
        try:
            return int(self._get_param(key, str(default)))
        except (TypeError, ValueError):
            return default

    @api.model
    def _parse_days(self, text):
        days = set()
        for part in (text or '').replace(';', ',').split(','):
            part = part.strip()
            if part.isdigit():
                days.add(int(part))
        return sorted(days, reverse=True)

    def _get_reminder_days(self):
        """Reminder stages (days before expiry), highest first.
        The document type setting overrides the global setting."""
        self.ensure_one()
        days = self._parse_days(self.document_id.reminder_days)
        if not days:
            days = self._parse_days(
                self._get_param('reminder_days', DEFAULT_REMINDER_DAYS))
        return days or self._parse_days(DEFAULT_REMINDER_DAYS)

    # ------------------------------------------------------------------
    # Computed fields
    # ------------------------------------------------------------------
    @api.depends('expiry_date', 'document_id.reminder_days')
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for doc in self:
            if not doc.expiry_date:
                doc.state = 'valid'
                continue
            days_left = (doc.expiry_date - today).days
            if days_left < 0:
                doc.state = 'expired'
            elif days_left <= max(doc._get_reminder_days()):
                doc.state = 'expiring'
            else:
                doc.state = 'valid'

    @api.depends('expiry_date')
    def _compute_days_left(self):
        today = fields.Date.context_today(self)
        for doc in self:
            doc.days_left = (doc.expiry_date - today).days \
                if doc.expiry_date else 0

    # ------------------------------------------------------------------
    # ORM overrides
    # ------------------------------------------------------------------
    def write(self, vals):
        """When the expiry date changes (renewal), restart the reminder
        cycle and close the old reminder activities."""
        if 'expiry_date' in vals:
            vals.update({'reminder_stage': -1,
                         'last_expired_notice': False,
                         'escalated': False})
        res = super().write(vals)
        if 'expiry_date' in vals:
            self._close_expiry_activities(
                _("The expiry date was updated."))
        return res

    # ------------------------------------------------------------------
    # Recipients
    # ------------------------------------------------------------------
    def _get_hr_managers(self):
        group = self.env.ref('hr.group_hr_manager', raise_if_not_found=False)
        return group.users if group else self.env['res.users']

    def _get_notification_users(self):
        """Users notified inside Odoo: the selected users, or by default the
        employee, his manager and all HR managers."""
        self.ensure_one()
        if self.notify_user_ids:
            return self.notify_user_ids.filtered('active')
        employee = self.employee_id
        users = employee.user_id | employee.parent_id.user_id \
            | self._get_hr_managers()
        return users.filtered(lambda u: u.active and not u.share)

    def _get_escalation_users(self):
        """Employee manager, department manager and HR managers."""
        self.ensure_one()
        employee = self.employee_id
        users = employee.parent_id.user_id \
            | employee.department_id.manager_id.user_id \
            | self._get_hr_managers()
        return users.filtered(lambda u: u.active and not u.share)

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    def _get_status_text(self, days_left):
        if days_left < 0:
            return _("expired %s day(s) ago") % abs(days_left)
        if days_left == 0:
            return _("expires today")
        return _("will expire in %s day(s)") % days_left

    def _notify_in_odoo(self, days_left, users=None, escalation=False):
        """Inbox notification (bell) + activity (clock) on the document."""
        self.ensure_one()
        users = users if users is not None else self._get_notification_users()
        if not users:
            return
        employee_name = self.employee_id.name or ''
        note = _("Employee %s: document %s (%s) %s (expiry date: %s).") % (
            employee_name, self.name, self.document_id.name or '',
            self._get_status_text(days_left), self.expiry_date)
        subject = _("Employee document expiry: %s") % self.name
        if escalation:
            subject = _("ESCALATION - %s") % subject

        self.message_notify(
            partner_ids=users.partner_id.ids,
            subject=subject,
            body=escape(note),
            author_id=self.env.user.partner_id.id,
        )
        # Replace stale reminder activities of these users
        self.env['mail.activity'].sudo().search([
            ('res_model', '=', self._name),
            ('res_id', '=', self.id),
            ('user_id', 'in', users.ids),
            ('activity_type_id', '=',
             self.env.ref(ACTIVITY_TYPE).id),
        ]).unlink()
        for user in users:
            self.sudo().activity_schedule(
                act_type_xmlid=ACTIVITY_TYPE,
                date_deadline=self.expiry_date,
                summary=subject,
                note=escape(note),
                user_id=user.id,
            )

    def _send_reminder_email(self):
        """Send the reminder email to the employee using the template."""
        self.ensure_one()
        template = self.env.ref(REMINDER_TEMPLATE, raise_if_not_found=False)
        if template and self.employee_id.work_email:
            template.send_mail(self.id, force_send=True,
                               raise_exception=False)

    def _escalate(self, days_left):
        self.ensure_one()
        users = self._get_escalation_users()
        if users:
            self._notify_in_odoo(days_left, users=users, escalation=True)
        self.escalated = True

    def _close_expiry_activities(self, feedback=None):
        """Mark the reminder activities of these documents as done."""
        if self.ids:
            self.sudo().activity_feedback([ACTIVITY_TYPE], feedback=feedback)

    # ------------------------------------------------------------------
    # Scheduled actions
    # ------------------------------------------------------------------
    def _process_reminder(self, today):
        """Apply the staged reminder logic on one document."""
        self.ensure_one()
        days_left = (self.expiry_date - today).days
        notify = False
        if days_left >= 0:
            stages = [s for s in self._get_reminder_days() if days_left <= s]
            if stages:
                stage = min(stages)
                if self.reminder_stage == -1 or stage < self.reminder_stage:
                    self.reminder_stage = stage
                    notify = True
        else:
            repeat = self._get_int_param('expired_repeat_days', 7)
            last = self.last_expired_notice
            if not last or (repeat > 0 and (today - last).days >= repeat):
                self.last_expired_notice = today
                notify = True
        if notify:
            self._notify_in_odoo(days_left)
            self._send_reminder_email()
        escalation_days = self._get_int_param('escalation_days', 3)
        if escalation_days > 0 and days_left <= escalation_days \
                and not self.escalated:
            self._escalate(days_left)

    def mail_reminder(self):
        """Daily scheduled action: refresh statuses and send the reminders
        (email + Odoo notification + activity) and escalations."""
        today = fields.Date.context_today(self)
        docs = self.search([('expiry_date', '!=', False)])
        docs._compute_state()
        for doc in docs:
            try:
                with self.env.cr.savepoint():
                    doc._process_reminder(today)
            except Exception:
                _logger.exception(
                    "Expiry reminder failed for document %s (id %s)",
                    doc.name, doc.id)

    @api.model
    def cron_weekly_summary(self):
        """Weekly scheduled action: one summary email for HR managers."""
        enabled = str(self._get_param('summary_enabled', 'True')).lower()
        if enabled not in ('true', '1'):
            return
        today = fields.Date.context_today(self)
        limit = today + timedelta(
            days=self._get_int_param('summary_days', 30))
        docs = self.search([('expiry_date', '!=', False),
                            ('expiry_date', '<=', limit)],
                           order='expiry_date')
        emails = [e for e in self._get_hr_managers().mapped(
            'partner_id.email') if e]
        if not docs or not emails:
            return
        rows = Markup('').join(
            Markup('<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td>'
                   '<td>%s</td></tr>') % (
                doc.employee_id.name or '', doc.name,
                doc.document_id.name or '', doc.expiry_date,
                _("Expired") if doc.state == 'expired'
                else _("%s day(s)") % doc.days_left)
            for doc in docs)
        body = Markup(
            '<p>%s</p><table border="1" cellpadding="6" cellspacing="0" '
            'style="border-collapse:collapse;">'
            '<tr style="background:#eee;"><th>%s</th><th>%s</th><th>%s</th>'
            '<th>%s</th><th>%s</th></tr>%s</table>') % (
            _("Employee documents expired or expiring within the next "
              "%s days:") % self._get_int_param('summary_days', 30),
            _("Employee"), _("Document Number"), _("Document"),
            _("Expiry Date"), _("Status"), rows)
        self.env['mail.mail'].sudo().create({
            'subject': _("Weekly summary: employee documents expiry"),
            'body_html': body,
            'email_to': ','.join(emails),
            'auto_delete': True,
        }).send()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_open_renew_wizard(self):
        self.ensure_one()
        return {
            'name': _('Renew Document'),
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee.document.renew',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_document_id': self.id},
        }

    @api.onchange('expiry_date')
    def check_expr_date(self):
        """Warn when the chosen expiry date is already in the past."""
        if self.expiry_date and self.expiry_date < fields.Date.context_today(
                self):
            return {
                'warning': {
                    'title': _('Document Expired.'),
                    'message': _("Your Document Is Already Expired.")
                }
            }
