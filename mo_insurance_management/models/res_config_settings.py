# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    insurance_invoice_journal_id = fields.Many2one(
        related="company_id.insurance_invoice_journal_id",
        readonly=False,
        string="Insurance Invoices Journal",
    )
    insurance_default_payment_journal_id = fields.Many2one(
        related="company_id.insurance_default_payment_journal_id",
        readonly=False,
        string="Default Claim Payment Journal",
    )
    insurance_rejection_account_id = fields.Many2one(
        related="company_id.insurance_rejection_account_id",
        readonly=False,
        string="Rejected Claims Account",
    )
