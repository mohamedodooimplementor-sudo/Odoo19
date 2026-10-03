{
    'name': 'Multi-Branch Management Suite',
    'version': '19.0.1.0.1',
    'category': 'Operations/Operations',
    'summary': 'Branch-level security, inter-branch transfers, credit limits and live dashboards for a single Odoo company',
    'description': """
Multi-Branch Management Suite
==============================
A complete foundation for running multi-branch operations on a single
Odoo company, with strict, row-level data isolation between branches:

* Branch master (res.branch) linked to Warehouse, Sales Journal,
  Purchase Journal and Analytic Account.
* Dedicated "Branch Access" tab on the user profile to assign a
  Default Branch and Allowed Branches, with an Access Mode
  (Restricted to Selected Branches / All Branches).
* Security groups and record rules enforcing branch-level visibility
  across Sales, Purchases, Journal Entries, Journal Items, Payments,
  Stock Pickings and Inter-Branch Transfers.
* Branch performance dashboards (Sales, Purchase, Payment, Overview)
  and printable branch reports.
* Inter-Branch Transfers with approval workflow and credit-limit
  escalation.
    """,
    'author': 'Eng. M.Aboelmagde',
    'website': '',
    'license': 'OPL-1',
    'price': 149.00,
    'currency': 'USD',
    'images': ['static/description/img/banner.png'],
    'depends': ['base', 'mail', 'account', 'stock', 'analytic', 'product', 'sale_management', 'purchase'],
    'data': [
        'security/branch_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_escalation.xml',
        'views/res_branch_views.xml',
        'views/res_users_views.xml',
        'views/res_partner_views.xml',
        'views/product_template_views.xml',
        'views/sale_order_views.xml',
        'views/purchase_order_views.xml',
        'views/purchase_menu_views.xml',
        'views/account_move_views.xml',
        'views/account_journal_views.xml',
        'wizards/account_payment_register_views.xml',
        'wizards/inter_branch_transfer_cancel_wizard_views.xml',
        'views/inter_branch_transfer_views.xml',
        'views/stock_picking_views.xml',
        'views/stock_picking_type_views.xml',
        'views/stock_quant_views.xml',
        'views/stock_warehouse_views.xml',
        'views/branch_credit_limit_warning_views.xml',
        'views/branch_sales_dashboard_views.xml',
        'views/branch_purchase_dashboard_views.xml',
        'views/branch_payment_dashboard_views.xml',
        'views/branch_overview_dashboard_views.xml',
        'report/branch_sales_report_templates.xml',
        'report/branch_purchase_report_templates.xml',
        'report/branch_payment_report_templates.xml',
        'report/inter_branch_transfer_report_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'branch_management/static/src/js/branch_sales_dashboard.js',
            'branch_management/static/src/xml/branch_sales_dashboard.xml',
            'branch_management/static/src/js/branch_purchase_dashboard.js',
            'branch_management/static/src/xml/branch_purchase_dashboard.xml',
            'branch_management/static/src/js/branch_payment_dashboard.js',
            'branch_management/static/src/xml/branch_payment_dashboard.xml',
            'branch_management/static/src/js/branch_overview_dashboard.js',
            'branch_management/static/src/xml/branch_overview_dashboard.xml',
            'branch_management/static/src/css/branch_overview_dashboard.css',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
