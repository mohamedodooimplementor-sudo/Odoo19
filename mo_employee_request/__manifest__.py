# -*- coding: utf-8 -*-
{
    'name': 'Employee Requests',
    'version': '19.0.1.3.0',
    'category': 'Inventory',
    'summary': 'Employee material requests with multi-step approvals (Department, Warehouse, Budget)',
    'description': """
Employee Purchase & Material Request
=====================================================
* Employee requests with lines, per-warehouse availability and the standard Odoo product catalog
* Approval workflow: Department -> Warehouse -> Budget
* Automatic split into Stock Orders (standard transfers) and Employee Purchase Orders
* Purchase approvals, Budget Control, standard Odoo PO / receipts / bills
* Dashboard, reports, settings, security
    """,
    'author': 'Eng. M.Aboelmagde',
    'license': 'LGPL-3',
    'price': 149.0,
    'currency': 'USD',
    'depends': ['base', 'hr', 'project', 'product', 'stock', 'stock_account', 'analytic', 'mail', 'account',
                'purchase', 'purchase_stock', 'purchase_requisition'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'data/er_required_field_data.xml',
        'wizard/reject_wizard_views.xml',
        'wizard/epo_discount_views.xml',
        'views/employee_request_views.xml',
        'views/employee_purchase_order_views.xml',
        'views/report_views.xml',
        'views/dashboard_views.xml',
        'views/res_config_settings_views.xml',
        'views/res_users_views.xml',
        'views/er_required_field_views.xml',
        'report/epo_report.xml',
        'data/mail_template.xml',
        'views/stock_picking_views.xml',
        'views/menus.xml',
    ],
    'demo': ['data/demo_data.xml'],
    'assets': {
        'web.assets_backend': [
            'mo_employee_request/static/src/css/ribbon.css',
            'mo_employee_request/static/src/css/er_stock.css',
            'mo_employee_request/static/src/css/er_mobile.css',
            'mo_employee_request/static/src/js/forecast_field.js',
            'mo_employee_request/static/src/js/dashboard.js',
            'mo_employee_request/static/src/js/catalog_patch.js',
            'mo_employee_request/static/src/xml/er_templates.xml',
        ],
        'web.assets_web_dark': [
            'mo_employee_request/static/src/css/dashboard.dark.scss',
        ],
    },
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
}
