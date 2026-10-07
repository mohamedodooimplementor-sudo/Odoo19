from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = 'res.partner'

    mo_whatsapp = fields.Char('WhatsApp')
    mo_approval_state = fields.Selection(
        [('approved', 'Approved'), ('waiting', 'Waiting Approval'), ('refused', 'Refused')],
        'Rep Approval', default='approved', copy=False, tracking=True)
    mo_created_by_rep_id = fields.Many2one('mo.sales.rep', 'Created by Representative', copy=False, index=True)
    mo_client_uid = fields.Char(copy=False, index=True)
    mo_refuse_reason = fields.Char('Refusal Reason', copy=False)

    def _mo_check_manager(self):
        if not self.env.user.has_group('mo_sales_rep_portal.group_mo_rep_manager'):
            raise UserError(_('Only sales managers can approve or refuse customers.'))

    def action_mo_approve(self):
        self._mo_check_manager()
        for partner in self.filtered(lambda p: p.mo_approval_state != 'approved'):
            partner.mo_approval_state = 'approved'
            rep = partner.mo_created_by_rep_id
            if rep:
                rep._notify(_('Customer approved'), partner.display_name, '/rep/customer/%s' % partner.id,
                            key='cust-ok:%s' % partner.id)
            partner.message_post(body=_('Approved by %s', self.env.user.name), subtype_xmlid='mail.mt_note')

    def action_mo_refuse(self):
        self._mo_check_manager()
        for partner in self.filtered(lambda p: p.mo_approval_state != 'refused'):
            partner.mo_approval_state = 'refused'
            rep = partner.mo_created_by_rep_id
            if rep:
                rep._notify(_('Customer refused'), '%s %s' % (partner.display_name, partner.mo_refuse_reason or ''),
                            '/rep/customer/%s' % partner.id, key='cust-no:%s' % partner.id)
            partner.message_post(body=_('Refused by %s', self.env.user.name), subtype_xmlid='mail.mt_note')
