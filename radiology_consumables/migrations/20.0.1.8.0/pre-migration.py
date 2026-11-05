def migrate(cr, version):
    """The analytic account feature moved to radiology_consumables_analytic.

    Hand the two existing fields over to the new module (same model and field
    names), so Odoo does not drop their columns when this module stops
    defining them. Existing room analytic accounts are kept."""
    cr.execute("""
        UPDATE ir_model_data
           SET module = 'radiology_consumables_analytic'
         WHERE module = 'radiology_consumables'
           AND model = 'ir.model.fields'
           AND name IN ('field_stock_location__rc_analytic_account_id',
                        'field_rc_exam_consumption__analytic_account_id')
    """)
