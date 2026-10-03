# -*- coding: utf-8 -*-
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Our own field, fully independent from Odoo's native res.partner
    # 'credit_limit' field. We don't touch/redeclare the native one at all
    # anymore -- doing so kept conflicting with core Odoo internals
    # (security group, company_dependent storage, migration of the
    # existing column, etc). This is a plain, simple field we fully own.
    no_credit_limit = fields.Boolean(
        string='Unlimited Credit',
        help='If checked, this customer has no credit limit: the Credit '
             'Limit field is hidden and the credit limit check is never '
             'triggered for this customer.')
    partner_credit_limit = fields.Monetary(
        string='Credit Limit', currency_field='currency_id',
        help='Credit limit specific to this customer, used by Branch '
             "Management's credit limit check on Sale Orders.")

    vendor_type = fields.Selection([
        ('local', 'Local Supplier'),
        ('foreign', 'Foreign Supplier'),
        ('service', 'Service Supplier'),
    ], string='Vendor Type', tracking=True, default='local',
        help='Used to classify Purchase Orders into Local / Foreign / Service Purchases.')

    branch_ids = fields.Many2many(
        'res.branch', 'res_partner_res_branch_rel', 'partner_id', 'branch_id',
        string='Branches',
        help='Restrict this contact to specific branches: it will only be '
             'selectable on Sales/Purchase Orders of those branches. '
             'Leave empty to make it available in every branch.')
