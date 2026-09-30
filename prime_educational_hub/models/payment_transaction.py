# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    education_lead_id = fields.Many2one(
        'education.lead', string='Education Booking', ondelete='set null',
        help='Set when this transaction was created from the Prime Educational Hub public '
             'website (Courses ▸ Book a Group ▸ Pay Reservation).')

    @api.model_create_multi
    def create(self, vals_list):
        transactions = super().create(vals_list)
        # The visitor pays through Odoo's own generic payment-link checkout (/payment/pay),
        # not through a controller of ours, so we can't pass education_lead_id at creation
        # time. Instead, match it up here via the dedicated partner created specifically for
        # that one booking (see education.lead.website_partner_id) - since that partner is
        # never reused across leads, this match is unambiguous.
        to_link = transactions.filtered(lambda t: not t.education_lead_id and t.partner_id)
        if to_link:
            leads = self.env['education.lead'].sudo().search([
                ('website_partner_id', 'in', to_link.partner_id.ids),
            ])
            lead_by_partner = {lead.website_partner_id.id: lead for lead in leads}
            for tx in to_link:
                lead = lead_by_partner.get(tx.partner_id.id)
                if lead:
                    tx.education_lead_id = lead.id
        return transactions

    def _post_process(self):
        """Called by the payment framework once a transaction's state is settled (including
        to 'done'). education.lead.reservation_paid is a computed field reading straight from
        this relation, so nothing else needs to happen here beyond logging - but this is the
        natural hook where any *side effect* (confirmation email, staff notification) belongs,
        so it's kept as an explicit, well-documented extension point rather than relying on
        the compute alone to "just happen to work"."""
        super()._post_process()
        done_with_lead = self.filtered(lambda t: t.state == 'done' and t.education_lead_id)
        for tx in done_with_lead:
            lead = tx.education_lead_id
            lead.message_post(
                body=(
                    f"Online reservation payment of {tx.amount} {tx.currency_id.name} "
                    f"received via {tx.provider_id.name} (reference: {tx.reference})."
                )
            )
