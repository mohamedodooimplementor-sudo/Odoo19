# -*- coding: utf-8 -*-

from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
from odoo.tools.misc import format_date, get_lang


class ResCompany(models.Model):
    _inherit = 'res.company'

    pl_currency = fields.Many2one("res.currency", string='Partner Ledger Currency')
    euro_pl_currency = fields.Many2one("res.currency", string='Euro Partner Ledger Currency')


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    conf_pl_currency = fields.Many2one(related='company_id.pl_currency', readonly=False)
    conf_euro_pl_currency = fields.Many2one(related='company_id.euro_pl_currency', readonly=False)
