# -*- coding: utf-8 -*-
"""
Payment receipt numbering moved from one shared sequence (RCPT-000001 for
every payment regardless of method) to one sequence PER payment method
(e.g. CASH-000001, BANK-000001), using each method's own code as the
prefix. New/edited payment methods get their sequence automatically via
create()/write(), but existing methods need it backfilled once here.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = _api_env(cr)
    methods = env['education.payment.method'].search([('sequence_id', '=', False)])
    for method in methods:
        method._ensure_sequence()
    if methods:
        _logger.info(
            'prime_educational_hub: created a dedicated receipt sequence for %s existing '
            'payment method(s).', len(methods))


def _api_env(cr):
    from odoo import api, SUPERUSER_ID
    return api.Environment(cr, SUPERUSER_ID, {})
