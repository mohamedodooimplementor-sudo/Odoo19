# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class ResUsers(models.Model):
    _inherit = 'res.users'

    # A teacher does NOT have to be an Odoo user at all (see education.teacher).
    # This is only populated for the subset of teachers who were given a
    # System User account -- it looks up the education.teacher record (if
    # any) linked back to this login, purely for convenient navigation from
    # Settings > Users.
    education_teacher_id = fields.Many2one(
        'education.teacher', string='Linked Teacher Record', compute='_compute_education_teacher_id')
    education_is_teacher = fields.Boolean(
        string='Is Education Teacher', compute='_compute_education_teacher_id')
    education_group_count = fields.Integer(
        string='Teaching Groups', compute='_compute_education_teacher_id')
    education_session_count = fields.Integer(
        string='Sessions Given', compute='_compute_education_teacher_id')

    def _compute_education_teacher_id(self):
        # sudo(): an Administrator/Supervisor browsing another user's profile
        # should see the linked teacher's real counts, not be limited by
        # that teacher's own record rules.
        Teacher = self.env['education.teacher'].sudo()
        for user in self:
            teacher = Teacher.search([('user_id', '=', user.id)], limit=1)
            user.education_teacher_id = teacher.id
            user.education_is_teacher = bool(teacher)
            user.education_group_count = teacher.group_count
            user.education_session_count = teacher.session_count

    def action_view_education_sessions(self):
        self.ensure_one()
        if not self.education_teacher_id:
            return
        return self.education_teacher_id.action_view_sessions()

    def action_view_education_groups(self):
        self.ensure_one()
        if not self.education_teacher_id:
            return
        return self.education_teacher_id.action_view_groups()

    @api.model
    def _education_apply_dashboard_home_action(self):
        """Sets the Prime Education Hub Dashboard as the (native) Home Action for every user
        who is currently a member of any Prime Educational Hub group. Uses the exact same
        `action_id` field as Settings > Users > a user > Home Action - this is what actually
        makes Odoo land the user on this dashboard right after login instead of the Apps
        switcher, with no core hack involved."""
        dashboard_action = self.env.ref('prime_educational_hub.action_education_dashboard', raise_if_not_found=False)
        base_group = self.env.ref('prime_educational_hub.group_education_read_only', raise_if_not_found=False)
        if not dashboard_action or not base_group:
            return
        # Query res.users directly by group_ids rather than going through res.groups' own
        # reverse relation - that reverse field's name has changed between Odoo versions
        # before (e.g. 'users' in older versions), so this is the more stable way to ask
        # "which users are in this group".
        members = self.sudo().search([('group_ids', 'in', base_group.id)])
        if members:
            members.write({'action_id': dashboard_action.id})

    def write(self, vals):
        res = super().write(vals)
        if 'groups_id' in vals or 'group_ids' in vals:
            auto_apply = self.env['ir.config_parameter'].sudo().get_param(
                'prime_educational_hub.dashboard_as_home_page')
            if auto_apply and auto_apply != 'False':
                base_group = self.env.ref('prime_educational_hub.group_education_read_only', raise_if_not_found=False)
                dashboard_action = self.env.ref(
                    'prime_educational_hub.action_education_dashboard', raise_if_not_found=False)
                if base_group and dashboard_action:
                    newly_in_module = self.filtered(
                        lambda u: base_group in u.group_ids and not u.action_id)
                    if newly_in_module:
                        newly_in_module.sudo().write({'action_id': dashboard_action.id})
        return res
