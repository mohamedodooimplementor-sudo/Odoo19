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


class EmployeeChecklist(models.Model):
    """Create an 'employee_checklist' model to incorporate
    details about document types"""
    _name = 'employee.checklist'
    _inherit = 'mail.thread'
    _description = "Employee Checklist"

    name = fields.Char(string='Document Name', copy=False, required=True,
                       help="Enter Document Name")
    document_type = fields.Selection([('entry', 'Entry Process'),
                                      ('exit', 'Exit Process'),
                                      ('other', 'Other')],
                                     string='Checklist Type', required=True,
                                     help="Select checklist type for document")

    reminder_days = fields.Char(
        string='Reminder Days',
        help="Overrides the global reminder days for this document type. "
             "Days before expiry separated by commas. Example: 90,60,30,7,0")

    @api.constrains('reminder_days')
    def _check_reminder_days(self):
        for rec in self:
            if rec.reminder_days:
                parts = [p.strip() for p in
                         rec.reminder_days.replace(';', ',').split(',')]
                if not all(p.isdigit() for p in parts):
                    raise ValidationError(_(
                        "Reminder days must be numbers separated by commas."))

    @api.depends('document_type')
    def _compute_display_name(self):
        super()._compute_display_name()
        for order in self:
            name = order.name
            if order.document_type == 'entry':
                name = f"{name} - en"
            elif order.document_type == 'exit':
                name = f"{name} - ex"
            elif order.document_type == 'other':
                name = f"{name} - ot"
            order.display_name = name
