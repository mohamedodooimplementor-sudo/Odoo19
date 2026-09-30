# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

EXPIRING_SOON_DAYS = 30


class InsurancePolicy(models.Model):
    """A customer's insurance policy / card (Customer Insurance Profile).

    A partner can hold several policies (e.g. two different insurance
    companies); at most one of them is flagged ``is_primary`` and is the
    one auto-selected on new Sales Orders.
    """

    _name = "insurance.policy"
    _description = "Customer Insurance Policy"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "is_primary desc, id desc"
    _rec_name = "policy_number"

    partner_id = fields.Many2one(
        "res.partner", string="Customer / Patient", required=True, ondelete="cascade", index=True
    )
    insurance_company_id = fields.Many2one(
        "insurance.company", string="Insurance Company", required=True, tracking=True
    )
    plan_id = fields.Many2one(
        "insurance.plan",
        string="Insurance Plan",
        required=True,
        domain="[('insurance_company_id', '=', insurance_company_id)]",
        tracking=True,
    )

    # Personal data: only Insurance users may read it. Sales / Billing users can
    # still pick a policy (policy number, company, plan) but never see these.
    member_id = fields.Char(string="Member ID", groups="mo_insurance_management.group_insurance_user")
    card_number = fields.Char(string="Card Number", groups="mo_insurance_management.group_insurance_user")
    policy_number = fields.Char(string="Policy Number", required=True, copy=False)

    date_start = fields.Date(string="Start Date", default=fields.Date.context_today)
    date_end = fields.Date(string="Expiry Date")

    state = fields.Selection(
        [
            ("active", "Active"),
            ("expired", "Expired"),
            ("suspended", "Suspended"),
            ("cancelled", "Cancelled"),
        ],
        default="active",
        required=True,
        tracking=True,
    )
    is_primary = fields.Boolean(string="Primary Insurance")

    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id
    )
    annual_coverage_limit = fields.Monetary(
        related="plan_id.annual_coverage_limit", string="Annual Limit", readonly=True
    )
    coverage_used = fields.Monetary(
        string="Used Coverage", default=0.0, copy=False,
        help="Cumulative insurance amount already granted this year on "
        "confirmed Sales Orders for this policy.",
    )
    coverage_remaining = fields.Monetary(
        string="Remaining Coverage", compute="_compute_coverage_remaining", store=True
    )

    is_valid = fields.Boolean(
        string="Currently Valid", compute="_compute_is_valid", search="_search_is_valid",
        help="True only if state is Active and today is within the "
        "policy's validity dates. Sales Orders only auto-apply valid "
        "policies.",
    )

    notes = fields.Text(groups="mo_insurance_management.group_insurance_user")

    days_to_expiry = fields.Integer(compute="_compute_expiry_info", string="Days to Expiry")
    expiry_state = fields.Selection(
        [("none", "No expiry"), ("ok", "Valid"), ("soon", "Expiring soon"), ("expired", "Expired")],
        compute="_compute_expiry_info",
        string="Expiry",
    )
    coverage_used_percent = fields.Float(
        compute="_compute_coverage_used_percent", string="Used Coverage %"
    )
    authorization_count = fields.Integer(compute="_compute_relation_counts")

    sale_order_count = fields.Integer(compute="_compute_relation_counts")

    _sql_constraints = [
        ("policy_number_company_uniq", "unique(policy_number, insurance_company_id)",
         "Policy Number must be unique per Insurance Company."),
    ]

    def _compute_relation_counts(self):
        order_data = self.env["sale.order"]._read_group(
            [("insurance_policy_id", "in", self.ids)], ["insurance_policy_id"], ["__count"]
        )
        order_counts = {policy.id: count for policy, count in order_data}
        for rec in self:
            rec.sale_order_count = order_counts.get(rec.id, 0)
            # sudo(): counting only - authorizations follow the customer + company
            rec.authorization_count = self.env["insurance.authorization"].sudo().search_count(
                [("partner_id", "=", rec.partner_id.id), ("insurance_company_id", "=", rec.insurance_company_id.id)]
            )

    def action_view_authorizations(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Authorizations",
            "res_model": "insurance.authorization",
            "view_mode": "list,form",
            "domain": [
                ("partner_id", "=", self.partner_id.id),
                ("insurance_company_id", "=", self.insurance_company_id.id),
            ],
            "context": {
                "default_partner_id": self.partner_id.id,
                "default_insurance_company_id": self.insurance_company_id.id,
            },
        }

    @api.depends("date_end")
    def _compute_expiry_info(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.date_end:
                rec.days_to_expiry = 0
                rec.expiry_state = "none"
                continue
            days = (rec.date_end - today).days
            rec.days_to_expiry = days
            if days < 0:
                rec.expiry_state = "expired"
            elif days <= EXPIRING_SOON_DAYS:
                rec.expiry_state = "soon"
            else:
                rec.expiry_state = "ok"

    @api.depends("annual_coverage_limit", "coverage_used")
    def _compute_coverage_used_percent(self):
        for rec in self:
            if rec.annual_coverage_limit:
                rec.coverage_used_percent = min(100.0, rec.coverage_used / rec.annual_coverage_limit * 100.0)
            else:
                rec.coverage_used_percent = 0.0

    # ------------------------------------------------------------------
    # Status buttons
    # ------------------------------------------------------------------
    def unlink(self):
        used = self.env["sale.order"].sudo().search_count([("insurance_policy_id", "in", self.ids)])
        if used:
            raise UserError(
                "This policy is used on sales orders and cannot be deleted - "
                "use Cancel Policy instead so the history stays intact."
            )
        return super().unlink()

    def action_suspend(self):
        self.filtered(lambda p: p.state == "active").write({"state": "suspended"})
        return True

    def action_expire(self):
        self.filtered(lambda p: p.state in ("active", "suspended")).write({"state": "expired"})
        return True

    def action_cancel(self):
        self.filtered(lambda p: p.state in ("active", "suspended", "expired")).write({"state": "cancelled"})
        return True

    def action_reactivate(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.state == "active":
                continue
            if rec.date_end and rec.date_end < today:
                raise UserError(
                    f"Policy {rec.policy_number}: the Expiry Date ({rec.date_end}) has passed. "
                    "Use Renew, or move the Expiry Date forward first."
                )
            rec.state = "active"
        return True

    def action_renew(self):
        """Extend the policy by one year (from today if it already lapsed)
        and make it Active again."""
        today = fields.Date.context_today(self)
        for rec in self:
            start = max(rec.date_end or today, today)
            rec.write({"date_end": start + relativedelta(years=1), "state": "active"})
            rec.message_post(body=f"Policy renewed until {rec.date_end}.")
        return True

    @api.model
    def _cron_expire_policies(self):
        """Daily: mark Active policies whose Expiry Date has passed as Expired."""
        today = fields.Date.context_today(self)
        self.search(
            [("state", "=", "active"), ("date_end", "!=", False), ("date_end", "<", today)]
        ).write({"state": "expired"})

    # ------------------------------------------------------------------
    # Printing
    # ------------------------------------------------------------------
    def action_print(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/mo_insurance_management/print/{self._name}/{self.id}",
            "target": "self",
        }

    def _pdf_document_data(self):
        self.ensure_one()
        env = self.env
        company = env.company
        currency = self.currency_id.name or company.currency_id.name or ""
        states = dict(self._fields["state"].selection)
        colors = {"active": "#16A34A", "suspended": "#D97706", "expired": "#DC2626", "cancelled": "#DC2626"}

        def money(value):
            return f"{value:,.2f}"

        orders = env["sale.order"].search(
            [("insurance_policy_id", "=", self.id), ("state", "in", ("sale", "done"))],
            order="date_order desc",
            limit=15,
        )
        order_rows = []
        for order in orders:
            when = order.date_order and fields.Datetime.context_timestamp(self, order.date_order).date()
            order_rows.append(
                [order.name, str(when or ""), money(order.amount_insurance_covered), money(order.amount_customer_responsibility)]
            )
        yes_no = lambda flag: "Yes" if flag else "No"  # noqa: E731
        return {
            "filename": f"Insurance Policy - {self.policy_number}.pdf".replace("/", "-"),
            "company": company.name,
            "title": "Insurance Policy Card",
            "subtitle": self.policy_number,
            "status": (states.get(self.state, self.state), colors.get(self.state, "#64748B")),
            "currency": currency,
            "generated": fields.Datetime.to_string(fields.Datetime.context_timestamp(self, fields.Datetime.now())),
            "user": env.user.name,
            "sections": [
                {
                    "title": "Customer",
                    "rows": [
                        ("Customer", self.partner_id.display_name),
                        ("Phone", self.partner_id.phone),
                        ("Member ID", self.member_id),
                        ("Card Number", self.card_number),
                    ],
                },
                {
                    "title": "Insurance",
                    "rows": [
                        ("Insurance Company", self.insurance_company_id.display_name),
                        ("Plan", self.plan_id.display_name),
                        ("Policy Number", self.policy_number),
                        ("Primary Insurance", yes_no(self.is_primary)),
                    ],
                },
                {
                    "title": "Validity",
                    "rows": [
                        ("Start Date", str(self.date_start or "")),
                        ("Expiry Date", str(self.date_end or "")),
                        ("Currently Valid", yes_no(self.is_valid)),
                        ("Days to Expiry", str(self.days_to_expiry) if self.date_end else ""),
                    ],
                },
                {
                    "title": f"Coverage ({currency})",
                    "rows": [
                        ("Annual Limit", money(self.annual_coverage_limit) if self.annual_coverage_limit else "Unlimited"),
                        ("Used", money(self.coverage_used)),
                        ("Remaining", money(self.coverage_remaining) if self.annual_coverage_limit else "-"),
                        ("Used %", f"{self.coverage_used_percent:.1f}%" if self.annual_coverage_limit else ""),
                    ],
                },
            ],
            "table": {
                "title": "Recent Insured Orders",
                "empty": "No insured orders yet",
                "columns": [
                    {"label": "Order", "kind": "text", "width": 26},
                    {"label": "Date", "kind": "text", "width": 24},
                    {"label": "Insurance Covered", "kind": "money", "width": 32},
                    {"label": "Customer Share", "kind": "money", "width": 30},
                ],
                "rows": order_rows,
            },
            "texts": [("Notes", self.notes)],
            "signatures": ["Customer", "Insurance Officer"],
        }

    def action_view_sale_orders(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Sales Orders",
            "res_model": "sale.order",
            "view_mode": "list,form",
            "domain": [("insurance_policy_id", "=", self.id)],
        }

    @api.depends("annual_coverage_limit", "coverage_used")
    def _compute_coverage_remaining(self):
        for rec in self:
            if rec.annual_coverage_limit:
                rec.coverage_remaining = max(0.0, rec.annual_coverage_limit - rec.coverage_used)
            else:
                rec.coverage_remaining = 0.0

    @api.depends("state", "date_start", "date_end")
    def _compute_is_valid(self):
        today = fields.Date.context_today(self)
        for rec in self:
            valid = rec.state == "active"
            if valid and rec.date_start and rec.date_start > today:
                valid = False
            if valid and rec.date_end and rec.date_end < today:
                valid = False
            rec.is_valid = valid

    def _search_is_valid(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            raise NotImplementedError("Unsupported search on is_valid")
        today = fields.Date.context_today(self)
        want_true = value if operator == "=" else not value
        domain = [
            ("state", "=", "active"),
            "|", ("date_start", "=", False), ("date_start", "<=", today),
            "|", ("date_end", "=", False), ("date_end", ">=", today),
        ]
        valid_ids = self.search(domain).ids
        if want_true:
            return [("id", "in", valid_ids)]
        return [("id", "not in", valid_ids)]

    @api.constrains("is_primary", "partner_id")
    def _check_single_primary(self):
        for rec in self:
            if rec.is_primary:
                others = self.search(
                    [
                        ("partner_id", "=", rec.partner_id.id),
                        ("is_primary", "=", True),
                        ("id", "!=", rec.id),
                    ]
                )
                if others:
                    raise ValidationError(
                        f"{rec.partner_id.display_name} already has a primary "
                        "insurance policy. Unset it first."
                    )

    def action_reset_coverage_used(self):
        """Zero out this year's tracked usage (Insurance Manager only).

        Needed because ``coverage_used`` is only ever incremented, never
        decremented, by the Sales Order confirmation flow - so a stuck/wrong
        value (e.g. from test confirmations, or from a since-fixed double
        counting bug) has no other way to be corrected from the UI, since
        the field is read-only on the form for everyone else.
        """
        self.write({"coverage_used": 0.0})

    def action_mark_expired_cron(self):
        """Called by a scheduled action to flip stale policies to Expired."""
        today = fields.Date.context_today(self)
        stale = self.search(
            [("state", "=", "active"), ("date_end", "!=", False), ("date_end", "<", today)]
        )
        stale.write({"state": "expired"})
