# -*- coding: utf-8 -*-
def migrate(cr, version):
    """One General Projects Location became a list: keep the old one as the first entry."""
    cr.execute("""
        CREATE TABLE IF NOT EXISTS er_company_general_location_rel (
            company_id integer NOT NULL, location_id integer NOT NULL,
            PRIMARY KEY (company_id, location_id))""")
    cr.execute("""
        INSERT INTO er_company_general_location_rel (company_id, location_id)
        SELECT id, er_general_location_id FROM res_company
         WHERE er_general_location_id IS NOT NULL
        ON CONFLICT DO NOTHING""")
    cr.execute("""SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'stock_location' AND column_name = 'er_is_general'""")
    if not cr.fetchone():
        return  # first install of the flag: migration 19.0.1.26.0 sets it
    cr.execute("""
        UPDATE stock_location SET er_is_general = TRUE
         WHERE id IN (SELECT er_general_location_id FROM res_company
                       WHERE er_general_location_id IS NOT NULL)""")
