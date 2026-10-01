from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class ConstructionProjectExpense(models.Model):
    _name = "construction.project.expense"
    _description = "Manual Project Expense"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(string="Description", required=True, tracking=True)
    project_id = fields.Many2one("project.project", required=True, tracking=True)
    budget_id = fields.Many2one(
        "construction.project.budget", required=True, tracking=True,
        domain="[('project_id', '=', project_id)]",
    )
    category_id = fields.Many2one(
        "construction.budget.category", required=True, tracking=True,
        domain="[('id', 'in', available_budget_category_ids)]",
    )
    available_budget_category_ids = fields.Many2many(
        "construction.budget.category", compute="_compute_available_budget_categories",
    )
    date = fields.Date(default=fields.Date.context_today, required=True, tracking=True)
    amount = fields.Monetary(required=True, tracking=True)
    currency_id = fields.Many2one("res.currency", related="budget_id.currency_id", readonly=True)
    employee_id = fields.Many2one("hr.employee", string="Employee / Responsible")
    reference = fields.Char()
    notes = fields.Text()
    state = fields.Selection([
        ("draft", "Draft"), ("confirmed", "Confirmed"), ("cancelled", "Cancelled"),
    ], default="draft", required=True, tracking=True)
    budget_expense_id = fields.Many2one(
        "construction.project.budget.expense", string="Budget Actual Entry", copy=False, readonly=True,
    )
    move_id = fields.Many2one(
        "account.move", string="Journal Entry", copy=False, readonly=True,
        help="Accounting entry posted when this expense was confirmed.",
    )
    allowed_company_ids = fields.Many2many(
        "res.company", compute="_compute_allowed_company_ids",
    )
    counterpart_account_id = fields.Many2one(
        "account.account", string="Counterpart Account",
        domain="[('company_ids', 'in', allowed_company_ids), "
               "('account_type', 'in', ['asset_cash', 'asset_current', 'liability_current'])]",
        default=lambda self: self.env.company.construction_expense_counterpart_account_id,
        help="Credited (as the balancing side) when this expense is confirmed and posted - "
             "e.g. Cash, Petty Cash, or a specific employee's Accrued Expenses account. "
             "Defaults from the Construction Budget, or from Construction Budget > Settings, "
             "but can be changed per expense - e.g. one expense paid from Cash and another "
             "from Bank.",
    )
    expense_account_id = fields.Many2one(
        "account.account", string="Expense Account",
        domain="[('company_ids', 'in', allowed_company_ids), "
               "('account_type', 'in', ['expense', 'expense_direct_cost'])]",
        help="Debited when this expense is confirmed and posted. Defaults from the "
             "Budget Category's own Expense Account, but can be changed for this expense "
             "specifically if needed.",
    )

    @api.depends_context("allowed_company_ids")
    def _compute_allowed_company_ids(self):
        for rec in self:
            rec.allowed_company_ids = self.env.companies

    @api.constrains("expense_account_id", "counterpart_account_id")
    def _check_account_types(self):
        """The view domains on these fields are a UI convenience only - they
        don't stop a write via the API, an import, or a script. This is the
        real enforcement: a regular Budget User (no Accounting permissions)
        can confirm this expense, which posts a journal entry via sudo() - so
        the account types allowed here must be restricted server-side too, or
        they could point spending at an arbitrary GL account (a bank, equity,
        or payable account) they have no business touching.
        """
        for rec in self:
            if rec.expense_account_id and rec.expense_account_id.account_type not in ("expense", "expense_direct_cost"):
                raise ValidationError(_(
                    "'%s' is not an Expense-type account and cannot be used as this expense's "
                    "Expense Account."
                ) % rec.expense_account_id.display_name)
            if rec.counterpart_account_id and rec.counterpart_account_id.account_type not in (
                "asset_cash", "asset_current", "liability_current"
            ):
                raise ValidationError(_(
                    "'%s' is not a Cash/Bank/Current account and cannot be used as this "
                    "expense's Counterpart Account."
                ) % rec.counterpart_account_id.display_name)

    @api.depends("budget_id", "budget_id.line_ids.category_id")
    def _compute_available_budget_categories(self):
        for rec in self:
            rec.available_budget_category_ids = rec.budget_id.line_ids.category_id if rec.budget_id else False

    @api.constrains("amount")
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_("Amount must be greater than zero."))

    @api.constrains("project_id", "budget_id", "category_id")
    def _check_consistency(self):
        for rec in self:
            if rec.budget_id and rec.project_id and rec.budget_id.project_id != rec.project_id:
                raise ValidationError(_("The selected budget does not belong to the selected project."))
            if rec.category_id and rec.budget_id and rec.category_id not in rec.budget_id.line_ids.category_id:
                raise ValidationError(
                    _("Category '%s' is not configured in the selected budget.") % rec.category_id.display_name
                )

    def write(self, vals):
        protected = {"project_id", "budget_id", "category_id", "amount", "counterpart_account_id", "expense_account_id"}
        if not self.env.su and protected & set(vals.keys()):
            locked = self.filtered(lambda r: r.state == "confirmed")
            if locked:
                raise UserError(_(
                    "A confirmed expense can no longer be changed, since its Actual entry has "
                    "already been posted. Reset to Draft first."
                ))
        return super().write(vals)

    @api.onchange("project_id")
    def _onchange_project_id(self):
        for rec in self:
            rec.budget_id = rec.project_id.budget_id if rec.project_id else False

    @api.onchange("budget_id")
    def _onchange_budget_id(self):
        for rec in self:
            if rec.category_id not in rec.available_budget_category_ids:
                rec.category_id = False
            if not rec.counterpart_account_id and rec.budget_id.expense_counterpart_account_id:
                rec.counterpart_account_id = rec.budget_id.expense_counterpart_account_id

    @api.onchange("category_id")
    def _onchange_category_id(self):
        for rec in self:
            if rec.category_id.expense_account_id:
                rec.expense_account_id = rec.category_id.expense_account_id

    @api.onchange("amount", "category_id", "budget_id")
    def _onchange_warn_budget_overrun(self):
        for rec in self:
            if not (rec.budget_id and rec.category_id and rec.amount):
                continue
            line = rec.budget_id.line_ids.filtered(lambda l: l.category_id == rec.category_id)
            if not line:
                continue
            projected_remaining = line.remaining_amount - rec.amount
            if projected_remaining < 0:
                return {"warning": {
                    "title": _("This will exceed the budget"),
                    "message": _(
                        "Confirming this expense would put '%(category)s' %(over)s over its "
                        "planned budget for this project."
                    ) % {
                        "category": rec.category_id.name,
                        "over": rec._format_amount_for_warning(abs(projected_remaining)),
                    },
                }}

    def _format_amount_for_warning(self, amount):
        currency = self.currency_id or self.env.company.currency_id
        return "{:,.2f} {}".format(amount, currency.symbol or "")

    def action_confirm(self):
        Expense = self.env["construction.project.budget.expense"].sudo()
        for rec in self:
            if rec.state != "draft":
                continue
            if rec.budget_id.is_closed:
                raise UserError(_("You cannot confirm an expense against a closed budget."))
            if not rec.budget_id.is_approved:
                raise UserError(_(
                    "'%s' hasn't been approved yet (still in stage '%s'). Move the budget to "
                    "an Approved stage before confirming expenses against it."
                ) % (rec.budget_id.display_name, rec.budget_id.stage_id.name))
            if rec.category_id not in rec.budget_id.line_ids.category_id:
                raise UserError(_("Category '%s' is not configured in this project's budget.") % rec.category_id.display_name)
            move = rec._create_and_post_journal_entry()
            expense = Expense.create({
                "name": rec.name,
                "budget_id": rec.budget_id.id,
                "category_id": rec.category_id.id,
                "amount": rec.amount,
                "date": rec.date,
                "reference": rec.reference,
                "notes": rec.notes,
                "source_type": "manual",
                "source_model": self._name,
                "source_res_id": rec.id,
            })
            move.sudo().construction_budget_expense_id = expense.id
            rec.write({"state": "confirmed", "budget_expense_id": expense.id, "move_id": move.id})

    def action_view_move(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(_("This expense has no linked Journal Entry."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": self.move_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def _create_and_post_journal_entry(self):
        """Post the accounting entry for this Manual Expense: debit the category's
        Expense Account, credit the budget's Counterpart Account, both tagged with
        the budget's analytic account (via the account.move.line create() hook,
        since construction_budget_id/construction_category_id are set on the move).
        skip_budget_actual_post=True so account.move.action_post() doesn't also
        create a second, duplicate Actual entry for the same cost.
        """
        self.ensure_one()
        budget = self.budget_id
        journal = (
            budget.expense_journal_id
            or self.env.company.construction_expense_journal_id
            or self.env["account.journal"].sudo().search(
                [("type", "=", "general"), ("company_id", "=", budget.company_id.id)], limit=1
            )
        )
        if not journal:
            raise UserError(_(
                "No accounting journal is configured to post Manual Expenses. Set a "
                "'Manual Expense Journal' in Construction Budget > Settings, or on this "
                "Construction Budget (Accounting tab)."
            ))
        expense_account = self.expense_account_id or self.category_id.expense_account_id
        if not expense_account:
            raise UserError(_(
                "No Expense Account is set for this expense. Set one directly on this expense, "
                "or on Category '%s' so it applies by default."
            ) % self.category_id.display_name)
        counterpart_account = (
            self.counterpart_account_id
            or budget.expense_counterpart_account_id
            or self.env.company.construction_expense_counterpart_account_id
        )
        if not counterpart_account:
            raise UserError(_(
                "No Counterpart Account is configured to post this expense. Set one on this "
                "expense, or in Construction Budget > Settings, or on this Construction "
                "Budget (Accounting tab)."
            ))
        move = self.env["account.move"].sudo().create({
            "move_type": "entry",
            "journal_id": journal.id,
            "date": self.date,
            "ref": self.reference or self.name,
            "project_id": self.project_id.id,
            "construction_budget_id": budget.id,
            "construction_category_id": self.category_id.id,
            "skip_budget_actual_post": True,
            "line_ids": [
                (0, 0, {
                    "name": self.name,
                    "account_id": expense_account.id,
                    "debit": self.amount,
                    "credit": 0.0,
                }),
                (0, 0, {
                    "name": self.name,
                    "account_id": counterpart_account.id,
                    "debit": 0.0,
                    "credit": self.amount,
                }),
            ],
        })
        move.action_post()
        return move

    def _unlink_journal_entry(self):
        for rec in self:
            move = rec.move_id.sudo()
            rec.move_id = False
            if move:
                move.construction_budget_expense_id = False
                if move.state == "posted":
                    move.button_draft()
                move.unlink()

    def action_cancel(self):
        for rec in self:
            if rec.budget_expense_id:
                if rec.budget_expense_id.budget_id.is_closed:
                    raise UserError(_("You cannot cancel an expense already posted to a closed budget."))
                rec.budget_expense_id.sudo().unlink()
            rec._unlink_journal_entry()
            rec.write({"state": "cancelled", "budget_expense_id": False})

    def action_reset_draft(self):
        for rec in self:
            if rec.budget_expense_id:
                rec.budget_expense_id.sudo().unlink()
            rec._unlink_journal_entry()
            rec.write({"state": "draft", "budget_expense_id": False})
