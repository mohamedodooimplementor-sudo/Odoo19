from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    construction_expense_journal_id = fields.Many2one(
        "account.journal", related="company_id.construction_expense_journal_id",
        readonly=False, string="Manual Expense Journal",
    )
    construction_expense_counterpart_account_id = fields.Many2one(
        "account.account", related="company_id.construction_expense_counterpart_account_id",
        readonly=False, string="Manual Expense Counterpart Account",
    )
