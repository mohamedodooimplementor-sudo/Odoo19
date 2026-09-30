# -*- coding: utf-8 -*-
{
    "name": "Insurance Management",
    "version": "19.0.1.0.11",
    "category": "Accounting/Accounting",
    "summary": "Insurance co-pay billing for Odoo: split every sale between the customer and the insurance company, invoice both, collect claims and follow it all on a live dashboard",
    "description": """
Insurance Management
====================
For clinics, pharmacies, labs and any business whose customers are partly paid
for by an insurance company. Every insured sale is split between the
**Customer** (co-pay) and the **Insurance Company** (covered share) by
configurable coverage rules, billed with two real invoices, and the insurance
side is then collected through Claims - with payments, rejections, credit
notes, reports and a dashboard.

How it works
------------
1. Set up Insurance Companies, Plans and Coverage Rules (codes are filled in
   automatically and can be changed).
2. Register the customer's Policy (several per customer, one primary).
3. Sell as usual: the insured / customer split is calculated on the order lines
   and frozen at confirmation.
4. Invoicing posts the customer's invoice and a separate invoice to the
   insurance company (booked to the insurance journal's default account).
5. Submit a Claim to collect the insurance company's open invoices, register
   payments (settled oldest invoice first), book rejected amounts, print the
   statement.

Main features
-------------
* Coverage rules: Percentage / Fixed Insurance / Max Covered / Fixed Co-Pay,
  resolved Product > Category > Plan default
* Customer Policies with Suspend / Reactivate / Renew / Cancel, expiry alerts,
  used-coverage bar, daily auto-expiry, printable policy card
* Authorizations (prior approval) with approved amounts, printable
* Claims: statuses always follow the real payments; partial payments; partial
  rejections booked automatically as credit notes (with undo); credit-note
  refresh; claim statement PDF
* Sales Order integration, Insurance Invoices smart button, Customer Products tab
* Dashboard with two pages - Cards (16 KPIs + recent claims / top patients) and
  Charts (trend, status, coverage split, aging, collection overview, top
  companies / plans / products) - shared filters, click-through, tooltips,
  light / dark mode
* Reports as PDF (ReportLab) and Excel: Claims, Product Coverage, Aging;
  Arabic text supported; no dependency on wkhtmltopdf and no hook into Odoo's
  own reports
* Security: Insurance User / Officer / Manager / Accountant groups; people
  without an Insurance group can still work with insured orders and invoices
  but never see the Insurance app or a customer's member / card data;
  multi-company rules; accounting records cannot be deleted
""",
    "author": "Eng. M.Aboelmagde",
    "license": "OPL-1",
    "price": 149.00,
    "currency": "USD",
    "support": "odoolabtech.offical",
    "images": ["static/description/banner.png", "static/description/how_it_works.png", "static/description/coverage_example.png", "static/description/features.png"],
    "depends": ["sale_management", "account", "contacts"],
    "assets": {
        "web.assets_backend": [
            "insurance_management/static/src/scss/insurance_dashboard.scss",
            "insurance_management/static/src/scss/insurance_claim_kanban.scss",
            "insurance_management/static/src/js/color_scheme.js",
            "insurance_management/static/src/js/insurance_dashboard/dashboard_charts.js",
            "insurance_management/static/src/js/insurance_dashboard/insurance_dashboard.js",
            "insurance_management/static/src/js/insurance_dashboard/insurance_dashboard.xml",
        ],
    },
    "data": [
        "security/insurance_security_groups.xml",
        "security/ir.model.access.csv",
        "security/insurance_security_rules.xml",
        "data/insurance_sequences.xml",
        "views/insurance_company_views.xml",
        "views/insurance_plan_views.xml",
        "views/insurance_coverage_rule_views.xml",
        "views/insurance_policy_views.xml",
        "views/res_partner_views.xml",
        "views/sale_order_views.xml",
        "views/account_move_views.xml",
        "views/insurance_authorization_views.xml",
        "wizard/insurance_claim_payment_wizard_views.xml",
        "wizard/insurance_report_wizard_views.xml",
        "views/insurance_claim_views.xml",
        "report/insurance_claim_report_views.xml",
        "views/insurance_product_coverage_report_views.xml",
        "views/insurance_dashboard_views.xml",
        "views/res_config_settings_views.xml",
        "views/insurance_menus.xml",
        "data/insurance_setup_data.xml",
    ],
    "installable": True,
    "application": True,
}
