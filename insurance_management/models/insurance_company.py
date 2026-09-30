# -*- coding: utf-8 -*-
from odoo import api, fields, models


class InsuranceCompany(models.Model):
    """An Insurance Company that pays a share of a customer's transactions.

    A related ``res.partner`` is used for all accounting purposes (the
    Insurance Invoice / Insurance Receivable is booked on that partner).
    Using a real partner - instead of re-inventing accounting - lets the
    insurance company have its own Accounts Receivable, payment terms,
    credit limit, etc. through the standard Odoo partner/accounting
    mechanisms, which keeps customer money and insurance money on two
    completely distinct ledgers without any custom account-override code.
    """

    _name = "insurance.company"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Insurance Company"
    _order = "name"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(
        required=True, tracking=True, copy=False,
        default=lambda self: self._default_code(),
        help="Filled in automatically for a new company - you can change it.",
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", string="Company", default=lambda self: self.env.company
    )

    partner_id = fields.Many2one(
        "res.partner",
        string="Related Contact",
        required=True,
        ondelete="restrict",
        help="Partner used for invoicing / accounting (Insurance Receivable). "
        "Give this partner its own Accounts Receivable in "
        "Accounting > Customers > Customer if you want the insurance "
        "ledger fully separated from regular customers.",
    )

    contact_person = fields.Char()
    phone = fields.Char()
    mobile = fields.Char()
    email = fields.Char()

    street = fields.Char(related="partner_id.street", readonly=False)
    street2 = fields.Char(related="partner_id.street2", readonly=False)
    city = fields.Char(related="partner_id.city", readonly=False)
    country_id = fields.Many2one(
        related="partner_id.country_id", readonly=False
    )

    payment_term_id = fields.Many2one(
        "account.payment.term", string="Payment Terms"
    )
    default_payment_due_days = fields.Integer(
        string="Default Payment Due Days", default=30
    )
    credit_limit = fields.Monetary(string="Credit Limit", currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id
    )

    plan_ids = fields.One2many("insurance.plan", "insurance_company_id", string="Plans")
    plan_count = fields.Integer(compute="_compute_plan_count")

    claim_ids = fields.One2many("insurance.claim", "insurance_company_id", string="Claims")
    claim_count = fields.Integer(compute="_compute_claim_count")

    policy_count = fields.Integer(compute="_compute_policy_count")
    invoice_count = fields.Integer(compute="_compute_invoice_count")

    notes = fields.Text()

    _sql_constraints = [
        ("code_uniq", "unique(code, company_id)", "Insurance Company Code must be unique."),
    ]

    @api.model
    def _default_code(self):
        """Next free code from the sequence; the user can overwrite it."""
        Sequence = self.env["ir.sequence"]
        existing = self.with_context(active_test=False)
        for _attempt in range(100):  # skip codes somebody already typed by hand
            code = Sequence.next_by_code("insurance.company.code")
            if code and not existing.search_count([("code", "=", code)]):
                return code
        return False

    @api.depends("plan_ids")
    def _compute_plan_count(self):
        for rec in self:
            rec.plan_count = len(rec.plan_ids)

    @api.depends("claim_ids")
    def _compute_claim_count(self):
        for rec in self:
            rec.claim_count = len(rec.claim_ids)

    def _compute_policy_count(self):
        data = self.env["insurance.policy"]._read_group(
            [("insurance_company_id", "in", self.ids)], ["insurance_company_id"], ["__count"]
        )
        counts = {company.id: count for company, count in data}
        for rec in self:
            rec.policy_count = counts.get(rec.id, 0)

    def _compute_invoice_count(self):
        # Counted directly off every posted insurance-company invoice
        # (an ordinary out_invoice whose partner_id is this company's own
        # partner - see account.move._create_insurance_sibling_invoice) -
        # independent of whether an Insurance Claim has been submitted for
        # it yet, so this is the place to see everything owed by this
        # company even before it's been claimed.
        data = self.env["account.move"]._read_group(
            [
                ("partner_id", "in", self.mapped("partner_id").ids),
                ("move_type", "=", "out_invoice"),
                ("state", "=", "posted"),
                ("insurance_invoice_role", "=", "insurance"),
            ],
            ["partner_id"],
            ["__count"],
        )
        counts = {partner.id: count for partner, count in data}
        for rec in self:
            rec.invoice_count = counts.get(rec.partner_id.id, 0)

    def action_view_invoices(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Insurance Invoices",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [
                ("partner_id", "=", self.partner_id.id),
                ("move_type", "=", "out_invoice"),
                ("insurance_invoice_role", "=", "insurance"),
            ],
        }

    def action_view_plans(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Insurance Plans",
            "res_model": "insurance.plan",
            "view_mode": "list,form",
            "domain": [("insurance_company_id", "=", self.id)],
            "context": {"default_insurance_company_id": self.id},
        }

    def action_view_claims(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Insurance Claims",
            "res_model": "insurance.claim",
            "view_mode": "list,form",
            "domain": [("insurance_company_id", "=", self.id)],
        }

    def action_view_policies(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Insurance Policies",
            "res_model": "insurance.policy",
            "view_mode": "list,form",
            "domain": [("insurance_company_id", "=", self.id)],
        }
