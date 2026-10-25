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
{
    'name': 'Employee Documents Expiry',
    'version': '18.0.1.1.0',
    'category': 'Human Resources',
    'summary': """Track employee documents and never miss an expiry date:
    staged reminders by email, Odoo notifications and activities.""",
    'description': """
Employee Documents Expiry
=========================
Keep every employee document (passport, residence, ID, contract, licenses...)
in one place and get warned before it expires.

Main features
-------------
* Staged reminders (default: 60, 30, 7, 1 and 0 days before expiry), set
  globally or per document type. Each stage is sent only once.
* Three notification channels: email to the employee, Odoo inbox notification
  and a "Document Expiry" activity assigned to the responsible users.
* Choose exactly who is notified for each document, or let the module notify
  the employee, his manager and the HR managers by default.
* Escalation to the manager, department manager and HR managers when a
  document is still not renewed.
* Weekly summary email for the HR managers.
* Document status (Valid / Expiring Soon / Expired), colored lists, filters
  and a graph / pivot dashboard.
* One-click renewal: creates the new document, archives the old one and
  closes its pending activities.
* Editable bilingual (English / Arabic) email template and configurable
  schedule for the scheduled actions.
""",
    'author': 'Eng. M.Aboelmagde Apps',
    'company': 'Eng. M.Aboelmagde Apps',
    'maintainer': 'Eng. M.Aboelmagde Apps',
    'depends': ['hr', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/employee_checklist_data.xml',
        'data/mail_activity_type_data.xml',
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'views/employee_checklist_views.xml',
        'views/hr_employee_document_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_employee_document_renew_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'images': ['static/description/banner.jpg'],
    'license': 'AGPL-3',
    'price': 25.00,
    'currency': 'USD',
    'installable': True,
    'auto_install': False,
    'application': False,
}
