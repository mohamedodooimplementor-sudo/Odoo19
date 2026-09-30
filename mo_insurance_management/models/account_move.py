# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_is_zero


class AccountMove(models.Model):
    _inherit = "account.move"

    insurance_sale_order_id = fields.Many2one(
        "sale.order", string="Related Sales Order (Insurance)", copy=False
    )
    insurance_invoice_role = fields.Selection(
        [
            ("patient", "Patient / Customer Invoice"),
            ("insurance", "Insurance Company Invoice"),
        ],
        string="Insurance Invoice Role",
        copy=False,
    )
    insurance_claim_line_ids = fields.One2many(
        "insurance.claim.line", "move_id", string="Insurance Claim Collections"
    )
    insurance_claim_count = fields.Integer(compute="_compute_insurance_claim_count")

    @api.depends("insurance_claim_line_ids")
    def _compute_insurance_claim_count(self):
        for rec in self:
            # sudo(): claims are only visible to Insurance users, but every
            # accountant opens invoices - the count must not raise.
            rec.insurance_claim_count = len(rec.sudo().insurance_claim_line_ids.claim_id)

    def action_view_insurance_claim(self):
        self.ensure_one()
        claims = self.insurance_claim_line_ids.claim_id
        return {
            "type": "ir.actions.act_window",
            "name": "Insurance Claim",
            "res_model": "insurance.claim",
            "view_mode": "list,form",
            "domain": [("id", "in", claims.ids)],
        }

    def action_view_insurance_sibling_invoice(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Insurance Sibling Invoice",
            "res_model": "account.move",
            "view_mode": "form",
            "res_id": self.insurance_sibling_invoice_id.id,
        }

    def action_view_insurance_sale_order(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Sales Order",
            "res_model": "sale.order",
            "view_mode": "form",
            "res_id": self.insurance_sale_order_id.id,
        }

    # ------------------------------------------------------------------
    # Two-real-invoices insurance billing cycle
    # ------------------------------------------------------------------
    # An earlier version of this tried to keep ONE combined invoice and
    # split its own receivable line between the customer and the insurance
    # company - impossible in Odoo, since account.move.line.partner_id on
    # an out_invoice is a compute+inverse+store field mirroring the
    # invoice's own header partner_id; no line on a single invoice can
    # belong to a different partner than the invoice itself.
    #
    # So instead: the "Insurance Company" field below can be set on a
    # draft customer invoice (only meaningful when it originates from an
    # insured sale order). On posting, *before* super().action_post()
    # runs (draft, fully mutable), a second real invoice is created -
    # partner = the insurance company - carrying only the insurance-covered
    # share of each covered line (per that line's own coverage ratio, so a
    # partially-invoiced order is split by the same ratio every time it's
    # invoiced again). The original invoice's own lines are shrunk down to
    # just the customer's remaining share. Both invoices are then posted
    # together. Each is now a completely ordinary, standalone invoice - it
    # shows up correctly in every native Odoo report (Aged Receivable,
    # Partner Ledger, Follow-up, the partner's own "Invoiced" stat) for its
    # own partner, with no separate reclassification entry needed.
    insurance_company_id = fields.Many2one(
        "res.partner",
        string="Insurance Company",
        help="Set (usually pre-filled from the Sales Order) to bill the "
        "insurance-covered share of this invoice to the insurance company "
        "as a separate invoice, generated automatically on posting.",
    )
    insurance_patient_id = fields.Many2one(
        "res.partner",
        string="Patient / Customer",
        copy=False,
        readonly=True,
        help="Set on the insurance company's own invoice to show which "
        "customer/patient this share was generated for.",
    )
    insurance_sibling_invoice_id = fields.Many2one(
        "account.move",
        string="Insurance Sibling Invoice",
        copy=False,
        readonly=True,
        help="The other invoice of the pair created from the same order: "
        "the patient's own invoice links here to the insurance company's "
        "invoice, and vice versa.",
    )
    insurance_split_done = fields.Boolean(
        string="Insurance Split Applied", copy=False, default=False
    )
    insurance_customer_product_line_ids = fields.Many2many(
        "sale.order.line",
        compute="_compute_insurance_customer_product_lines",
        string="Customer Products",
        help=(
            "Products from the originating customer sales order. These are "
            "informational insurance coverage lines only and are not invoice lines."
        ),
    )

    @api.depends("insurance_sale_order_id", "insurance_invoice_role")
    def _compute_insurance_customer_product_lines(self):
        for move in self:
            if move.insurance_invoice_role == "insurance" and move.insurance_sale_order_id:
                move.insurance_customer_product_line_ids = move.insurance_sale_order_id.sudo().order_line.filtered(
                    lambda line: not line.display_type and line.product_id and line.product_uom_qty
                )
            else:
                move.insurance_customer_product_line_ids = [(5, 0, 0)]

    def action_post(self):
        # Split *before* posting (draft, fully mutable) - see class comment
        # above for why a second real invoice, not a same-invoice split.
        to_split = self.filtered(
            lambda m: m.state == "draft"
            and m.move_type == "out_invoice"
            and m.insurance_sale_order_id
            and m.insurance_company_id
            and not m.insurance_split_done
            and m.insurance_invoice_role != "insurance"
        )
        siblings = self.env["account.move"]
        for move in to_split:
            sibling = move._create_insurance_sibling_invoice()
            if sibling:
                siblings |= sibling

        res = super().action_post()
        if siblings:
            # Recurses into this same override, but siblings all have
            # insurance_invoice_role == "insurance" so the filter above
            # skips them and they just get posted normally.
            siblings.action_post()
        return res

    def _create_insurance_sibling_invoice(self):
        """Create (but don't yet post) the insurance company's own invoice
        for this draft patient invoice's covered lines, and shrink this
        invoice's own covered lines down to the customer's remaining share.

        The insurance invoice does NOT itemize per product - it gets one
        summarized line per distinct taxes combination found among the
        covered lines (in the common case, just one line total:
        "Insurance Share - <invoice name>"), posted to the default account of
        the insurance invoices journal - not to the income account of the
        patient's own lines. The insurance company is billed for a *share of
        the claim*, not the patient's product/service breakdown.

        Returns an empty recordset (nothing created) if no line on this
        invoice actually has any insurance coverage.
        """
        self.ensure_one()
        precision = self.currency_id.rounding
        company_partner = self.insurance_company_id
        patient_partner = self.partner_id
        ref_name = self.name or self.payment_reference or ""

        # The insurance invoice bills the insurer's *share of the claim*, not
        # another sale of the product - so it must NOT reuse the income
        # account of the patient's invoice lines (that one comes from the
        # product / category). It always posts to the default account of
        # the journal the insurance invoice is created in.
        journal = self.company_id.insurance_invoice_journal_id or self.journal_id
        income_account = journal.default_account_id

        # Group the covered amounts by taxes only (the account is the same
        # for all of them now); in the common case that is a single line.
        groups = {}  # tax_ids tuple -> {"amount": float, "tax_ids": recordset}
        any_covered = False
        for line in self.invoice_line_ids:
            # sudo(): whoever posts the invoice (billing/accounting) does not
            # necessarily have access to sales order lines.
            sale_line = line.sudo().sale_line_ids[:1]
            ratio_insurance = 0.0
            if sale_line and not float_is_zero(sale_line.price_subtotal, precision_rounding=precision):
                ratio_insurance = sale_line.insurance_amount / sale_line.price_subtotal
            ratio_insurance = max(0.0, min(1.0, ratio_insurance))
            if float_is_zero(ratio_insurance, precision_rounding=precision):
                continue  # nothing covered on this line - stays 100% customer

            any_covered = True
            insurance_amount = line.price_subtotal * ratio_insurance
            customer_price_unit = line.price_unit * (1 - ratio_insurance)

            key = tuple(sorted(line.tax_ids.ids))
            group = groups.setdefault(key, {"amount": 0.0, "tax_ids": line.tax_ids})
            group["amount"] += insurance_amount

            # Shrink the original (patient) line to just their own share.
            line.price_unit = customer_price_unit

        if not any_covered:
            return self.env["account.move"]

        if not income_account:
            raise UserError(
                f"Journal '{journal.display_name}' has no Default Account. It is used as the "
                "income account of the insurance company's invoice - set it in "
                "Accounting > Configuration > Journals (or pick another journal in "
                "Insurance > Configuration > Settings)."
            )

        sibling_line_vals = []
        for group in groups.values():
            label = f"Insurance Share - {ref_name}".strip(" -")
            if len(groups) > 1:
                tax_names = ", ".join(group["tax_ids"].mapped("name")) or "No tax"
                label = f"{label} ({tax_names})"
            sibling_line_vals.append(
                (
                    0,
                    0,
                    {
                        "name": label,
                        # IMPORTANT:
                        # This is a receivable/revenue document for the
                        # insurance share, NOT another product sale.
                        # Do not put product_id/product_uom_id here.
                        # Otherwise Sales/Invoicing Analysis counts the
                        # insurance invoice as an additional product sale,
                        # and product-related accounting can create an
                        # unwanted COGS impact.
                        "quantity": 1.0,
                        "price_unit": group["amount"],
                        "tax_ids": [(6, 0, group["tax_ids"].ids)],
                        "account_id": income_account.id,
                    },
                )
            )

        # NOTE: deliberately create() a brand-new invoice instead of
        # self.copy() - account.move._sanitize_vals() rejects CLEAR/SET
        # commands (needed to stop copy() from also duplicating this
        # invoice's own lines) on invoice_line_ids outright, even inside a
        # copy(). A plain create() only ever needs CREATE commands, so it
        # sidesteps that restriction entirely.
        sibling = self.env["account.move"].create(
            {
                "move_type": "out_invoice",
                "partner_id": company_partner.id,
                "invoice_date": self.invoice_date,
                "invoice_date_due": self.invoice_date_due,
                "journal_id": journal.id,
                "currency_id": self.currency_id.id,
                "company_id": self.company_id.id,
                "invoice_line_ids": sibling_line_vals,
                "insurance_sale_order_id": self.insurance_sale_order_id.id,
                "insurance_invoice_role": "insurance",
                "insurance_patient_id": patient_partner.id,
                "insurance_company_id": False,
                "insurance_split_done": True,
                "insurance_sibling_invoice_id": self.id,
                "ref": f"Insurance Share - {self.name or self.payment_reference or ''}".strip(" -"),
            }
        )

        self.insurance_sibling_invoice_id = sibling.id
        self.insurance_invoice_role = "patient"
        self.insurance_split_done = True
        return sibling


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    sale_order_line_id = fields.Many2one(
        "sale.order.line",
        string="Originating Sale Order Line",
        copy=False,
        help="Informational link back to the sale order line this invoice "
        "line originated from.",
    )


class AccountPayment(models.Model):
    _inherit = "account.payment"

    insurance_claim_id = fields.Many2one(
        "insurance.claim",
        string="Insurance Claim",
        copy=False,
        # Only Insurance users may link a payment to a claim: the link makes
        # the payment count towards the claim's Total Paid.
        groups="mo_insurance_management.group_insurance_user",
        help="Set when this payment was registered from an Insurance "
        "Claim's Register Payment wizard - a Claim can have several of "
        "these over time (partial payments).",
    )

    @api.constrains("insurance_claim_id", "partner_id", "payment_type")
    def _check_insurance_claim_link(self):
        """A payment may only count towards a claim if it is an incoming
        payment from that claim's insurance company - otherwise any unrelated
        payment could be tied to a claim to make it look paid."""
        for payment in self.filtered("insurance_claim_id"):
            claim = payment.insurance_claim_id.sudo()
            if payment.payment_type != "inbound" or payment.partner_id != claim.insurance_company_id.partner_id:
                raise ValidationError(
                    "A payment can only be linked to an insurance claim when it is an incoming "
                    "payment from that claim's insurance company."
                )
