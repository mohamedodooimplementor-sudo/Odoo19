from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, AccessError, UserError


class ConstructionBudgetCategory(models.Model):
    _name = "construction.budget.category"
    _description = "Construction Budget Category"
    _order = "sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    type = fields.Selection([
        ("cost", "Cost"),
        ("income", "Income"),
    ], default="cost", required=True,
        help="Cost categories (Materials, Labor, Subcontractors, ...) track money spent "
             "on the project. Income categories track money coming IN from the project "
             "(e.g. progress billing to the customer) - kept separate so reports can show "
             "real profit (Income - Cost) instead of mixing the two together.",
    )
    allowed_company_ids = fields.Many2many(
        "res.company", compute="_compute_allowed_company_ids",
        help="Technical: the company (or companies, in a multi-company session) the "
             "current user is working in - used only to filter the Expense Account "
             "dropdown below to relevant accounts, since this category itself may be "
             "shared across all companies (no company_id of its own).",
    )
    expense_account_id = fields.Many2one(
        "account.account", string="Expense Account",
        domain="[('company_ids', 'in', allowed_company_ids), ('account_type', 'in', ['expense', 'expense_direct_cost'])]",
        help="Debited when a Manual Expense or a Labor Cost entry in this category is "
             "confirmed and posted to the journal. Required before either can be confirmed. "
             "Shows accounts of whichever company/companies you're currently working in.",
    )

    @api.depends_context("allowed_company_ids")
    def _compute_allowed_company_ids(self):
        for rec in self:
            rec.allowed_company_ids = self.env.companies


class ConstructionBudgetStage(models.Model):
    _name = "construction.budget.stage"
    _description = "Construction Budget Stage"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    fold = fields.Boolean(help="Fold this column in the Kanban view when it has no budgets.")
    is_closed = fields.Boolean(
        string="Closed Stage",
        help="Budgets in a closed stage are locked: their lines and actual spending "
             "can no longer be edited, and only a Construction Budget Manager can move "
             "a budget into or out of this stage.",
    )
    is_approved = fields.Boolean(
        string="Approved Stage",
        help="A budget can only receive new spending (Manual Expenses, Labor, Stock "
             "consumption, Vendor Bills, Customer Invoices, Journal Entries) once it's in "
             "a stage marked as Approved here - e.g. after 'Pending Approval' has been "
             "signed off. This is what actually enforces the approval workflow, not just "
             "the stage label.",
    )


class ConstructionProjectBudget(models.Model):
    _name = "construction.project.budget"
    _description = "Construction Project Budget"
    _order = "id desc"

    name = fields.Char(required=True)
    project_id = fields.Many2one("project.project", required=True, ondelete="cascade")
    company_id = fields.Many2one("res.company", related="project_id.company_id", store=True, readonly=True)
    currency_id = fields.Many2one("res.currency", related="company_id.currency_id", readonly=True)
    stage_id = fields.Many2one(
        "construction.budget.stage", string="Stage", tracking=True, ondelete="restrict",
        group_expand="_read_group_stage_ids", copy=False,
        default=lambda self: self.env["construction.budget.stage"].search([], order="sequence, id", limit=1),
    )
    is_closed = fields.Boolean(related="stage_id.is_closed", store=True, string="Closed")
    is_approved = fields.Boolean(
        related="stage_id.is_approved", store=True, string="Approved",
        help="Whether this budget's current stage allows new spending to be recorded "
             "against it (Manual Expenses, Labor, Stock consumption, Vendor Bills, "
             "Customer Invoices, Journal Entries). Move it to an Approved stage first.",
    )
    next_stage_id = fields.Many2one(
        "construction.budget.stage", compute="_compute_stage_navigation",
        help="Technical: the stage this budget would move to via the 'Move to Next Stage' "
             "button, so that button can show the actual destination stage's name.",
    )
    previous_stage_id = fields.Many2one(
        "construction.budget.stage", compute="_compute_stage_navigation",
        help="Technical: the stage this budget would move to via the 'Move Back' button.",
    )
    analytic_account_id = fields.Many2one(
        "account.analytic.account", string="Analytic Account", copy=False,
        domain="[('company_id', 'in', (company_id, False))]",
        help="When set, selecting this budget on a journal entry or invoice automatically "
             "sets this analytic account on the entry's/invoice's lines, so spending on "
             "this project also flows into analytic (cost center) accounting.",
    )
    expense_journal_id = fields.Many2one(
        "account.journal", string="Manual Expense Journal",
        domain="[('type', '=', 'general'), ('company_id', '=', company_id)]",
        default=lambda self: self.env.company.construction_expense_journal_id,
        help="Journal used to post the accounting entry generated when a Manual Expense "
             "or a Labor Cost entry on this budget is confirmed. Defaults to the value set "
             "in Construction Budget > Settings, and can be overridden per budget here.",
    )
    expense_counterpart_account_id = fields.Many2one(
        "account.account", string="Manual Expense Counterpart Account",
        domain="[('company_ids', 'in', company_id), "
               "('account_type', 'in', ['asset_cash', 'asset_current', 'liability_current'])]",
        default=lambda self: self.env.company.construction_expense_counterpart_account_id,
        help="Credited (as the balancing side) when a Manual Expense or a Labor Cost "
             "entry on this budget is confirmed - e.g. Cash, Petty Cash, Accrued Payroll, "
             "or an Accrued Expenses clearing account. Defaults to the value set in "
             "Construction Budget > Settings, and can be overridden per budget here.",
    )

    line_ids = fields.One2many("construction.project.budget.line", "budget_id", string="Budget Lines")
    expense_ids = fields.One2many("construction.project.budget.expense", "budget_id", string="Actual Spending")
    project_expense_ids = fields.One2many("construction.project.expense", "budget_id", string="Manual Expenses")
    labor_cost_ids = fields.One2many("construction.labor.cost", "budget_id", string="Labor Entries")

    planned_total = fields.Monetary(compute="_compute_totals", store=True, currency_field="currency_id",
                                     help="Sum of the Planned Amount on every Cost category line below - "
                                          "the total budget you set out to spend, before anything happens.")
    committed_total = fields.Monetary(compute="_compute_totals", currency_field="currency_id",
                                       help="Open (not yet billed) amount on purchase orders linked to this budget. "
                                            "Always computed live (not cached) since it depends on Purchase Orders, "
                                            "which aren't a direct Odoo relation of this record.")
    actual_total = fields.Monetary(compute="_compute_totals", store=True, currency_field="currency_id",
                                    help="Actual spending - Cost categories only (Income is tracked separately).")
    income_total = fields.Monetary(compute="_compute_totals", store=True, currency_field="currency_id",
                                    help="Actual money received - Income categories only (e.g. progress billing).")
    profit_total = fields.Monetary(compute="_compute_totals", store=True, currency_field="currency_id",
                                    help="Income Total - Actual Total (Cost). The project's real profit so far.")
    remaining_total = fields.Monetary(compute="_compute_totals", store=True, currency_field="currency_id",
                                       help="Planned Budget - Actual Spending (Cost categories only).")
    utilization = fields.Float(compute="_compute_totals", store=True, string="Budget Used %",
                                help="Actual Spending as a percentage of Planned Budget (Cost categories only). "
                                     "Over 100% means you've spent more than planned.")
    expense_count = fields.Integer(compute="_compute_expense_count")
    project_expense_count = fields.Integer(compute="_compute_expense_count")
    labor_cost_count = fields.Integer(compute="_compute_expense_count")
    picking_count = fields.Integer(compute="_compute_related_document_counts")
    purchase_count = fields.Integer(compute="_compute_related_document_counts")
    vendor_bill_count = fields.Integer(compute="_compute_related_document_counts")
    customer_invoice_count = fields.Integer(compute="_compute_related_document_counts")
    journal_entry_count = fields.Integer(compute="_compute_related_document_counts")

    _sql_constraints = [
        ("project_unique", "unique(project_id)",
         "This project already has a Construction Budget. Only one budget per project is supported."),
    ]

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        """Kanban group_expand: always show every stage as a column, even empty ones."""
        return stages.search([], order="sequence, id")

    @api.depends(
        "line_ids.planned_amount", "line_ids.committed_amount", "line_ids.category_id.type",
        "expense_ids.amount", "expense_ids.category_id.type",
    )
    def _compute_totals(self):
        for rec in self:
            cost_lines = rec.line_ids.filtered(lambda l: l.category_id.type != "income")
            cost_expenses = rec.expense_ids.filtered(lambda e: e.category_id.type != "income")
            income_expenses = rec.expense_ids.filtered(lambda e: e.category_id.type == "income")
            planned = sum(cost_lines.mapped("planned_amount"))
            actual = sum(cost_expenses.mapped("amount"))
            income = sum(income_expenses.mapped("amount"))
            committed = sum(cost_lines.mapped("committed_amount"))
            rec.planned_total = planned
            rec.committed_total = committed
            rec.actual_total = actual
            rec.income_total = income
            rec.profit_total = income - actual
            rec.remaining_total = planned - actual
            rec.utilization = actual / planned * 100.0 if planned else 0.0

    @api.depends("expense_ids", "project_expense_ids", "labor_cost_ids")
    def _compute_expense_count(self):
        for rec in self:
            rec.expense_count = len(rec.expense_ids)
            rec.project_expense_count = len(rec.project_expense_ids)
            rec.labor_cost_count = len(rec.labor_cost_ids)

    @api.depends("stage_id")
    def _compute_stage_navigation(self):
        stages = self._get_ordered_stages()
        stage_ids = list(stages.ids)
        for rec in self:
            idx = stage_ids.index(rec.stage_id.id) if rec.stage_id.id in stage_ids else -1
            rec.next_stage_id = stages[idx + 1].id if 0 <= idx < len(stages) - 1 else False
            rec.previous_stage_id = stages[idx - 1].id if idx > 0 else False

    def write(self, vals):
        if "stage_id" in vals and not self.env.su and not self.env.user.has_group(
            "construction_project_budget.group_construction_budget_manager"
        ):
            new_stage = self.env["construction.budget.stage"].browse(vals["stage_id"])
            for rec in self:
                was_closed = rec.stage_id.is_closed
                was_approved = rec.stage_id.is_approved
                if new_stage.is_closed or was_closed:
                    raise AccessError(_(
                        "Only a Construction Budget Manager can move a budget into or out of "
                        "a closed stage."
                    ))
                if new_stage.is_approved and not was_approved:
                    raise AccessError(_(
                        "Only a Construction Budget Manager can approve a budget (move it into "
                        "an Approved stage)."
                    ))
                if was_approved and not new_stage.is_approved:
                    raise AccessError(_(
                        "Only a Construction Budget Manager can move an approved budget back "
                        "out of approval."
                    ))
        return super().write(vals)

    def _get_ordered_stages(self):
        return self.env["construction.budget.stage"].search([], order="sequence, id")

    def action_next_stage(self):
        stages = self._get_ordered_stages()
        for rec in self:
            idx = list(stages.ids).index(rec.stage_id.id) if rec.stage_id in stages else -1
            if idx == -1 or idx + 1 >= len(stages):
                continue
            rec.stage_id = stages[idx + 1].id

    def action_previous_stage(self):
        stages = self._get_ordered_stages()
        for rec in self:
            idx = list(stages.ids).index(rec.stage_id.id) if rec.stage_id in stages else -1
            if idx <= 0:
                continue
            rec.stage_id = stages[idx - 1].id

    def action_view_expenses(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Actual Spending"),
            "res_model": "construction.project.budget.expense",
            "view_mode": "list,form",
            "domain": [("budget_id", "=", self.id)],
            "context": {"default_budget_id": self.id, "default_project_id": self.project_id.id},
        }

    def action_view_project_expenses(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Manual Expenses"),
            "res_model": "construction.project.expense",
            "view_mode": "list,form",
            "domain": [("budget_id", "=", self.id)],
            "context": {"default_budget_id": self.id, "default_project_id": self.project_id.id},
        }

    def action_view_labor_costs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Labor Entries"),
            "res_model": "construction.labor.cost",
            "view_mode": "list,form",
            "domain": [("budget_id", "=", self.id)],
            "context": {"default_budget_id": self.id, "default_project_id": self.project_id.id},
        }

    def _compute_related_document_counts(self):
        picking_counts = {}
        for grp in self.env["stock.picking"]._read_group(
            [("construction_budget_id", "in", self.ids)], ["construction_budget_id"], ["__count"]
        ):
            picking_counts[grp[0].id] = grp[1]

        purchase_counts = {}
        for grp in self.env["purchase.order"]._read_group(
            [("construction_budget_id", "in", self.ids)], ["construction_budget_id"], ["__count"]
        ):
            purchase_counts[grp[0].id] = grp[1]

        bill_counts = {}
        for grp in self.env["account.move"]._read_group(
            [("construction_budget_id", "in", self.ids), ("move_type", "=", "in_invoice")],
            ["construction_budget_id"], ["__count"],
        ):
            bill_counts[grp[0].id] = grp[1]

        invoice_counts = {}
        for grp in self.env["account.move"]._read_group(
            [("construction_budget_id", "in", self.ids), ("move_type", "=", "out_invoice")],
            ["construction_budget_id"], ["__count"],
        ):
            invoice_counts[grp[0].id] = grp[1]

        je_counts = {}
        for grp in self.env["account.move"]._read_group(
            [("construction_budget_id", "in", self.ids), ("move_type", "=", "entry")],
            ["construction_budget_id"], ["__count"],
        ):
            je_counts[grp[0].id] = grp[1]

        for rec in self:
            rec.picking_count = picking_counts.get(rec.id, 0)
            rec.purchase_count = purchase_counts.get(rec.id, 0)
            rec.vendor_bill_count = bill_counts.get(rec.id, 0)
            rec.customer_invoice_count = invoice_counts.get(rec.id, 0)
            rec.journal_entry_count = je_counts.get(rec.id, 0)

    def action_view_stock_pickings(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Stock Transfers"),
            "res_model": "stock.picking",
            "view_mode": "list,form",
            "domain": [("construction_budget_id", "=", self.id)],
        }

    def action_view_purchase_orders(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Purchase Orders"),
            "res_model": "purchase.order",
            "view_mode": "list,form",
            "domain": [("construction_budget_id", "=", self.id)],
        }

    def action_view_vendor_bills(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Vendor Bills"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("construction_budget_id", "=", self.id), ("move_type", "=", "in_invoice")],
            "context": {"default_move_type": "in_invoice"},
        }

    def action_copy_categories_from_budget(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Copy Categories From Another Budget"),
            "res_model": "construction.budget.copy.categories.wizard",
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "new",
            "context": {"default_target_budget_id": self.id},
        }

    def action_view_customer_invoices(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Customer Invoices"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("construction_budget_id", "=", self.id), ("move_type", "=", "out_invoice")],
            "context": {"default_move_type": "out_invoice"},
        }

    def action_view_journal_entries(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Journal Entries"),
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("construction_budget_id", "=", self.id), ("move_type", "=", "entry")],
            "context": {"default_move_type": "entry"},
        }

    @api.model
    def get_dashboard_data(self, project_id=None):
        """Aggregate data consumed by the OWL budget dashboard client action."""
        domain = [("project_id", "=", project_id)] if project_id else []
        budgets = self.search(domain)
        active_budgets = budgets.filtered(lambda b: not b.is_closed)
        over_budget = budgets.filtered(lambda b: b.remaining_total < 0)

        report_currency = self.env.company.currency_id
        today = fields.Date.context_today(self)

        def to_report_currency(amount, from_currency):
            if not amount or not from_currency or from_currency == report_currency:
                return amount
            return from_currency._convert(amount, report_currency, self.env.company, today)

        projects = [{
            "id": b.id,
            "project_id": b.project_id.id,
            "name": b.project_id.display_name or b.name,
            "stage": b.stage_id.name,
            "is_closed": b.is_closed,
            "planned": b.planned_total,
            "committed": b.committed_total,
            "actual": b.actual_total,
            "remaining": b.remaining_total,
            "utilization": b.utilization,
            "income": b.income_total,
            "profit": b.profit_total,
            "currency_symbol": b.currency_id.symbol,
        } for b in budgets.sorted(key=lambda b: b.utilization, reverse=True)]

        top_profit_projects = sorted(
            [p for p in projects if p["income"]], key=lambda p: p["profit"], reverse=True
        )[:5]

        lines = self.env["construction.project.budget.line"].search(
            [("budget_id", "in", budgets.ids)]
        )
        categories = {}
        for line in lines:
            cat = line.category_id
            entry = categories.setdefault(cat.id, {
                "name": cat.name, "planned": 0.0, "committed": 0.0, "actual": 0.0,
            })
            line_currency = line.currency_id
            entry["planned"] += to_report_currency(line.planned_amount, line_currency)
            entry["committed"] += to_report_currency(line.committed_amount, line_currency)
            entry["actual"] += to_report_currency(line.actual_amount, line_currency)

        expenses = self.env["construction.project.budget.expense"].search(
            [("budget_id", "in", budgets.ids)]
        )
        source_totals = {}
        for exp in expenses:
            key = exp.source_type or "manual"
            source_totals[key] = source_totals.get(key, 0.0) + to_report_currency(exp.amount, exp.currency_id)

        recent_expenses = self.env["construction.project.budget.expense"].search(
            [("budget_id", "in", budgets.ids)], order="date desc, id desc", limit=8
        )

        all_projects = self.env["project.project"].search([("budget_id", "!=", False)])

        multi_currency = len(set(budgets.mapped("currency_id.id"))) > 1

        # Last 6 calendar months of Actual spending (Cost only) - real numbers,
        # not a fabricated trend: used both for the "Total Spent" KPI's
        # month-over-month change and for the spending-trend chart.
        from dateutil.relativedelta import relativedelta
        cost_expenses = expenses.filtered(lambda e: e.category_id.type != "income")
        income_expenses = expenses.filtered(lambda e: e.category_id.type == "income")
        month_starts = [(today.replace(day=1) - relativedelta(months=i)) for i in range(5, -1, -1)]
        monthly_trend = []
        for i, month_start in enumerate(month_starts):
            month_end = (month_start + relativedelta(months=1)) - relativedelta(days=1)
            month_actual = sum(
                to_report_currency(e.amount, e.currency_id) for e in cost_expenses
                if e.date and month_start <= e.date <= month_end
            )
            month_income = sum(
                to_report_currency(e.amount, e.currency_id) for e in income_expenses
                if e.date and month_start <= e.date <= month_end
            )
            monthly_trend.append({
                "label": month_start.strftime("%b"),
                "actual": month_actual,
                "income": month_income,
                "profit": month_income - month_actual,
            })
        this_month_actual = monthly_trend[-1]["actual"] if monthly_trend else 0.0
        last_month_actual = monthly_trend[-2]["actual"] if len(monthly_trend) > 1 else 0.0
        if last_month_actual:
            actual_trend_pct = (this_month_actual - last_month_actual) / last_month_actual * 100.0
        else:
            actual_trend_pct = 100.0 if this_month_actual else 0.0

        total_income = sum(to_report_currency(e.amount, e.currency_id) for e in income_expenses)
        total_actual = sum(to_report_currency(e.amount, e.currency_id) for e in cost_expenses)

        # Real, computed alerts (no fabricated notifications) - budgets that
        # are over or near their limit, most severe first.
        alerts = []
        for b in budgets.filtered(lambda b: b.utilization > 100).sorted(key=lambda b: b.utilization, reverse=True):
            alerts.append({
                "type": "danger",
                "text": _("'%s' exceeded its planned budget by %.0f%%") % (
                    b.project_id.display_name or b.name, b.utilization - 100,
                ),
            })
        for b in budgets.filtered(lambda b: 80 <= b.utilization <= 100).sorted(key=lambda b: b.utilization, reverse=True):
            alerts.append({
                "type": "warning",
                "text": _("'%s' is at %.0f%% of its planned budget") % (
                    b.project_id.display_name or b.name, b.utilization,
                ),
            })
        for e in recent_expenses[:3]:
            alerts.append({
                "type": "info",
                "text": _("%s recorded: %s") % (e.category_id.name or _("Expense"), e.name),
            })
        alerts = alerts[:8]

        return {
            "kpis": {
                "total_budgets": len(budgets),
                "active_budgets": len(active_budgets),
                "total_planned": sum(to_report_currency(b.planned_total, b.currency_id) for b in budgets),
                "total_committed": sum(to_report_currency(b.committed_total, b.currency_id) for b in budgets),
                "total_actual": total_actual,
                "total_income": total_income,
                "net_profit": total_income - total_actual,
                "over_budget_count": len(over_budget),
                "actual_trend_pct": actual_trend_pct,
                "currency_symbol": report_currency.symbol,
                "currency_position": report_currency.position,
                "multi_currency": multi_currency,
            },
            "monthly_trend": monthly_trend,
            "alerts": alerts,
            "projects": projects,
            "top_profit_projects": top_profit_projects,
            "categories": list(categories.values()),
            "sources": [{
                "name": label, "amount": amount,
            } for label, amount in source_totals.items()],
            "recent_expenses": [{
                "id": e.id,
                "name": e.name,
                "project": e.project_id.display_name,
                "category": e.category_id.name,
                "amount": e.amount,
                "currency_symbol": e.currency_id.symbol,
                "source_type": e.source_type,
                "date": fields.Date.to_string(e.date) if e.date else "",
            } for e in recent_expenses],
            "project_options": [{"id": p.id, "name": p.display_name} for p in all_projects],
        }

    @api.model
    def get_profitability_data(self, project_id=None, date_from=None, date_to=None):
        """Aggregate data for the Project Profitability Report (client action + PDF).

        Always broken down by budget category (Materials, Labor, Manual Expenses,
        ...) - every category configured on the budget appears, even ones with
        zero Actuals in the period - so the report shows the project's whole
        budget, not just a lump total:
        - project_id set: only that project's categories, each with its Actual
          entries for the period as drill-down lines (ledger-style).
        - project_id not set: every project's categories, grouped under that
          project's name.

        Income categories (money coming IN from the project, e.g. progress
        billing) are kept in their own section and totalled separately from
        Cost categories - "Total" at the bottom is Cost only (matching what a
        budget's own Planned/Committed/Actual mean), with Income and Net Profit
        (Income - Cost) shown as their own summary lines.

        Only Actual spending is restricted to [date_from, date_to]; Planned and
        Committed reflect the budget's current state (they aren't period figures).
        """
        report_currency = self.env.company.currency_id
        today = fields.Date.context_today(self)

        def to_report_currency(amount, from_currency):
            if not amount or not from_currency or from_currency == report_currency:
                return amount
            return from_currency._convert(amount, report_currency, self.env.company, today)

        def _fmt_range(exp_domain):
            if date_from:
                exp_domain = exp_domain + [("date", ">=", date_from)]
            if date_to:
                exp_domain = exp_domain + [("date", "<=", date_to)]
            return exp_domain

        def _line(label, planned, committed, actual, category_type="cost", lines=None):
            variance = planned - actual
            variance_pct = (variance / planned * 100.0) if planned else 0.0
            return {
                "label": label,
                "planned": planned,
                "committed": committed,
                "actual": actual,
                "variance": variance,
                "variance_pct": variance_pct,
                "category_type": category_type,
                "lines": lines or [],
            }

        if project_id:
            projects = self.env["project.project"].browse(project_id)
            report_title = projects.display_name
        else:
            projects = self.env["project.project"].search([("budget_id", "!=", False)])
            report_title = _("All Projects")

        budgets = projects.mapped("budget_id")
        all_expenses = self.env["construction.project.budget.expense"].search(
            _fmt_range([("budget_id", "in", budgets.ids)]), order="date, id"
        )
        by_budget_category = {}
        for exp in all_expenses:
            key = (exp.budget_id.id, exp.category_id.id)
            by_budget_category.setdefault(key, self.env["construction.project.budget.expense"].browse())
            by_budget_category[key] |= exp

        def _category_sections(budget):
            budget_sections = []
            for bline in budget.line_ids:
                expenses = by_budget_category.get((budget.id, bline.category_id.id), all_expenses.browse())
                actual = sum(to_report_currency(e.amount, e.currency_id) for e in expenses)
                budget_sections.append(_line(
                    bline.category_id.name,
                    to_report_currency(bline.planned_amount, bline.currency_id),
                    to_report_currency(bline.committed_amount, bline.currency_id),
                    actual,
                    category_type=bline.category_id.type,
                    lines=[{
                        "date": fields.Date.to_string(e.date) if e.date else "",
                        "name": e.name,
                        "reference": e.reference or "",
                        "source_type": e.source_type,
                        "amount": e.amount,
                    } for e in expenses],
                ))
            return budget_sections

        multi_project = not project_id and len(projects.filtered(lambda p: p.budget_id)) > 1

        if multi_project:
            # One collapsed row per project (an arrow expands it to reveal that
            # project's category breakdown) instead of one flat row per
            # (project, category) pair.
            groups = []
            for project in projects:
                budget = project.budget_id
                if not budget:
                    continue
                budget_sections = _category_sections(budget)
                cost_secs = [s for s in budget_sections if s["category_type"] != "income"]
                income_secs = [s for s in budget_sections if s["category_type"] == "income"]
                planned = sum(s["planned"] for s in cost_secs)
                committed = sum(s["committed"] for s in cost_secs)
                actual = sum(s["actual"] for s in cost_secs)
                income = sum(s["actual"] for s in income_secs)
                variance = planned - actual
                groups.append({
                    "label": project.display_name or budget.name,
                    "planned": planned,
                    "committed": committed,
                    "actual": actual,
                    "variance": variance,
                    "variance_pct": (variance / planned * 100.0) if planned else 0.0,
                    "income": income,
                    "net_profit": income - actual,
                    "sections": cost_secs,
                    "income_sections": income_secs,
                })
            cost_sections = [s for g in groups for s in g["sections"]]
            income_sections = [s for g in groups for s in g["income_sections"]]
        else:
            groups = None
            budget_sections = []
            for project in projects:
                if project.budget_id:
                    budget_sections += _category_sections(project.budget_id)
            cost_sections = [s for s in budget_sections if s["category_type"] != "income"]
            income_sections = [s for s in budget_sections if s["category_type"] == "income"]

        total_planned = sum(s["planned"] for s in cost_sections)
        total_committed = sum(s["committed"] for s in cost_sections)
        total_actual = sum(s["actual"] for s in cost_sections)
        total_variance = total_planned - total_actual
        total_income = sum(s["actual"] for s in income_sections)

        return {
            "title": report_title,
            "company_name": self.env.company.name,
            "currency_symbol": report_currency.symbol,
            "currency_position": report_currency.position,
            "date_from": date_from or "",
            "date_to": date_to or "",
            "grouped_by": "project" if groups is not None else "category",
            "groups": groups,
            "sections": cost_sections,
            "income_sections": income_sections,
            "totals": {
                "planned": total_planned,
                "committed": total_committed,
                "actual": total_actual,
                "variance": total_variance,
                "variance_pct": (total_variance / total_planned * 100.0) if total_planned else 0.0,
                "income": total_income,
                "net_profit": total_income - total_actual,
            },
        }


class ConstructionProjectBudgetLine(models.Model):
    _name = "construction.project.budget.line"
    _description = "Construction Project Budget Line"
    _order = "sequence, id"

    budget_id = fields.Many2one("construction.project.budget", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    category_id = fields.Many2one("construction.budget.category", required=True, ondelete="restrict")
    planned_amount = fields.Monetary(required=True, currency_field="currency_id")
    committed_amount = fields.Monetary(compute="_compute_actual", currency_field="currency_id",
                                        help="Open (not yet billed) amount on purchase orders in this category.")
    actual_amount = fields.Monetary(compute="_compute_actual", currency_field="currency_id")
    remaining_amount = fields.Monetary(compute="_compute_actual", currency_field="currency_id")
    utilization = fields.Float(compute="_compute_actual", string="Used %")
    currency_id = fields.Many2one("res.currency", related="budget_id.currency_id", readonly=True)

    _sql_constraints = [
        ("budget_category_unique", "unique(budget_id, category_id)",
         "This category already has a line in this budget. Edit the existing line instead of adding a new one."),
    ]

    @api.depends("planned_amount", "budget_id.expense_ids.amount", "budget_id.expense_ids.category_id")
    def _compute_actual(self):
        purchase_totals = {}
        if self:
            pos = self.env["purchase.order"].search([
                ("construction_budget_id", "in", self.budget_id.ids),
                ("state", "=", "purchase"),
            ])
            for po in pos:
                key = (po.construction_budget_id.id, po.construction_category_id.id)
                purchase_totals[key] = purchase_totals.get(key, 0.0) + po.committed_amount
        for line in self:
            actual = sum(line.budget_id.expense_ids.filtered(
                lambda e: e.category_id == line.category_id
            ).mapped("amount"))
            line.committed_amount = purchase_totals.get((line.budget_id.id, line.category_id.id), 0.0)
            line.actual_amount = actual
            line.remaining_amount = line.planned_amount - actual
            line.utilization = actual / line.planned_amount * 100.0 if line.planned_amount else 0.0

    def _check_budget_state(self, budget_ids=None):
        if self.env.su:
            return
        budgets = self.env["construction.project.budget"].browse(budget_ids) if budget_ids else self.mapped("budget_id")
        if any(b.is_closed for b in budgets):
            raise UserError(_("You cannot modify budget lines of a closed budget."))

    @api.model_create_multi
    def create(self, vals_list):
        self._check_budget_state({v.get("budget_id") for v in vals_list if v.get("budget_id")})
        return super().create(vals_list)

    def write(self, vals):
        self._check_budget_state()
        return super().write(vals)

    def unlink(self):
        self._check_budget_state()
        return super().unlink()


class ConstructionProjectBudgetExpense(models.Model):
    _name = "construction.project.budget.expense"
    _description = "Construction Project Budget Actual"
    _order = "date desc, id desc"

    name = fields.Char(string="Description", required=True)
    budget_id = fields.Many2one("construction.project.budget", required=True, ondelete="cascade")
    project_id = fields.Many2one("project.project", related="budget_id.project_id", store=True, readonly=True)
    category_id = fields.Many2one("construction.budget.category", required=True, ondelete="restrict")
    amount = fields.Monetary(required=True, currency_field="currency_id")
    date = fields.Date(default=fields.Date.context_today, required=True)
    reference = fields.Char()
    notes = fields.Text()
    currency_id = fields.Many2one("res.currency", related="budget_id.currency_id", readonly=True)

    # Legacy field, kept for the stock-consumption flow and backward compatibility.
    stock_move_id = fields.Many2one("stock.move", string="Source Stock Move", readonly=True, copy=False, index=True)
    product_id = fields.Many2one("product.product", string="Product", readonly=True)
    quantity = fields.Float(readonly=True)
    uom_id = fields.Many2one("uom.uom", string="UoM", readonly=True)

    # Unified cost-source tracking.
    source_type = fields.Selection([
        ("manual", "Manual Expense"),
        ("employee_expense", "Employee Expense"),
        ("vendor_bill", "Vendor Bill"),
        ("customer_invoice", "Customer Invoice"),
        ("journal_entry", "Journal Entry"),
        ("timesheet", "Timesheet"),
        ("labor", "Labor Entry"),
        ("stock_consumption", "Stock Consumption"),
        ("other", "Other"),
    ], default="manual", required=True)
    source_model = fields.Char(readonly=True, help="Technical model of the originating document, if any.")
    source_res_id = fields.Integer(readonly=True, help="Technical id of the originating document, if any.")
    cost_is_estimated = fields.Boolean(
        string="Estimated Cost", default=False,
        help="Set when this amount was estimated from the product's current Cost Price "
             "because no precise accounting valuation was available at posting time "
             "(e.g. manual/periodic inventory valuation). Unset means the amount came "
             "directly from an accounting document or an exact valuation layer.",
    )

    _PROTECTED_FIELDS = {"source_type", "source_model", "source_res_id", "stock_move_id"}

    @api.constrains("amount")
    def _check_amount(self):
        for rec in self:
            if rec.amount == 0:
                raise ValidationError(_("Spending amount cannot be zero."))

    @api.constrains("budget_id", "category_id")
    def _check_category_in_budget(self):
        for rec in self:
            if rec.budget_id and rec.category_id and not rec.budget_id.line_ids.filtered(
                lambda l: l.category_id == rec.category_id
            ):
                raise ValidationError(
                    _("Category '%s' is not configured in this project's budget.")
                    % rec.category_id.display_name
                )

    def _check_budget_state(self):
        if self.env.su:
            return
        if any(b.is_closed for b in self.mapped("budget_id")):
            raise UserError(_("You cannot modify actual spending on a closed budget."))

    def _check_source_protection(self, vals):
        """Only automated (sudo) flows may set/change the technical source-tracking
        fields. A regular user creating or editing an entry by hand can never spoof
        being e.g. a Vendor Bill or Stock Move - that would let them fabricate
        traceable "system" entries or silently detach a real one from its source."""
        if self.env.su:
            return
        if self._PROTECTED_FIELDS & set(vals.keys()):
            raise AccessError(
                _("The source of an Actual Spending entry is set automatically and cannot be "
                  "changed by hand.")
            )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            budget_ids = {v.get("budget_id") for v in vals_list if v.get("budget_id")}
            budgets = self.env["construction.project.budget"].browse(budget_ids)
            if any(b.is_closed for b in budgets):
                raise UserError(_("You cannot add actual spending to a closed budget."))
        for vals in vals_list:
            self._check_source_protection(vals)
        return super().create(vals_list)

    def write(self, vals):
        self._check_budget_state()
        self._check_source_protection(vals)
        return super().write(vals)

    def unlink(self):
        self._check_budget_state()
        if not self.env.su and not self.env.user.has_group(
            "construction_project_budget.group_construction_budget_manager"
        ):
            if any(rec.source_model for rec in self):
                raise AccessError(
                    _("This entry was generated automatically from a source document. "
                      "Cancel/reset that document instead of deleting the entry directly, "
                      "or ask a Construction Budget Manager.")
                )
        return super().unlink()

    def action_open_source(self):
        self.ensure_one()
        if not self.source_model or not self.source_res_id:
            raise UserError(_("This entry has no linked source document."))
        return {
            "type": "ir.actions.act_window",
            "res_model": self.source_model,
            "res_id": self.source_res_id,
            "view_mode": "form",
            "views": [(False, "form")],
            "target": "current",
        }

    @api.model
    def _source_exists(self, source_model, source_res_id):
        """Duplicate-prevention helper: has this source document already been posted?"""
        domain = [("source_model", "=", source_model), ("source_res_id", "=", source_res_id)]
        return bool(self.sudo().search_count(domain))

    @api.model
    def _cron_upgrade_estimated_stock_actuals(self, batch_size=200):
        """If a stock-move Actual was posted as an Estimate (cost_is_estimated=True
        - see stock.py, used when no stock.valuation.layer existed yet at posting
        time, e.g. manual/periodic costing), and a real valuation layer for that
        same move has since appeared, update that same Expense record with the
        now-known exact accounting value instead of ever creating a second one.

        A no-op wherever stock.valuation.layer isn't registered at all (some
        Odoo distributions don't provide it even with stock_account installed) -
        checked at runtime rather than assumed, since a hard model dependency
        declared via _inherit would break installation entirely on such builds.
        """
        if "stock.valuation.layer" not in self.env.registry.models:
            return
        Layer = self.env["stock.valuation.layer"].sudo()
        estimated = self.sudo().search([
            ("source_model", "=", "stock.move"),
            ("cost_is_estimated", "=", True),
        ], limit=batch_size)
        if not estimated:
            return
        move_ids = estimated.mapped("source_res_id")
        layers = Layer.search([("stock_move_id", "in", move_ids)])
        layers_by_move = {}
        for layer in layers:
            move_id = layer.stock_move_id.id
            layers_by_move.setdefault(move_id, Layer.browse())
            layers_by_move[move_id] |= layer
        for expense in estimated:
            move_layers = layers_by_move.get(expense.source_res_id)
            if not move_layers:
                continue
            value = abs(sum(move_layers.mapped("value")))
            if not value:
                continue
            sign = -1 if expense.amount < 0 else 1
            budget = expense.budget_id
            company = move_layers[0].company_id or self.env.company
            company_currency = company.currency_id
            if company_currency and budget.currency_id and company_currency != budget.currency_id:
                value = company_currency._convert(
                    value, budget.currency_id, company,
                    expense.date or fields.Date.context_today(self),
                )
            expense.write({"amount": sign * value, "cost_is_estimated": False})

    _sql_constraints = [
        ("stock_move_budget_unique", "unique(stock_move_id, budget_id)",
         "This stock move has already been posted to this budget."),
    ]
