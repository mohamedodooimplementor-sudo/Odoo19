# -*- coding: utf-8 -*-
"""
The 'stage' field on education.lead changed from a Selection to a
Many2one('education.lead.stage') named 'stage_id'. This migration copies
each lead's old text stage value onto the matching new stage record so
existing pipelines aren't reset to the default stage after the upgrade.
"""
import logging

_logger = logging.getLogger(__name__)

OLD_TO_XMLID = {
    'new': 'prime_educational_hub.education_lead_stage_new',
    'contacted': 'prime_educational_hub.education_lead_stage_contacted',
    'trial_scheduled': 'prime_educational_hub.education_lead_stage_trial_scheduled',
    'enrolled': 'prime_educational_hub.education_lead_stage_enrolled',
    'lost': 'prime_educational_hub.education_lead_stage_lost',
}


def migrate(cr, version):
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'education_lead' AND column_name = 'stage'
    """)
    if not cr.fetchone():
        # Fresh install, or already migrated - nothing to do.
        return

    env = api_env(cr)

    for old_value, xmlid in OLD_TO_XMLID.items():
        stage = env.ref(xmlid, raise_if_not_found=False)
        if not stage:
            continue
        cr.execute(
            "UPDATE education_lead SET stage_id = %s WHERE stage = %s AND stage_id IS NULL",
            (stage.id, old_value),
        )
        _logger.info(
            "prime_educational_hub: migrated %s lead(s) from stage '%s' to stage_id %s",
            cr.rowcount, old_value, stage.id,
        )

    # Any row that still has no stage_id (unexpected/custom old value) falls
    # back to the first stage by sequence.
    cr.execute("""
        SELECT id FROM education_lead_stage ORDER BY sequence, id LIMIT 1
    """)
    row = cr.fetchone()
    if row:
        cr.execute("UPDATE education_lead SET stage_id = %s WHERE stage_id IS NULL", (row[0],))

    # Drop the old orphaned column now that its data has been copied over.
    cr.execute("ALTER TABLE education_lead DROP COLUMN IF EXISTS stage")


def api_env(cr):
    from odoo import api, SUPERUSER_ID
    return api.Environment(cr, SUPERUSER_ID, {})
