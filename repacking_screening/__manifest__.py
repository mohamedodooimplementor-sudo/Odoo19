{
    'name': 'Repacking & Screening',
    'version': '18.0.1.0.0',
    'category': 'Inventory',
    'summary': 'Repack and screen stock through real transfers and Manufacturing Orders, with cost allocation and yield analysis',
    'description': """
Repacking & Screening
=====================
Repack bulk stock into packages or screen (grade) a product, with every step
backed by a real Odoo document: an internal transfer, two Manufacturing Orders
and the delivery transfers.

Flow:
0. Transfer to Manufacturing (internal transfer of product + packaging)
1. Confirm (intermediate WIP Manufacturing Order, lot-tracked)
2. Validate (final Manufacturing Order: product + byproducts)
3. Delivery to destination locations

Each step can be automatic or manual. Includes cost allocation to byproducts,
yield / loss analysis, recurring operations, dashboard and PDF report.
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
    'license': 'OPL-1',
    'price': 79.00,
    'currency': 'USD',
    'support': 'odoolabtech.offical',
    'images': ['static/description/banner.png', 'static/description/workflow.png', 'static/description/types_and_cost.png', 'static/description/setup_steps.png'],
}
