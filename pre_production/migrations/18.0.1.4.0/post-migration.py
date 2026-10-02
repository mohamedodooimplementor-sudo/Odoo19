from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    """Draft is now the first stage: existing draft orders (which had no stage) are put in it."""
    env = api.Environment(cr, SUPERUSER_ID, {'tracking_disable': True, 'active_test': False})
    draft = env['pp.stage'].search([('code', '=', 'draft')], limit=1)
    if draft:
        orders = env['pp.order'].search([('state', '=', 'draft'), ('current_stage_id', '=', False)])
        orders.write({'current_stage_id': draft.id})
