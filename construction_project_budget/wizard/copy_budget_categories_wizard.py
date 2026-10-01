from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ConstructionBudgetCopyCategoriesWizard(models.TransientModel):
    _name = "construction.budget.copy.categories.wizard"
    _description = "Copy Budget Categories From Another Budget"

    target_budget_id = fields.Many2one("construction.project.budget", required=True)
    source_budget_id = fields.Many2one(
        "construction.project.budget", string="Copy From",
        domain="[('id', '!=', target_budget_id)]",
        help="Pick an existing budget (e.g. a similar past project) to copy its "
             "category lines and Planned Amounts from - a quick way to start a new "
             "budget from a known-good template instead of typing every line by hand.",
    )
    copy_planned_amounts = fields.Boolean(
        default=True,
        help="If unchecked, only the categories themselves are copied (Planned Amount "
             "starts at 0 for you to fill in) - useful when the categories match but the "
             "amounts for this project are different.",
    )

    def action_copy(self):
        self.ensure_one()
        if not self.source_budget_id:
            raise UserError(_("Pick a budget to copy from first."))
        if self.target_budget_id.line_ids:
            raise UserError(_(
                "'%s' already has budget lines - this quick-copy is only offered for a "
                "brand new, empty budget, to avoid creating duplicate category lines."
            ) % self.target_budget_id.display_name)
        lines = [
            (0, 0, {
                "category_id": line.category_id.id,
                "planned_amount": line.planned_amount if self.copy_planned_amounts else 0.0,
            })
            for line in self.source_budget_id.line_ids
        ]
        self.target_budget_id.write({"line_ids": lines})
        return {
            "type": "ir.actions.act_window",
            "res_model": "construction.project.budget",
            "res_id": self.target_budget_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }
