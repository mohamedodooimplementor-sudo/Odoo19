from odoo import fields, models

class ProjectProject(models.Model):
    _inherit = "project.project"

    budget_id = fields.Many2one("construction.project.budget", string="Construction Budget", copy=False)
    budget_total = fields.Monetary(related="budget_id.planned_total", currency_field="currency_id", readonly=True)
    budget_committed = fields.Monetary(related="budget_id.committed_total", currency_field="currency_id", readonly=True)
    budget_spent = fields.Monetary(related="budget_id.actual_total", currency_field="currency_id", readonly=True)
    budget_remaining = fields.Monetary(related="budget_id.remaining_total", currency_field="currency_id", readonly=True)
    budget_utilization = fields.Float(related="budget_id.utilization", readonly=True)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", readonly=True)

    def action_open_budget(self):
        self.ensure_one()
        if not self.budget_id:
            self.budget_id = self.env["construction.project.budget"].create({
                "name": f"Budget - {self.name}",
                "project_id": self.id,
            })
        return {
            "type": "ir.actions.act_window",
            "name": "Project Budget",
            "res_model": "construction.project.budget",
            "view_mode": "form",
            "res_id": self.budget_id.id,
        }
