# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

COVERAGE_TYPES = [
    ("percentage", "Percentage Coverage"),
    ("fixed_insurance", "Fixed Insurance Amount"),
    ("max_covered", "Maximum Covered Amount"),
    ("fixed_copay", "Customer Fixed Co-Payment"),
]


class InsuranceCoverageRule(models.Model):
    """A single coverage rule for a Plan.

    Resolution priority (see spec section 6 / 32):
        1. Specific Product Rule   (product_id set)
        2. Product Category Rule   (category_id set, product_id empty)
        3. Plan Default Rule       (synthetic - plan.default_coverage_percentage)

    Only one of ``product_id`` / ``category_id`` may be set on a given
    rule; leaving both empty is not allowed (the plan default already
    covers that case and does not need a rule record).
    """

    _name = "insurance.coverage.rule"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Insurance Coverage Rule"
    _order = "plan_id, sequence, id"

    plan_id = fields.Many2one("insurance.plan", required=True, ondelete="cascade")
    insurance_company_id = fields.Many2one(
        related="plan_id.insurance_company_id", store=True, readonly=True
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    product_id = fields.Many2one("product.product", string="Product")
    category_id = fields.Many2one("product.category", string="Product Category")

    coverage_type = fields.Selection(
        COVERAGE_TYPES, required=True, default="percentage"
    )
    coverage_percentage = fields.Float(string="Coverage %")
    fixed_insurance_amount = fields.Monetary(string="Fixed Insurance Amount")
    max_coverage_amount = fields.Monetary(string="Maximum Covered Amount")
    fixed_copay_amount = fields.Monetary(string="Customer Fixed Co-Pay")

    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id
    )

    @api.constrains("product_id", "category_id")
    def _check_specificity(self):
        for rec in self:
            if rec.product_id and rec.category_id:
                raise ValidationError(
                    "A coverage rule should target either a specific Product "
                    "OR a Product Category, not both."
                )
            if not rec.product_id and not rec.category_id:
                raise ValidationError(
                    "A coverage rule must target either a Product or a "
                    "Product Category. For the plan-wide default, use the "
                    "plan's 'Default Coverage %' field instead of a rule."
                )

    @api.model
    def resolve_rule(self, plan, product):
        """Return the most specific applicable rule for ``product`` under
        ``plan``, or an empty recordset if only the plan default applies.
        """
        if not plan:
            return self.browse()

        rule = self.search(
            [("plan_id", "=", plan.id), ("product_id", "=", product.id), ("active", "=", True)],
            limit=1,
        )
        if rule:
            return rule

        category = product.categ_id
        while category:
            rule = self.search(
                [("plan_id", "=", plan.id), ("category_id", "=", category.id), ("active", "=", True)],
                limit=1,
            )
            if rule:
                return rule
            category = category.parent_id

        return self.browse()

    def compute_amounts(self, price_subtotal):
        """Compute (insurance_amount, customer_amount) for a line subtotal,
        given this rule (self may be empty -> caller should use plan
        default percentage instead by calling ``compute_default_amounts``).
        """
        self.ensure_one()
        price_subtotal = price_subtotal or 0.0
        if self.coverage_type == "percentage":
            insurance_amount = price_subtotal * (self.coverage_percentage or 0.0) / 100.0
        elif self.coverage_type == "fixed_insurance":
            insurance_amount = min(self.fixed_insurance_amount or 0.0, price_subtotal)
        elif self.coverage_type == "max_covered":
            insurance_amount = min(self.max_coverage_amount or 0.0, price_subtotal)
        elif self.coverage_type == "fixed_copay":
            copay = min(self.fixed_copay_amount or 0.0, price_subtotal)
            insurance_amount = price_subtotal - copay
        else:
            insurance_amount = 0.0
        insurance_amount = max(0.0, min(insurance_amount, price_subtotal))
        customer_amount = price_subtotal - insurance_amount
        return insurance_amount, customer_amount

    @api.model
    def compute_default_amounts(self, plan, price_subtotal):
        price_subtotal = price_subtotal or 0.0
        pct = plan.default_coverage_percentage if plan else 0.0
        insurance_amount = max(0.0, min(price_subtotal * pct / 100.0, price_subtotal))
        customer_amount = price_subtotal - insurance_amount
        return insurance_amount, customer_amount
