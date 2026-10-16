# -*- encoding: utf-8 -*-
# reference: [8961]
{
    'name': "Multi-Currency General Ledger and Partner Ledger (USD, EUR, Company)",
    'summary': "General Ledger and Partner Ledger in USD, EUR, Combined and Company currency, with a smart button on the partner form.",
    'description': "General Ledger and Partner Ledger in USD, EUR, Combined and Company currency.",
    'category': 'Accounting/Accounting',
    'version': '18.0.1.0.1',
    'author': "Eng.Aboelmagde",
    'license': 'OPL-1',
    'price': 150.00,
    'currency': 'USD',
    'images': ['static/description/banner.png'],
    'depends': ['account_reports', 'account'],
    'data': [
        # views
        'security/ir.model.access.csv',
        'views/setting.xml',

        # root reports (Combined) must load first: the $ and € reports are variants of them
        'reports/general_ledger_multi.xml',
        'reports/partner_ledger_multi.xml',

        'reports/general_ledger_company.xml',
        'reports/partner_ledger_company.xml',

        'reports/general_ledger_cur.xml',
        'reports/partner_ledger_cur.xml',
        # 'reports/cash_cur.xml',
        
        'reports/general_ledger_cur_euro.xml',
        'reports/partner_ledger_cur_euro.xml',
        # 'reports/cash_cur _euro.xml',

        # 'reports/cash_multi.xml',

    ],

    'installable': True,
    'application': False,
    'auto_install': False,
}
