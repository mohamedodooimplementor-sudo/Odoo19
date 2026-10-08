# -*- coding: utf-8 -*-
def migrate(cr, version):
    """Purchase order states: 'ordered' -> 'approved' (Open), billed 'done' -> 'invoiced'."""
    cr.execute("UPDATE employee_purchase_order SET state = 'invoiced' WHERE state = 'done'")
    cr.execute("UPDATE employee_purchase_order SET state = 'approved' WHERE state = 'ordered'")
    cr.execute("UPDATE employee_purchase_order_approval SET stage = 'approved' "
               "WHERE stage = 'ordered'")
    cr.execute("UPDATE employee_purchase_order_approval SET stage = 'invoiced' "
               "WHERE stage = 'done'")
