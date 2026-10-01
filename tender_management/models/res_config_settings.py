# -*- coding: utf-8 -*-
from odoo import fields, models

_ACCOUNT_DOMAIN = "[('account_type', 'not in', ('asset_receivable', 'liability_payable'))]"


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    tm_labour_account_id = fields.Many2one(
        related='company_id.tm_labour_account_id', readonly=False, domain=_ACCOUNT_DOMAIN)
    tm_overhead_account_id = fields.Many2one(
        related='company_id.tm_overhead_account_id', readonly=False, domain=_ACCOUNT_DOMAIN)
    tm_other_account_id = fields.Many2one(
        related='company_id.tm_other_account_id', readonly=False, domain=_ACCOUNT_DOMAIN)
