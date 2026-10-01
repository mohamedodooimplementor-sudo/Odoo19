# -*- coding: utf-8 -*-
{
    'name': 'Advanced Intercompany Management',
    'version': '18.0.1.8.0',
    'category': 'Accounting/Accounting',
    'summary': 'Manage intercompany sales, purchases, payments and returns in one operation',
    'description': """
        Advanced Intercompany Management Module
        =========================================
        - Create one operation for multiple companies (Sale / Purchase / Payment)
        - Auto group lines by company
        - Auto create Sale/Purchase Orders per company
        - Auto create Pickings per company
        - Payment distribution across companies (amount per company, percentage shown)
        - Branch transfers between companies: stock (two legs) and money (clearing account)
        - Landed Cost operations with validation wizard
        - Auto create Invoices per company
        - Smart buttons for all related documents
        - Real-time Dashboard with KPI cards, pipeline and monthly chart
        - Intercompany Returns with approval cycle (Draft → To Approve → Approved → Confirmed → Returned → Done)
        - Manager-only Cancel / Refuse on Returns
        - Multi-order returns: individual orders or from a grouped operation
        - Return wizard showing products, original qty, already-returned qty and max returnable
        - Optional MRP integration: Manufacturing fields appear only when mrp is installed
    """,
    'author': 'Eng. M.Aboelmagde',
    'images': ['static/description/banner.png', 'static/description/overview.png', 'static/description/approval_flow.png', 'static/description/setup_steps.png'],
    'price': 249.00,
    'currency': 'USD',
    'support': 'odoolabtech.offical',
    'depends': [
        'base',
        'uom',
        'sale_management',
        'purchase',
        'stock',
        'account',
        'web',
        'stock_landed_costs',
    ],
    'data': [
        'security/intercompany_security.xml',
        'security/intercompany_record_rules.xml',
        'security/ir.model.access.csv',
        'data/sequences.xml',
        'data/locations.xml',
        'data/accounts.xml',
        'data/cron.xml',
        'wizard/intercompany_reject_wizard_views.xml',
        'wizard/intercompany_return_picking_wizard_views.xml',
        'wizard/intercompany_landed_cost_validate_wizard_views.xml',
        'reports/report_intercompany_operation.xml',
        'views/product_views.xml',
        'views/intercompany_operation_views.xml',
        'views/intercompany_return_views.xml',
        'views/intercompany_payment_views.xml',
        'views/branch_transfer_views.xml',
        'views/report_views.xml',
        'views/dashboard_views.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'intercompany_operation_modified/static/src/css/dashboard.css',
            'intercompany_operation_modified/static/src/js/dashboard.js',
            'intercompany_operation_modified/static/src/dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'OPL-1',
}
