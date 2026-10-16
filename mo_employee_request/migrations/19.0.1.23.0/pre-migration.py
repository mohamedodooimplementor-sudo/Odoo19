# -*- coding: utf-8 -*-
def _column_exists(cr, table, column):
    cr.execute("SELECT 1 FROM information_schema.columns WHERE table_name = %s "
               "AND column_name = %s", (table, column))
    return bool(cr.fetchone())


def migrate(cr, version):
    """Warehouses became locations: every old warehouse is replaced by its stock location."""
    for table in ('employee_request_line', 'employee_purchase_order',
                  'employee_purchase_order_line', 'er_project_allocation'):
        if not _column_exists(cr, table, 'warehouse_id'):
            continue
        cr.execute("ALTER TABLE %s ADD COLUMN IF NOT EXISTS location_id integer" % table)
        cr.execute("""
            UPDATE %s t SET location_id = w.lot_stock_id
              FROM stock_warehouse w
             WHERE w.id = t.warehouse_id AND t.location_id IS NULL""" % table)
        # the old column is no longer a field: it must not block new records
        cr.execute("ALTER TABLE %s ALTER COLUMN warehouse_id DROP NOT NULL" % table)
    if _column_exists(cr, 'res_company', 'er_general_warehouse_id'):
        cr.execute("ALTER TABLE res_company ADD COLUMN IF NOT EXISTS er_general_location_id integer")
        cr.execute("""
            UPDATE res_company c SET er_general_location_id = w.lot_stock_id
              FROM stock_warehouse w
             WHERE w.id = c.er_general_warehouse_id AND c.er_general_location_id IS NULL""")
