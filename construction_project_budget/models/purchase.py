from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class PurchaseOrder(models.Model):
    _inherit = "purchase.order"

    project_id = fields.Many2one(
        "project.project",
        string="Project",
    )
    construction_budget_id = fields.Many2one(
        "construction.project.budget",
        string="Construction Budget",
        domain="[('project_id', '=', project_id)]",
    )
    construction_category_id = fields.Many2one(
        "construction.budget.category",
        string="Budget Category",
        domain="[('id', 'in', available_budget_category_ids)]",
    )
    available_budget_category_ids = fields.Many2many(
        "construction.budget.category",
        compute="_compute_available_budget_categories",
    )
    committed_amount = fields.Monetary(
        compute="_compute_committed_amount",
        currency_field="currency_id",
        help="Portion of this order not yet invoiced — the Committed cost for its budget category. "
             "Always computed live, never cached, so it can never go stale.",
    )

    @api.depends("construction_budget_id", "construction_budget_id.line_ids.category_id")
    def _compute_available_budget_categories(self):
        for po in self:
            budget = po.construction_budget_id
            po.available_budget_category_ids = budget.line_ids.category_id if budget else False

    @api.depends("order_line.price_subtotal", "order_line.qty_invoiced", "order_line.product_qty", "state")
    def _compute_committed_amount(self):
        for po in self:
            if po.state != "purchase" or not po.construction_budget_id:
                po.committed_amount = 0.0
                continue
            total = 0.0
            for line in po.order_line:
                if not line.product_qty:
                    continue
                open_ratio = max(0.0, (line.product_qty - line.qty_invoiced) / line.product_qty)
                total += line.price_subtotal * open_ratio
            po.committed_amount = total

    @api.constrains("project_id", "construction_budget_id", "construction_category_id")
    def _check_construction_budget_consistency(self):
        for po in self:
            if po.construction_budget_id and po.project_id and po.construction_budget_id.project_id != po.project_id:
                raise ValidationError(_(
                    "The selected Construction Budget does not belong to the selected Project."
                ))
            if po.construction_category_id and po.construction_budget_id and po.construction_category_id not in (
                po.construction_budget_id.line_ids.category_id
            ):
                raise ValidationError(_(
                    "Category '%s' is not configured in the selected budget."
                ) % po.construction_category_id.display_name)
            if po.construction_category_id and not po.construction_budget_id:
                raise ValidationError(_("Select a Construction Budget before choosing a Budget Category."))

    def write(self, vals):
        protected = {"project_id", "construction_budget_id", "construction_category_id"}
        if not self.env.su and protected & set(vals.keys()):
            locked = self.filtered(lambda po: po.state not in ("draft", "sent"))
            if locked:
                raise UserError(_(
                    "The Project/Budget/Category of a confirmed Purchase Order can no longer be "
                    "changed, since Committed and Actual amounts have already been calculated "
                    "against it. Cancel the order first if this was set up wrong."
                ))
        return super().write(vals)

    @api.onchange("project_id")
    def _onchange_project_id(self):
        for po in self:
            if po.project_id:
                po.construction_budget_id = po.project_id.budget_id
            else:
                po.construction_budget_id = False

    @api.onchange("construction_budget_id")
    def _onchange_construction_budget_id(self):
        for po in self:
            if po.construction_category_id not in po.available_budget_category_ids:
                po.construction_category_id = False

    def _prepare_picking(self):
        vals = super()._prepare_picking()
        if self.project_id:
            vals["construction_project_id"] = self.project_id.id
        if self.construction_budget_id:
            vals["construction_budget_id"] = self.construction_budget_id.id
        if self.construction_category_id:
            vals["construction_category_id"] = self.construction_category_id.id
        return vals
