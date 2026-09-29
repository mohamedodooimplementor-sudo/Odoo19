{
    "name": "Professional Check Management",
    "version": "19.0.8.1.0",
    "category": "Accounting/Accounting",
    "summary": "Professional incoming and outgoing check management with interactive dashboard",
    "description": """
Professional Check Management
==============================
Manage incoming and outgoing checks end to end, with automatic accounting entries and a
real check-printing template.

Key Features
------------
* Kanban pipeline per direction: Draft > Received > Deposited > Under Collection > Collected
  (incoming) and Draft > Handed Over > Cleared (outgoing), with Bounce / Cancel at any stage.
* Separate reference sequences for incoming (CHK-IN) and outgoing (CHK-OUT) checks.
* Banks carry their own accounting journal and account number: picking a bank on a check
  fills the Bank Journal and Account Number automatically (still editable).
* Automatic, reversible journal entries: notes receivable / payable, checks under collection,
  bank charges on bounce, and reconciliation with the settled customer invoices / vendor bills.
* Real check printing: position fields over a bank's pre-printed leaf, or use the Full Check
  Design mode for a complete check face (border, bank header, field labels, signature line)
  printed on blank paper, in common preset sizes or a custom size, in any font.
* Amount-in-words (Tafqeet) in Arabic or English.
* Interactive OWL dashboard (KPIs, status breakdown, expected cash flow, top banks / partners,
  next 30 days) with a scrollable layout and full dark-mode support.
* Due-date reminders, movement history, and per-role permissions (User / Manager) enforced
  both on menus and on the sensitive actions (Bounce, Cancel, Reset to Draft).
* Multi-company ready: company-scoped records, security rules and accounting entries, with
  per-company incoming/outgoing sequences and a dashboard that follows the active company
  (or companies) selected in the switcher.
""",
    "author": "Eng. M.Aboelmagde",
    "license": "LGPL-3",
    "depends": ["base", "mail", "account", "web"],
    "data": [
        "security/check_security.xml",
        "security/ir.model.access.csv",
        "data/check_sequence.xml",
        "data/check_data.xml",
        "data/check_print_data.xml",
        "report/check_report.xml",
        "report/check_details_report.xml",
        "report/check_print_report.xml",
        "views/check_views.xml",
        "views/check_config_views.xml",
        "views/check_report_views.xml",
        "views/check_print_views.xml",
        "views/check_menus.xml"
    ],
    "assets": {
        "web.assets_backend": [
            "check_management/static/src/js/check_dashboard.js",
            "check_management/static/src/xml/check_dashboard.xml",
            "check_management/static/src/scss/check_dashboard.scss"
        ]
    },
    "application": True,
    "installable": True
}
