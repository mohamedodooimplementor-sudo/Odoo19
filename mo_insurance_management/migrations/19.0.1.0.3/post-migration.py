# -*- coding: utf-8 -*-
"""Claim lines existing before this version were submitted without knowing
about post-submission credit notes. Treat whatever credit notes are already
applied to their invoices as part of the amount that was claimed (the
"snapshot"), so only credit notes issued from now on show up as pending."""
from odoo import SUPERUSER_ID, api

from odoo.addons.mo_insurance_management.models.insurance_claim import credited_amount


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    for line in env["insurance.claim.line"].search([]):
        snapshot = credited_amount(line.move_id, exclude_move=line.rejection_move_id)
        if snapshot:
            line.credit_note_snapshot = snapshot
