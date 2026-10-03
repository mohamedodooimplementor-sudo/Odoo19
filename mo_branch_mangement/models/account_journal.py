# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountJournal(models.Model):
    _inherit = 'account.journal'

    branch_id = fields.Many2one(
        'res.branch', string='Branch',
        domain="[('company_id', '=', company_id)]",
        help='Restrict this Journal to a single Branch: only users with '
             'that Branch among their Allowed Branches (or Branch Managers '
             '/ Settings Administrators / "All Branches" access) will be '
             'able to see or use it - on this configuration screen as '
             'well as everywhere it can be picked (Invoices, Bills, '
             'Payments, Sales/Purchase Orders...).\n'
             'Leave empty to keep this Journal shared and usable by every '
             'branch.')
