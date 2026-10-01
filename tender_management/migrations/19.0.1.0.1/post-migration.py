# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Tenders created while the sequence hook was missing kept the name 'New': number them."""
    env = api.Environment(cr, SUPERUSER_ID, {'tracking_disable': True})
    tenders = env['tm.tender'].search([('name', 'in', ('New', False))], order='id')
    for tender in tenders:
        number = env['ir.sequence'].next_by_code('tm.tender')
        if number:
            tender.name = number
