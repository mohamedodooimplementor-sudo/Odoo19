from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class ConstructionLaborCost(models.Model):
    _name = "construction.labor.cost"
    _description = "Construction Labor Cost Entry"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(string="Description", compute="_compute_name", store=True, readonly=False, required=True)
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
    employee_id = fields.Many2one("hr.employee", string="Employee / Worker", required=True, tracking=True)
    date = fields.Date(default=fields.Date.context_today, required=True, tracking=True)
    hours = fields.Float(required=True, tracking=True)
    hourly_rate = fields.Monetary(required=True, tracking=True)
    total_cost = fields.Monetary(compute="_compute_total_cost", store=True, tracking=True)
    currency_id = fields.Many2one("res.currency", related="budget_id.currency_id", readonly=True)
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
        help="Accounting entry posted when this labor entry was confirmed.",
    )
    allowed_company_ids = fields.Many2many(
        "res.company", compute="_compute_allowed_company_ids",
    )
    counterpart_account_id = fields.Many2one(
        "account.account", string="Counterpart Account",
        domain="[('company_ids', 'in', allowed_company_ids), "
               "('account_type', 'in', ['asset_cash', 'asset_current', 'liability_current'])]",
        default=lambda self: self.env.company.construction_expense_counterpart_account_id,
        help="Credited (as the balancing side) when this labor entry is confirmed and "
             "posted - e.g. Cash, Accrued Payroll, or Bank. Defaults from the Construction "
             "Budget, or from Construction Budget > Settings, but can be changed per entry.",
    )
    expense_account_id = fields.Many2one(
        "account.account", string="Expense Account",
        domain="[('company_ids', 'in', allowed_company_ids), "
               "('account_type', 'in', ['expense', 'expense_direct_cost'])]",
        help="Debited when this labor entry is confirmed and posted. Defaults from the "
             "Budget Category's own Expense Account, but can be changed for this entry "
             "specifically if needed.",
    )

    @api.depends_context("allowed_company_ids")
    def _compute_allowed_company_ids(self):
        for rec in self:
            rec.allowed_company_ids = self.env.companies

    @api.constrains("expense_account_id", "counterpart_account_id")
    def _check_account_types(self):
        """See the identical constraint on construction.project.expense - the
        view domains alone don't stop a write via the API/import/script."""
        for rec in self:
            if rec.expense_account_id and rec.expense_account_id.account_type not in ("expense", "expense_direct_cost"):
                raise ValidationError(_(
                    "'%s' is not an Expense-type account and cannot be used as this labor "
                    "entry's Expense Account."
                ) % rec.expense_account_id.display_name)
            if rec.counterpart_account_id and rec.counterpart_account_id.account_type not in (
                "asset_cash", "asset_current", "liability_current"
            ):
                raise ValidationError(_(
                    "'%s' is not a Cash/Bank/Current account and cannot be used as this "
                    "labor entry's Counterpart Account."
                ) % rec.counterpart_account_id.display_name)

    @api.depends("employee_id", "project_id")
    def _compute_name(self):
        for rec in self:
            if not rec.name and rec.employee_id and rec.project_id:
                rec.name = _("Labor - %(employee)s (%(project)s)") % {
                    "employee": rec.employee_id.name, "project": rec.project_id.name,
                }

    @api.depends("hours", "hourly_rate")
    def _compute_total_cost(self):
        for rec in self:
            rec.total_cost = (rec.hours or 0.0) * (rec.hourly_rate or 0.0)

    @api.depends("budget_id", "budget_id.line_ids.category_id")
    def _compute_available_budget_categories(self):
        for rec in self:
            rec.available_budget_category_ids = rec.budget_id.line_ids.category_id if rec.budget_id else False

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

    @api.onchange("total_cost", "category_id", "budget_id")
    def _onchange_warn_budget_overrun(self):
        for rec in self:
            if not (rec.budget_id and rec.category_id and rec.total_cost):
                continue
            line = rec.budget_id.line_ids.filtered(lambda l: l.category_id == rec.category_id)
            if not line:
                continue
            projected_remaining = line.remaining_amount - rec.total_cost
            if projected_remaining < 0:
                currency = rec.currency_id or self.env.company.currency_id
                return {"warning": {
                    "title": _("This will exceed the budget"),
                    "message": _(
                        "Confirming this labor entry would put '%(category)s' %(over)s over its "
                        "planned budget for this project."
                    ) % {
                        "category": rec.category_id.name,
                        "over": "{:,.2f} {}".format(abs(projected_remaining), currency.symbol or ""),
                    },
                }}

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        for rec in self:
            cost = getattr(rec.employee_id, "timesheet_cost", 0.0) or getattr(rec.employee_id, "hourly_cost", 0.0)
            if cost:
                rec.hourly_rate = cost

    @api.constrains("hours")
    def _check_hours(self):
        for rec in self:
            if rec.hours <= 0:
                raise ValidationError(_("Hours must be greater than zero."))

    @api.constrains("hourly_rate")
    def _check_hourly_rate(self):
        for rec in self:
            if rec.hourly_rate < 0:
                raise ValidationError(_("Hourly rate cannot be negative."))

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
        protected = {"project_id", "budget_id", "category_id", "hours", "hourly_rate", "employee_id", "counterpart_account_id", "expense_account_id"}
        if not self.env.su and protected & set(vals.keys()):
            locked = self.filtered(lambda r: r.state == "confirmed")
            if locked:
                raise UserError(_(
                    "A confirmed labor entry can no longer be changed, since its Actual entry has "
                    "already been posted. Reset to Draft first."
                ))
        return super().write(vals)

    def _find_overlapping_timesheet(self, rec):
        """Soft duplicate-cost check against Timesheets (only meaningful if
        hr_timesheet is installed, which adds employee_id to analytic lines -
        the base 'account' module's account.analytic.line doesn't have it)."""
        AnalyticLine = self.env["account.analytic.line"]
        if "employee_id" not in AnalyticLine._fields or "construction_budget_expense_id" not in AnalyticLine._fields:
            return False
        return bool(AnalyticLine.sudo().search_count([
            ("employee_id", "=", rec.employee_id.id),
            ("project_id", "=", rec.project_id.id),
            ("date", "=", rec.date),
            ("construction_budget_expense_id", "!=", False),
        ]))

    def action_confirm(self):
        Expense = self.env["construction.project.budget.expense"].sudo()
        for rec in self:
            if rec.state != "draft":
                continue
            if rec.budget_id.is_closed:
                raise UserError(_("You cannot confirm a labor entry against a closed budget."))
            if not rec.budget_id.is_approved:
                raise UserError(_(
                    "'%s' hasn't been approved yet (still in stage '%s'). Move the budget to "
                    "an Approved stage before confirming labor entries against it."
                ) % (rec.budget_id.display_name, rec.budget_id.stage_id.name))
            if rec.category_id not in rec.budget_id.line_ids.category_id:
                raise UserError(_("Category '%s' is not configured in this project's budget.") % rec.category_id.display_name)
            if rec.total_cost <= 0:
                raise UserError(_(
                    "This entry's total cost is zero or negative (%s hours x %s/hour) - nothing to post. "
                    "Check the hourly rate."
                ) % (rec.hours, rec.hourly_rate))
            notes = rec.notes or ""
            if rec._find_overlapping_timesheet(rec):
                notes += _(
                    "\nNote: a Timesheet with a posted Labor Actual also exists for this employee, "
                    "project and date - check it isn't double-counting the same hours."
                )
            expense = Expense.create({
                "name": rec.name,
                "budget_id": rec.budget_id.id,
                "category_id": rec.category_id.id,
                "amount": rec.total_cost,
                "date": rec.date,
                "reference": rec.reference,
                "notes": notes,
                "source_type": "labor",
                "source_model": self._name,
                "source_res_id": rec.id,
            })
            move = rec._create_and_post_journal_entry()
            move.sudo().construction_budget_expense_id = expense.id
            rec.write({"state": "confirmed", "budget_expense_id": expense.id, "move_id": move.id})

    def action_view_move(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(_("This labor entry has no linked Journal Entry."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": self.move_id.id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    def _create_and_post_journal_entry(self):
        """Post the accounting entry for this Labor Cost entry: debit the
        category's Expense Account, credit the budget's Counterpart Account,
        both tagged with the budget's analytic account (via the
        account.move.line create() hook, since construction_budget_id /
        construction_category_id are set on the move). skip_budget_actual_post
        =True so account.move.action_post() doesn't also create a second,
        duplicate Actual entry for the same cost.
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
                "No accounting journal is configured to post Labor Costs. Set a "
                "'Manual Expense Journal' in Construction Budget > Settings, or on this "
                "Construction Budget (Accounting tab)."
            ))
        expense_account = self.expense_account_id or self.category_id.expense_account_id
        if not expense_account:
            raise UserError(_(
                "No Expense Account is set for this labor entry. Set one directly on this "
                "entry, or on Category '%s' so it applies by default."
            ) % self.category_id.display_name)
        counterpart_account = (
            self.counterpart_account_id
            or budget.expense_counterpart_account_id
            or self.env.company.construction_expense_counterpart_account_id
        )
        if not counterpart_account:
            raise UserError(_(
                "No Counterpart Account is configured to post this labor entry. Set one on "
                "this labor entry, or in Construction Budget > Settings, or on this "
                "Construction Budget (Accounting tab)."
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
                    "debit": self.total_cost,
                    "credit": 0.0,
                }),
                (0, 0, {
                    "name": self.name,
                    "account_id": counterpart_account.id,
                    "debit": 0.0,
                    "credit": self.total_cost,
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
                    raise UserError(_("You cannot cancel a labor entry already posted to a closed budget."))
                rec.budget_expense_id.sudo().unlink()
            rec._unlink_journal_entry()
            rec.write({"state": "cancelled", "budget_expense_id": False})

    def action_reset_draft(self):
        for rec in self:
            if rec.budget_expense_id:
                rec.budget_expense_id.sudo().unlink()
            rec._unlink_journal_entry()
            rec.write({"state": "draft", "budget_expense_id": False})
