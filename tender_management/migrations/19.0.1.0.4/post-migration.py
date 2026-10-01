# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """bom_cost_unit (and the fields derived from it) now also reacts to changes made
    directly on the linked BOM after the tender line was created: recompute existing lines
    once so old lines that were left stale ("Refresh Costs" never pressed) get corrected."""
    env = api.Environment(cr, SUPERUSER_ID, {'tracking_disable': True})
    lines = env['tm.tender.line'].search([('tender_id.state', 'in', ('draft', 'submitted'))])
    for field_name in ('material_cost_unit', 'labour_cost_unit', 'overhead_cost_unit',
                       'other_cost_unit', 'bom_cost_unit', 'total_bom_cost', 'profit',
                       'margin_percent'):
        env.add_to_compute(lines._fields[field_name], lines)
    env.flush_all()
