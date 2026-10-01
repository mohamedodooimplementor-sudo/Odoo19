from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    project_id = fields.Many2one("project.project", string="Project", copy=False,
                                  domain="[('company_id', '=', company_id)]")
    construction_budget_id = fields.Many2one(
        "construction.project.budget", string="Construction Budget", copy=False,
        domain="[('project_id', '=', project_id)]",
    )
    construction_category_id = fields.Many2one(
        "construction.budget.category", string="Budget Category", copy=False,
        domain="[('id', 'in', available_budget_category_ids)]",
    )
    available_budget_category_ids = fields.Many2many(
        "construction.budget.category", compute="_compute_available_budget_categories",
    )
    construction_budget_expense_id = fields.Many2one(
        "construction.project.budget.expense", string="Budget Actual Entry", copy=False, readonly=True,
    )
    skip_budget_actual_post = fields.Boolean(
        default=False, copy=False,
        help="Technical flag: when set, posting this entry will not create a second Budget "
             "Actual entry, because one was already posted by another flow (e.g. a Manual "
             "Expense) that generated this journal entry itself.",
    )

    @api.depends("construction_budget_id", "construction_budget_id.line_ids.category_id", "move_type")
    def _compute_available_budget_categories(self):
        for move in self:
            budget = move.construction_budget_id
            categories = budget.line_ids.category_id if budget else self.env["construction.budget.category"]
            if move.move_type == "out_invoice":
                categories = categories.filtered(lambda c: c.type == "income")
            elif move.move_type == "in_invoice":
                categories = categories.filtered(lambda c: c.type == "cost")
            move.available_budget_category_ids = categories

    @api.constrains("project_id", "construction_budget_id", "construction_category_id")
    def _check_construction_budget_consistency(self):
        for move in self:
            if move.construction_budget_id and move.project_id and (
                move.construction_budget_id.project_id != move.project_id
            ):
                raise ValidationError(_(
                    "The selected Construction Budget does not belong to the selected Project."
                ))
            if move.construction_category_id and move.construction_budget_id and (
                move.construction_category_id not in move.construction_budget_id.line_ids.category_id
            ):
                raise ValidationError(_(
                    "Category '%s' is not configured in the selected budget."
                ) % move.construction_category_id.display_name)
            if move.construction_category_id and not move.construction_budget_id:
                raise ValidationError(_("Select a Construction Budget before choosing a Budget Category."))
            if move.construction_category_id and move.move_type == "out_invoice" and move.construction_category_id.type != "income":
                raise ValidationError(_(
                    "On a Customer Invoice, only an Income category can be selected - '%s' is a "
                    "Cost category."
                ) % move.construction_category_id.display_name)
            if move.construction_category_id and move.move_type == "in_invoice" and move.construction_category_id.type != "cost":
                raise ValidationError(_(
                    "On a Vendor Bill, only a Cost category can be selected - '%s' is an Income "
                    "category."
                ) % move.construction_category_id.display_name)
            if move.construction_budget_id and move.construction_budget_id.is_closed and not self.env.su:
                raise ValidationError(_(
                    "Budget '%s' is closed and cannot be selected on a new document."
                ) % move.construction_budget_id.display_name)
            if move.construction_budget_id and not move.construction_budget_id.is_approved and not self.env.su:
                raise ValidationError(_(
                    "Budget '%s' hasn't been approved yet (still in stage '%s') and cannot "
                    "receive new spending. Move it to an Approved stage first."
                ) % (move.construction_budget_id.display_name, move.construction_budget_id.stage_id.name))
            if move.construction_budget_id and move.company_id and (
                move.construction_budget_id.company_id != move.company_id
            ):
                raise ValidationError(_(
                    "The selected Construction Budget belongs to a different company than this document."
                ))

    def write(self, vals):
        protected = {"project_id", "construction_budget_id", "construction_category_id"}
        if not self.env.su and protected & set(vals.keys()):
            locked = self.filtered(lambda m: m.state == "posted" and m.construction_budget_expense_id)
            if locked:
                raise UserError(_(
                    "The Project/Budget/Category of a posted entry that already has an Actual "
                    "Spending entry can no longer be changed. Reset to Draft first if this was "
                    "set up wrong - that will remove the old Actual entry."
                ))
        return super().write(vals)

    @api.onchange("project_id")
    def _onchange_construction_project_id(self):
        for move in self:
            if move.project_id:
                move.construction_budget_id = move.project_id.budget_id
            else:
                move.construction_budget_id = False

    @api.onchange("construction_budget_id")
    def _onchange_construction_budget_id(self):
        for move in self:
            if move.construction_category_id not in move.available_budget_category_ids:
                move.construction_category_id = False
            move._apply_construction_budget_analytic_account()

    def _apply_construction_budget_analytic_account(self):
        """Push the budget's analytic account down to the eligible move lines, so
        that choosing a Construction Budget on a Vendor Bill or a plain Journal
        Entry also tags its lines analytically - without overwriting a line where
        the user already picked an analytic distribution by hand.
        """
        for move in self:
            analytic_account = move.construction_budget_id.analytic_account_id
            if not analytic_account:
                continue
            for line in move._get_construction_budget_analytic_target_lines():
                if line.analytic_distribution:
                    continue
                line.analytic_distribution = {str(analytic_account.id): 100}

    def _get_construction_budget_analytic_target_lines(self):
        self.ensure_one()
        if self.is_invoice(include_receipts=True):
            lines = self.invoice_line_ids
            return lines.filtered(
                lambda l: l.display_type not in ("line_section", "line_note")
                and l.account_id.account_type not in ("asset_receivable", "liability_payable")
            )
        # Plain journal entry (e.g. one generated by a Manual Expense or Labor
        # Cost entry): "Debit Expense 11,000 / Credit Cash 11,000" should only
        # tag the Expense line, not the Cash counterpart - so pick only the
        # side that matches the budget category's direction (Cost -> debit,
        # Income -> credit) instead of every non-receivable/payable line.
        category_type = self.construction_category_id.type if self.construction_category_id else "cost"
        lines = self.line_ids.filtered(lambda l: l.display_type not in ("line_section", "line_note"))
        if category_type == "income":
            return lines.filtered(lambda l: l.credit > 0)
        return lines.filtered(lambda l: l.debit > 0)

    def action_post(self):
        # Safety net: guarantee the analytic account is on the lines at posting time,
        # regardless of whether the header onchange fired (e.g. fields set through code,
        # an import, or a UI edit path that skipped it).
        self.filtered(lambda m: m.construction_budget_id)._apply_construction_budget_analytic_account()
        res = super().action_post()
        candidates = self.filtered(
            lambda m: m.move_type in ("in_invoice", "entry", "out_invoice")
            and m.construction_budget_id
            and not m.skip_budget_actual_post
        )
        # Belt-and-braces: never post a second Actual for a Stock Valuation entry,
        # even if skip_budget_actual_post somehow wasn't set on it (e.g. a timing
        # gap between when Odoo core creates/posts the valuation entry and when
        # stock.py gets a chance to tag it). This check doesn't depend on that
        # flag at all - it looks at the actual, structural relationship Odoo core
        # itself uses (stock.valuation.layer.account_move_id), so it's correct
        # regardless of when/whether the tagging write landed.
        candidates -= candidates._filter_stock_valuation_moves()
        candidates._post_budget_actual()
        self.filtered(
            lambda m: m.move_type in ("in_refund", "out_refund")
        )._apply_credit_note_to_budget_actual()
        return res

    def _filter_stock_valuation_moves(self):
        """Return the subset of self that are Stock Valuation accounting entries
        (i.e. some stock.valuation.layer points at them as its account_move_id).
        These represent the accounting side of a material consumption whose
        Actual was already posted from the stock.move itself (see stock.py) -
        they must never separately go through _post_budget_actual(), or the
        same cost would be counted twice.
        """
        if not self or "stock.valuation.layer" not in self.env.registry.models:
            return self.browse()
        linked_move_ids = self.env["stock.valuation.layer"].sudo().search(
            [("account_move_id", "in", self.ids)]
        ).account_move_id.ids
        return self.filtered(lambda m: m.id in linked_move_ids)

    def _post_budget_actual(self):
        Expense = self.env["construction.project.budget.expense"].sudo()
        # Defense in depth: even if this method is ever called directly (bypassing
        # the filtering already done in action_post above), never double-count a
        # Stock Valuation entry.
        stock_valuation_moves = self._filter_stock_valuation_moves()
        for move in self:
            if move in stock_valuation_moves:
                continue
            budget = move.construction_budget_id
            if not budget or budget.is_closed or not budget.is_approved:
                continue
            category = move.construction_category_id
            if not category or category not in budget.line_ids.category_id:
                continue
            if Expense._source_exists("account.move", move.id):
                continue

            if move.move_type == "entry":
                # A miscellaneous journal entry has no invoice amount; its debit
                # total (always equal to its credit total on a balanced entry)
                # is the real amount being charged to the project. This assumes
                # the whole entry is the project cost - if it mixes unrelated
                # accounts, tag only the relevant lines by splitting the entry.
                amount_company_currency = sum(move.line_ids.mapped("debit"))
                amount = amount_company_currency  # already in company currency
                label = _("Journal Entry - %s") % (move.name or move.ref or "")
                source_type = "journal_entry"
            elif move.move_type == "out_invoice":
                amount_move_currency = abs(move.amount_untaxed_signed) or abs(move.amount_untaxed)
                if move.currency_id and move.currency_id != budget.currency_id:
                    amount = move.currency_id._convert(
                        amount_move_currency, budget.currency_id, move.company_id,
                        move.invoice_date or fields.Date.context_today(move),
                    )
                else:
                    amount = amount_move_currency
                label = _("Customer Invoice - %s") % (move.name or move.ref or "")
                source_type = "customer_invoice"
            else:
                amount_move_currency = abs(move.amount_untaxed_signed) or abs(move.amount_untaxed)
                if move.currency_id and move.currency_id != budget.currency_id:
                    amount = move.currency_id._convert(
                        amount_move_currency, budget.currency_id, move.company_id,
                        move.invoice_date or fields.Date.context_today(move),
                    )
                else:
                    amount = amount_move_currency
                label = _("Vendor Bill - %s") % (move.name or move.ref or "")
                source_type = "vendor_bill"

            if not amount:
                continue
            expense = Expense.create({
                "name": label,
                "budget_id": budget.id,
                "category_id": category.id,
                "amount": amount,
                "date": move.invoice_date or move.date or fields.Date.context_today(move),
                "reference": move.name,
                "source_type": source_type,
                "source_model": "account.move",
                "source_res_id": move.id,
            })
            move.construction_budget_expense_id = expense.id

    def _apply_credit_note_to_budget_actual(self):
        """A credit note against a bill that already posted an Actual should reduce
        that Actual rather than being ignored or counted as a second positive cost.
        Full credit -> the original Actual is removed. Partial credit -> reduced.
        This only handles credit notes created through Odoo's own "Reversal" (which
        sets reversed_entry_id) - a credit note not linked to the original bill has
        no way to know which Actual it should offset, and is left untouched.
        """
        for credit_note in self:
            origin = credit_note.reversed_entry_id
            if not origin or not origin.construction_budget_expense_id:
                continue
            expense = origin.construction_budget_expense_id.sudo()
            if expense.budget_id.is_closed:
                continue
            credit_amount_move_currency = abs(credit_note.amount_untaxed_signed) or abs(credit_note.amount_untaxed)
            if credit_note.currency_id and credit_note.currency_id != expense.currency_id:
                credit_amount = credit_note.currency_id._convert(
                    credit_amount_move_currency, expense.currency_id, credit_note.company_id,
                    credit_note.invoice_date or fields.Date.context_today(credit_note),
                )
            else:
                credit_amount = credit_amount_move_currency

            new_amount = expense.amount - credit_amount
            if new_amount <= 0:
                origin.sudo().construction_budget_expense_id = False
                expense.unlink()
            else:
                expense.write({
                    "amount": new_amount,
                    "notes": (expense.notes or "") + _(
                        "\nReduced by %(amount)s following Credit Note %(name)s."
                    ) % {"amount": credit_amount, "name": credit_note.name},
                })

    def button_draft(self):
        res = super().button_draft()
        self._remove_budget_actual()
        return res

    def button_cancel(self):
        res = super().button_cancel()
        self._remove_budget_actual()
        return res

    def _remove_budget_actual(self):
        """Un-posting or cancelling a bill must not leave an orphaned Actual entry.

        If this entry was itself auto-generated by our own Manual Expense / Labor
        Cost flows (see skip_budget_actual_post), that source document is reset to
        Draft too, so it doesn't stay "Confirmed" while pointing at a Draft/Cancelled
        journal entry. Only those two models are touched this way - they're the
        only sources whose write contract (state/move_id/budget_expense_id) this
        code assumes. A stock.move (material consumption) can also be the source of
        a tagged valuation entry, but resetting a *done* stock move's state here
        would be meaningless/unsafe, so it's deliberately left alone.
        """
        RESETTABLE_SOURCE_MODELS = ("construction.project.expense", "construction.labor.cost")
        for move in self:
            expense = move.construction_budget_expense_id
            if expense and not expense.budget_id.is_closed:
                move.construction_budget_expense_id = False
                source_model, source_res_id = expense.source_model, expense.source_res_id
                expense.sudo().unlink()
                if move.skip_budget_actual_post and source_model in RESETTABLE_SOURCE_MODELS and source_res_id:
                    source = self.env[source_model].sudo().browse(source_res_id)
                    if source.exists():
                        source.write({"state": "draft", "move_id": False, "budget_expense_id": False})


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._apply_construction_budget_analytic_default()
        return lines

    def _apply_construction_budget_analytic_default(self):
        """Cover lines added after the header's Construction Budget was already
        chosen (e.g. new rows typed straight into a Journal Entry's editable
        grid), where the header onchange above never fires. A line the user has
        already given its own analytic distribution is left untouched.
        """
        for line in self:
            if line.analytic_distribution:
                continue
            if line.display_type in ("line_section", "line_note"):
                continue
            move = line.move_id
            budget = move.construction_budget_id
            analytic_account = budget.analytic_account_id if budget else False
            if not analytic_account:
                continue
            if move.is_invoice(include_receipts=True):
                if line.account_id.account_type in ("asset_receivable", "liability_payable"):
                    continue
            else:
                # Plain journal entry: only the side matching the budget
                # category's direction is the cost/income line - the other
                # side (e.g. the Cash counterpart of a Manual Expense entry)
                # must not get tagged. See _get_construction_budget_analytic_target_lines.
                category_type = move.construction_category_id.type if move.construction_category_id else "cost"
                if category_type == "income":
                    if not line.credit:
                        continue
                elif not line.debit:
                    continue
            line.analytic_distribution = {str(analytic_account.id): 100}
