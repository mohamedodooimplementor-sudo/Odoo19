from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    construction_expense_journal_id = fields.Many2one(
        "account.journal", string="Manual Expense Journal",
        domain="[('type', '=', 'general'), ('company_id', '=', id)]",
        help="Default journal used to post Manual Expense and Labor Cost entries on "
             "Construction Budgets that don't set their own journal.",
    )
    construction_expense_counterpart_account_id = fields.Many2one(
        "account.account", string="Manual Expense Counterpart Account",
        help="Default counterpart account (e.g. Cash, Petty Cash, Accrued Payroll) credited "
             "when a Manual Expense or Labor Cost entry is posted, for Construction Budgets "
             "that don't set their own counterpart account.",
    )
