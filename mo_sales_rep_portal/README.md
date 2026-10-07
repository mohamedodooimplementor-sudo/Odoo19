# mo_sales_rep_portal (Odoo 19)
Author: Eng. M.Aboelmagde

## Setup (5 steps)
1. Install the module (depends: sale_management, sale_stock, account, stock, portal).
2. Sales Representative > Configuration > Payment Methods: create Cash / Bank / Cheque, each linked to a journal.
3. Sales Representative > Configuration > Settings: set the Main Warehouse and permissions.
4. Create a Portal user (Contacts > Grant portal access), then Sales Representative > Sales Representatives:
   link the user, assign customers, van warehouse and payment methods.
5. Create a Route (day + customers). The rep opens /rep (login redirects there automatically).

## Test scenarios (spec section 30)
1 login -> own dashboard | 2 Route shows today's customers | 3 Start visit stores GPS + time |
4 Create order from visit -> real sale.order | 5 Confirm in backend -> portal shows Confirmed |
6 Invoice appears in My Invoices | 7 Register payment -> residual updates |
8 Stock operation -> real stock.picking | 9 Manager dashboard shows everything per rep.
Note: browsers only give GPS over HTTPS (or localhost).

## Added in v1.1
- Portal: edit a quotation (products, qty, price, discount) before it is confirmed; "Save and confirm" supported.
- Arabic: the whole portal switches to Arabic (RTL) when the portal user's language is Arabic. Backend labels/menus: i18n/ar.po
  (install the Arabic language, then update the module).
- Employee link on the representative (HR is a dependency of the module).
- Notification bodies (e.g. document names) are stored as created; only their titles are translated.

## Added in v1.2
- Route optimizer: portal button on /rep/route (nearest-first from the rep's location, needs customer locations); backend "Optimize Order" on a Route.
- Offline: installable PWA + service worker. Previously opened pages are readable offline; creating/saving documents needs a connection (a banner says so). Cache is cleared on logout.
- Advanced KPIs on the management dashboard (conversion, avg visit duration, avg order value, collection ratio, trend, top customers).
- Multi-company record rules on reps, routes, visits and payment methods.
- Optional email copy of notifications (Settings > Send Notifications by Email). Mail is queued and sent by the standard mail cron.
- static/description/screenshots: sample-data renders of the portal made with the real CSS. Replace with real captures after testing.
- Management dashboard (OWL) texts are English only.

## v1.3
- Menu icon (Home menu + Apps list).
- Management dashboard: follows Odoo's dark theme; every KPI, number, table cell, chart bar, trend point and top customer opens the matching records (orders / visits / payments / customers).
- Payments: a rep sees every payment he registered ("My Payments", "My Collections", the invoice page) even if the audit link is missing; the invoice page lists its payments.
- Auto-validate stock operations: master switch in Settings > Inventory + per-rep permission ("Auto-validate Stock Operations"). The portal form shows a "Validate automatically" checkbox (checked by default). It validates only when every line is fully available; otherwise the operation stays ready/waiting and the rep is told why.
- Product selection: besides typing, each line has a "Choose from list" dropdown (saleable products; for stock operations only products on hand at the source location).

## v1.3.1
- Dashboard cards/charts use neutral translucent surfaces so they stay readable in Odoo dark theme (cards were white with light text).

## v1.3.2
- Auto-validate permission now also validates the sale order's delivery (all steps) right after the order is confirmed (portal or backend), when the order belongs to a rep with the permission. Only fully reserved transfers are validated; otherwise the transfer stays as is and the rep gets a notification and a portal message.

## v1.3.3
- Product field is now ONE searchable dropdown: tap to open the full product list, type to filter (also keyboard: arrows/Enter/Esc). Replaces the separate search box + select.
- Stock operations list every product (on-hand quantity shown when known); before, the list was limited to products with stock at the source and could appear empty.

## v1.4
- Per-representative permissions: Sales Representatives > (rep) > Permissions tab. Every permission is "Use global setting / Allowed / Not allowed", so each rep can have different rights (quotation, order, discount + own max %, price change, invoice, direct invoice, payment, stock view, transfer, return, delivery validation, auto-validate). The global Settings are now the defaults. The portal resolves every check per rep, server side.
- Backend menus (Payments, Stock Operations, Sales Orders) now show everything created by a representative, including deliveries generated from his sale orders. Documents created under a rep's user automatically get their Sales Representative link.
- Upgrade script keeps what each rep could do before and links the existing documents to their rep.

## v2.0 - Field Sales Management (the 25-point enhancement list)
Portal (mobile first, Arabic RTL):
- Smart dashboard: visits, orders, sales, collections, outstanding, overdue, monthly figures, target achievement, new customers, follow-ups, "Customers to Visit Today" with the reason for each (no visit / no order / outstanding / overdue / reorder due / missed visit / high value). Quick-actions button (+) on every page.
- Customer 360: contact, call / WhatsApp / maps, quotations, orders, invoices, payments, outstanding + aging buckets with "Collect Payment", overdue, last visit / order, total sales / collected, products bought before, visits, follow-ups, deliveries and returns.
- Customer search (name, mobile, phone, code, address) with filters: on today's route, visited today, not visited, with outstanding, overdue, no recent order.
- New customer from the portal (type, contacts, address, GPS, price list, payment terms, notes, attachments), auto-assigned to the rep; optional approval (Settings > Require Approval) - managers approve / refuse from New Customers or the Action menu.
- Targets (sales, collection, orders, visits, new customers) per rep and period, with target / actual / % / remaining / progress bar; "Target achieved" notification; "Copy to Next Month".
- Outstanding & aging page (current, 1-30, 31-60, 61-90, 90+, total overdue).
- Expenses (type, amount, date, customer / visit, notes, receipt photo): Draft > Submitted > Approved / Refused, manager approval in the backend.
- Payment receipt: mobile page with Print + PDF (QWeb report), shows invoices, reference, rep, company, cheque details.
- Cheques: when the payment method is Cheque the form asks number, bank, cheque date, due date, photo; status Received > Deposited > Cleared / Returned, visible to the rep.
- Customer returns: customer > invoice / sales order > product > quantity > reason; quantity is limited to what was delivered minus what was already returned; configurable reasons; creates the Odoo return transfer (auto-validated when the rep has the auto-validate permission).
- Recurring routes: per customer frequency Daily / Weekly / Every 2 weeks / Monthly / Custom (every N days) with a start date; visits are generated a week ahead.
- Faster visit screen: customer snapshot (phone, balance, last order / visit, purpose), actions (quotation, order, payment, return, follow-up, expense, outstanding invoices), notes, photos, GPS on start / finish, required visit result (8 results), next follow-up and visit dates, "Next customer".
- Follow-ups: create from visit / customer, dashboard counters, today / overdue / upcoming, mark done.
- Product search by name, reference or barcode; shows free stock, customer-pricelist price, discount, UoM; customer's frequently bought products first (★).
- Ranking (optional, per-rep permission): shows rank and score %, never other people's amounts unless enabled.
- Notifications: new customer assigned, new visit, visit overdue, invoice overdue, order confirmed, stock operation completed, expense / cheque / customer decisions, target achieved, follow-up due.
- Audit trail: chatter entries (who, what, GPS, time) on orders, invoices, payments, visits, returns, customers, expenses.
- Offline: Online / Offline / Syncing indicator, today's route, customers and details pre-loaded on the device; visits (start / finish with device time + GPS), notes, follow-ups, expenses, new customers, customer location and quotations are queued on the device and synced automatically when the connection returns (each carries a device reference so nothing is created twice). Payments, confirmed orders, invoices, returns and stock operations need a connection by design.
Backend:
- Menus: Targets, Follow-ups, New Customers, Expenses, Cheques, Customer Returns, Return Reasons.
- Manager dashboard filters (date, representative, team, route, customer) and extra KPIs (new customers, outstanding, overdue, target achievement, expenses, returns); everything is clickable.
- New per-rep permissions: Creating Customers, Expenses, Customer Returns, Ranking.
Upgrade: update the module; migration scripts keep previous data valid.

## v2.0.1
- One single module: the Employee link now lives inside mo_sales_rep_portal (the separate bridge module is gone; `hr` is installed as a dependency).

## License
OPL-1 (Odoo Proprietary License v1.0): one purchased license per database, no redistribution. See `LICENSE`.

## v2.1 - responsive & lively dashboards
- Portal: full-width desktop layout (sidebar menu with every section, multi-column cards and dashboard grid), tablet layout, phone layout with bottom bar. Forms stay at a comfortable width.
- Portal dashboard: greeting + Live indicator, animated KPI numbers with day-over-day change and sparklines, 14-day sales / collection trend, today's visits donut, target rings, outstanding-by-age bar, top customers; refreshes every minute (`/rep/dashboard.json`), respects reduced-motion.
- Manager dashboard: Live indicator with auto refresh, counting numbers, hero sparkline, visits donut, ageing bar, top customers bars, per-representative cards with target rings, animated bars; still dark-theme safe and fully clickable.

## v2.1.1
- Manager dashboard: fixed the page not scrolling (the client action had no fixed height; it is now sized from the viewport and scrolls inside).
