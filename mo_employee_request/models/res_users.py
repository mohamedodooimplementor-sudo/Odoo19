# -*- coding: utf-8 -*-
from odoo import api, fields, models, Command

# boolean field name -> external id of the group it toggles
ER_FLAG_GROUPS = {
    'er_is_request_user': 'mo_employee_request.group_employee_request_user',
    'er_is_all_documents': 'mo_employee_request.group_employee_request_all_documents',
    'er_is_request_on_behalf': 'mo_employee_request.group_request_on_behalf',
    'er_is_dashboard': 'mo_employee_request.group_er_dashboard',
    'er_is_request_manager': 'mo_employee_request.group_employee_request_manager',
    'er_is_purchase_user': 'mo_employee_request.group_purchase_user',
    'er_is_purchase_manager': 'mo_employee_request.group_purchase_manager',
}


# groups managed from the module settings (not from the user form): never wipe them either
ER_SETTINGS_GROUPS = [
    'mo_employee_request.group_warehouse_approver',
    'mo_employee_request.group_budget_approver',
    'mo_employee_request.group_budget_control',
]


class ResUsers(models.Model):
    _inherit = 'res.users'

    er_is_request_user = fields.Boolean(
        string='Request User', compute='_compute_er_flags', readonly=False,
        help='Create, read and edit own requests. Required to see the app.')
    er_is_all_documents = fields.Boolean(
        string='All Documents', compute='_compute_er_flags', readonly=False,
        help='See all requests, stock transfers and purchase orders (read only).')
    er_is_request_on_behalf = fields.Boolean(
        string='Create Requests for Employees', compute='_compute_er_flags', readonly=False,
        help='Create requests on behalf of any employee.')
    er_is_dashboard = fields.Boolean(
        string='Dashboard', compute='_compute_er_flags', readonly=False,
        help='Open the Employee Requests dashboard.')
    er_is_request_manager = fields.Boolean(
        string='Request Manager', compute='_compute_er_flags', readonly=False,
        help='Read all requests, reset and cancel them.')
    er_is_purchase_user = fields.Boolean(
        string='Purchase User', compute='_compute_er_flags', readonly=False,
        help='Create and edit employee purchase orders.')
    er_is_purchase_manager = fields.Boolean(
        string='Purchase Manager', compute='_compute_er_flags', readonly=False,
        help='Full control over employee purchase orders.')

    def _er_group(self, xmlid):
        return self.env.ref(xmlid, raise_if_not_found=False) or self.env['res.groups']

    # NOTE: deliberately NO dependency on `group_ids`.
    # The standard "Access Rights" widget (res_user_group_ids) sends `group_ids` as a SET that
    # contains only the groups it displays; the module groups are hidden, so they are missing
    # from that list. If this compute depended on `group_ids`, the form onchange would recompute
    # every toggle as False and the save would then remove the groups from the user.
    @api.depends()
    def _compute_er_flags(self):
        groups = {fname: self._er_group(xmlid) for fname, xmlid in ER_FLAG_GROUPS.items()}
        for user in self:
            # Effective groups (direct + implied) when the version has `all_group_ids`
            # (Odoo 19), so the toggles reflect what the user can really do.
            effective = user.all_group_ids if 'all_group_ids' in user._fields else user.group_ids
            for fname, group in groups.items():
                user[fname] = bool(group) and group in effective

    def _er_apply_flags(self, flags):
        """Apply only the toggles that were actually changed on the form."""
        for user in self:
            commands = []
            for fname, value in flags.items():
                group = self._er_group(ER_FLAG_GROUPS[fname])
                if not group:
                    continue
                if value and group not in user.group_ids:
                    commands.append(Command.link(group.id))
                elif not value and group in user.group_ids:
                    commands.append(Command.unlink(group.id))
            if commands:
                user.group_ids = commands

    @api.model_create_multi
    def create(self, vals_list):
        flags_list = [{f: vals.pop(f) for f in list(vals) if f in ER_FLAG_GROUPS}
                      for vals in vals_list]
        users = super().create(vals_list)
        for user, flags in zip(users, flags_list):
            if flags:
                user._er_apply_flags(flags)
        return users

    @staticmethod
    def _er_replaces_groups(commands):
        """True when a `group_ids` write replaces the whole list (set / clear)."""
        return isinstance(commands, (list, tuple)) and any(
            isinstance(c, (list, tuple)) and c and c[0] in (5, 6) for c in commands)

    def write(self, vals):
        # The module groups are managed ONLY by the toggles of the "Employee Requests" tab
        # (they are hidden from the standard access-rights list). So:
        #  1. only the toggles that were really changed touch their group, and
        #  2. a full replacement of `group_ids` coming from another part of the user form
        #     must not wipe the module groups.
        flags = {f: vals.pop(f) for f in list(vals) if f in ER_FLAG_GROUPS}
        keep = {}
        if 'group_ids' in vals and self._er_replaces_groups(vals['group_ids']):
            er_groups = self.env['res.groups']
            for xmlid in list(ER_FLAG_GROUPS.values()) + ER_SETTINGS_GROUPS:
                er_groups |= self._er_group(xmlid)
            for user in self:
                keep[user.id] = user.group_ids & er_groups
        res = super().write(vals)
        for user in self:
            missing = keep.get(user.id, self.env['res.groups']) - user.group_ids
            if missing:
                user.group_ids = [Command.link(g.id) for g in missing]
        if flags:
            self._er_apply_flags(flags)
        if flags or 'group_ids' in vals:
            # toggles have no dependency any more: refresh them after groups changed
            self.invalidate_recordset(list(ER_FLAG_GROUPS))
        return res
