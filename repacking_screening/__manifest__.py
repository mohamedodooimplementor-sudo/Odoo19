{
    'name': 'Repacking & Screening',
    'version': '18.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Repacking & Screening Operations for Inventory',
    'description': """
Repacking & Screening
======================
Allows creating Repacking operations (split a product into new packages)
and Screening operations (split a product into graded products / waste),
based on an Inventory Loss + Receipt mechanism.

Flow:
1. Create Operation
2. Choose Type (Repacking / Screening)
3. Select Source Location
4. Select Product
5. Enter Result Lines
6. System creates Inventory Loss Transfer (consumes original product)
7. Finish Operation
8. System creates Receipt from Inventory Loss (receives new packages/grades)
""",
    'author': 'odoolabtech.offical',
    'website': '',
    'depends': ['stock', 'mrp', 'mail'],
    'data': [
        'security/repacking_screening_security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'data/stock_location_data.xml',
        'data/product_data.xml',
        'data/cron_data.xml',
        'data/repacking_screening_settings_data.xml',
        'report/repacking_screening_reports.xml',
        'views/repacking_screening_operation_views.xml',
        'views/repacking_screening_dashboard_views.xml',
        'views/repacking_screening_settings_views.xml',
        'views/repacking_screening_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'repacking_screening/static/src/js/dashboard.js',
            'repacking_screening/static/src/xml/dashboard.xml',
            'repacking_screening/static/src/scss/dashboard.scss',
            'repacking_screening/static/src/scss/operation_kanban.scss',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
