# -*- coding: utf-8 -*-
"""Insurance Claim = a collection round against one Insurance Company: pick
the company (and optionally narrow it down to one customer and/or one
plan), a date range, and a payment journal.

Submit pulls in every posted invoice that still has an outstanding balance
owed by that company and freezes "Total Claimed". From there the Claim can
receive any number of separate payments over time (see
insurance.claim.payment.wizard) - each one a real, posted account.payment
reconciled against the underlying invoices - and its status (Submitted /
Partial Paid / Paid) always reflects the actual sum of posted payments, not
a manually-set flag.
"""
import logging

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare, float_is_zero

_logger = logging.getLogger(__name__)

# Odoo 18/19 replaced account.payment.state "posted" with "in_process" (posted,
# waiting for the bank/statement) and "paid" (posted and matched). There is no
# "posted" value on a payment any more, so a `state == "posted"` filter never
# matches and every payment silently counts as zero.
EFFECTIVE_PAYMENT_STATES = ("in_process", "paid")



def credited_amount(move, exclude_move=None):
    """Total of credit notes (out_refund) already reconciled against this
    invoice's receivable line, in the invoice's currency. Payments are not
    counted; ``exclude_move`` lets the caller leave out the credit note this
    module itself generated for a rejected amount."""
    total = 0.0
    receivable = move.line_ids.filtered(lambda l: l.account_id.account_type == "asset_receivable")
    for partial in receivable.matched_credit_ids:
        counterpart = partial.credit_move_id.move_id
        if counterpart.move_type == "out_refund" and counterpart != exclude_move:
            total += partial.debit_amount_currency
    return total


STATE_LABELS = [
    ("draft", "Draft"),
    ("submitted", "Submitted"),
    ("partial_paid", "Partially Paid"),
    ("paid", "Paid"),
    ("rejected", "Rejected"),
    ("cancelled", "Cancelled"),
]

ALLOWED_TRANSITIONS = {
    "draft": {"submitted", "cancelled"},
    "submitted": {"draft", "partial_paid", "paid", "rejected", "cancelled"},
    "partial_paid": {"paid", "cancelled"},
    "paid": set(),
    "rejected": {"draft"},
    "cancelled": {"draft"},
}

STATE_COLOR_HEX = {
    "draft": "#94A3B8",
    "submitted": "#3B82F6",
    "partial_paid": "#F59E0B",
    "paid": "#10B981",
    "rejected": "#EF4444",
    "cancelled": "#64748B",
}


class InsuranceClaim(models.Model):
    _name = "insurance.claim"
    _description = "Insurance Claim (Collection from an Insurance Company)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Claim Number", required=True, copy=False, default="New")
    company_id = fields.Many2one(
        "res.company", string="Company", default=lambda self: self.env.company
    )
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id
    )

    insurance_company_id = fields.Many2one(
        "insurance.company", string="Insurance Company", required=True, tracking=True
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        help="Optional: only pull invoices for this one customer. Leave "
        "empty to collect for every customer covered by this insurance "
        "company at once.",
    )
    insurance_plan_id = fields.Many2one(
        "insurance.plan",
        string="Plan",
        domain="[('insurance_company_id', '=', insurance_company_id)]",
        help="Optional: only pull invoices originating from orders under "
        "this one plan. Leave empty for every plan.",
    )
    date_from = fields.Date(string="Invoice Date From", required=True, tracking=True)
    date_to = fields.Date(string="Invoice Date To", required=True, tracking=True)

    journal_id = fields.Many2one(
        "account.journal",
        string="Default Payment Journal",
        domain="[('type', 'in', ['bank', 'cash'])]",
        default=lambda self: self.env.company.insurance_default_payment_journal_id,
        help="Pre-filled as the default journal on the Register Payment wizard.",
    )

    state = fields.Selection(
        STATE_LABELS, default="draft", required=True, tracking=True, group_expand="_read_group_state"
    )

    @api.model
    def _read_group_state(self, stages, domain):
        # Kanban grouped by this field should always show every stage as a
        # fixed column - even ones with zero claims right now - instead of
        # columns appearing/disappearing as claims move between them.
        return [key for key, _label in STATE_LABELS]
    state_color = fields.Char(compute="_compute_state_color")

    claim_line_ids = fields.One2many("insurance.claim.line", "claim_id", string="Invoices")
    invoice_count = fields.Integer(compute="_compute_totals")

    total_claimed = fields.Monetary(
        string="Total Claimed", compute="_compute_totals", store=True,
        help="Frozen total outstanding-from-insurance amount across the "
        "included invoices, as of the last time this Claim was Submitted.",
    )
    total_paid = fields.Monetary(
        string="Total Paid", compute="_compute_totals", store=True,
        help="Sum of this Claim's posted payments only - draft or "
        "cancelled payments never count.",
    )
    total_rejected = fields.Monetary(
        string="Total Rejected", compute="_compute_totals", store=True,
        help="Amounts the insurance company rejected on individual invoices "
        "and that were written off through a posted credit note.",
    )
    remaining_balance = fields.Monetary(
        string="Remaining Balance", compute="_compute_totals", store=True
    )
    credit_notes_pending = fields.Boolean(
        compute="_compute_pending_flags",
        help="A credit note was applied to an included invoice after this "
        "claim was submitted and is not reflected in Total Claimed yet.",
    )
    has_pending_rejections = fields.Boolean(compute="_compute_pending_flags")
    pending_rejected_amount = fields.Monetary(
        compute="_compute_pending_flags",
        help="Rejected amounts typed on the invoice lines that are not booked yet.",
    )

    payment_ids = fields.One2many("account.payment", "insurance_claim_id", string="Payments")
    payment_count = fields.Integer(compute="_compute_totals")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("insurance.claim") or "New"
        return super().create(vals_list)

    @api.depends("state")
    def _compute_state_color(self):
        for rec in self:
            rec.state_color = STATE_COLOR_HEX.get(rec.state, "#94A3B8")

    @api.depends(
        "claim_line_ids.amount_due",
        "claim_line_ids.credit_note_amount",
        "claim_line_ids.rejected_amount",
        "claim_line_ids.rejection_move_id",
        "claim_line_ids.include",
        "payment_ids.amount",
        "payment_ids.state",
    )
    def _compute_totals(self):
        for rec in self:
            included = rec.claim_line_ids.filtered("include")
            rec.invoice_count = len(included)
            rec.total_claimed = sum(line.amount_due - line.credit_note_amount for line in included)
            rec.total_rejected = sum(line.rejected_amount for line in included if line.rejection_move_id)
            effective_payments = rec.payment_ids.filtered(lambda p: p.state in EFFECTIVE_PAYMENT_STATES)
            rec.payment_count = len(effective_payments)
            rec.total_paid = sum(effective_payments.mapped("amount"))
            rec.remaining_balance = max(0.0, rec.total_claimed - rec.total_rejected - rec.total_paid)

    def _compute_pending_flags(self):
        for rec in self:
            included = rec.claim_line_ids.filtered("include")
            rec.credit_notes_pending = any(line.credit_note_pending for line in included)
            pending = included.filtered(lambda l: l.rejected_amount > 0 and not l.rejection_move_id)
            rec.has_pending_rejections = bool(pending)
            rec.pending_rejected_amount = sum(pending.mapped("rejected_amount"))

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------
    def _transition(self, new_state):
        for rec in self:
            allowed = ALLOWED_TRANSITIONS.get(rec.state, set())
            if new_state not in allowed:
                raise UserError(
                    f"Cannot move Claim {rec.name} from '{rec.state}' to '{new_state}'. "
                    f"Allowed next states: {', '.join(sorted(allowed)) or 'none'}."
                )
        self.write({"state": new_state})

    def unlink(self):
        """A claim that was submitted carries payments and credit notes: it
        is part of the accounting trail and must be Cancelled, not deleted."""
        for rec in self:
            if rec.state not in ("draft", "cancelled") or rec.payment_ids:
                raise UserError(
                    f"Claim {rec.name} cannot be deleted (status: {rec.state}). "
                    "Only draft or cancelled claims without payments can be deleted."
                )
        return super().unlink()

    def write(self, vals):
        if "state" in vals:
            for rec in self:
                new_state = vals["state"]
                if new_state != rec.state and new_state not in ALLOWED_TRANSITIONS.get(rec.state, set()):
                    raise UserError(
                        f"Cannot move Claim {rec.name} from '{rec.state}' to '{new_state}' "
                        "this way. Use the status buttons instead."
                    )
        return super().write(vals)

    def _sync_state_from_payments(self):
        """The only place that ever sets state to partial_paid/paid - keeps
        the status a direct reflection of actual posted payments and posted
        rejections (section 5 / 14 of the spec) instead of something the
        user sets by hand.

        A claim is *settled* once payments + rejected amounts cover Total
        Claimed: Paid if anything was actually collected, Rejected if the
        insurance company rejected everything.
        """
        precision = self.currency_id.rounding if self.currency_id else 0.01
        for rec in self:
            if rec.state not in ("submitted", "partial_paid", "paid"):
                continue
            settled = rec.total_claimed > 0 and float_compare(
                rec.total_paid + rec.total_rejected, rec.total_claimed, precision_rounding=precision
            ) >= 0
            if settled:
                target = "paid" if rec.total_paid > 0 else "rejected"
            elif rec.total_paid > 0:
                target = "partial_paid"
            else:
                target = "submitted"
            if target != rec.state:
                rec._transition(target)

    def action_draft(self):
        for rec in self:
            if rec.payment_ids or rec.claim_line_ids.rejection_move_id:
                raise UserError(
                    f"Claim {rec.name} already has payments or posted rejections and cannot "
                    "be reset to draft."
                )
            rec._transition("draft")

    def action_submit(self):
        for rec in self:
            if not rec.insurance_company_id or not rec.date_from or not rec.date_to:
                raise UserError("Select an Insurance Company and a date range before submitting.")
            if rec.date_from > rec.date_to:
                raise UserError("'Invoice Date From' must be before 'Invoice Date To'.")
            rec.claim_line_ids.unlink()
            company_partner = rec.insurance_company_id.partner_id
            if not company_partner:
                raise UserError(
                    f"Insurance Company {rec.insurance_company_id.name} has no linked "
                    "Contact (partner) - cannot look up its invoices."
                )
            domain = [
                ("move_type", "=", "out_invoice"),
                ("state", "=", "posted"),
                ("partner_id", "=", company_partner.id),
                ("insurance_invoice_role", "=", "insurance"),
                ("invoice_date", ">=", rec.date_from),
                ("invoice_date", "<=", rec.date_to),
            ]
            if rec.partner_id:
                domain.append(("insurance_patient_id", "=", rec.partner_id.id))
            if rec.insurance_plan_id:
                domain.append(("insurance_sale_order_id.insurance_plan_id", "=", rec.insurance_plan_id.id))
            moves = self.env["account.move"].search(domain)

            line_vals = []
            for move in moves:
                # This IS the insurance company's own ordinary invoice now
                # (move.partner_id == company_partner already) - its own
                # receivable line carries the real, native amount_residual.
                receivable = move.line_ids.filtered(
                    lambda l: l.account_id.account_type == "asset_receivable"
                )
                amount_due = sum(receivable.mapped("amount_residual"))
                if amount_due <= 0.01:
                    continue
                line_vals.append(
                    (
                        0,
                        0,
                        {
                            "move_id": move.id,
                            "amount_due": amount_due,
                            "include": True,
                            # Credit notes already applied at this moment are
                            # part of amount_due; only later ones are "new".
                            "credit_note_snapshot": credited_amount(move),
                        },
                    )
                )
            if not line_vals:
                raise UserError(
                    "No outstanding invoices were found for the selected Insurance "
                    "Company / period / filters."
                )
            rec.claim_line_ids = line_vals
            rec._transition("submitted")

    def action_reject(self):
        for rec in self:
            rec._transition("rejected")

    def action_cancel(self):
        for rec in self:
            if rec.state == "paid":
                raise UserError(f"Cannot cancel Claim {rec.name}: it has already been paid.")
            rec._transition("cancelled")

    # ------------------------------------------------------------------
    # Rejections & credit notes
    # ------------------------------------------------------------------
    def action_post_rejections(self):
        """Book the rejected amounts typed on the invoice lines. This happens
        automatically as soon as a rejected amount is saved on a line; the
        button is only a fallback (e.g. for amounts typed before the Rejected
        Claims Account was configured)."""
        self.ensure_one()
        if self.state not in ("submitted", "partial_paid"):
            raise UserError("Rejections can only be posted on a Submitted or Partially Paid Claim.")
        lines = self.claim_line_ids.filtered(
            lambda l: l.include and l.rejected_amount > 0 and not l.rejection_move_id
        )
        if not lines:
            raise UserError("Enter a Rejected Amount on at least one invoice line first.")
        self._post_rejections(lines)
        return True

    def _post_rejections(self, lines):
        """A credit note (Rejected Claims Account) is posted against each
        line's insurance company invoice and reconciled with it, so the
        invoice really closes - Aged Receivable and the claim stay in
        agreement, and Remaining Balance drops by the rejected amount."""
        self.ensure_one()
        # Booking a rejection posts a credit note: an accounting act reserved to
        # billing/accounting users (also keeps a clerk from writing off amounts).
        if not self.env.user.has_group("account.group_account_invoice"):
            raise AccessError(
                "Only accounting users (Billing / Insurance Accountant) can book a rejected amount."
            )
        company = self.company_id or self.env.company
        account = company.insurance_rejection_account_id
        if not account:
            raise UserError(
                "Set the 'Rejected Claims Account' in Insurance > Configuration > Settings "
                "before entering a rejected amount - it is the expense account the rejection "
                "is booked to."
            )
        for line in lines:
            line._post_rejection(account)
        self.invalidate_recordset()
        self._compute_totals()
        self._sync_state_from_payments()
        self.message_post(
            body="Rejected amounts booked: "
            + ", ".join(
                f"{l.move_id.name}: {l.rejected_amount:,.2f}"
                + (f" ({l.rejection_reason})" if l.rejection_reason else "")
                for l in lines
            )
        )

    def action_refresh_credit_notes(self):
        """Pick up credit notes applied to the included invoices after the
        claim was submitted, so Total Claimed follows what is really owed."""
        self.ensure_one()
        if self.state not in ("submitted", "partial_paid"):
            raise UserError("Only a Submitted or Partially Paid Claim can be refreshed.")
        before = self.total_claimed
        for line in self.claim_line_ids.filtered("include"):
            line.credit_note_amount = max(0.0, line.credit_note_live - line.credit_note_snapshot)
        self.invalidate_recordset()
        self._compute_totals()
        self._sync_state_from_payments()
        self.message_post(
            body=f"Credit notes refreshed: Total Claimed {before:,.2f} -> {self.total_claimed:,.2f}"
        )
        return True

    def _lines_oldest_first(self):
        """Included invoices, oldest invoice first - the order in which
        every payment is reconciled."""
        lines = self.claim_line_ids.filtered("include")
        return lines.sorted(
            key=lambda l: (l.invoice_date or l.move_id.date or fields.Date.today(), l.move_id.id)
        )

    def action_print_statement(self):
        """Download the claim's collection statement (ReportLab PDF)."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/mo_insurance_management/claim_statement/{self.id}",
            "target": "self",
        }

    def action_open_register_payment_wizard(self):
        self.ensure_one()
        if self.state not in ("submitted", "partial_paid"):
            raise UserError("Only a Submitted or Partially Paid Claim can receive a payment.")
        if self.remaining_balance <= 0:
            raise UserError("This claim has no remaining balance.")
        return {
            "type": "ir.actions.act_window",
            "name": "Register Payment",
            "res_model": "insurance.claim.payment.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_claim_id": self.id,
                "default_journal_id": self.journal_id.id,
                "default_amount_to_pay": self.remaining_balance,
            },
        }

    def action_view_invoices(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Invoices",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", self.claim_line_ids.move_id.ids)],
        }

    def action_view_payments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Payments",
            "res_model": "account.payment",
            "view_mode": "list,form",
            "domain": [("insurance_claim_id", "=", self.id)],
        }


class InsuranceClaimLine(models.Model):
    _name = "insurance.claim.line"
    _description = "Insurance Claim Line (one collected invoice)"
    _order = "id"

    claim_id = fields.Many2one("insurance.claim", required=True, ondelete="cascade")
    move_id = fields.Many2one("account.move", string="Invoice", required=True)
    partner_id = fields.Many2one(related="move_id.partner_id", string="Billed To", store=True)
    insurance_patient_id = fields.Many2one(
        related="move_id.insurance_patient_id", string="Patient / Customer", store=True
    )
    insurance_plan_id = fields.Many2one(
        related="move_id.insurance_sale_order_id.insurance_plan_id", string="Insurance Plan", store=True
    )
    invoice_date = fields.Date(related="move_id.invoice_date", store=True)
    amount_total = fields.Monetary(related="move_id.amount_total", string="Invoice Total")
    amount_due = fields.Monetary(
        string="Insurance Share",
        help="Outstanding amount on this invoice's receivable line that "
        "belonged to the insurance company at the moment the claim was "
        "submitted - the fixed target this line contributes to Total Claimed.",
    )
    paid_amount = fields.Monetary(compute="_compute_live_amounts", string="Paid Amount")
    residual = fields.Monetary(compute="_compute_live_amounts", string="Residual")
    include = fields.Boolean(
        default=True,
        string="Include",
        help="Untick to leave this invoice out of Total Claimed / future "
        "payments without removing it from the list.",
    )
    currency_id = fields.Many2one(related="claim_id.currency_id")

    # Credit notes applied to the invoice AFTER the claim was submitted.
    credit_note_snapshot = fields.Monetary(
        copy=False, readonly=True,
        help="Credit notes already applied to the invoice when the claim was submitted.",
    )
    credit_note_amount = fields.Monetary(
        string="Credit Notes", copy=False, readonly=True,
        help="Credit notes applied since submission (picked up with 'Refresh Credit "
        "Notes'); they reduce this invoice's share of Total Claimed.",
    )
    credit_note_live = fields.Monetary(compute="_compute_live_amounts")
    credit_note_pending = fields.Boolean(compute="_compute_live_amounts")

    # Partial rejection by the insurance company.
    rejected_amount = fields.Monetary(
        string="Rejected Amount", copy=False,
        help="Part of this invoice the insurance company refuses to pay. "
        "Becomes final when 'Post Rejections' books the credit note.",
    )
    rejection_reason = fields.Char(string="Rejection Reason", copy=False)
    rejection_move_id = fields.Many2one(
        "account.move", string="Rejection Credit Note", copy=False, readonly=True
    )

    def unlink(self):
        for line in self:
            if line.rejection_move_id:
                raise UserError(
                    f"The line for {line.move_id.name} has a booked rejection; undo it before removing the line."
                )
            if line.claim_id.state != "draft":
                raise UserError("Lines can only be removed while the claim is in draft.")
        return super().unlink()

    def write(self, vals):
        if "rejected_amount" in vals:
            for line in self.filtered("rejection_move_id"):
                precision = line.currency_id.rounding or 0.01
                if float_compare(vals["rejected_amount"] or 0.0, line.rejected_amount, precision_rounding=precision):
                    raise UserError(
                        f"The rejection on {line.move_id.name} is already booked. Use the undo "
                        "button on the line first if the amount has to change."
                    )
        result = super().write(vals)
        if "rejected_amount" in vals or "rejection_reason" in vals:
            self._auto_post_rejections()
        return result

    def _auto_post_rejections(self):
        """A rejected amount saved on a line is booked right away - no extra
        button to remember."""
        pending = self.filtered(
            lambda l: l.claim_id.state in ("submitted", "partial_paid")
            and l.include
            and l.rejected_amount > 0
            and not l.rejection_move_id
        )
        for claim in pending.mapped("claim_id"):
            claim._post_rejections(pending.filtered(lambda l, c=claim: l.claim_id == c))

    def action_cancel_rejection(self):
        """Undo a booked rejection: the credit note is unreconciled and
        cancelled, and the amount can be entered again."""
        self.ensure_one()
        claim = self.claim_id
        if claim.state not in ("submitted", "partial_paid"):
            raise UserError("A rejection can only be undone while the claim is Submitted or Partially Paid.")
        refund = self.rejection_move_id
        if not refund:
            return True
        if refund.state == "posted":
            refund.button_draft()  # also removes its reconciliation with the invoice
        refund.button_cancel()
        self.write({"rejection_move_id": False})
        self.write({"rejected_amount": 0.0, "rejection_reason": False})
        claim.invalidate_recordset()
        claim._compute_totals()
        claim._sync_state_from_payments()
        claim.message_post(body=f"Rejection on {self.move_id.name} was undone (credit note {refund.name} cancelled).")
        return True

    @api.constrains("rejected_amount")
    def _check_rejected_amount(self):
        for line in self:
            if line.rejected_amount < 0:
                raise UserError("The rejected amount cannot be negative.")

    def _compute_live_amounts(self):
        for line in self:
            # move_id is the insurance company's own ordinary invoice
            # (partner_id == the company) - just its own receivable line.
            receivable = line.move_id.line_ids.filtered(
                lambda l: l.account_id.account_type == "asset_receivable"
            )
            live_residual = sum(receivable.mapped("amount_residual"))
            live_credit = credited_amount(line.move_id, exclude_move=line.rejection_move_id)
            new_credit = max(0.0, live_credit - line.credit_note_snapshot)
            rejected = line.rejected_amount if line.rejection_move_id else 0.0
            line.residual = live_residual
            line.credit_note_live = live_credit
            line.credit_note_pending = abs(new_credit - line.credit_note_amount) > 0.005
            line.paid_amount = max(0.0, line.amount_due - new_credit - rejected - live_residual)

    def _post_rejection(self, account):
        """Credit note for ``rejected_amount`` on the insurance invoice,
        posted and reconciled against it."""
        self.ensure_one()
        invoice = self.move_id
        if self.rejected_amount > invoice.amount_residual + 0.005:
            raise UserError(
                f"Invoice {invoice.name}: the rejected amount ({self.rejected_amount:,.2f}) is "
                f"greater than what is still open on it ({invoice.amount_residual:,.2f})."
            )
        claim = self.claim_id
        company = claim.company_id or self.env.company
        journal = company.insurance_invoice_journal_id or invoice.journal_id
        reason = self.rejection_reason or "Rejected by the insurance company"
        refund = self.env["account.move"].create(
            {
                "move_type": "out_refund",
                "partner_id": invoice.partner_id.id,
                "journal_id": journal.id,
                "invoice_date": fields.Date.context_today(self),
                "currency_id": invoice.currency_id.id,
                "company_id": invoice.company_id.id,
                "ref": f"Rejected claim amount - {invoice.name}",
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "name": f"{claim.name} / {invoice.name}: {reason}",
                            "quantity": 1.0,
                            "price_unit": self.rejected_amount,
                            "account_id": account.id,
                            "tax_ids": [(6, 0, [])],
                        },
                    )
                ],
            }
        )
        refund.action_post()
        to_reconcile = (invoice.line_ids | refund.line_ids).filtered(
            lambda l: l.account_id.account_type == "asset_receivable" and not l.reconciled
        )
        to_reconcile.reconcile()
        self.rejection_move_id = refund.id
