# -*- coding: utf-8 -*-
"""Recompute Total Paid / Remaining Balance / status for claims that were
stuck because payments were filtered by the old (non-existent) "posted"
payment state."""
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    claims = env["insurance.claim"].search([("state", "in", ("submitted", "partial_paid", "paid"))])
    claims._compute_totals()
    claims._sync_state_from_payments()
