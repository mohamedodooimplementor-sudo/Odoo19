# -*- coding: utf-8 -*-
"""
education.group.code used to be a free-text field the user typed in
manually, so many existing groups have it empty (or possibly duplicated
by hand). This migration backfills any blank code with the next value
from the 'education.group' sequence, so every group ends up with a
unique, auto-generated code going forward.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api_env(cr)
    groups = env['education.group'].sudo().search(
        [('code', 'in', [False, ''])], order='id')
    for group in groups:
        group.code = env['ir.sequence'].next_by_code('education.group') or 'New'
    if groups:
        _logger.info(
            'prime_educational_hub: backfilled auto-generated codes '
            'for %s existing group(s).', len(groups))


def api_env(cr):
    from odoo import api, SUPERUSER_ID
    return api.Environment(cr, SUPERUSER_ID, {})
