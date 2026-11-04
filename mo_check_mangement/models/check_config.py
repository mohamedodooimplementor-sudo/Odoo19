import zlib

from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError


class CheckConfig(models.Model):
    _name = "check.config"
    _description = "Check Accounting Settings"
    _check_company_auto = True
    _rec_name = "company_id"

    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company, index=True
    )
    auto_post = fields.Boolean(
        string="Create Accounting Entries", default=True,
        help="When enabled, every status change of a check posts its journal entry "
             "and reconciles the linked invoices.",
    )
    journal_id = fields.Many2one(
        "account.journal", string="Checks Journal", check_company=True,
        domain="[('type', '=', 'general')]",
        help="Miscellaneous journal used for the receive / deposit / hand over / bounce entries. "
             "If empty, the first miscellaneous journal of the company is used.",
    )
    notes_receivable_account_id = fields.Many2one(
        "account.account", string="Notes Receivable (Checks in Hand)", check_company=True,
        help="Debited when an incoming check is received.",
    )
    under_collection_account_id = fields.Many2one(
        "account.account", string="Checks Under Collection", check_company=True,
        help="Debited when an incoming check is deposited at the bank. "
             "Leave empty to use a single account for incoming checks "
             "(the deposit then posts no entry).",
    )
    notes_payable_account_id = fields.Many2one(
        "account.account", string="Notes Payable (Issued Checks)", check_company=True,
        help="Credited when an outgoing check is handed over to the partner.",
    )
    bank_charges_account_id = fields.Many2one(
        "account.account", string="Bank Charges (Bounced Checks)", check_company=True,
        help="Debited with the bank fee entered on a bounced incoming check.",
    )

    _company_uniq = models.Constraint("UNIQUE (company_id)", "Only one accounting setting per company.")

    # ------------------------------------------------------------------
    @api.model
    def _get_config(self, company=None):
        company = company or self.env.company
        config = self.sudo().search([("company_id", "=", company.id)], limit=1)
        if not config:
            config = self.sudo().create({"company_id": company.id})
        return config

    @api.model
    def action_open_config(self):
        config = self._get_config()
        return {
            "type": "ir.actions.act_window", "name": _("Accounting Settings"),
            "res_model": "check.config", "res_id": config.id, "view_mode": "form",
            "views": [(False, "form")], "target": "current",
        }

    def _account(self, fname):
        self.ensure_one()
        account = self[fname]
        if not account:
            raise UserError(_(
                'The account "%s" is not configured. '
                'Please set it in Checks > Configuration > Accounting Settings.',
                self._fields[fname].string,
            ))
        return account

    def _holding_account(self):
        """Account holding incoming checks sent to the bank (falls back to Notes Receivable)."""
        self.ensure_one()
        return self.under_collection_account_id or self._account("notes_receivable_account_id")

    def _entry_journal(self):
        self.ensure_one()
        journal = self.journal_id or self.env["account.journal"].sudo().search(
            [("type", "=", "general"), ("company_id", "=", self.company_id.id)], limit=1
        )
        if not journal:
            raise UserError(_("No miscellaneous journal found for company %s.", self.company_id.name))
        return journal

    # ------------------------------------------------------------------
    def _next_account_code(self, account_type):
        self.ensure_one()
        # Serialize concurrent callers (e.g. two users clicking "Create Missing Accounts" for the
        # same company at the same time) so they can never compute and reuse the same new code.
        # pg_advisory_xact_lock is released automatically at the end of this transaction.
        lock_key = zlib.crc32(account_type.encode()) & 0x7FFFFFFF
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s, %s)", (self.company_id.id, lock_key))
        Account = self.env["account.account"].with_company(self.company_id)
        codes = [a.code for a in Account.search([("account_type", "=", account_type)]) if a.code and a.code.isdigit()]
        if codes:
            width = max(len(c) for c in codes)
            number = max(int(c) for c in codes) + 1
        else:
            width, number = 6, 100000
        while Account.search_count([("code", "=", str(number).zfill(width))]):
            number += 1
        return str(number).zfill(width)

    def action_create_default_accounts(self):
        """Create (or reuse by name) the accounts that are still missing."""
        self.ensure_one()
        Account = self.env["account.account"].with_company(self.company_id)
        wanted = [
            ("notes_receivable_account_id", "Notes Receivable (Checks)", "asset_current"),
            ("under_collection_account_id", "Checks Under Collection", "asset_current"),
            ("notes_payable_account_id", "Notes Payable (Checks)", "liability_current"),
            ("bank_charges_account_id", "Bank Charges - Bounced Checks", "expense"),
        ]
        for fname, name, account_type in wanted:
            if self[fname]:
                continue
            account = Account.search([("name", "=", name), ("account_type", "=", account_type)], limit=1)
            if not account:
                account = Account.create({
                    "name": name,
                    "code": self._next_account_code(account_type),
                    "account_type": account_type,
                    "company_ids": [Command.link(self.company_id.id)],
                })
            self[fname] = account
        return True
