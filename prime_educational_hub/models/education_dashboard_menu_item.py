# -*- coding: utf-8 -*-
from odoo import api, fields, models


class EducationDashboardMenuItem(models.Model):
    _name = 'education.dashboard.menu.item'
    _description = 'Prime Education Hub Dashboard - Sidebar/Navigation Item'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    icon = fields.Char(
        required=True, default='fa-th-large',
        help="Font Awesome icon class, e.g. 'fa-graduation-cap'. This is the same icon "
             "font already bundled with the Odoo backend, so no extra assets are needed.")
    sequence = fields.Integer(default=10)
    color = fields.Char(
        default='#a855f7',
        help="Accent color for this item's icon badge (hex), used on the dashboard's "
             "sidebar/cards.")
    description = fields.Char(translate=True)
    active = fields.Boolean(default=True)

    action_id = fields.Many2one(
        'ir.actions.actions', string='Odoo Action', required=True, ondelete='cascade',
        help='The real Odoo action opened when this item is clicked (act_window, server '
             'action, client action...). Clicking always calls this action through the normal '
             'Odoo action service - this is never a static/decorative button.')
    res_model = fields.Char(
        compute='_compute_res_model', store=True,
        help="Target model of the action (when it is an act_window action), used to double-"
             "check the current user's real access rights on it before showing this item "
             "(defense-in-depth on top of the group filter below). Left empty for action "
             "types without a single target model (server actions, client actions...) - "
             "Odoo's own permission check still applies whenever the action actually runs.")

    @api.depends('action_id')
    def _compute_res_model(self):
        for item in self:
            item.res_model = False
            if not item.action_id:
                continue
            base = item.action_id.sudo()
            # ir.actions.actions is the abstract base row; res_model only really exists
            # on the concrete ir.actions.act_window model, so re-browse the record as its
            # own real type (the standard Odoo pattern, using the `type` field) before
            # reading it.
            try:
                typed_action = self.env[base.type].sudo().browse(base.id)
                item.res_model = getattr(typed_action, 'res_model', False) or False
            except Exception:
                item.res_model = False

    group_id = fields.Many2one(
        'res.groups', string='Restrict To Group',
        help='Only users in this group (or a group implying it) see this item. Leave empty '
             'to show it to every user who otherwise has access to the module. This is purely '
             "a navigation convenience filter - actual access to the records is always "
             "governed by that model's own Access Rights/Record Rules regardless of this field.")

    is_dashboard_home = fields.Boolean(
        string='Is the Dashboard Home Item',
        help='Marks the "Dashboard" entry itself, so it is always shown (skipping the '
             'target-model access check below, since the dashboard action itself has no '
             'res_model) and can be highlighted as the active/home item in the sidebar.')

    @api.model
    def get_visible_items(self):
        """Menu items visible to the current user: active, in their allowed group (if any),
        and only if they actually have read access to the linked action's target model. Real
        Odoo security is the source of truth here, not just this configuration record - a
        misconfigured/missing group_id can never expose something the user isn't otherwise
        allowed to open."""
        user_groups = self.env.user.group_ids
        items = self.search([('active', '=', True)])
        visible = self.env['education.dashboard.menu.item']
        for item in items:
            if item.group_id and item.group_id not in user_groups:
                continue
            if item.res_model and not item.is_dashboard_home:
                try:
                    if not self.env[item.res_model].has_access('read'):
                        continue
                except KeyError:
                    # target model no longer exists (e.g. action left over from an
                    # uninstalled module) - never show a dead/non-functional item
                    continue
            visible += item
        return visible
