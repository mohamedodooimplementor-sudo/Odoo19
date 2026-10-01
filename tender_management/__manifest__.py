# -*- coding: utf-8 -*-
{
    'name': 'Tender Management & BOM Manufacturing Costing',
    'version': '19.0.1.0.10',
    'category': 'Sales',
    'summary': 'Tenders for sales/manufacturing with BOM Labour/Overhead/Other costs '
               'flowing into MO cost, inventory valuation and accounting.',
    'description': """
Tender Management + BOM Manufacturing Costing
=============================================
* Tender workflow: Draft > Submitted > Approved > Quotation > Won > Delivered > Invoiced > Paid (or Lost / Cancelled).
* BOM "Manufacturing Costs" tab (Labour / Overhead / Other) with accounting accounts.
* Total BOM Cost = Materials + Labour + Overhead + Other.
* Tender products take their cost from the BOM; tender-level additional costs stay separate.
* Manufacturing Order: BOM costs are added once through the standard MO "Extra Cost"
  (inventory valuation), and the credit side is posted to the accounts chosen on the BOM.
    """,
    'author': 'Eng. M.Aboelmagde',
    'license': 'OPL-1',
    'price': 199.00,
    'currency': 'USD',
    'support': 'odoolabtech.offical',
    'images': ['static/description/banner.png', 'static/description/workflow.png', 'static/description/cost_flow.png', 'static/description/features.png', 'static/description/setup_steps.png'],
    'depends': ['base', 'mail', 'product', 'sale', 'sale_stock', 'mrp', 'mrp_account', 'purchase', 'stock_landed_costs'],
    'external_dependencies': {
        'python': ['openpyxl', 'xlsxwriter'],
    },
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequence_data.xml',
        'data/stage_data.xml',
        'data/landed_cost_product_data.xml',
        'data/tm_data.xml',
        'data/cron_data.xml',
        'report/tm_reports.xml',
        'views/tm_tender_views.xml',
        'views/mrp_bom_views.xml',
        'views/mrp_production_views.xml',
        'views/sale_order_views.xml',
        'views/purchase_order_views.xml',
        'views/stock_landed_cost_views.xml',
        'views/stock_account_views.xml',
        'views/tm_analysis_views.xml',
        'views/res_config_settings_views.xml',
        'views/tm_stage_views.xml',
        'views/tm_report_wizard_views.xml',
        'views/tm_misc_views.xml',
        'views/tm_dashboard_views.xml',
        'views/menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'tender_management/static/src/css/tm_common.css',
            'tender_management/static/src/css/tm_dashboard.css',
            'tender_management/static/src/js/tm_dashboard.js',
            'tender_management/static/src/xml/tm_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
}
