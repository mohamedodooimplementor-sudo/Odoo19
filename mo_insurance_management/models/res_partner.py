# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    insurance_enabled = fields.Boolean(
        string="Enable Insurance on Sales Orders",
        help="When checked, new Sales Orders created for this customer will "
        "automatically have 'Insurance Enabled' ticked, using this "
        "customer's primary Insurance Policy when it is valid.",
    )
    insurance_policy_ids = fields.One2many(
        "insurance.policy", "partner_id", string="Insurance Policies"
    )
    insurance_policy_count = fields.Integer(compute="_compute_insurance_policy_count")
    primary_insurance_policy_id = fields.Many2one(
        "insurance.policy",
        string="Primary Insurance Policy",
        compute="_compute_primary_insurance_policy_id",
        store=True,
    )

    @api.depends("insurance_policy_ids")
    def _compute_insurance_policy_count(self):
        for rec in self:
            # sudo(): every user can open a partner; only Insurance users may
            # read the policies themselves.
            rec.insurance_policy_count = len(rec.sudo().insurance_policy_ids)

    @api.depends("insurance_policy_ids.is_primary", "insurance_policy_ids.state")
    def _compute_primary_insurance_policy_id(self):
        for rec in self:
            primary = rec.insurance_policy_ids.filtered(lambda p: p.is_primary)
            rec.primary_insurance_policy_id = primary[:1]

    def action_view_insurance_policies(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Insurance Policies",
            "res_model": "insurance.policy",
            "view_mode": "list,form",
            "domain": [("partner_id", "=", self.id)],
            "context": {"default_partner_id": self.id},
        }
