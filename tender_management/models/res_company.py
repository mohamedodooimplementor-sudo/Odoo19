# -*- coding: utf-8 -*-
from odoo import fields, models

_ACCOUNT_DOMAIN = "[('account_type', 'not in', ('asset_receivable', 'liability_payable'))]"


class ResCompany(models.Model):
    _inherit = 'res.company'

    tm_labour_account_id = fields.Many2one(
        'account.account', string='Default Labour Cost Account', domain=_ACCOUNT_DOMAIN)
    tm_overhead_account_id = fields.Many2one(
        'account.account', string='Default Overhead Cost Account', domain=_ACCOUNT_DOMAIN)
    tm_other_account_id = fields.Many2one(
        'account.account', string='Default Other Manufacturing Cost Account', domain=_ACCOUNT_DOMAIN)
