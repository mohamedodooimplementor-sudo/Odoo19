# -*- coding: utf-8 -*-
from odoo import api, fields, models


class InsurancePlan(models.Model):
    _name = "insurance.plan"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Insurance Plan"
    _order = "insurance_company_id, name"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(
        required=True, copy=False,
        default=lambda self: self._default_code(),
        help="Filled in automatically for a new plan - you can change it.",
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company", string="Company", default=lambda self: self.env.company
    )
    insurance_company_id = fields.Many2one(
        "insurance.company", string="Insurance Company", required=True, ondelete="cascade"
    )

    date_start = fields.Date(string="Start Date")
    date_end = fields.Date(string="End Date")

    default_coverage_percentage = fields.Float(
        string="Default Coverage %", default=80.0,
        help="Used as the fallback coverage rule (Plan Default) when no "
        "product- or category-specific coverage rule matches.",
    )
    default_copay_percentage = fields.Float(
        string="Default Customer Co-Pay %", compute="_compute_default_copay", store=True
    )

    max_coverage_amount = fields.Monetary(
        string="Maximum Coverage Amount",
        help="Overall lifetime cap this plan will ever pay for a single policy.",
    )
    annual_coverage_limit = fields.Monetary(string="Annual Coverage Limit")
    coverage_limit_per_transaction = fields.Monetary(string="Coverage Limit per Transaction")

    requires_authorization = fields.Boolean(string="Requires Authorization")

    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id
    )

    coverage_rule_ids = fields.One2many(
        "insurance.coverage.rule", "plan_id", string="Coverage Rules"
    )
    policy_ids = fields.One2many("insurance.policy", "plan_id", string="Policies")
    coverage_rule_count = fields.Integer(compute="_compute_relation_counts")
    policy_count = fields.Integer(compute="_compute_relation_counts")
    claim_count = fields.Integer(compute="_compute_relation_counts")

    notes = fields.Text()

    _sql_constraints = [
        ("code_uniq", "unique(code, insurance_company_id)", "Plan Code must be unique per Insurance Company."),
    ]

    @api.model
    def _default_code(self):
        """Next free code from the sequence; the user can overwrite it."""
        Sequence = self.env["ir.sequence"]
        existing = self.with_context(active_test=False)
        for _attempt in range(100):  # skip codes somebody already typed by hand
            code = Sequence.next_by_code("insurance.plan.code")
            if code and not existing.search_count([("code", "=", code)]):
                return code
        return False

    @api.depends("coverage_rule_ids", "policy_ids")
    def _compute_relation_counts(self):
        claim_data = self.env["insurance.claim"]._read_group(
            [("insurance_plan_id", "in", self.ids)], ["insurance_plan_id"], ["__count"]
        )
        claim_counts = {plan.id: count for plan, count in claim_data}
        for rec in self:
            rec.coverage_rule_count = len(rec.coverage_rule_ids)
            rec.policy_count = len(rec.policy_ids)
            rec.claim_count = claim_counts.get(rec.id, 0)

    def action_view_coverage_rules(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Coverage Rules",
            "res_model": "insurance.coverage.rule",
            "view_mode": "list,form",
            "domain": [("plan_id", "=", self.id)],
            "context": {"default_plan_id": self.id},
        }

    def action_view_policies(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Policies",
            "res_model": "insurance.policy",
            "view_mode": "list,form",
            "domain": [("plan_id", "=", self.id)],
        }

    def action_view_claims(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Claims",
            "res_model": "insurance.claim",
            "view_mode": "list,form",
            "domain": [("insurance_plan_id", "=", self.id)],
        }

    @api.depends("default_coverage_percentage")
    def _compute_default_copay(self):
        for rec in self:
            rec.default_copay_percentage = max(0.0, 100.0 - rec.default_coverage_percentage)

    @api.depends("name", "insurance_company_id.name")
    def _compute_display_name(self):
        # name_get() was removed in Odoo 18/19; display_name is now computed.
        for rec in self:
            rec.display_name = (
                f"{rec.insurance_company_id.name} - {rec.name}"
                if rec.insurance_company_id
                else rec.name
            )
