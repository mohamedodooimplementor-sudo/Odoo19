# -*- coding: utf-8 -*-
"""
The 'Find Student' top-level menu was removed from education_menus.xml --
it duplicated the existing Students menu and added no value. Odoo's module
update only creates/updates records that are still present in a module's
XML; it never deletes a record just because its <menuitem> tag disappeared.
Without this migration, anyone who already upgraded to the version that
introduced 'Find Student' would keep seeing it forever.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = _api_env(cr)
    menu = env.ref('prime_educational_hub.menu_education_find_student', raise_if_not_found=False)
    if menu:
        menu.unlink()
        _logger.info('prime_educational_hub: removed the redundant "Find Student" menu.')


def _api_env(cr):
    from odoo import api, SUPERUSER_ID
    return api.Environment(cr, SUPERUSER_ID, {})
