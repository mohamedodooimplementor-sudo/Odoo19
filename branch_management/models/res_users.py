# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    _inherit = 'res.users'

    branch_id = fields.Many2one(
        'res.branch', string='Default Branch',
        domain="[('id', 'in', branch_ids)]",
        help='Branch used by default on documents created by this user.')

    branch_ids = fields.Many2many(
        'res.branch', 'res_branch_res_users_rel', 'user_id', 'branch_id',
        string='Allowed Branches',
        help='Branches this user is allowed to work with when Access Mode '
             'is "Restricted to Selected Branches".')

    branch_access_mode = fields.Selection([
        ('restricted', 'Restricted to Selected Branches'),
        ('all', 'All Branches'),
    ], string='Branch Access Mode', default='restricted', required=True)

    is_branch_manager = fields.Boolean(
        string='Branch Manager', compute='_compute_is_branch_manager',
        inverse='_inverse_is_branch_manager',
        help='Branch Managers always see and manage every branch and all '
             'their documents (Sales, Purchases, Journal Entries, Journal '
             'Items, Payments, Stock Pickings, Inter-Branch Transfers...), '
             'regardless of their own Branch Access Mode / Allowed Branches '
             'above. Equivalent to being a member of the "Branch Management '
             '/ Branch Manager" security group.')

    def _compute_is_branch_manager(self):
        group = self.env.ref('branch_management.group_branch_manager')
        for user in self:
            user.is_branch_manager = group in user.group_ids

    def _inverse_is_branch_manager(self):
        group = self.env.ref('branch_management.group_branch_manager')
        for user in self:
            if user.is_branch_manager:
                user.group_ids = [(4, group.id)]
            else:
                user.group_ids = [(3, group.id)]

    @api.constrains('branch_id', 'branch_ids', 'branch_access_mode')
    def _check_default_branch_allowed(self):
        for user in self:
            if (user.branch_access_mode == 'restricted' and user.branch_id
                    and user.branch_id not in user.branch_ids):
                raise ValidationError(
                    "The Default Branch must be part of the user's Allowed Branches.")

    def get_allowed_branches(self):
        """Return the recordset of res.branch this user may operate on.

        Used by other modules (Sale/Purchase branch integration,
        Inter-Branch Transfers, ...) to build domains / defaults.
        """
        self.ensure_one()
        if self.branch_access_mode == 'all':
            return self.env['res.branch'].search(
                [('company_id', 'in', self.company_ids.ids)])
        return self.branch_ids

    @api.onchange('branch_access_mode')
    def _onchange_branch_access_mode(self):
        if self.branch_access_mode == 'all':
            self.branch_ids = [(6, 0, self.env['res.branch'].search(
                [('company_id', 'in', self.company_ids.ids)]).ids)]
