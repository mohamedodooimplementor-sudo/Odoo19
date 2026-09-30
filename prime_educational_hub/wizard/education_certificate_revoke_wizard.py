# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class EducationCertificateRevokeWizard(models.TransientModel):
    _name = 'education.certificate.revoke.wizard'
    _description = 'Revoke Certificate Wizard'

    certificate_id = fields.Many2one('education.certificate', string='Certificate', required=True)
    reason = fields.Text(string='Revoke Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise UserError(_('A revoke reason is required.'))
        self.certificate_id.action_revoke(reason=self.reason)
        return {'type': 'ir.actions.act_window_close'}
