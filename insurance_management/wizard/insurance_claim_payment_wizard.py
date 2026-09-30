# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare, float_is_zero

_logger = logging.getLogger(__name__)


class InsuranceClaimPaymentWizard(models.TransientModel):
    _name = "insurance.claim.payment.wizard"
    _description = "Register an Insurance Claim Payment"

    claim_id = fields.Many2one("insurance.claim", required=True, ondelete="cascade")
    insurance_company_id = fields.Many2one(related="claim_id.insurance_company_id", readonly=True)
    currency_id = fields.Many2one(related="claim_id.currency_id", readonly=True)

    total_claimed = fields.Monetary(related="claim_id.total_claimed", readonly=True)
    total_rejected = fields.Monetary(related="claim_id.total_rejected", readonly=True, string="Rejected")
    already_paid = fields.Monetary(related="claim_id.total_paid", readonly=True, string="Already Paid")
    remaining_balance = fields.Monetary(related="claim_id.remaining_balance", readonly=True)

    amount_to_pay = fields.Monetary(required=True)
    journal_id = fields.Many2one(
        "account.journal",
        string="Payment Journal",
        domain="[('type', 'in', ['bank', 'cash'])]",
        required=True,
    )
    payment_date = fields.Date(default=fields.Date.context_today, required=True)
    memo = fields.Char(string="Memo / Reference")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if res.get("claim_id"):
            claim = self.env["insurance.claim"].browse(res["claim_id"])
            if not res.get("memo"):
                res["memo"] = claim.name
            if "amount_to_pay" in fields_list and not res.get("amount_to_pay"):
                # pre-filled with what is really still owed: rejected amounts
                # (booked or about to be) are not part of it
                res["amount_to_pay"] = max(0.0, claim.remaining_balance - claim.pending_rejected_amount)
        return res

    def action_confirm(self):
        self.ensure_one()
        claim = self.claim_id
        precision = self.currency_id.rounding

        # A rejection that was typed but not booked yet must not be paid.
        if claim.has_pending_rejections:
            claim.action_post_rejections()
            self.invalidate_recordset()

        if float_is_zero(self.amount_to_pay, precision_rounding=precision) or self.amount_to_pay < 0:
            raise UserError("The payment amount must be greater than zero.")
        if float_is_zero(claim.remaining_balance, precision_rounding=precision):
            raise UserError("This claim has no remaining balance.")
        if float_compare(self.amount_to_pay, claim.remaining_balance, precision_rounding=precision) > 0:
            raise UserError("Payment amount cannot exceed the remaining balance.")
        if not self.journal_id:
            raise UserError("Select a Payment Journal.")
        # the form's domain is only a suggestion - enforce it on the server
        if self.journal_id.type not in ("bank", "cash"):
            raise UserError("The payment journal must be a Bank or Cash journal.")
        if self.journal_id.company_id != (claim.company_id or self.env.company):
            raise UserError("The payment journal belongs to another company than the claim.")

        payment = self.env["account.payment"].create(
            {
                "payment_type": "inbound",
                "partner_type": "customer",
                "partner_id": claim.insurance_company_id.partner_id.id,
                "amount": self.amount_to_pay,
                "journal_id": self.journal_id.id,
                "currency_id": self.currency_id.id,
                "company_id": claim.company_id.id,
                "date": self.payment_date or fields.Date.context_today(self),
                "memo": self.memo or claim.name,
                "insurance_claim_id": claim.id,
            }
        )
        payment.action_post()
        self._reconcile_payment(claim, payment)
        # Belt-and-suspenders: force a real recompute of the totals rather
        # than relying only on lazy invalidation - payment_ids is an
        # inverse one2many (via account.payment.insurance_claim_id), and
        # if anything upstream (multi-company record rules, a stale
        # prefetch on `claim`) ever kept it from refreshing here, the
        # status would silently stay wrong until the record is reloaded
        # some other way.
        claim.invalidate_recordset()
        claim._compute_totals()
        claim._sync_state_from_payments()

        return {
            "type": "ir.actions.act_window",
            "res_model": "insurance.claim",
            "view_mode": "form",
            "res_id": claim.id,
            "target": "current",
        }

    def _reconcile_payment(self, claim, payment):
        """Reconciles the new payment against the claim's invoices, OLDEST
        INVOICE FIRST, until either the payment or the invoices' outstanding
        amounts are exhausted - so a payment that only covers part of the
        total fully settles the oldest invoices first and leaves whatever is
        left on the newer ones for the next payment.

        Each reconciliation runs in its own savepoint: if one fails it is
        rolled back on its own, logged and reported in the claim's chatter
        (instead of being silently skipped) and the remaining invoices are
        still processed.
        """
        payment_lines = payment.move_id.line_ids.filtered(
            lambda l: l.account_id.account_type == "asset_receivable" and not l.reconciled
        )
        failures = []
        for cline in claim._lines_oldest_first():
            if not payment_lines.filtered(lambda l: not l.reconciled):
                break  # payment fully allocated already
            # cline.move_id IS the insurance company's own ordinary invoice
            # (partner_id == company_partner already) - just reconcile
            # against its own receivable line directly.
            move_lines = cline.move_id.line_ids.filtered(
                lambda l: l.account_id.account_type == "asset_receivable" and not l.reconciled
            )
            if not move_lines:
                continue
            try:
                with self.env.cr.savepoint():
                    (move_lines + payment_lines).reconcile()
            except Exception as error:  # noqa: BLE001 - report, never hide
                _logger.warning(
                    "Claim %s: could not reconcile payment %s with invoice %s: %s",
                    claim.name, payment.name, cline.move_id.name, error,
                )
                failures.append(f"{cline.move_id.name}: {error}")

        if failures:
            claim.message_post(
                body="Payment %s was registered, but it could NOT be reconciled with: %s. "
                "Reconcile it manually from the payment or the invoice." % (payment.name, "; ".join(failures))
            )
