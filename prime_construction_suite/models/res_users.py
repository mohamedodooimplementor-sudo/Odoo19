# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ResUsers(models.Model):
    _inherit = 'res.users'

    construction_suite_role = fields.Selection([
        ('none',      'No Access'),
        ('user',      'Site User'),
        ('manager',   'Project Manager'),
        ('financial', 'Financial Manager'),
    ], string='Prime Construction Suite Role', compute='_compute_construction_suite_role',
       inverse='_inverse_construction_suite_role', store=False,
       help='Single role selector for the Prime Construction Suite. Cost & financial figures '
            '(prices, amounts, margins) are only visible to Project Manager and Financial Manager.')

    @api.depends('group_ids')
    def _compute_construction_suite_role(self):
        financial = self.env.ref('prime_construction_suite.group_construction_financial', raise_if_not_found=False)
        manager   = self.env.ref('prime_construction_suite.group_construction_manager', raise_if_not_found=False)
        user      = self.env.ref('prime_construction_suite.group_construction_user', raise_if_not_found=False)
        for rec in self:
            if financial and financial in rec.group_ids:
                rec.construction_suite_role = 'financial'
            elif manager and manager in rec.group_ids:
                rec.construction_suite_role = 'manager'
            elif user and user in rec.group_ids:
                rec.construction_suite_role = 'user'
            else:
                rec.construction_suite_role = 'none'

    def _inverse_construction_suite_role(self):
        financial = self.env.ref('prime_construction_suite.group_construction_financial', raise_if_not_found=False)
        manager   = self.env.ref('prime_construction_suite.group_construction_manager', raise_if_not_found=False)
        user      = self.env.ref('prime_construction_suite.group_construction_user', raise_if_not_found=False)
        all_groups = (financial or self.env['res.groups']) | (manager or self.env['res.groups']) | (user or self.env['res.groups'])
        target_by_role = {'financial': financial, 'manager': manager, 'user': user, 'none': False}
        for rec in self:
            target = target_by_role.get(rec.construction_suite_role)
            commands = [(3, g.id) for g in all_groups]
            if target:
                commands.append((4, target.id))
            rec.write({'group_ids': commands})
