# -*- coding: utf-8 -*-
{
    'name': 'UoM Barcode for Product | باركود لكل وحدة قياس للمنتج',
    'version': '18.0.1.1.0',
    'summary': 'Add unique barcode for each Unit of Measure (UoM) per product',
    'description': """
UoM Barcode for Product
=======================
This module allows you to assign a unique barcode for each Unit of Measure (UoM)
of a product. The barcode will automatically appear in all transactions:
- Purchases
- Sales
- Inventory / Stock
- Invoices

Features:
- Unique barcode per unit of measure
- Appears automatically in all transactions (Sales, Purchases, Inventory, Invoices)
- Scan a barcode on sales orders, purchase orders and transfers to add the product with the right unit
- Barcode labels (Code 128) printed from the product form
- Compatible with Odoo 18
    """,
    'author': 'Eng. M.Aboelmagde',
    'website': 'https://www.youtube.com/@odoolab',
    'category': 'Inventory/Inventory',
    'license': 'OPL-1',
    'price': 39.00,
    'currency': 'USD',
    'support': 'odoolabtech.offical',
    'depends': [
        'product',
        'stock',
        'purchase',
        'sale',
        'account',
        'uom',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/product_uom_barcode_views.xml',
        'views/product_views.xml',
        'views/purchase_views.xml',
        'views/sale_views.xml',
        'views/stock_views.xml',
        'views/account_views.xml',
        'views/report_barcode.xml',
    ],
    'images': ['static/description/banner.png', 'static/description/how_it_works.png', 'static/description/where_it_shows.png', 'static/description/setup_steps.png'],
    'installable': True,
    'application': False,
    'auto_install': False,
}
