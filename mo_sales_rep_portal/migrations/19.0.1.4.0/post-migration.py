"""v1.4: per-representative permissions + ownership backfill.

* old rep.allow_price_change / allow_auto_validate / max_discount become the new per-rep settings
  without changing what each representative could do before;
* documents created by a representative's user (payments, deliveries, orders, invoices) get their
  mo_rep_id so they show up in the module menus.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def _columns(cr, table):
    cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,))
    return {r[0] for r in cr.fetchall()}


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    cols = _columns(cr, 'mo_sales_rep')

    if 'allow_price_change' in cols:
        cr.execute("""UPDATE mo_sales_rep
                         SET perm_allow_price_change = CASE WHEN allow_price_change THEN 'default' ELSE 'no' END""")
    if 'allow_auto_validate' in cols:
        cr.execute("""UPDATE mo_sales_rep
                         SET perm_allow_auto_validate = CASE WHEN allow_auto_validate THEN 'yes' ELSE 'no' END""")
    # old semantics: cap = min(global, rep). New: a value above zero replaces the global maximum.
    glob = env['mo.sales.rep.settings'].get_settings()
    cr.execute("UPDATE mo_sales_rep SET max_discount = 0 WHERE max_discount IS NULL OR max_discount >= %s OR max_discount >= 100",
               (glob.max_discount,))

    reps = env['mo.sales.rep'].with_context(active_test=False).search([])
    for model in ('account.payment', 'sale.order', 'account.move', 'stock.picking'):
        Model = env[model].with_context(active_test=False)
        for rep in reps:
            try:
                recs = Model.search([('create_uid', '=', rep.user_id.id), ('mo_rep_id', '=', False)])
                if recs:
                    recs.write({'mo_rep_id': rep.id, 'mo_source': 'portal'})
            except Exception as e:  # never block the upgrade on a legacy record
                _logger.warning('Backfill of %s for %s skipped: %s', model, rep.name, e)
    try:
        pickings = env['stock.picking'].search([('mo_rep_id', '=', False), ('sale_id.mo_rep_id', '!=', False)])
        for picking in pickings:
            picking.mo_rep_id = picking.sale_id.mo_rep_id
    except Exception as e:
        _logger.warning('Delivery backfill skipped: %s', e)
