# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

# States in which the insurance calculation is still allowed to
# auto-recompute. Once the order leaves these states the amounts are
# considered frozen (section 12 of the spec).
_EDITABLE_STATES = ("draft", "sent")


class SaleOrder(models.Model):
    _inherit = "sale.order"

    insurance_enabled = fields.Boolean(string="Insurance Enabled", tracking=True)
    insurance_policy_id = fields.Many2one(
        "insurance.policy",
        string="Insurance Policy",
        domain="[('partner_id', '=', partner_id), ('is_valid', '=', True)]",
        tracking=True,
    )
    insurance_company_id = fields.Many2one(
        related="insurance_policy_id.insurance_company_id", store=True, readonly=True
    )
    insurance_plan_id = fields.Many2one(
        related="insurance_policy_id.plan_id", store=True, readonly=True
    )
    insurance_member_id = fields.Char(
        related="insurance_policy_id.member_id", readonly=True,
        groups="mo_insurance_management.group_insurance_user",
    )
    insurance_policy_number = fields.Char(
        related="insurance_policy_id.policy_number", readonly=True
    )
    insurance_policy_state = fields.Selection(
        related="insurance_policy_id.state", string="Insurance Status", readonly=True
    )

    insurance_authorization_id = fields.Many2one(
        "insurance.authorization",
        string="Authorization",
        domain="[('partner_id', '=', partner_id)]",
    )
    insurance_authorization_required = fields.Boolean(
        compute="_compute_insurance_authorization_required"
    )

    amount_insurance_covered = fields.Monetary(
        string="Total Covered by Insurance", compute="_compute_insurance_totals", store=True
    )
    amount_customer_responsibility = fields.Monetary(
        string="Total Customer Responsibility", compute="_compute_insurance_totals", store=True
    )
    amount_not_covered = fields.Monetary(
        string="Total Not Covered", compute="_compute_insurance_totals", store=True
    )

    insurance_invoice_id = fields.Many2one(
        "account.move",
        string="Invoice (Customer + Insurance Split)",
        copy=False,
        readonly=True,
        help="The customer's own invoice for this order. Its 'Insurance "
        "Company' field is pre-filled here; on posting, a separate real "
        "invoice for the insurance company's share is generated "
        "automatically - see account.move._create_insurance_sibling_invoice.",
    )

    @api.depends("order_line.authorization_required", "insurance_plan_id.requires_authorization")
    def _compute_insurance_authorization_required(self):
        for order in self:
            order.insurance_authorization_required = bool(
                order.insurance_enabled
                and (
                    order.insurance_plan_id.sudo().requires_authorization
                    or any(order.order_line.mapped("authorization_required"))
                )
            )

    @api.depends(
        "amount_total",
        "order_line.insurance_amount",
        "order_line.customer_copay_amount",
        "order_line.amount_not_covered",
    )
    def _compute_insurance_totals(self):
        for order in self:
            covered = sum(order.order_line.mapped("insurance_amount"))
            not_covered = sum(order.order_line.mapped("amount_not_covered"))
            order.amount_insurance_covered = covered
            # Guarantee the invariant: Order Total = Insurance + Customer.
            order.amount_customer_responsibility = order.amount_total - covered
            order.amount_not_covered = not_covered

    @api.onchange("partner_id")
    def _onchange_partner_id_insurance(self):
        for order in self:
            partner = order.partner_id
            primary = partner.primary_insurance_policy_id
            if partner.insurance_enabled:
                # Customer is flagged to always sell with insurance: tick
                # the box automatically and attach the primary policy when
                # it is currently valid (left empty otherwise so the user
                # can pick/create one).
                order.insurance_enabled = True
                order.insurance_policy_id = primary if primary and primary.sudo().is_valid else False
            else:
                order.insurance_enabled = False
                order.insurance_policy_id = False

    @api.onchange("insurance_enabled", "insurance_policy_id")
    def _onchange_insurance_recompute_lines(self):
        for order in self:
            order.order_line._compute_insurance_fields()

    # ------------------------------------------------------------------
    # Integrity: the form's domain only *suggests* the customer's own policy;
    # anyone calling the API could otherwise attach ANOTHER customer's policy
    # (and burn that person's annual coverage). Enforce it on the server.
    # ------------------------------------------------------------------
    @api.constrains("insurance_policy_id", "insurance_authorization_id", "partner_id")
    def _check_insurance_belongs_to_customer(self):
        for order in self:
            customer = order.partner_id.commercial_partner_id
            policy = order.insurance_policy_id.sudo()
            if policy and policy.partner_id.commercial_partner_id != customer:
                raise ValidationError(
                    f"Insurance policy {policy.policy_number} belongs to another customer and "
                    f"cannot be used on {order.name or 'this order'}."
                )
            auth = order.insurance_authorization_id.sudo()
            if auth:
                if auth.partner_id.commercial_partner_id != customer:
                    raise ValidationError(
                        f"Authorization {auth.name} belongs to another customer and cannot be used here."
                    )
                if policy and auth.insurance_company_id != policy.insurance_company_id:
                    raise ValidationError(
                        f"Authorization {auth.name} was issued by a different insurance company "
                        "than the selected policy."
                    )

    # ------------------------------------------------------------------
    # Confirmation
    # ------------------------------------------------------------------
    def action_confirm(self):
        # Snapshot BEFORE calling super(): once super() runs, every order's
        # state becomes 'sale', so filtering on state afterwards can no
        # longer tell a genuinely-new confirmation apart from action_confirm
        # being invoked again on an already-confirmed order (double click,
        # a portal/email re-confirmation, an automated action, ...). Without
        # this snapshot, _apply_annual_limit_at_confirm() would silently
        # re-add this order's covered amount to the policy's annual
        # coverage_used every single time action_confirm() runs, until the
        # policy looks "exhausted" and every future order gets 0 insurance.
        to_process = self.filtered(
            lambda o: o.insurance_enabled and o.state in _EDITABLE_STATES
        )
        for order in to_process:
            # Re-derive the insured/customer split from the coverage rules right
            # before it is frozen, so a value typed straight into the line
            # fields (they are read-only only in the form) cannot survive.
            order.order_line._compute_insurance_fields()
            order._check_insurance_before_confirm()
        result = super().action_confirm()
        for order in to_process:
            order._apply_annual_limit_at_confirm()
        return result

    def _check_insurance_before_confirm(self):
        self.ensure_one()
        # sudo(): a salesperson without any Insurance group can still confirm
        # an insured order - the checks only read insurance data.
        policy = self.insurance_policy_id.sudo()
        if not policy:
            raise UserError("Select a valid Insurance Policy before confirming an insured order.")
        if not policy.is_valid:
            raise UserError(
                f"Insurance Policy {policy.policy_number} is not currently valid "
                f"(status: {policy.state}). Cannot confirm the order with insurance."
            )
        if self.insurance_authorization_required:
            auth = self.insurance_authorization_id.sudo()
            if not auth or auth.state not in ("approved", "partially_approved"):
                raise UserError(
                    "This Insurance Plan requires prior Authorization. Please "
                    "obtain an Approved (or Partially Approved) Authorization "
                    "before confirming this order."
                )

    def _apply_annual_limit_at_confirm(self):
        """Hard-cap the aggregated insurance amount against the policy's
        remaining annual coverage (shifting any excess to the customer),
        then immediately book the (possibly capped) amount as used - there
        is no more separate claim-approval step to defer this to.
        """
        for order in self:
            # sudo(): booking the used coverage writes to the policy, which a
            # user without an Insurance group is not allowed to edit directly.
            policy = order.insurance_policy_id.sudo()
            if not policy:
                continue
            if policy.plan_id.annual_coverage_limit:
                remaining = policy.coverage_remaining
                total_insurance = sum(order.order_line.mapped("insurance_amount"))
                if total_insurance > remaining and total_insurance > 0:
                    factor = remaining / total_insurance if remaining > 0 else 0.0
                    for line in order.order_line.filtered("insurance_amount"):
                        old_amount = line.insurance_amount
                        new_amount = round(old_amount * factor, 2)
                        shifted = old_amount - new_amount
                        line.write(
                            {
                                "insurance_amount": new_amount,
                                "customer_copay_amount": line.customer_copay_amount + shifted,
                                "amount_not_covered": line.amount_not_covered + shifted,
                            }
                        )
            covered = sum(order.order_line.mapped("insurance_amount"))
            if covered:
                policy.coverage_used += covered

    # ------------------------------------------------------------------
    # Invoicing
    # ------------------------------------------------------------------
    # Nothing here runs automatically on confirm - the invoice is only
    insurance_invoice_count = fields.Integer(
        string="Insurance Invoices", compute="_compute_insurance_invoice_count"
    )

    def _compute_insurance_invoice_count(self):
        counts = {}
        if self.ids:
            data = self.env["account.move"].sudo()._read_group(
                [
                    ("insurance_sale_order_id", "in", self.ids),
                    ("insurance_invoice_role", "=", "insurance"),
                ],
                ["insurance_sale_order_id"],
                ["__count"],
            )
            counts = {order.id: count for order, count in data}
        for order in self:
            order.insurance_invoice_count = counts.get(order.id, 0)

    def action_view_insurance_invoices(self):
        """Smart button: the insurance company's own invoice(s) generated
        from this order (shown only once at least one exists)."""
        self.ensure_one()
        invoices = self.env["account.move"].search(
            [
                ("insurance_sale_order_id", "=", self.id),
                ("insurance_invoice_role", "=", "insurance"),
            ]
        )
        action = {
            "type": "ir.actions.act_window",
            "name": "Insurance Invoices",
            "res_model": "account.move",
            "context": {"default_move_type": "out_invoice"},
        }
        if len(invoices) == 1:
            action.update({"view_mode": "form", "res_id": invoices.id})
        else:
            action.update({"view_mode": "list,form", "domain": [("id", "in", invoices.ids)]})
        return action

    # created when the user actually clicks Odoo's normal "Create Invoice"
    # button/wizard (or any other standard path that ends up calling
    # _create_invoices), exactly like a regular, non-insured sale order.
    # This override just tags whichever move(s) that normal flow produces
    # with the insurance split info the receivable-split logic needs once
    # the invoice is posted - see ``account.move._create_insurance_sibling_invoice``.
    def _create_invoices(self, grouped=False, final=False, date=None):
        moves = super()._create_invoices(grouped=grouped, final=final, date=date)
        for order in self.filtered("insurance_enabled"):
            order_moves = moves.filtered(lambda m: order in m.line_ids.sale_line_ids.order_id)
            if not order_moves:
                continue
            # Tag *every* invoice generated for this order (not just the
            # first) - a partially-invoiced order can go through
            # _create_invoices several times over its life, and each new
            # invoice needs the same treatment for its own covered lines.
            order_moves.write(
                {
                    "insurance_sale_order_id": order.id,
                    "insurance_company_id": order.insurance_company_id.partner_id.id
                    if order.amount_insurance_covered
                    else False,
                }
            )
            if not order.insurance_invoice_id:
                order.insurance_invoice_id = order_moves[0].id
        return moves

    # ------------------------------------------------------------------
    # Cancellation / reversal
    # ------------------------------------------------------------------
    def _action_cancel(self):
        for order in self.filtered("insurance_enabled"):
            covered = sum(order.order_line.mapped("insurance_amount"))
            policy = order.insurance_policy_id.sudo()
            if covered and policy:
                policy.coverage_used = max(0.0, policy.coverage_used - covered)
        return super()._action_cancel()


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    insurance_eligible = fields.Boolean(string="Insurance Eligible", default=True)
    coverage_rule_id = fields.Many2one(
        "insurance.coverage.rule", string="Coverage Rule", readonly=True, copy=False
    )
    coverage_type = fields.Selection(
        [
            ("percentage", "Percentage Coverage"),
            ("fixed_insurance", "Fixed Insurance Amount"),
            ("max_covered", "Maximum Covered Amount"),
            ("fixed_copay", "Customer Fixed Co-Payment"),
        ],
        readonly=True,
        copy=False,
    )
    coverage_percentage = fields.Float(string="Coverage %", readonly=True, copy=False)

    insurance_amount = fields.Monetary(string="Insurance Amount", readonly=True, copy=False)
    customer_copay_amount = fields.Monetary(string="Customer Co-Pay Amount", readonly=True, copy=False)
    amount_not_covered = fields.Monetary(string="Not Covered (limit exceeded)", readonly=True, copy=False)
    covered = fields.Boolean(string="Covered", readonly=True, copy=False)

    # The full commercial value of the product sale is always kept on the
    # sales order line. Insurance/customer split is a collection allocation,
    # not a discount to the product's real selling price.
    full_sale_unit_price = fields.Monetary(
        string="Full Sale Unit Price",
        compute="_compute_full_sale_values",
        store=True,
        readonly=True,
        copy=False,
    )
    full_sale_amount = fields.Monetary(
        string="Full Sale Amount",
        compute="_compute_full_sale_values",
        store=True,
        readonly=True,
        copy=False,
    )

    @api.depends("price_unit", "product_uom_qty", "discount", "price_subtotal")
    def _compute_full_sale_values(self):
        for line in self:
            line.full_sale_unit_price = line.price_unit
            line.full_sale_amount = line.price_subtotal

    # Reporting fields: the insurance invoice is intentionally not a
    # product invoice, so insurance product reporting comes from the
    # original sale order line. These stored related fields make the
    # report filterable/groupable by insurer, customer, plan and invoice.
    insurance_company_report_id = fields.Many2one(
        "res.partner",
        related="order_id.insurance_company_id.partner_id",
        string="Insurance Company",
        store=True,
        readonly=True,
    )
    insurance_plan_report_id = fields.Many2one(
        "insurance.plan",
        related="order_id.insurance_plan_id",
        string="Insurance Plan",
        store=True,
        readonly=True,
    )
    insurance_patient_report_id = fields.Many2one(
        "res.partner",
        related="order_id.partner_id",
        string="Customer / Patient",
        store=True,
        readonly=True,
    )
    insurance_invoice_report_id = fields.Many2one(
        "account.move",
        related="order_id.insurance_invoice_id",
        string="Customer Invoice",
        store=True,
        readonly=True,
    )
    insurance_coverage_percent_report = fields.Float(
        string="Insurance Coverage %",
        compute="_compute_insurance_coverage_percent_report",
        store=True,
        readonly=True,
    )

    @api.depends("price_subtotal", "insurance_amount")
    def _compute_insurance_coverage_percent_report(self):
        for line in self:
            if line.price_subtotal:
                line.insurance_coverage_percent_report = (
                    line.insurance_amount / line.price_subtotal * 100.0
                )
            else:
                line.insurance_coverage_percent_report = 0.0

    authorization_required = fields.Boolean(readonly=True, copy=False)
    authorization_number = fields.Char(related="order_id.insurance_authorization_id.name", readonly=True)
    authorization_status = fields.Selection(
        related="order_id.insurance_authorization_id.state", string="Authorization Status", readonly=True
    )

    @api.depends(
        "product_id",
        "product_uom_qty",
        "price_unit",
        "discount",
        "price_subtotal",
        "insurance_eligible",
        "order_id.insurance_enabled",
        "order_id.insurance_policy_id",
    )
    def _compute_insurance_fields(self):
        # sudo(): coverage rules / policies / plans are insurance master data;
        # anybody who can edit a sales order line must get the split computed.
        Rule = self.env["insurance.coverage.rule"].sudo()
        for line in self:
            order = line.order_id
            if order.state not in _EDITABLE_STATES:
                # Frozen after confirmation - never silently recompute.
                continue

            policy = order.insurance_policy_id.sudo()
            if not (order.insurance_enabled and policy and line.insurance_eligible and line.product_id):
                line.coverage_rule_id = False
                line.coverage_type = False
                line.coverage_percentage = 0.0
                line.insurance_amount = 0.0
                line.customer_copay_amount = line.price_subtotal
                line.amount_not_covered = 0.0
                line.authorization_required = False
                line.covered = False
                continue

            plan = policy.plan_id
            rule = Rule.resolve_rule(plan, line.product_id)
            if rule:
                insurance_amount, _customer_amount = rule.compute_amounts(line.price_subtotal)
                coverage_type = rule.coverage_type
                coverage_percentage = rule.coverage_percentage if rule.coverage_type == "percentage" else 0.0
            else:
                insurance_amount, _customer_amount = Rule.compute_default_amounts(plan, line.price_subtotal)
                coverage_type = "percentage"
                coverage_percentage = plan.default_coverage_percentage

            requested_amount = insurance_amount

            if plan.coverage_limit_per_transaction:
                insurance_amount = min(insurance_amount, plan.coverage_limit_per_transaction)

            insurance_amount = max(0.0, min(insurance_amount, line.price_subtotal))
            not_covered = max(0.0, requested_amount - insurance_amount)
            customer_amount = line.price_subtotal - insurance_amount

            line.coverage_rule_id = rule if rule else False
            line.coverage_type = coverage_type
            line.coverage_percentage = coverage_percentage
            line.insurance_amount = insurance_amount
            line.customer_copay_amount = customer_amount
            line.amount_not_covered = not_covered
            line.authorization_required = plan.requires_authorization
            line.covered = insurance_amount > 0

    @api.onchange("product_id", "product_uom_qty", "price_unit", "discount", "insurance_eligible")
    def _onchange_product_recompute_insurance(self):
        self._compute_insurance_fields()

    # The UI onchange above only fires while a form/list row is actively
    # being edited client-side. Adding a line can bypass that (e.g. a
    # quick add straight into the list, imports, or any server-side
    # creation) and would otherwise sit at zero until something else - like
    # toggling "Insurance Enabled" - forces a recompute. These hooks make
    # the split happen right away no matter how the line was created or
    # changed.
    _INSURANCE_TRIGGER_FIELDS = {
        "product_id",
        "product_uom_qty",
        "price_unit",
        "discount",
        "insurance_eligible",
    }

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines.filtered(lambda l: l.order_id.state in _EDITABLE_STATES)._compute_insurance_fields()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if self._INSURANCE_TRIGGER_FIELDS & set(vals.keys()):
            self.filtered(lambda l: l.order_id.state in _EDITABLE_STATES)._compute_insurance_fields()
        return res
