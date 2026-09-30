# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class EducationSessionCancelWizard(models.TransientModel):
    """Forces a reason onto every session cancellation and logs it as a
    chatter note -- P0 audit-trail requirement: staff and admins need to be
    able to see WHY a session was cancelled after the fact, not just that
    it was."""
    _name = 'education.session.cancel.wizard'
    _description = 'Cancel Session (with reason)'

    session_id = fields.Many2one('education.session', string='Session', required=True)
    reason = fields.Char(string='Cancellation Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise UserError(_('Please enter a reason for cancelling this session.'))
        session = self.session_id
        session.write({'state': 'cancelled', 'cancellation_reason': self.reason.strip()})
        session.message_post(
            body=_('Session cancelled. Reason: %s') % self.reason.strip(),
            subtype_xmlid='mail.mt_note',
        )
