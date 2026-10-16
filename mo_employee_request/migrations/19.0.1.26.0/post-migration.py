# -*- coding: utf-8 -*-
def migrate(cr, version):
    """The location chosen as General Projects Location in the settings is flagged as General."""
    cr.execute("""
        UPDATE stock_location l SET er_is_general = TRUE
          FROM res_company c
         WHERE c.er_general_location_id = l.id""")
