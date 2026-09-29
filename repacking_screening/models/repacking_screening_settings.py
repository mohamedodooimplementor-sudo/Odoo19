# -*- coding: utf-8 -*-
from odoo import api, fields, models


class RepackingScreeningSettings(models.Model):
    _name = 'repacking.screening.settings'
    _description = 'Repacking & Screening Settings'

    name = fields.Char(default='Workflow Automation', readonly=True)

    step0_auto_validate = fields.Boolean(
        string='Step 0 — Internal Transfer to Manufacturing Location', default=True,
        help='Automatically validate the Step 0 internal transfer that '
             'moves the input product (and packaging materials, for '
             'Repacking) from the Source Location to the Manufacturing Location. '
             'If disabled, it is created and reserved, ready for you to '
             'validate manually from Inventory before Step 1 can be '
             'confirmed.')
    step1_auto_validate = fields.Boolean(
        string='Step 1 — Intermediate Manufacturing Order', default=True,
        help='Automatically mark the Step 1 Manufacturing Order as Done '
             '(produces the intermediate product into the Manufacturing '
             'Location). If disabled, you complete it yourself in the '
             'Manufacturing app before Step 2 can be validated.')
    step2_auto_validate = fields.Boolean(
        string='Step 2 — Final Manufacturing Order', default=True,
        help='Automatically mark the Step 2 Manufacturing Order as Done '
             '(produces the final product and any byproducts into the '
             'Manufacturing Location). If disabled, you complete it '
             'yourself in the Manufacturing app, then click "Complete '
             'Manufacturing" on the operation.')
    step3_auto_validate = fields.Boolean(
        string='Step 3 — Manufacturing → Destination(s)', default=True,
        help='Automatically validate the final transfer(s) that move the '
             'finished product and secondary products out of the '
             'manufacturing location. If disabled, they are created and '
             'reserved, ready for you to validate manually from Inventory.')

    @api.model
    def get_settings(self):
        """Singleton accessor: returns the one settings record, creating it
        with default values the first time it's needed."""
        rec = self.search([], limit=1)
        if not rec:
            rec = self.create({})
        return rec
