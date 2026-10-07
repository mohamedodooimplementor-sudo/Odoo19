"""v2.2: back-office groups. Existing Sales managers / salesmen keep access by being added to the new groups once."""
import logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    pairs = [('sales_team.group_sale_manager', 'mo_sales_rep_portal.group_mo_rep_manager'),
             ('sales_team.group_sale_salesman', 'mo_sales_rep_portal.group_mo_rep_user')]
    for old_xid, new_xid in pairs:
        old, new = env.ref(old_xid, False), env.ref(new_xid, False)
        if old and new:
            users = old.user_ids.filtered(lambda u: u.share is False) if 'user_ids' in old._fields else old.users
            new.write({'user_ids': [(4, u.id) for u in users]} if 'user_ids' in new._fields else {'users': [(4, u.id) for u in users]})
    _logger.info('Sales rep back-office groups migrated')
