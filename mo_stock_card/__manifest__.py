{
    'name': 'Stock Card Report',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Reporting',
    'summary': 'Stock Card / Product Card with Opening Balance, In/Out Movements, and Closing Balance',
    'description': """
Stock Card Report
=================
An essential tool for tracking the complete history of your inventory.

Features:
---------
* Detailed Stock Card / Product Card view
* Opening Balances, In/Out movements, and Closing Balances
* Support for Standard and Average Costing
* Dynamic filtering by Product, Category, and Location (including child locations)
* Grouping options by Product or Category
* Professional PDF and Excel reports
* On-screen analysis with valid running balances
    """,
    'author': 'Eng. M.Aboelmagde',
    'license': 'OPL-1',
    'depends': [
        'stock',
        'stock_account',
        'product',
        'mail',
    ],
    'data': [
        'security/stock_card_security.xml',
        'security/ir.model.access.csv',
        'wizard/stock_card_wizard_views.xml',
        'report/stock_card_report.xml',
        'report/stock_card_report_template.xml',
        'views/stock_card_views.xml',
        'views/menu_views.xml',
        'views/stock_card_schedule_views.xml',
        'views/res_users_views.xml',
        'data/stock_card_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'mo_stock_card/static/src/css/stock_card.css',
        ],
        'web.assets_web_dark': [
            'mo_stock_card/static/src/scss/stock_card.dark.scss',
        ],
    },
    'images': ['static/description/banner.png'],
    'installable': True,
    'application': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}
