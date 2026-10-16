# -*- coding: utf-8 -*-
def migrate(cr, version):
    """The product code no longer uses the Color / Size / Shape lists: it is built with the
    category codes and the codes of the variant attribute values. The lists are removed;
    the codes already written on the products (default_code) are kept as they are."""
    for kind in ('color', 'size', 'shape'):
        cr.execute("ALTER TABLE product_template DROP COLUMN IF EXISTS er_%s_id" % kind)
        cr.execute("DELETE FROM ir_model_data WHERE module = 'mo_employee_request' "
                   "AND name = %s", ('er_product_%s_none' % kind,))
        cr.execute("DROP TABLE IF EXISTS er_product_%s CASCADE" % kind)
