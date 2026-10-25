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


class HrEmployeeDocumentRenew(models.TransientModel):
    """Wizard to renew an employee document."""
    _name = 'hr.employee.document.renew'
    _description = 'Renew Employee Document'

    document_id = fields.Many2one('hr.employee.document', required=True,
                                  readonly=True)
    name = fields.Char(string='New Document Number',
                       help="Leave the current number if it does not change.")
    issue_date = fields.Date(default=fields.Date.context_today, required=True)
    expiry_date = fields.Date(required=True)
    attachment_ids = fields.Many2many('ir.attachment',
                                      'hr_doc_renew_attachment_rel',
                                      'wizard_id', 'attachment_id',
                                      string='Attachment')

    @api.onchange('document_id')
    def _onchange_document_id(self):
        if self.document_id and not self.name:
            self.name = self.document_id.name

    def action_renew(self):
        """Create the new document, archive the old one and close its
        reminder activities."""
        self.ensure_one()
        old = self.document_id
        new = old.copy({
            'name': self.name or old.name,
            'document_id': old.document_id.id,
            'employee_id': old.employee_id.id,
            'description': old.description,
            'issue_date': self.issue_date,
            'expiry_date': self.expiry_date,
            'notify_user_ids': [(6, 0, old.notify_user_ids.ids)],
            'doc_attachment_ids': [(6, 0, self.attachment_ids.ids)],
            'previous_document_id': old.id,
        })
        old._close_expiry_activities(
            _("Document renewed: %s") % new.name)
        old.active = False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.employee.document',
            'res_id': new.id,
            'view_mode': 'form',
            'target': 'current',
        }
