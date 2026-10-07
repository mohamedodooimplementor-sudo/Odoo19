# Odoo Apps listing - Field Sales Management (mo_sales_rep_portal)

## Fields to fill in on apps.odoo.com
| Field | Value |
|---|---|
| Technical name | `mo_sales_rep_portal` |
| Version | 19.0 |
| Title | Field Sales Management - Sales Representative Portal & Routes |
| Category | Sales |
| Price | **299 USD** (one-time, per Odoo instance - adjust to your policy; it is also set in `__manifest__.py`) |
| License | `OPL-1` (Odoo Proprietary License) - already set in `__manifest__.py`; the `LICENSE` file in the module folder carries the notice |
| Banner | `static/description/banner.png` (560x280); a larger copy is `banner_large.png` |
| Description page | `static/description/index.html` (already contains the screenshots, features, Arabic summary) |
| Gallery | the images listed under `'images'` in the manifest (`static/description/screenshots/`) |
| Dependencies | sale_management, sale_stock, account, stock, portal, hr, sales_team, mail |

## Short description (one line)
Field sales portal for Odoo 19: routes, GPS visits, orders, collections, cheques, returns, expenses, targets and offline sync - on standard Odoo documents.

## Long description (English)
Give every sales representative a fast, mobile-first portal for the whole daily workflow - routes, visits with GPS, orders, collections, cheques, returns, expenses and targets - while Odoo keeps doing the accounting, inventory and sales behind the scenes.

**For the representative (phone, tablet or PC, no separate app):**
- Smart home screen with today's visits, sales, collections, outstanding and overdue amounts, monthly figures, target achievement and "customers to visit today" with the reason for each.
- Customer 360: contacts with call / WhatsApp / maps, orders, quotations, invoices, payments, aging buckets, collect payment in one tap, last visit and order, total sales and collected, products bought before.
- Fast visit screen with GPS on start and finish, notes, photos, quotation / order / payment / return / expense / follow-up from the same screen, required visit result.
- Recurring routes (daily, weekly, every 2 weeks, monthly, custom) with automatic planned visits and nearest-first re-ordering.
- Order entry with one searchable product list (name, reference, barcode), stock, customer price and discount shown.
- Payments with printable receipts (mobile page + PDF), cheque tracking, controlled returns, expenses with approval, follow-ups, targets and optional ranking.
- Online / Offline / Syncing indicator; the day's pages are pre-loaded and visits, notes, follow-ups, expenses, new customers and quotations sync automatically.
- Full Arabic (RTL) and English.

**For the manager (Odoo backend):**
- Dashboard with filters (date, rep, team, route, customer) and KPIs: sales, collections, visits, conversion, new customers, outstanding, overdue, target achievement, expenses, returns - every number opens its records.
- Routes, visits, targets, expenses, cheques, follow-ups, customer approval, return reasons and per-representative permissions.

**Security:** Portal users with access rights and record rules; each rep sees only his own records; permissions can differ per representative; audit trail on every document; multi-company aware.

## Description (Arabic)
موديول متكامل لإدارة مبيعات المناديب الميدانية على Odoo 19. بوابة للموبايل تغطي يوم المندوب كاملًا: خطوط السير والزيارات بالـ GPS، الطلبات، التحصيل والشيكات، المرتجعات، المصروفات، الأهداف والمتابعات، وكل العمليات تتسجل كمستندات Odoo القياسية (أمر بيع، فاتورة، دفعة، حركة مخزون).

- المندوب يعمل كمستخدم بوابة (Portal) من أي جهاز بدون تطبيق منفصل، والواجهة عربي كاملة من اليمين لليسار.
- Customer 360 وأعمار الديون وتحصيل بضغطة وإيصال دفع للطباعة وتتبع الشيكات.
- صلاحيات مختلفة لكل مندوب، وكل مندوب يرى بياناته فقط، وسجل تدقيق لكل عملية.
- لوحة تحكم للمدير بفلاتر وكل رقم فيها يفتح السجلات.
- يعمل مع ضعف الإنترنت: الزيارات والملاحظات والمتابعات والمصروفات والعملاء الجدد وعروض الأسعار تُحفظ وتُزامن تلقائيًا.

## Why 299 USD (my suggestion, please review)
- I looked for comparable field-sales apps on apps.odoo.com but the search did not return clear, reliable prices, so this number is **not market-verified**. It reflects the scope: a portal for the full daily workflow (routes, visits, orders, collections, cheques, returns, expenses, targets, offline, manager dashboard) with no extra mobile app to maintain.
- Suggested options: 199 USD (entry, to build reviews), 299 USD (recommended), 399+ USD (with paid support / customization hours).
- Consider selling support as a separate paid item rather than raising the price.

## Upload checklist
1. Check the final price in `__manifest__.py` (`'price'`, `'currency'`); the license is already `OPL-1`.
2. Zip the `mo_sales_rep_portal` folder (one folder = one module).
3. Upload on apps.odoo.com > Publish a Module; the description page and images are picked up from `static/description/`.
4. Replace the sample screenshots with captures from a real Odoo 19 database if you can (they are rendered from the portal's real CSS with sample data).
5. Add your support contact and website in the support text on the store page.

## Changelog (store text)
- 19.0.2.0: field sales management - Customer 360, new customers with approval, targets and ranking, aging, expenses, receipts, cheques, advanced returns, recurring routes, follow-ups, smart dashboard, quick actions, offline queue, manager dashboard filters, per-rep permissions.
