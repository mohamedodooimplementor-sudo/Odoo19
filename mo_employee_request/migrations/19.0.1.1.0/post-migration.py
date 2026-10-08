# -*- coding: utf-8 -*-
def migrate(cr, version):
    """Orders already received and billed must not send the "received" notification again."""
    cr.execute("UPDATE employee_purchase_order SET received_notified = TRUE "
               "WHERE state = 'invoiced'")
