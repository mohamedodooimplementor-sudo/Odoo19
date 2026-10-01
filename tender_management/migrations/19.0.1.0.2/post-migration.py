# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Margin % is now the profit on cost (was on the sale price): recompute the stored values."""
    env = api.Environment(cr, SUPERUSER_ID, {'tracking_disable': True})
    lines = env['tm.tender.line'].search([])
    env.add_to_compute(lines._fields['margin_percent'], lines)
    tenders = env['tm.tender'].search([])
    env.add_to_compute(tenders._fields['margin_percent'], tenders)
    env.flush_all()
