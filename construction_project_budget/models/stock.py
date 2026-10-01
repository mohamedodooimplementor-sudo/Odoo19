from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError

# Destination location "usage" values that represent material actually leaving the
# company's stock for use on the project: a customer delivery, consumption into a
# manufacturing/production order, or a scrap/inventory-loss write-off.
# Deliberately excluded: 'internal' (plain warehouse-to-warehouse transfer - not a
# cost event), 'supplier' (a return to vendor - the PO/bill side already tracks that
# cost), 'transit' (still in motion, not yet consumed), and 'view' (a virtual folder,
# never a real destination).
CONSUMPTION_LOCATION_USAGES = ("customer", "production", "inventory")


def _expense_exists_for_picking(env, picking):
    """Has any move on this picking already posted an Actual? Used only to
    decide whether editing Project/Budget/Category should be blocked on a
    Done transfer - a Done transfer whose moves were all plain internal
    transfers (no cost event at all) has nothing to protect.
    """
    move_ids = picking.move_ids.ids
    if not move_ids:
        return False
    Expense = env["construction.project.budget.expense"].sudo()
    return bool(Expense.search_count([("source_model", "=", "stock.move"), ("source_res_id", "in", move_ids)]))


class StockPicking(models.Model):
    _inherit = "stock.picking"

    construction_project_id = fields.Many2one("project.project", string="Construction Project", copy=False)
    construction_budget_id = fields.Many2one(
        "construction.project.budget", string="Construction Budget", copy=False,
        domain="[('project_id', '=', construction_project_id)]",
    )
    construction_category_id = fields.Many2one(
        "construction.budget.category", string="Budget Category", copy=False,
        domain="[('id', 'in', available_budget_category_ids)]",
    )
    available_budget_category_ids = fields.Many2many(
        "construction.budget.category", compute="_compute_available_budget_categories",
    )

    @api.depends("construction_budget_id", "construction_budget_id.line_ids.category_id")
    def _compute_available_budget_categories(self):
        for picking in self:
            budget = picking.construction_budget_id
            picking.available_budget_category_ids = budget.line_ids.category_id if budget else False

    @api.constrains("construction_project_id", "construction_budget_id", "construction_category_id")
    def _check_construction_budget_consistency(self):
        for picking in self:
            if picking.construction_budget_id and picking.construction_project_id and (
                picking.construction_budget_id.project_id != picking.construction_project_id
            ):
                raise ValidationError(_(
                    "The selected Construction Budget does not belong to the selected Project."
                ))
            if picking.construction_category_id and picking.construction_budget_id and (
                picking.construction_category_id not in picking.construction_budget_id.line_ids.category_id
            ):
                raise ValidationError(_(
                    "Category '%s' is not configured in the selected budget."
                ) % picking.construction_category_id.display_name)
            if picking.construction_budget_id and picking.construction_budget_id.is_closed and not self.env.su:
                raise ValidationError(_(
                    "Budget '%s' is closed and cannot be selected on a new transfer."
                ) % picking.construction_budget_id.display_name)
            if picking.construction_budget_id and not picking.construction_budget_id.is_approved and not self.env.su:
                raise ValidationError(_(
                    "Budget '%s' hasn't been approved yet (still in stage '%s') and cannot be "
                    "selected on a transfer. Move it to an Approved stage first."
                ) % (picking.construction_budget_id.display_name, picking.construction_budget_id.stage_id.name))
            if picking.construction_budget_id and picking.company_id and (
                picking.construction_budget_id.company_id != picking.company_id
            ):
                raise ValidationError(_(
                    "The selected Construction Budget belongs to a different company than this transfer."
                ))

    def write(self, vals):
        protected = {"construction_project_id", "construction_budget_id", "construction_category_id"}
        if not self.env.su and protected & set(vals.keys()):
            locked = self.filtered(
                lambda p: p.state == "done" and _expense_exists_for_picking(self.env, p)
            )
            if locked:
                raise UserError(_(
                    "The Project/Budget/Category of this validated transfer can no longer be "
                    "changed, since its Actual cost has already been posted."
                ))
        return super().write(vals)

    @api.onchange("construction_project_id")
    def _onchange_construction_project_id(self):
        for picking in self:
            if picking.construction_project_id:
                picking.construction_budget_id = picking.construction_project_id.budget_id
            else:
                picking.construction_budget_id = False

    @api.onchange("construction_budget_id")
    def _onchange_construction_budget_id(self):
        for picking in self:
            if picking.construction_category_id not in picking.available_budget_category_ids:
                picking.construction_category_id = False

    def button_validate(self):
        # Block up front rather than silently validating the transfer with no
        # cost recorded: a budget can be closed *after* a picking was already
        # tagged with it but before that picking is validated, so the
        # save-time constraint above isn't enough on its own.
        if not self.env.su:
            blocked = self.filtered(
                lambda p: p.construction_budget_id
                and p.construction_budget_id.is_closed
                and p.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
            )
            if blocked:
                raise UserError(_(
                    "'%(picking)s' is tagged with Construction Budget '%(budget)s', which is now "
                    "closed. Remove the Construction Budget/Category from this transfer, or reopen "
                    "the budget, before validating."
                ) % {"picking": blocked[0].name, "budget": blocked[0].construction_budget_id.display_name})
            not_approved = self.filtered(
                lambda p: p.construction_budget_id
                and not p.construction_budget_id.is_approved
                and p.move_ids.filtered(lambda m: m.state not in ("done", "cancel"))
            )
            if not_approved:
                raise UserError(_(
                    "'%(picking)s' is tagged with Construction Budget '%(budget)s', which hasn't "
                    "been approved yet (still in stage '%(stage)s'). Remove the Construction "
                    "Budget/Category from this transfer, or move the budget to an Approved stage, "
                    "before validating."
                ) % {
                    "picking": not_approved[0].name,
                    "budget": not_approved[0].construction_budget_id.display_name,
                    "stage": not_approved[0].construction_budget_id.stage_id.name,
                })
        res = super().button_validate()
        self.filtered(
            lambda p: p.state == "done" and p.construction_budget_id
        )._create_budget_actuals_for_done_moves()
        return res

    @staticmethod
    def _get_done_qty(move):
        """Return the actually-moved quantity, whatever this Odoo build calls it.

        The field that carries the done quantity on stock.move has changed
        name across versions (quantity_done -> quantity). Rather than assume
        one, check what's actually declared on the model.
        """
        for fname in ("quantity", "quantity_done", "product_qty"):
            if fname in move._fields:
                qty = move[fname]
                if qty:
                    return abs(qty)
        return abs(move.product_uom_qty)

    def _create_budget_actuals_for_done_moves(self):
        """Post a Budget Actual entry for material consumed on the project, and
        for material *returned* from the project back to company stock (which
        reduces spending rather than adding to it).

        A move counts as "consumption" only if its destination location usage is
        one of CONSUMPTION_LOCATION_USAGES (see comment above) - a plain internal
        transfer between two of the company's own stock locations is NOT a cost
        event and is correctly ignored, even though it's part of a picking that
        is tagged with a project/budget. A move going the other way (FROM a
        consumption location back to internal stock) is treated as a return and
        posts a *negative* Actual, netting the original cost down.

        This does NOT require perpetual/automated inventory valuation. If
        real-time valuation IS configured and stock.valuation.layer records
        exist for the move, we use their exact accounting value (marked as
        NOT estimated). Otherwise (manual/periodic valuation) we value the
        quantity at the product's current Cost Price (standard_price) instead,
        and flag the entry as an estimate (cost_is_estimated=True) so nobody
        mistakes it for an exact accounting figure. Known limitation: if an
        exact accounting value later becomes available for that same move
        (e.g. a delayed valuation run), this module has no mechanism to
        retroactively upgrade the already-posted estimate - it only ever posts
        once per move (see the duplicate-prevention check below), by design,
        to guarantee no double-count.
        """
        Expense = self.env["construction.project.budget.expense"].sudo()
        # Some Odoo distributions install "stock_account" as a dependency shell
        # without actually registering stock.valuation.layer. Never assume it
        # exists - check the registry first and simply skip straight to the
        # standard_price fallback below when it doesn't.
        has_valuation_layers = "stock.valuation.layer" in self.env.registry.models
        Layer = self.env["stock.valuation.layer"].sudo() if has_valuation_layers else None
        AccountMove = self.env["account.move"].sudo()
        material_category = self.env.ref(
            "construction_project_budget.category_materials", raise_if_not_found=False
        )
        for picking in self:
            budget = picking.construction_budget_id
            if not budget or budget.is_closed or not budget.is_approved:
                continue
            category = picking.construction_category_id or material_category
            if not category or category not in budget.line_ids.category_id:
                continue

            consumption_moves = picking.move_ids.filtered(
                lambda m: m.state == "done" and m.location_dest_id.usage in CONSUMPTION_LOCATION_USAGES
            )
            return_moves = picking.move_ids.filtered(
                lambda m: m.state == "done"
                and m.location_id.usage in CONSUMPTION_LOCATION_USAGES
                and m.location_dest_id.usage not in CONSUMPTION_LOCATION_USAGES
            )
            moves = consumption_moves | return_moves
            if not moves:
                continue

            # Make sure any pending write from Odoo core's own valuation-posting
            # step (e.g. linking a stock.valuation.layer to the accounting entry
            # it just created) is actually visible before we search for it below -
            # otherwise a same-transaction ORM cache/ordering gap can make that
            # link look empty even though the entry was posted successfully.
            self.env.flush_all()

            picking_valuation_accounts = moves.mapped("product_id.categ_id.property_stock_valuation_account_id")

            for move in consumption_moves:
                self._post_stock_move_actual(Expense, Layer, budget, category, picking, move, sign=1)
            for move in return_moves:
                self._post_stock_move_actual(
                    Expense, Layer, budget, category, picking, move, sign=-1,
                    name=_("Material return - %s") % move.product_id.display_name,
                )

            valuation_moves = AccountMove.browse()
            if Layer is not None:
                layers = Layer.search([("stock_move_id", "in", moves.ids)])
                valuation_moves = layers.mapped("account_move_id")
            if not valuation_moves:
                valuation_moves = self._find_valuation_moves_fallback(picking, picking_valuation_accounts)

            if valuation_moves:
                self._tag_valuation_move_with_budget(valuation_moves, picking, budget, category)
                self._apply_budget_analytic_to_valuation_move(valuation_moves, budget, picking_valuation_accounts)

    def _post_stock_move_actual(self, Expense, Layer, budget, category, picking, move, sign=1, name=None):
        """Create the Actual entry for a single stock move, if it hasn't been
        posted already. sign=-1 posts a negative amount (a return, reducing
        the net Actual for this budget/category instead of adding to it).

        Race-condition safe: a concurrent validation of the same move is
        caught via the DB-level unique(stock_move_id, budget_id) constraint
        (see project_budget.py) rather than trusting the pre-check alone,
        which has an unavoidable gap between "check" and "create" under
        concurrent requests. A savepoint keeps that failure from aborting the
        whole transaction.
        """
        if Expense._source_exists("stock.move", move.id):
            return None

        qty = self._get_done_qty(move)
        if not qty:
            return None

        out_layers = Layer.search([("stock_move_id", "=", move.id)]) if Layer is not None else Layer
        value_in_budget_currency = False
        if out_layers:
            value = abs(sum(out_layers.mapped("value")))
            is_estimated = False
        elif sign == -1:
            # Return, and no valuation layer of its own to price it from: use
            # the unit cost this module actually recorded when the material
            # was originally consumed (amount / quantity of the most recent
            # matching consumption on this budget), not today's standard_price
            # - the cost may have changed since, and the whole point of a
            # return is to reverse the *original* cost, not re-price it.
            original = Expense.search([
                ("budget_id", "=", budget.id),
                ("product_id", "=", move.product_id.id),
                ("source_type", "=", "stock_consumption"),
                ("quantity", ">", 0),
            ], order="date desc, id desc", limit=1)
            if original and original.quantity:
                # original.amount is already expressed in the budget's own
                # currency (see currency_field on the Expense model) - it must
                # NOT go through the company->budget conversion below a second
                # time.
                value = qty * abs(original.amount / original.quantity)
                is_estimated = original.cost_is_estimated
                value_in_budget_currency = True
            else:
                value = qty * (move.product_id.standard_price or 0.0)
                is_estimated = True
        else:
            value = qty * (move.product_id.standard_price or 0.0)
            is_estimated = True

        if not value:
            return None

        # Stock valuation is always kept in company currency; convert to the
        # budget's own currency if they differ (multi-currency companies).
        # Skipped when the value was already derived in budget currency above.
        if not value_in_budget_currency:
            company_currency = move.company_id.currency_id
            if company_currency and budget.currency_id and company_currency != budget.currency_id:
                value = company_currency._convert(
                    value, budget.currency_id, move.company_id,
                    fields.Date.to_date(picking.date_done or fields.Datetime.now()),
                )

        vals = {
            "name": name or _("Material consumption - %s") % move.product_id.display_name,
            "budget_id": budget.id,
            "category_id": category.id,
            "amount": sign * value,
            "date": fields.Date.to_date(picking.date_done or fields.Datetime.now()),
            "reference": picking.name,
            "stock_move_id": move.id,
            "product_id": move.product_id.id,
            "quantity": sign * qty,
            "uom_id": move.product_id.uom_id.id,
            "source_type": "stock_consumption",
            "source_model": "stock.move",
            "source_res_id": move.id,
            "cost_is_estimated": is_estimated,
        }
        try:
            with self.env.cr.savepoint():
                return Expense.create(vals)
        except Exception as exc:
            # A concurrent validation of the very same move already won the
            # race and created this Actual first (unique(stock_move_id,
            # budget_id) constraint) - that's success, not a failure, so don't
            # surface a raw DB error to the user.
            if "stock_move_budget_unique" in str(exc) or "duplicate key" in str(exc).lower():
                return None
            raise

    def _find_valuation_moves_fallback(self, picking, valuation_accounts):
        """Last-resort, timing-independent lookup for this picking's Stock
        Valuation journal entry(ies), used only when the direct
        stock.valuation.layer.account_move_id relationship yielded nothing.

        Matching purely on ref == picking.name would be unsafe on its own (two
        different documents could in principle share a ref), so a candidate is
        only accepted if it also structurally looks like this picking's
        valuation entry: same company, not yet claimed by a *different*
        budget, and at least one of its lines uses one of this picking's own
        products' Stock Valuation accounts (the one thing a coincidentally
        same-ref, unrelated entry would essentially never share).
        """
        candidates = self.env["account.move"].sudo().search([
            ("ref", "=", picking.name),
            ("move_type", "=", "entry"),
            ("company_id", "=", picking.company_id.id),
        ])
        if not candidates:
            return candidates
        candidates = candidates.filtered(
            lambda m: not m.construction_budget_id or m.construction_budget_id == picking.construction_budget_id
        )
        if valuation_accounts:
            candidates = candidates.filtered(
                lambda m: bool(set(m.line_ids.account_id.ids) & set(valuation_accounts.ids))
            )
        return candidates

    @staticmethod
    def _tag_valuation_move_with_budget(moves, picking, budget, category):
        """The perpetual/automated inventory valuation entry (posted by Odoo core's
        stock_account, separate from anything this module creates) doesn't carry any
        Project/Budget/Category on its own header - only the line-level analytic
        account is set (see _apply_budget_analytic_to_valuation_move). Tag the header
        too, mirroring the picking's own Project/Budget/Category, so the entry shows
        up correctly under the budget's "Journal Entries" smart button and its form.
        skip_budget_actual_post=True so a later action_post() on it (e.g. after a
        manual Reset to Draft + re-post) doesn't also create a second, duplicate
        Actual entry.

        Note this deliberately never sets construction_budget_expense_id: a
        combined valuation entry can represent several stock moves (several
        Expense records) at once, so there is no single Expense to point at.
        The source of truth for a material Actual is always the stock.move
        itself (source_model/source_res_id/stock_move_id on the Expense
        record), never this accounting entry - see also
        account_move.py:_remove_budget_actual, which deliberately never
        touches stock-move-sourced Actuals for the same reason.
        """
        if not moves:
            return
        moves.write({
            "project_id": picking.construction_project_id.id,
            "construction_budget_id": budget.id,
            "construction_category_id": category.id,
            "skip_budget_actual_post": True,
        })

    @staticmethod
    def _apply_budget_analytic_to_valuation_move(moves, budget, valuation_accounts):
        """Perpetual/automated inventory valuation posts its own accounting entry
        for the consumption - separate from, and earlier than, anything this
        module creates. That entry's lines never carry an analytic account on
        their own, so tag its cost-side line(s) with the budget's analytic
        account here.

        Which line is "the cost side" is found deterministically - it's whatever
        account on the move is NOT one of the consumed products' own Stock
        Valuation accounts - rather than guessing at an account_type value,
        since that enum's exact keys vary across Chart of Account templates/
        localizations and a filter that doesn't match one just silently tags
        nothing. A line that already has an analytic distribution (set by hand,
        or by an earlier run) is never overwritten.
        """
        analytic_account = budget.analytic_account_id
        if not analytic_account or not moves:
            return
        target_lines = moves.line_ids.filtered(
            lambda l: l.account_id not in valuation_accounts
            and l.display_type not in ("line_section", "line_note")
            and not l.analytic_distribution
        )
        if target_lines:
            target_lines.write({"analytic_distribution": {str(analytic_account.id): 100}})
            return
        target_lines = moves.line_ids.filtered(
            lambda l: l.account_id.account_type in ("expense", "expense_direct_cost")
            and not l.analytic_distribution
        )
        if target_lines:
            target_lines.write({"analytic_distribution": {str(analytic_account.id): 100}})
