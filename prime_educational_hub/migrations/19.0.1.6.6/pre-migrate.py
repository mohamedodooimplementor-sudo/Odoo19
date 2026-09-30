# -*- coding: utf-8 -*-
"""
Menu reorganization: the top-level bar had 17 items (Dashboard, Sessions
Calendar, Quick Enroll, Admissions, Students, Guardians, Teachers,
Academic, Groups, Attendance, Exams, Assignments, Fees, Accounting,
Certificates, Reports, Configuration) -- too many to scan at a glance.
Everything is now grouped under 8: Dashboard, Students, Academics,
Teachers, Exams & Assignments, Fees & Accounting, Reports, Configuration.

Every menu ITEM keeps its original external id (so this is a pure re-parent,
no data loss) except one: the "Accounting" container itself
(menu_education_accounting_root) is gone now that Expenses / Cash & Bank
Accounts / Expense Categories moved under "Fees & Accounting" -- Odoo never
deletes a record just because its <menuitem> tag was removed from the XML,
so it has to be done explicitly here.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = _api_env(cr)
    accounting_menu = env.ref('prime_educational_hub.menu_education_accounting_root', raise_if_not_found=False)
    if accounting_menu:
        accounting_menu.unlink()
        _logger.info(
            'prime_educational_hub: removed the now-empty "Accounting" menu container '
            '(its items moved under "Fees & Accounting").')


def _api_env(cr):
    from odoo import api, SUPERUSER_ID
    return api.Environment(cr, SUPERUSER_ID, {})
