{
    'name': 'Sales Representative Portal & Route Management',
    'version': '19.0.2.7.1',
    'summary': 'Field sales portal for Odoo 19: routes, GPS visits, orders, collections, cheques, returns, expenses, targets and offline sync - on standard Odoo documents',
    'description': """
Sales Representative Portal & Route Management
==============================================
Portal interface + Route/Visit management + integration layer over standard Odoo
(sale.order, account.move, account.payment, stock.picking).

What is new in 2.6
------------------
* Reliable uploads: phone photos are reduced in the browser (and on the server as a safety net)
  before they are saved, and the portal now says clearly when a file was refused (over 10 MB)
  instead of silently ignoring it.
* No duplicate customers: a new customer with a phone number (any format) or a name + city that
  already exists is stopped; the representative is taken to the existing record when it is his,
  or told to ask his manager when it is not (nothing about other customers is revealed).
  "Create anyway" is available for a different branch.
* Automated tests for customer visibility, the Salesperson field, duplicate detection and
  the protection of customer pages against direct links.

What is new in 2.7.1
--------------------
* New permission "Create Invoice Automatically When the Order Is Confirmed" (global setting + per representative).
  Together with automatic delivery validation, confirming an order can now also issue its invoice.
* Visit: payments registered against the invoices of the visit now show on it, and a payment registered from the
  portal is linked to the representative's open visit with that customer. Orders / Invoices / Payments are
  smart buttons instead of tabs.

What is new in 2.7
------------------
* Sales commission: the manager defines commission rules per representative (or for everyone) based on
  confirmed sales orders, collected payments or target achievement, calculated as a percentage, tiered slabs
  or a fixed amount. Monthly statements are generated, reviewed/adjusted and approved by the manager.
  The representative sees a live estimate for the month with its detail, plus his approved statements.

What is new in 2.5
------------------
* Odoo chatter (messages, notes, activities, attachments) on every form: visits, routes,
  targets, expenses, follow-ups, cheques, payment methods, return reasons and settings.
* Representative customers: a representative flagged "can view all customers" sees real
  customers only (no users, employees or company contacts); any other representative sees
  only the customers assigned to him or whose Salesperson he is.
* Salesperson on customers and on sales orders now accepts portal users, so a sales rep
  (portal user) can be selected. Representatives can also be assigned from the customer form.
* Attachments: the Receipts button on expenses was disabled and is now active; cheques get
  an Attachments button too.
* Portal theme button on every page: Auto (follows the phone) / Dark / Light, remembered
  on the device. Offline cache refreshed automatically.
""",
    'category': 'Sales',
    'author': 'Eng. M.Aboelmagde',
    'website': 'https://www.youtube.com/@odoolab',
    'license': 'OPL-1',
    'price': 800.0,
    'currency': 'USD',
    'images': [
        'static/description/banner.png',
        'static/description/screenshots/19_portal_desktop.png',
        'static/description/screenshots/20_portal_dashboard_phone.png',
        'static/description/screenshots/01_home.png',
        'static/description/screenshots/07_quick_actions.png',
        'static/description/screenshots/08_customer_360.png',
        'static/description/screenshots/10_visit.png',
        'static/description/screenshots/02_route.png',
        'static/description/screenshots/04_new_order.png',
        'static/description/screenshots/11_receipt.png',
        'static/description/screenshots/14_cheques.png',
        'static/description/screenshots/15_return.png',
        'static/description/screenshots/09_targets.png',
        'static/description/screenshots/13_expenses.png',
        'static/description/screenshots/12_outstanding.png',
        'static/description/screenshots/16_followups.png',
        'static/description/screenshots/17_offline.png',
        'static/description/screenshots/18_manager_dashboard.png',
        'static/description/screenshots/06_home_arabic.png',
    ],
    'depends': ['base', 'mail', 'portal', 'hr', 'sales_team', 'sale_management', 'sale_stock', 'account', 'stock'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/data.xml',
        'data/alerts.xml',
        'views/backend_views.xml',
        'views/backend_views_v2.xml',
        'views/backend_views_v3.xml',
        'views/backend_views_v4.xml',
        'views/report_receipt.xml',
        'views/inherit_views.xml',
        'views/employee_views.xml',
        'views/menus.xml',
        'views/portal_templates.xml',
        'views/portal_templates_v2.xml',
        'views/portal_templates_v3.xml',
        'views/portal_templates_v4.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'mo_sales_rep_portal/static/src/dashboard/dashboard.js',
            'mo_sales_rep_portal/static/src/dashboard/dashboard.xml',
            'mo_sales_rep_portal/static/src/dashboard/dashboard.scss',
        ],
    },
    'installable': True,
    'application': True,
}
