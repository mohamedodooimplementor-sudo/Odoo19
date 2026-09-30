# -*- coding: utf-8 -*-
from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    construction_approval_threshold_1 = fields.Monetary(
        string='Auto-Approval Limit (Site User)', default=50000,
        currency_field='currency_id',
        help='Actual costs at or below this amount can be approved by any Construction Suite user.')
    construction_approval_threshold_2 = fields.Monetary(
        string='Project Manager Limit', default=250000,
        currency_field='currency_id',
        help='Actual costs above the first limit and up to this amount require a Project Manager. '
             'Above this amount requires a Financial Manager.')

    # ── Accounting integration: post Actual Costs to the General Ledger ──
    construction_cost_journal_id = fields.Many2one(
        'account.journal', string='Construction Cost Journal',
        domain=[('type', '=', 'general')],
        help='Miscellaneous-type journal used to post Actual Cost entries to Accounting when they '
             'are approved. Leave empty to keep Actual Costs tracked only within the Construction '
             'Suite, with no automatic accounting entries.')
    construction_accrual_account_id = fields.Many2one(
        'account.account', string='Accrued Project Costs Account (Credit)',
        help='Clearing account credited when an Actual Cost is posted to Accounting.')
    construction_material_account_id = fields.Many2one(
        'account.account', string='Materials Cost Account (Debit)')
    construction_labor_account_id = fields.Many2one(
        'account.account', string='Labor Cost Account (Debit)')
    construction_equipment_account_id = fields.Many2one(
        'account.account', string='Equipment Cost Account (Debit)')
    construction_subcontract_account_id = fields.Many2one(
        'account.account', string='Subcontract Cost Account (Debit)')
    construction_overhead_account_id = fields.Many2one(
        'account.account', string='Overhead Cost Account (Debit)')
    construction_other_account_id = fields.Many2one(
        'account.account', string='Other Cost Account (Debit)')


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    construction_approval_threshold_1 = fields.Monetary(
        related='company_id.construction_approval_threshold_1', readonly=False,
        string='Site User Approval Limit')
    construction_approval_threshold_2 = fields.Monetary(
        related='company_id.construction_approval_threshold_2', readonly=False,
        string='Project Manager Approval Limit')

    construction_cost_journal_id = fields.Many2one(
        related='company_id.construction_cost_journal_id', readonly=False,
        string='Construction Cost Journal')
    construction_accrual_account_id = fields.Many2one(
        related='company_id.construction_accrual_account_id', readonly=False,
        string='Accrued Project Costs Account')
    construction_material_account_id = fields.Many2one(
        related='company_id.construction_material_account_id', readonly=False,
        string='Materials Cost Account')
    construction_labor_account_id = fields.Many2one(
        related='company_id.construction_labor_account_id', readonly=False,
        string='Labor Cost Account')
    construction_equipment_account_id = fields.Many2one(
        related='company_id.construction_equipment_account_id', readonly=False,
        string='Equipment Cost Account')
    construction_subcontract_account_id = fields.Many2one(
        related='company_id.construction_subcontract_account_id', readonly=False,
        string='Subcontract Cost Account')
    construction_overhead_account_id = fields.Many2one(
        related='company_id.construction_overhead_account_id', readonly=False,
        string='Overhead Cost Account')
    construction_other_account_id = fields.Many2one(
        related='company_id.construction_other_account_id', readonly=False,
        string='Other Cost Account')
