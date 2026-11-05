from odoo import api, fields, models

RC_CHAIN = (  # highest level first; each level implies the ones below it
    ('manager', 'radiology_consumables.group_rc_manager'),
    ('storekeeper', 'radiology_consumables.group_rc_storekeeper'),
    ('nurse', 'radiology_consumables.group_rc_nurse'),
)
RC_ANALYST = 'radiology_consumables.group_rc_analytics'


class ResUsers(models.Model):
    _inherit = 'res.users'

    rc_access_level = fields.Selection(
        [('none', 'No access'),
         ('nurse', 'Room Nurse'),
         ('storekeeper', 'Storekeeper'),
         ('manager', 'Manager')],
        string='Operations Role', default='none',
        compute='_compute_rc_access', inverse='_inverse_rc_access_level',
        help='Exam consumption, room stock and configuration. Each role includes the ones below it.')
    rc_is_analyst = fields.Boolean(
        string='Cost & Performance Analyst',
        compute='_compute_rc_access', inverse='_inverse_rc_is_analyst',
        help='Access to the Cost & Performance Analytics dashboard and reports, independent of the operations role.')

    @api.depends('group_ids')
    def _compute_rc_access(self):
        analyst = self.env.ref(RC_ANALYST, raise_if_not_found=False)
        chain = [(level, self.env.ref(xmlid, raise_if_not_found=False)) for level, xmlid in RC_CHAIN]
        for user in self:
            ids = set(user.group_ids.ids)
            user.rc_access_level = next(
                (level for level, group in chain if group and group.id in ids), 'none')
            user.rc_is_analyst = bool(analyst and analyst.id in ids)

    def _inverse_rc_access_level(self):
        groups = {level: self.env.ref(xmlid, raise_if_not_found=False) for level, xmlid in RC_CHAIN}
        for user in self:
            target = groups.get(user.rc_access_level)
            commands = [(3, g.id) for g in groups.values() if g and g != target]
            if target:
                commands.append((4, target.id))
            user.group_ids = commands

    def _inverse_rc_is_analyst(self):
        analyst = self.env.ref(RC_ANALYST, raise_if_not_found=False)
        if not analyst:
            return
        for user in self:
            user.group_ids = [(4 if user.rc_is_analyst else 3, analyst.id)]
