# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    insurance_invoice_journal_id = fields.Many2one(
        "account.journal",
        string="Insurance Invoices Journal",
        domain="[('type', '=', 'sale'), ('company_id', '=', id)]",
        help="Journal used for the insurance company's own invoice, "
        "generated automatically when a patient invoice with an Insurance "
        "Company set is posted (see "
        "account.move._create_insurance_sibling_invoice). Leave empty to "
        "use the same journal as the patient's own invoice.",
    )
    insurance_default_payment_journal_id = fields.Many2one(
        "account.journal",
        string="Default Insurance Claim Payment Journal",
        domain="[('type', 'in', ['bank', 'cash']), ('company_id', '=', id)]",
        help="Pre-filled as the default 'Payment Journal' on every new "
        "Insurance Claim.",
    )
    insurance_rejection_account_id = fields.Many2one(
        "account.account",
        string="Rejected Claims Account",
        domain="[('account_type', 'in', ('expense', 'expense_direct_cost', 'expense_depreciation'))]",
        help="Expense account charged when an insurance company rejects part "
        "of an invoice (the credit note posted by 'Post Rejections' uses it).",
    )
