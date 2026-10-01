from odoo import api, fields, models

# field name -> group xml id
PP_STAGE_FIELDS = {
    'pp_g_confirm': 'group_pp_confirm',
    'pp_g_issue': 'group_pp_issue',
    'pp_g_weight': 'group_pp_weight',
    'pp_g_prd': 'group_pp_prd',
    'pp_g_check1': 'group_pp_check1',
    'pp_g_check': 'group_pp_check',
    'pp_g_filling': 'group_pp_filling',
    'pp_g_pack': 'group_pp_pack',
    'pp_g_check2': 'group_pp_check2',
    'pp_g_final': 'group_pp_final',
}
PP_ALL_FIELDS = dict(PP_STAGE_FIELDS, pp_g_user='group_pp_user', pp_g_dashboard='group_pp_dashboard',
                     pp_g_cost='group_pp_cost', pp_g_manager='group_pp_manager')


class ResUsers(models.Model):
    _inherit = 'res.users'

    pp_g_user = fields.Boolean('User (Create / Read / Edit)', compute='_compute_pp_groups', inverse='_inverse_pp_groups')
    pp_g_dashboard = fields.Boolean('Dashboard', compute='_compute_pp_groups', inverse='_inverse_pp_groups')
    pp_g_cost = fields.Boolean('Cost (Costs, Totals and Cost Reports)', compute='_compute_pp_groups', inverse='_inverse_pp_groups')
    pp_g_confirm = fields.Boolean('Confirm Orders', compute='_compute_pp_groups', inverse='_inverse_pp_groups')
    pp_g_issue = fields.Boolean('Material / Packaging Issue', compute='_compute_pp_groups', inverse='_inverse_pp_groups')
    pp_g_weight = fields.Boolean('Weight Confirmation', compute='_compute_pp_groups', inverse='_inverse_pp_groups')
    pp_g_prd = fields.Boolean('PRD Line Check Approval', compute='_compute_pp_groups', inverse='_inverse_pp_groups')
    pp_g_check1 = fields.Boolean('Product Check 1 Approval', compute='_compute_pp_groups', inverse='_inverse_pp_groups')
    pp_g_check = fields.Boolean('Product Check Approval', compute='_compute_pp_groups', inverse='_inverse_pp_groups')
    pp_g_filling = fields.Boolean('Filling Line Check Approval', compute='_compute_pp_groups', inverse='_inverse_pp_groups')
    pp_g_pack = fields.Boolean('Pack Line Check Approval', compute='_compute_pp_groups', inverse='_inverse_pp_groups')
    pp_g_check2 = fields.Boolean('Product Check 2 Approval', compute='_compute_pp_groups', inverse='_inverse_pp_groups')
    pp_g_final = fields.Boolean('Final Approval / Create MO', compute='_compute_pp_groups', inverse='_inverse_pp_groups')
    pp_g_manager = fields.Boolean('Manager (All permissions + Configuration)',
                                  compute='_compute_pp_groups', inverse='_inverse_pp_groups')

    def _pp_group_ids(self):
        return {f: self.env.ref('pre_production.' + xid).id for f, xid in PP_ALL_FIELDS.items()}

    @api.depends('groups_id')
    def _compute_pp_groups(self):
        gids = self._pp_group_ids()
        for user in self:
            current = set(user.groups_id.ids)
            for fname, gid in gids.items():
                user[fname] = gid in current

    def _inverse_pp_groups(self):
        gids = self._pp_group_ids()
        for user in self:
            current = set(user.groups_id.ids)
            cmds = []
            for fname, gid in gids.items():
                wanted = bool(user[fname])
                if wanted and gid not in current:
                    cmds.append((4, gid))
                elif not wanted and gid in current:
                    cmds.append((3, gid))
            if cmds:
                user.write({'groups_id': cmds})

    # ---- instant UI behaviour -------------------------------------------
    @api.onchange('pp_g_manager')
    def _onchange_pp_g_manager(self):
        for user in self:
            if user.pp_g_manager:
                user.pp_g_user = True
                user.pp_g_dashboard = True
                user.pp_g_cost = True
                for fname in PP_STAGE_FIELDS:
                    user[fname] = True

    @api.onchange('pp_g_user')
    def _onchange_pp_g_user(self):
        for user in self:
            if not user.pp_g_user:
                user.pp_g_manager = False
                user.pp_g_dashboard = False
                user.pp_g_cost = False
                for fname in PP_STAGE_FIELDS:
                    user[fname] = False

    @api.onchange(*PP_STAGE_FIELDS)
    def _onchange_pp_g_stages(self):
        for user in self:
            if any(user[f] for f in PP_STAGE_FIELDS):
                user.pp_g_user = True
            if user.pp_g_manager and not all(user[f] for f in PP_STAGE_FIELDS):
                user.pp_g_manager = False

    @api.onchange('pp_g_dashboard')
    def _onchange_pp_g_dashboard(self):
        for user in self:
            if user.pp_g_dashboard:
                user.pp_g_user = True
            else:
                user.pp_g_manager = False

    @api.onchange('pp_g_cost')
    def _onchange_pp_g_cost(self):
        for user in self:
            if user.pp_g_cost:
                user.pp_g_user = True
            else:
                user.pp_g_manager = False
