# -*- coding: utf-8 -*-
"""
Also marks the point where this module's technical name changed from
prime_education_management to prime_educational_hub. If you're upgrading
from the old name, run this BEFORE starting Odoo with the renamed addon
folder (so Odoo treats this as a continued upgrade instead of a fresh
install of an unrelated module):

    UPDATE ir_module_module SET name = 'prime_educational_hub'
        WHERE name = 'prime_education_management';
    UPDATE ir_model_data SET module = 'prime_educational_hub'
        WHERE module = 'prime_education_management';

Two ir.cron records ship with this version:
  - cron_generate_upcoming_sessions: existed before but was shipped inactive;
    now that it's backed by a proper implementation it should be turned on.
  - cron_refresh_room_status: brand new, active="True" in its data record,
    but that only takes effect on a *fresh* install -- data files live under
    noupdate="1" so an *upgrade* never re-reads their field values. Both
    need to be flipped on explicitly here for anyone upgrading from an
    older version of the module.
"""
import logging

_logger = logging.getLogger(__name__)

CRON_XML_IDS = (
    'prime_educational_hub.cron_generate_upcoming_sessions',
    'prime_educational_hub.cron_refresh_room_status',
)


def migrate(cr, version):
    env = _api_env(cr)
    for xml_id in CRON_XML_IDS:
        cron = env.ref(xml_id, raise_if_not_found=False)
        if cron and not cron.active:
            cron.active = True
            _logger.info('prime_educational_hub: activated cron "%s".', cron.name)


def _api_env(cr):
    from odoo import api, SUPERUSER_ID
    return api.Environment(cr, SUPERUSER_ID, {})
