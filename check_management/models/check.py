from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

CHECK_STATES = [
    ("draft", "Draft"),
    ("received", "Received"),
    ("deposited", "Deposited"),
    ("under_collection", "Under Collection"),
    ("collected", "Collected"),
    ("handed_over", "Handed Over"),
    ("cleared", "Cleared"),
    ("bounced", "Bounced"),
    ("cancelled", "Cancelled"),
]
# A check is "open" while money is still expected to move for it.
OPEN_STATES = ("draft", "received", "deposited", "under_collection", "handed_over")
CLOSED_STATES = ("collected", "cleared", "bounced", "cancelled")
PARTNER_ACCOUNT_TYPES = ("asset_receivable", "liability_payable")

# One numbering sequence per direction: incoming (income) and outgoing (out).
SEQUENCE_CODES = {
    "incoming": "check.management.incoming",
    "outgoing": "check.management.outgoing",
}
LEGACY_SEQUENCE_CODE = "check.management"  # single sequence used before v4, kept as fallback

# Columns shown in the kanban view for each check type.
KANBAN_STATES = {
    "incoming": ["draft", "received", "deposited", "under_collection", "collected", "bounced", "cancelled"],
    "outgoing": ["draft", "handed_over", "cleared", "bounced", "cancelled"],
}


class CheckBank(models.Model):
    _name = "check.bank"
    _description = "Check Bank"
    _order = "name"
    _check_company_auto = True
    _rec_names_search = ["name", "account_number", "code"]

    name = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    code = fields.Char(index=True)
    bic = fields.Char(string="BIC")
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True, index=True
    )
    journal_id = fields.Many2one(
        "account.journal", string="Bank Journal", check_company=True, index="btree_not_null",
        domain="[('company_id', '=', company_id), ('type', '=', 'bank')]",
        help="Journal of this bank. It is filled automatically on every check that uses this bank "
             "and receives the accounting entries when the check is collected / cleared.",
    )
    account_number = fields.Char(
        string="Account Number", compute="_compute_account_number", store=True,
        readonly=False, precompute=True, index=True,
        help="Taken from the bank account of the journal when it has one; can be typed / edited manually.",
    )
    notes = fields.Text()

    _name_company_uniq = models.Constraint(
        "UNIQUE (name, company_id)",
        "Bank name must be unique per company. Use a different name for each account "
        "(for example 'NBE - EGP' and 'NBE - USD').",
    )
    _journal_company_uniq = models.Constraint(
        "UNIQUE (journal_id, company_id)",
        "This Bank Journal is already used by another Bank record in this company. "
        "Each journal should be linked to a single Bank so its account number is unambiguous.",
    )

    @api.depends("journal_id")
    def _compute_account_number(self):
        for bank in self:
            # sudo: the user may lack accounting rights, the journal is only read to copy the number
            journal_number = bank.journal_id.sudo().bank_account_id.acc_number
            bank.account_number = journal_number or bank.account_number

    @api.depends("name", "account_number")
    def _compute_display_name(self):
        for bank in self:
            bank.display_name = (
                "%s - %s" % (bank.name, bank.account_number) if bank.account_number else (bank.name or "")
            )


class CheckMovement(models.Model):
    _name = "check.movement"
    _description = "Check Movement"
    _order = "date desc, id desc"

    check_id = fields.Many2one("check.management", required=True, ondelete="cascade", index=True)
    date = fields.Datetime(default=fields.Datetime.now, required=True)
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)
    state = fields.Selection(related="check_id.state", string="Current Status", readonly=True)
    state_at_movement = fields.Selection(CHECK_STATES, string="Status", required=True)
    note = fields.Text()


class CheckManagement(models.Model):
    _name = "check.management"
    _description = "Check"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "due_date asc, id desc"
    _check_company_auto = True

    # Fields that cannot change once accounting entries exist for the check.
    LOCKED_FIELDS = {"amount", "partner_id", "check_type", "currency_id", "company_id", "invoice_ids"}
    # Narrower, state-based locks (enforced in write(), mirrored by readonly attrs in the form view).
    CHECK_NUMBER_LOCKED_FIELDS = {"check_number"}
    BANK_LOCKED_FIELDS = {"bank_id", "journal_id", "bank_account"}
    DATE_LOCKED_FIELDS = {"due_date", "issue_date"}

    name = fields.Char(string="Check Reference", required=True, copy=False, readonly=True, default=lambda self: _("New"))
    check_number = fields.Char(string="Check Number", required=True, tracking=True, index=True)
    check_type = fields.Selection(
        [("incoming", "Incoming"), ("outgoing", "Outgoing")],
        string="Type", required=True, default="incoming", tracking=True
    )
    partner_id = fields.Many2one("res.partner", string="Partner", required=True, tracking=True, index=True)
    bank_id = fields.Many2one("check.bank", string="Bank", tracking=True, check_company=True)
    bank_account = fields.Char(
        string="Account Number", compute="_compute_bank_details", store=True, readonly=False, precompute=True,
        help="Filled from the selected bank; can be edited manually.",
    )
    issue_date = fields.Date(string="Issue Date", default=fields.Date.context_today, required=True, tracking=True)
    due_date = fields.Date(string="Due Date", required=True, tracking=True, index=True)
    amount = fields.Monetary(string="Amount", required=True, tracking=True)
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, required=True
    )
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, required=True, index=True
    )
    journal_id = fields.Many2one(
        "account.journal", string="Bank Journal",
        compute="_compute_bank_details", store=True, readonly=False, precompute=True,
        domain="[('company_id', '=', company_id), ('type', 'in', ('bank', 'cash'))]",
        tracking=True,
        help="Filled from the selected bank. Bank used when the check is collected (incoming) "
             "or cleared (outgoing).",
    )
    move_ids = fields.One2many("account.move", "check_id", string="Journal Entries", readonly=True)
    invoice_ids = fields.Many2many(
        "account.move", "check_invoice_rel", "check_id", "move_id", string="Invoices",
        domain="[('company_id', '=', company_id), ('state', '=', 'posted')]",
        help="Invoices (customer invoices for incoming checks, vendor bills for outgoing "
             "checks) settled by this check. They are reconciled when the check is "
             "received / handed over."
    )
    bounce_fee = fields.Monetary(
        string="Bank Charges", currency_field="currency_id",
        help="Fee charged by the bank when an incoming check bounces after being deposited.",
    )
    state = fields.Selection(
        CHECK_STATES, string="Status", default="draft", required=True, tracking=True, index=True,
        group_expand="_expand_state_groups",
    )
    # Same value as `state`: lets the form show a different statusbar for outgoing checks.
    state_outgoing = fields.Selection(related="state", string="Status (outgoing)")
    notes = fields.Text()
    active = fields.Boolean(default=True)
    payee_name = fields.Char(
        string="Payee (as printed)", compute="_compute_payee_name", store=True, readonly=False,
        help="Name printed after 'Pay to' on the check. Defaults to the partner name.",
    )
    print_template_id = fields.Many2one(
        "check.print.template", string="Print Template", check_company=True,
        help="Layout used to print the check. If empty, the template of the bank (or a generic one) is used.",
    )
    print_count = fields.Integer(string="Times Printed", copy=False, readonly=True)
    last_print_date = fields.Datetime(string="Last Printed", copy=False, readonly=True)
    movement_ids = fields.One2many("check.movement", "check_id", string="Movements", readonly=True)
    movement_count = fields.Integer(compute="_compute_counts")
    invoice_count = fields.Integer(compute="_compute_counts")
    move_count = fields.Integer(compute="_compute_counts")
    is_overdue = fields.Boolean(compute="_compute_due_flags", search="_search_is_overdue")
    is_due_today = fields.Boolean(compute="_compute_due_flags", search="_search_is_due_today")
    days_to_due = fields.Integer(compute="_compute_due_flags")
    color = fields.Integer(compute="_compute_color")

    _check_number_company_uniq = models.Constraint(
        "UNIQUE (check_number, company_id)", "Check number must be unique per company."
    )

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model
    def _expand_state_groups(self, values, domain):
        """Kanban: always show the columns that make sense for the check type."""
        check_type = self.env.context.get("default_check_type")
        wanted = KANBAN_STATES.get(check_type) or [s for s, _label in CHECK_STATES]
        return wanted + [v for v in values if v not in wanted]

    @api.model
    def _ensure_company_sequence(self, code, company_id):
        """Make sure `code` has its own numbering for `company_id`.

        The data file only ships one global sequence per code (company_id=False),
        shared by every company. That is fine for a single-company database, but in
        multi-company it means all companies count off the same running number
        (company A's 6th check picks up right after company B's 5th). ir.sequence
        already prefers a company-specific row over the global one when both exist
        (next_by_code filters on company_id in [False, current company], company
        row first), so creating that row once per company is all that's needed —
        mirrors how check.config auto-creates its settings record per company.
        """
        Sequence = self.env["ir.sequence"].sudo()
        if Sequence.search_count([("code", "=", code), ("company_id", "=", company_id)]):
            return
        template = Sequence.search([("code", "=", code), ("company_id", "=", False)], limit=1)
        Sequence.create({
            "name": "%s (%s)" % (template.name or code, self.env["res.company"].browse(company_id).name),
            "code": code,
            "prefix": template.prefix or "",
            "padding": template.padding or 5,
            "company_id": company_id,
        })

    @api.model
    def _next_reference(self, check_type, company_id=None):
        """Next number of the sequence of this direction (incoming / outgoing)."""
        company_id = company_id or self.env.company.id
        code = SEQUENCE_CODES.get(check_type, SEQUENCE_CODES["incoming"])
        self._ensure_company_sequence(code, company_id)
        sequence = self.env["ir.sequence"].with_company(company_id)
        return (
            sequence.next_by_code(code)
            or sequence.next_by_code(LEGACY_SEQUENCE_CODE)
            or _("New")
        )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                check_type = vals.get("check_type") or self.env.context.get("default_check_type") or "incoming"
                vals["name"] = self._next_reference(check_type, vals.get("company_id"))
        records = super().create(vals_list)
        for record in records:
            record._log_movement(record.state, _("Check created"))
        return records

    def write(self, vals):
        if self.LOCKED_FIELDS & set(vals) and any(r.sudo().move_ids for r in self):
            raise UserError(_(
                "Amount, partner, type, currency, company and invoices cannot be changed once "
                "accounting entries exist. Cancel this check and create a new one."
            ))
        resetting_to_draft = vals.get("state") == "draft"
        touched = set(vals)
        if not resetting_to_draft:
            if touched & self.CHECK_NUMBER_LOCKED_FIELDS:
                locked = self.filtered(lambda r: r.state != "draft")
                if locked:
                    raise UserError(_(
                        "Check Number can only be edited while the check is in Draft: %s",
                        ", ".join(locked.mapped("name")),
                    ))
            if touched & self.BANK_LOCKED_FIELDS:
                locked = self.filtered(lambda r: r.state in CLOSED_STATES)
                if locked:
                    raise UserError(_(
                        "Bank, Bank Journal and Account Number cannot be changed once a check is "
                        "Collected, Cleared, Bounced or Cancelled: %s", ", ".join(locked.mapped("name")),
                    ))
            if touched & self.DATE_LOCKED_FIELDS:
                locked = self.filtered(lambda r: r.state in CLOSED_STATES)
                if locked:
                    raise UserError(_(
                        "Issue Date and Due Date cannot be changed once a check is Collected, "
                        "Cleared, Bounced or Cancelled: %s", ", ".join(locked.mapped("name")),
                    ))
        old_states = {r.id: r.state for r in self}
        retyped = self.filtered(lambda r: r.state == "draft" and r.check_type != vals["check_type"]) \
            if "check_type" in vals else self.browse()
        if "state" in vals:
            # Defense in depth: this repeats the same rules the action_* buttons already enforced,
            # so a normal button click is re-validated harmlessly, while a raw write() from an
            # automation rule, Studio, import or RPC call that skips the buttons is rejected here
            # instead of silently landing the check in an inconsistent state with no journal entry.
            for record in self:
                if record.state != vals["state"]:
                    record._check_state_transition(vals["state"])
        res = super().write(vals)
        for record in retyped:
            # a draft that switches direction takes a number from the sequence of its new direction
            old_name = record.name
            record.name = record._next_reference(record.check_type, record.company_id.id)
            record.message_post(body=_("Reference changed from %(old)s to %(new)s.", old=old_name, new=record.name))
        if "state" in vals:
            for record in self:
                if old_states.get(record.id) != record.state:
                    record._log_movement(record.state, _("Status changed"))
                    label = dict(record._fields["state"].selection).get(record.state, record.state)
                    record.message_post(body=_("Check status changed to %s.") % label)
        return res

    def unlink(self):
        if any(r.sudo().move_ids for r in self):
            raise UserError(_("A check with accounting entries cannot be deleted. Cancel or archive it instead."))
        return super().unlink()

    # ------------------------------------------------------------------
    # Constraints & computes
    # ------------------------------------------------------------------
    @api.constrains("issue_date", "due_date")
    def _check_dates(self):
        for record in self:
            if record.issue_date and record.due_date and record.due_date < record.issue_date:
                raise ValidationError(_("Due Date cannot be earlier than Issue Date."))

    @api.constrains("amount")
    def _check_amount(self):
        for record in self:
            if record.amount <= 0:
                raise ValidationError(_("Check amount must be greater than zero."))

    @api.depends("partner_id")
    def _compute_payee_name(self):
        for record in self:
            if not record.payee_name or record.partner_id:
                record.payee_name = record.partner_id.name or record.payee_name

    @api.depends("bank_id")
    def _compute_bank_details(self):
        """Picking a bank fills its journal and account number (still editable afterwards)."""
        for record in self:
            bank = record.bank_id.sudo()  # the user may lack accounting rights on the journal
            record.journal_id = bank.journal_id or record.journal_id
            record.bank_account = bank.account_number or record.bank_account

    @api.depends("movement_ids", "invoice_ids", "move_ids")
    def _compute_counts(self):
        for record in self:
            record.movement_count = len(record.movement_ids)
            record.invoice_count = len(record.sudo().invoice_ids)
            record.move_count = len(record.sudo().move_ids)

    @api.depends("due_date", "state")
    def _compute_due_flags(self):
        today = fields.Date.context_today(self)
        for record in self:
            if record.due_date:
                delta = (record.due_date - today).days
                record.days_to_due = delta
                is_open = record.state in OPEN_STATES
                record.is_due_today = delta == 0 and is_open
                record.is_overdue = delta < 0 and is_open
            else:
                record.days_to_due = 0
                record.is_due_today = False
                record.is_overdue = False

    @api.model
    def _boolean_search_target(self, operator, value):
        """Normalize a search on a computed boolean field.

        Odoo 19 rewrites ('flag', '=', True) into ('flag', 'in', [True]) before
        calling the field's search method, so every operator form must be handled.
        Returns True / False (which records are wanted), or "all" / "none".
        """
        if operator in ("=", "!="):
            values = {bool(value)}
            operator = "in" if operator == "=" else "not in"
        elif operator in ("in", "not in"):
            values = {bool(v) for v in (value if hasattr(value, "__iter__") else [value])}
        else:
            raise NotImplementedError(_("Unsupported operator %s for this field.", operator))
        match_true = (True in values) if operator == "in" else (True not in values)
        match_false = (False in values) if operator == "in" else (False not in values)
        if match_true and match_false:
            return "all"
        if not match_true and not match_false:
            return "none"
        return match_true

    def _search_is_overdue(self, operator, value):
        today = fields.Date.context_today(self)
        target = self._boolean_search_target(operator, value)
        if target == "all":
            return [(1, "=", 1)]
        if target == "none":
            return [(0, "=", 1)]
        if target:
            return [("due_date", "<", today), ("state", "in", OPEN_STATES)]
        return ["|", ("due_date", ">=", today), ("state", "not in", OPEN_STATES)]

    def _search_is_due_today(self, operator, value):
        today = fields.Date.context_today(self)
        target = self._boolean_search_target(operator, value)
        if target == "all":
            return [(1, "=", 1)]
        if target == "none":
            return [(0, "=", 1)]
        if target:
            return [("due_date", "=", today), ("state", "in", OPEN_STATES)]
        return ["|", ("due_date", "!=", today), ("state", "not in", OPEN_STATES)]

    @api.depends("state", "is_overdue")
    def _compute_color(self):
        for record in self:
            record.color = 1 if record.is_overdue else {
                "draft": 0, "received": 4, "deposited": 4, "handed_over": 4,
                "under_collection": 3, "collected": 10, "cleared": 10,
                "bounced": 1, "cancelled": 1
            }.get(record.state, 0)

    def _log_movement(self, state, note=False):
        for record in self:
            # Users may not have create rights on movements: the log is written as superuser.
            self.env["check.movement"].sudo().create({
                "check_id": record.id,
                "state_at_movement": state,
                "user_id": self.env.user.id,
                "note": note or False
            })

    # ------------------------------------------------------------------
    # Status workflow
    # ------------------------------------------------------------------
    def _require_manager(self):
        """Bounce, cancel and reset to draft are reserved to Check Managers."""
        if not self.env.user.has_group("check_management.check_management_group_manager"):
            raise UserError(_("Only Check Managers can bounce, cancel or reset a check to draft."))

    def _ensure_transition(self, allowed_from, check_type=None):
        self.ensure_one()
        self.check_access("write")  # read-only users get a clear error before any entry is posted
        if check_type and self.check_type != check_type:
            raise UserError(_("Check %s: this action is not available for %s checks.", self.name, self.check_type))
        if self.state not in allowed_from:
            raise UserError(_(
                "Check %(name)s is %(state)s: this action is not allowed in this status.",
                name=self.name, state=dict(self._fields["state"].selection)[self.state],
            ))

    def _check_state_transition(self, target):
        """Validate a direct change of `state` to `target`, and require Manager rights where the
        action_* buttons would. This is the single source of truth enforced from write() itself
        (see write() above), so it also covers state changes that do not go through a button."""
        self.ensure_one()
        simple_rules = {
            "received": ("incoming", ("draft",)),
            "deposited": ("incoming", ("received",)),
            "under_collection": ("incoming", ("deposited",)),
            "collected": ("incoming", ("deposited", "under_collection")),
            "handed_over": ("outgoing", ("draft",)),
            "cleared": ("outgoing", ("handed_over",)),
        }
        if target in simple_rules:
            check_type, allowed_from = simple_rules[target]
            manager_required = False
            if self.check_type != check_type:
                raise UserError(_(
                    "Check %(name)s: '%(state)s' is not a valid status for %(type)s checks.",
                    name=self.name, state=target, type=self.check_type,
                ))
        elif target == "bounced":
            allowed_from = ("received", "deposited", "under_collection") if self.check_type == "incoming" else ("handed_over",)
            manager_required = True
        elif target == "cancelled":
            allowed_from = ("draft", "received", "deposited", "under_collection", "handed_over")
            manager_required = True
        elif target == "draft":
            allowed_from = ("cancelled", "bounced")
            manager_required = True
        else:
            return  # unknown target: let the ORM's selection constraint reject it
        if self.state not in allowed_from:
            raise UserError(_(
                "Check %(name)s cannot move directly from %(old)s to %(new)s. Use the status buttons instead.",
                name=self.name, old=dict(self._fields["state"].selection).get(self.state, self.state),
                new=dict(self._fields["state"].selection).get(target, target),
            ))
        if manager_required:
            self._require_manager()

    def action_receive(self):
        for rec in self:
            rec._ensure_transition(("draft",), "incoming")
            rec._entry_receive_or_handover()
            rec.write({"state": "received"})

    def action_deposit(self):
        for rec in self:
            rec._ensure_transition(("received",), "incoming")
            rec._entry_deposit()
            rec.write({"state": "deposited"})

    def action_under_collection(self):
        for rec in self:
            rec._ensure_transition(("deposited",), "incoming")
            rec.write({"state": "under_collection"})

    def action_collect(self):
        for rec in self:
            rec._ensure_transition(("deposited", "under_collection"), "incoming")
            rec._entry_collect()
            rec.write({"state": "collected"})

    def action_handover(self):
        for rec in self:
            rec._ensure_transition(("draft",), "outgoing")
            rec._entry_receive_or_handover()
            rec.write({"state": "handed_over"})

    def action_clear(self):
        for rec in self:
            rec._ensure_transition(("handed_over",), "outgoing")
            rec._entry_clear()
            rec.write({"state": "cleared"})

    def action_bounce(self):
        self._require_manager()
        for rec in self:
            if rec.check_type == "incoming":
                rec._ensure_transition(("received", "deposited", "under_collection"))
            else:
                rec._ensure_transition(("handed_over",))
            rec._entry_bounce(rec.state)
            rec.write({"state": "bounced"})

    def action_cancel(self):
        self._require_manager()
        for rec in self:
            rec._ensure_transition(("draft", "received", "deposited", "under_collection", "handed_over"))
            rec._entry_cancel()
            rec.write({"state": "cancelled"})

    def action_reset_draft(self):
        self._require_manager()
        for rec in self:
            rec._ensure_transition(("cancelled", "bounced"))
            rec.write({"state": "draft"})

    # ------------------------------------------------------------------
    # Accounting helpers
    # ------------------------------------------------------------------
    def _accounting_config(self):
        """Return the company's check.config, or False when auto-posting is disabled."""
        self.ensure_one()
        config = self.env["check.config"]._get_config(self.company_id)
        return config if config.auto_post else False

    def _partner_account(self):
        self.ensure_one()
        partner = self.partner_id.sudo().with_company(self.company_id)
        account = (
            partner.property_account_receivable_id if self.check_type == "incoming"
            else partner.property_account_payable_id
        )
        if not account:
            raise UserError(_("The partner has no suitable receivable/payable account."))
        return account

    def _bank_account(self):
        self.ensure_one()
        journal = self.sudo().journal_id  # the user may lack accounting rights
        if not journal:
            raise UserError(_(
                "Please select a Bank whose journal is set (or the Bank Journal itself) on check %s first.",
                self.name,
            ))
        if not journal.default_account_id:
            raise UserError(_("The journal %s has no default account.", journal.name))
        return journal.default_account_id

    def _live_moves(self):
        """Posted, not-reversed journal entries of this check (superuser read)."""
        self.ensure_one()
        return self.sudo().move_ids.filtered(
            lambda m: m.state == "posted" and not m.reversed_entry_id and not m.reversal_move_ids
        ).sorted("id")

    def _cycle_moves(self):
        """Entries since the last bounce: a bounce neutralizes everything before it."""
        moves = self._live_moves()
        bounces = moves.filtered(lambda m: m.check_role == "bounce")
        if bounces:
            last = bounces[-1].id
            moves = moves.filtered(lambda m: m.id > last)
        return moves

    def _build_line_vals(self, spec, date):
        """spec: [{'account': account, 'amount': +debit / -credit, in check currency}]"""
        self.ensure_one()
        company = self.company_id
        company_currency = company.currency_id
        foreign = self.currency_id != company_currency
        debits = [s for s in spec if s["amount"] > 0]
        credits = [s for s in spec if s["amount"] < 0]
        if self.currency_id.compare_amounts(
            sum(s["amount"] for s in debits), -sum(s["amount"] for s in credits)
        ):
            raise UserError(_("Internal error: unbalanced entry for check %s.", self.name))

        def convert(value):
            return company_currency.round(
                self.currency_id._convert(value, company_currency, company, date) if foreign else value
            )

        total = convert(sum(s["amount"] for s in debits))
        lines = []
        for side, sign in ((debits, 1), (credits, -1)):
            balances = [convert(abs(s["amount"])) for s in side]
            if balances:  # push rounding differences on the last line so that the entry balances
                balances[-1] += total - sum(balances)
            for item, balance in zip(side, balances):
                vals = {
                    "name": self.name,
                    "account_id": item["account"].id,
                    "partner_id": self.partner_id.id,
                    "debit": balance if sign > 0 else 0.0,
                    "credit": balance if sign < 0 else 0.0,
                }
                if foreign:
                    vals["currency_id"] = self.currency_id.id
                    vals["amount_currency"] = self.currency_id.round(sign * abs(item["amount"]))
                lines.append((0, 0, vals))
        return lines

    def _create_move(self, role, journal, spec, date=None):
        self.ensure_one()
        date = date or fields.Date.context_today(self)
        labels = dict(self.env["account.move"]._fields["check_role"].selection)
        move = self.env["account.move"].sudo().with_company(self.company_id).create({
            "move_type": "entry",
            "date": date,
            "journal_id": journal.id,
            "ref": "%s - %s" % (self.name, labels.get(role, role)),
            "check_id": self.id,
            "check_role": role,
            "line_ids": self._build_line_vals(spec, date),
        })
        move.action_post()
        self.message_post(body=_("Journal entry %s posted.", move.display_name))
        return move

    def _validate_invoices(self):
        self.ensure_one()
        expected = "out_invoice" if self.check_type == "incoming" else "in_invoice"
        for inv in self.sudo().invoice_ids:
            if inv.move_type != expected:
                raise UserError(_(
                    "%(inv)s is not a %(kind)s: %(type)s checks can only settle %(kind)s.",
                    inv=inv.display_name, type=self.check_type,
                    kind=_("customer invoice") if expected == "out_invoice" else _("vendor bill"),
                ))
            if inv.state != "posted":
                raise UserError(_("Invoice %s must be posted.", inv.display_name))
            if inv.company_id != self.company_id:
                raise UserError(_("Invoice %s belongs to another company.", inv.display_name))
            if inv.commercial_partner_id != self.partner_id.commercial_partner_id:
                raise UserError(_("Invoice %s belongs to a different partner.", inv.display_name))
            if inv.currency_id != self.currency_id:
                raise UserError(_(
                    "Invoice %(inv)s is in %(c1)s but the check is in %(c2)s.",
                    inv=inv.display_name, c1=inv.currency_id.name, c2=self.currency_id.name,
                ))

    def _allocate_invoices(self):
        """Spread the check amount over the open lines of the linked invoices (oldest due first).

        Returns {partner account: [amount, open invoice lines]}. Whatever is not
        allocated to an invoice stays on the partner's default account as an
        unapplied payment.
        """
        self.ensure_one()
        currency = self.currency_id
        remaining = self.amount
        allocation = {}
        invoices = self.sudo().invoice_ids.sorted(lambda m: (m.invoice_date_due or m.date, m.id))
        for inv in invoices:
            for line in inv.line_ids.filtered(
                lambda l: l.account_id.account_type in PARTNER_ACCOUNT_TYPES and not l.reconciled
            ):
                if currency.compare_amounts(remaining, 0) <= 0:
                    break
                available = abs(line.amount_residual_currency)
                take = currency.round(min(available, remaining))
                if currency.is_zero(take):
                    continue
                entry = allocation.setdefault(line.account_id, [0.0, self.env["account.move.line"]])
                entry[0] = currency.round(entry[0] + take)
                entry[1] |= line
                remaining = currency.round(remaining - take)
        if currency.compare_amounts(remaining, 0) > 0:
            entry = allocation.setdefault(self._partner_account(), [0.0, self.env["account.move.line"]])
            entry[0] = currency.round(entry[0] + remaining)
        return allocation

    # ------------------------------------------------------------------
    # Accounting entries
    # ------------------------------------------------------------------
    def _entry_receive_or_handover(self):
        """Incoming: Dr Notes Receivable / Cr Customer.  Outgoing: Dr Vendor / Cr Notes Payable."""
        self.ensure_one()
        config = self._accounting_config()
        if not config:
            return
        incoming = self.check_type == "incoming"
        notes = config._account("notes_receivable_account_id" if incoming else "notes_payable_account_id")
        journal = config._entry_journal()
        self._validate_invoices()
        allocation = self._allocate_invoices()
        sign = -1 if incoming else 1  # partner side: credit for incoming, debit for outgoing
        spec = [{"account": notes, "amount": -sign * self.amount}]
        spec += [{"account": acc, "amount": sign * amount} for acc, (amount, _lines) in allocation.items()]
        move = self._create_move("receive" if incoming else "handover", journal, spec)
        for account, (_amount, lines) in allocation.items():
            if lines:
                move_line = move.line_ids.filtered(lambda l, a=account: l.account_id == a)
                (move_line + lines).reconcile()

    def _entry_deposit(self):
        """Dr Checks Under Collection / Cr Notes Receivable (skipped in single-account mode)."""
        self.ensure_one()
        config = self._accounting_config()
        if not config:
            return
        notes = config._account("notes_receivable_account_id")
        holding = config._holding_account()
        if holding == notes:
            return
        self._create_move("deposit", config._entry_journal(), [
            {"account": holding, "amount": self.amount},
            {"account": notes, "amount": -self.amount},
        ])

    def _entry_collect(self):
        """Dr Bank / Cr Checks Under Collection."""
        self.ensure_one()
        config = self._accounting_config()
        if not config:
            return
        bank = self._bank_account()
        holding = config._holding_account()
        self._create_move("collect", self.sudo().journal_id, [
            {"account": bank, "amount": self.amount},
            {"account": holding, "amount": -self.amount},
        ])

    def _entry_clear(self):
        """Dr Notes Payable / Cr Bank."""
        self.ensure_one()
        config = self._accounting_config()
        if not config:
            return
        bank = self._bank_account()
        notes = config._account("notes_payable_account_id")
        self._create_move("clear", self.sudo().journal_id, [
            {"account": notes, "amount": self.amount},
            {"account": bank, "amount": -self.amount},
        ])

    def _entry_bounce(self, previous_state):
        """Reverse every accounting entry created by the check lifecycle.

        A bounced check must undo the complete accounting trail, not only the
        original receive/handover entry.  For example, an incoming check that
        was received -> deposited -> collected will reverse collect, deposit,
        and receive in reverse order.  Reversing the receive entry also removes
        the invoice reconciliation, so the customer balance is reopened.

        Bank charges are posted separately and are NOT reversed: they are an
        actual bank expense caused by the bounce.
        """
        self.ensure_one()
        config = self._accounting_config()
        if not config:
            return

        # Remove invoice reconciliation before reversing the lifecycle entries.
        # _reverse_move also removes any move-line reconciliation, but doing it
        # explicitly makes the intent clear and handles all receive/handover
        # lines even when several invoices were allocated to the check.
        partner_lines = self.sudo().move_ids.filtered(
            lambda m: m.state == "posted"
            and m.check_role in ("receive", "handover")
            and not m.reversed_entry_id
        ).mapped("line_ids").filtered(
            lambda l: l.account_id.account_type in PARTNER_ACCOUNT_TYPES
            and (l.matched_debit_ids or l.matched_credit_ids)
        )
        if partner_lines:
            partner_lines.remove_move_reconcile()

        # Reverse ALL lifecycle entries, newest first.  This is the key fix: a
        # bounce must not stop after reversing only the first entry.
        lifecycle_roles = ("receive", "deposit", "collect", "handover", "clear")
        moves = self.sudo().move_ids.filtered(
            lambda m: m.state == "posted"
            and m.check_role in lifecycle_roles
            and not m.reversed_entry_id
            and not m.reversal_move_ids
        ).sorted("id", reverse=True)

        for move in moves:
            self._reverse_move(move)

        # Bank charges are a real expense and therefore remain posted.
        if (self.check_type == "incoming"
                and previous_state in ("deposited", "under_collection")
                and self.currency_id.compare_amounts(self.bounce_fee, 0) > 0):
            fee_bank = self._bank_account()
            fee_account = config._account("bank_charges_account_id")
            self._create_move("bounce_fee", self.sudo().journal_id, [
                {"account": fee_account, "amount": self.bounce_fee},
                {"account": fee_bank, "amount": -self.bounce_fee},
            ])

    def _reverse_move(self, move):
        self.ensure_one()
        move.line_ids.filtered(lambda l: l.matched_debit_ids or l.matched_credit_ids).remove_move_reconcile()
        reversal = move._reverse_moves([{
            "date": fields.Date.context_today(self),
            "ref": _("Reversal of: %s", move.ref or move.name),
            "check_id": self.id,
            "check_role": "reversal",
        }], cancel=True)
        self.message_post(body=_("Journal entry %(move)s reversed by %(rev)s.", move=move.display_name, rev=reversal.display_name))

    def _entry_cancel(self):
        self.ensure_one()
        config = self._accounting_config()
        if not config:
            return
        moves = self._cycle_moves().filtered(lambda m: m.check_role in ("receive", "deposit", "handover"))
        for move in moves.sorted("id", reverse=True):
            self._reverse_move(move)

    # ------------------------------------------------------------------
    # Printing
    # ------------------------------------------------------------------
    def _get_print_template(self):
        self.ensure_one()
        if self.print_template_id:
            return self.print_template_id
        Template = self.env["check.print.template"]
        domain = [("company_id", "=", self.company_id.id)]
        template = Template.search(domain + [("bank_id", "=", self.bank_id.id)], limit=1) if self.bank_id else Template
        template = template or Template.search(domain + [("bank_id", "=", False)], limit=1) \
            or Template.search(domain, limit=1)
        if not template:
            raise UserError(_("No check print template found. Create one in Checks > Configuration > Print Templates."))
        return template

    def _print_values(self, template):
        self.ensure_one()
        date = self.due_date if template.date_source == "due_date" else self.issue_date
        bank_name = self.bank_id.display_name or self.company_id.name
        return template._values_for(
            self.payee_name or self.partner_id.name, self.amount, self.currency_id, date,
            bank_name=bank_name, check_number=self.check_number, reference=self.name,
        )

    def action_print_check(self):
        if not self:
            return False
        for check in self:
            if check.state in ("draft", "cancelled"):
                raise UserError(_(
                    "Check %s cannot be printed while Draft or Cancelled: pick a bank and move it "
                    "forward first (Receive / Hand Over at least).", check.name,
                ))
        # discard_logo_check: a check leaf has no company layout, do not ask the admin to configure one
        return self.env.ref("check_management.action_report_check_print").with_context(
            discard_logo_check=True).report_action(self)

    # ------------------------------------------------------------------
    # Smart buttons
    # ------------------------------------------------------------------
    def action_open_journal_entries(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Journal Entries"),
            "res_model": "account.move", "view_mode": "list,form",
            "domain": [("check_id", "=", self.id)],
        }

    def action_open_invoices(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Invoices"),
            "res_model": "account.move", "view_mode": "list,form",
            "domain": [("id", "in", self.invoice_ids.ids)]
        }

    def action_open_movements(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": _("Check Movements"),
            "res_model": "check.movement", "view_mode": "list,form",
            "domain": [("check_id", "=", self.id)]
        }

    # ------------------------------------------------------------------
    # Reminders
    # ------------------------------------------------------------------
    @api.model
    def cron_due_check_activities(self):
        today = fields.Date.context_today(self)
        checks = self.sudo().search([
            ("due_date", "in", [today, fields.Date.add(today, days=1)]),
            ("state", "in", OPEN_STATES)
        ])
        activity_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        if not activity_type:
            return True
        model_id = self.env["ir.model"]._get_id("check.management")
        root = self.env.ref("base.user_root")
        for check in checks:
            existing = self.env["mail.activity"].search([
                ("res_model_id", "=", model_id),
                ("res_id", "=", check.id),
                ("activity_type_id", "=", activity_type.id),
                ("summary", "=", _("Check Due Reminder"))
            ], limit=1)
            if not existing:
                owner = check.create_uid
                if not owner.active or owner.share or owner == root:
                    owner = self.env.user
                self.env["mail.activity"].create({
                    "activity_type_id": activity_type.id,
                    "res_model_id": model_id,
                    "res_id": check.id,
                    "user_id": owner.id,
                    "summary": _("Check Due Reminder"),
                    "note": _("Check %s for %s is due on %s.") % (
                        check.name, check.partner_id.display_name, check.due_date
                    ),
                    "date_deadline": check.due_date
                })
        return True
