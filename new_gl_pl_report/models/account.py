# -*- coding: utf-8 -*-

from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
from collections import defaultdict
from odoo.tools.misc import format_date, get_lang


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    conf_pl_currency = fields.Many2one("res.currency", related='company_id.pl_currency')
    conf_euro_pl_currency = fields.Many2one("res.currency", related='company_id.euro_pl_currency', store=True)

    # for dollar currency
    pl_currency = fields.Monetary(string="Partner Ledger Currency", compute='_compute_pl_currency',currency_field='conf_pl_currency', store=True)
    pl_credit = fields.Monetary(string="Credit Currency", compute='_compute_pl_currency',currency_field='conf_pl_currency', store=True)
    pl_debit = fields.Monetary(string="Debit Currency", compute='_compute_pl_currency',currency_field='conf_pl_currency', store=True)

    # for euro currency
    euro_pl_currency = fields.Monetary(string="Euro Partner Ledger Currency", compute='_compute_euro_pl_currency',currency_field='conf_euro_pl_currency', store=True)
    euro_pl_credit = fields.Monetary(string="Euro Credit Currency", compute='_compute_euro_pl_currency',currency_field='conf_euro_pl_currency', store=True)
    euro_pl_debit = fields.Monetary(string="Euro Debit Currency", compute='_compute_euro_pl_currency',currency_field='conf_euro_pl_currency', store=True)
    # for dollar currency
    @api.depends('amount_currency', 'balance', 'currency_id', 'currency_rate', 'date', 'conf_pl_currency')
    def _compute_pl_currency(self):
        for rec in self:
            rec.pl_debit = 0
            rec.pl_credit = 0
            if rec.currency_rate and rec.company_id.pl_currency.id == rec.currency_id.id:
                rec.pl_currency = rec.amount_currency
                if rec.amount_currency > 0:
                    rec.pl_debit = rec.amount_currency
                elif rec.amount_currency < 0:
                    rec.pl_credit = - rec.amount_currency
            else:
                # `balance` is already the amount in company currency, computed by Odoo
                # from the native exchange rate (res.currency.rate) of the move.
                company_currency = rec.balance
                converted = rec.company_currency_id._convert(
                    company_currency, rec.company_id.pl_currency, rec.company_id, rec.date)
                rec.pl_currency = converted
                if rec.amount_currency > 0:
                    rec.pl_debit = converted
                elif rec.amount_currency < 0:
                    rec.pl_credit = -converted


    # for euro currency
    @api.depends('amount_currency', 'balance', 'currency_id', 'currency_rate', 'date', 'conf_euro_pl_currency')
    def _compute_euro_pl_currency(self):
        for rec in self:
            rec.euro_pl_debit = 0
            rec.euro_pl_credit = 0
            if rec.currency_rate and rec.company_id.euro_pl_currency.id == rec.currency_id.id:
                rec.euro_pl_currency = rec.amount_currency
                if rec.amount_currency > 0:
                    rec.euro_pl_debit = rec.amount_currency
                elif rec.amount_currency < 0:
                    rec.euro_pl_credit = - rec.amount_currency

            else:
                # `balance` is already the amount in company currency, computed by Odoo
                # from the native exchange rate (res.currency.rate) of the move.
                company_currency = rec.balance
                converted = rec.company_currency_id._convert(
                    company_currency, rec.company_id.euro_pl_currency, rec.company_id, rec.date)
                rec.euro_pl_currency = converted
                if rec.amount_currency > 0:
                    rec.euro_pl_debit = converted
                elif rec.amount_currency < 0:
                    rec.euro_pl_credit = -converted
