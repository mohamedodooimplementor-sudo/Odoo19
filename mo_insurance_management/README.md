# Insurance Management for Odoo 19

Split-liability insurance module: an insured Sales Order's total is divided
between the **Customer** (co-pay) and the **Insurance Company** (covered
share), with a real accounting split - one combined invoice whose single
Accounts Receivable line is split, on the same journal entry, into two
lines with two different partners. Collecting from the insurance company
afterwards is a separate, periodic "Insurance Claim" process against
invoices directly - no manual reconciliation required.

## Install

1. Copy the `insurance_management` folder into your Odoo `addons` path.
2. Update Apps list, install **Insurance Management**.
3. Dependencies: `sale_management`, `account`, `contacts` (installed
   automatically).
4. ReportLab (PDF) and XlsxWriter (Excel) are used for the reports - no
   wkhtmltopdf/QWeb involved. Odoo already requires both, so they are normally
   just imported from your Odoo Python. If either is missing, the verified
   copies bundled in `libs/` are used, only while one of this module's own
   reports is being built (see `libs/README.txt`); nothing is downloaded. Arabic text in the PDFs is shaped by the module itself
   (`report/arabic_text.py`) using the bundled DejaVu Sans font.

## Required setup before first use

- **Products**: make sure the products/services you sell have an Income
  Account configured (directly, or via their Product Category) - standard
  Odoo invoicing requirement, unchanged by this module.
- **Insurance invoices journal**: the insurance company's invoice posts its
  line to the **Default Account** of the journal set in Insurance >
  Configuration > Settings (or of the patient invoice's journal if none is
  set) - not to the product's income account. That journal must have a
  Default Account.
- **Insurance Company contact**: each `insurance.company` record needs a
  linked `res.partner` (created inline from the form). This partner is who
  the split-off receivable line belongs to, and who the Claim payments are
  registered against.

## Data model

| Model | Purpose |
|---|---|
| `insurance.company` | Insurance company + linked partner for accounting |
| `insurance.plan` | Plan under a company: default %, limits, auth requirement |
| `insurance.coverage.rule` | Product / Category rule, resolved Product > Category > Plan default |
| `insurance.policy` | Customer's policy: validity, annual coverage usage |
| `res.partner` (ext.) | Insurance tab (individuals only), "Enable Insurance on Sales Orders" checkbox, primary policy |
| `sale.order` / `sale.order.line` (ext.) | Auto coverage calc per line, frozen at confirm, annual-limit capping |
| `account.move` (ext.) | Receivable-split fields + the split logic itself |
| `account.payment` (ext.) | `insurance_claim_id` link back to the Claim a payment was registered from |
| `insurance.claim` / `.claim.line` | The collection round against one Insurance Company (see below) |
| `insurance.claim.payment.wizard` | "Register Payment" wizard opened from a Claim |
| `insurance.authorization` | Pre-authorization gate on confirmation, for plans/products that require it |

## How the accounting split works

On `sale.order.action_confirm()`, if `insurance_enabled`:

1. Coverage is calculated **per line** (never a flat order-level %), using
   the most specific coverage rule, then capped by the policy's remaining
   annual limit - any excess shifts back to the customer. The capped
   amount is booked to `insurance.policy.coverage_used` immediately (no
   separate "pending" step), and reversed if the order is later cancelled.
2. **One** invoice is created for the full order total, through Odoo's
   normal `sale.order._create_invoices()` (so taxes/qty/analytic behave
   exactly like a regular sale) - not custom-built lines.
3. When that invoice is posted, `account.move._split_insurance_receivable()`
   splits its single Accounts Receivable line into **two lines on the same
   journal entry**: one for the Customer's co-pay share, one moved to the
   Insurance Company's partner for the covered share. This happens while
   the move is still in `draft`, right before `action_post()` actually
   posts it - so it's a normal, fully-mutable write that never has to
   fight a posted/locked entry or a journal's hash-chain integrity lock.
   - Revenue stays a single, correct amount (the full order total) -
     nothing is duplicated and nothing is discounted.
   - A fully insurance-covered order (no customer co-pay at all) simply
     moves the whole receivable line to the insurance company's partner,
     rather than creating a pointless zero-amount second line.
4. From here the Customer's line and the Insurance Company's line are
   completely independent for payment/reconciliation purposes: a normal
   **Register Payment** on the invoice only ever touches the Customer's
   line (since it matches on the invoice's own partner); the insurance
   company's line is collected separately through Insurance Claims.

## Insurance Claims: how collection works

A Claim is a collection round against **one Insurance Company**, optionally
narrowed to one Customer and/or one Plan, over a date range:

1. **Submit** searches every *posted* invoice whose split-off receivable
   line belongs to that insurance company's partner, within the date
   range (and customer/plan filters if set), and is still outstanding
   (`amount_residual > 0`). Each matching invoice becomes a Claim Line with
   a frozen "Insurance Share" (`amount_due`) - this is what "Total Claimed"
   is built from, and the Claim moves to **Submitted**.
2. **Register Payment** opens a wizard (not a single "pay everything"
   button): it shows Total Claimed / Already Paid / Remaining Balance and
   asks for an amount (defaulting to the full remaining balance, but
   editable for a partial payment), a journal, a date and a memo. It
   validates the amount is > 0 and does not exceed the remaining balance.
3. Confirming the wizard creates and posts a **real `account.payment`**
   (inbound, partner = the insurance company, linked back to the Claim via
   `insurance_claim_id`), then reconciles it against the Claim's invoice
   lines in list order until either the payment or the invoices'
   outstanding amounts are exhausted - so a partial payment simply leaves
   the right residual on the right invoice(s) for the next payment.
4. **Status is always derived from actual posted payments**, never set by
   hand: `Total Paid = 0` -> Submitted, `0 < Total Paid < Total Claimed` ->
   Partially Paid, `Total Paid >= Total Claimed` -> Paid. Draft/cancelled
   payments never count towards Total Paid.
5. A Claim supports **any number of payments over time** (`payment_ids`,
   with a "Payments" smart button) - there is no single `payment_id` field
   to bottleneck this.

Because `amount_due` is captured from the invoice line's real
`amount_residual` at Submit time, and that residual only ever decreases as
payments reconcile against it, the same insurance amount can never be
counted (or collected) twice - even across multiple Claims that happen to
overlap in period/company.

State machine (`insurance.claim._transition()` centrally validates every
jump, including a Kanban card being dragged into the wrong column):

```
draft -> submitted -> partial_paid -> paid
                   -> rejected -> draft
(cancelled reachable from any non-paid state; draft reachable from rejected/cancelled)
```

## Dashboard

Insurance > Dashboard has two pages (also switchable with the Cards / Charts
pills at the top) that share the same filters - period, insurance companies
and plans - which are remembered while you move between the pages:

- **Cards** - 16 KPI cards (with vs-previous-period badges) plus the Recent
  Claims and Top Patients tables.
- **Charts** - sales/coverage trend, claims by status, coverage split,
  receivable aging, collection overview, outstanding by company, and top
  companies / plans / products.

Everything is clickable (drills into the matching records), charts show
tooltips on hover, cards have a visible shadow and press/ripple effects, and
the light/dark theme toggle applies to all of it. Each page only loads the
data it shows. The old pivot entries (Claims Dashboard / Insured Sales) were
removed - the same analysis is in Insurance > Reporting.

## Claim statement

Claim > *Print Statement* downloads the ReportLab PDF directly
(`/insurance_management/claim_statement/<id>`); see *Independence from Odoo's
own reports* below.

## Independence from Odoo's own reports

This module does **not** touch Odoo's report engine or its PDF generation in any way: no
`ir.actions.report` records or overrides, no wkhtmltopdf detection / PATH / installer
code, no monkey-patching. Its own PDFs (ReportLab) and Excel files (XlsxWriter) are built
by plain Python code and downloaded through the module's own routes, so Odoo's invoices,
sales orders etc. behave exactly as they would without this module.
ReportLab and XlsxWriter come with Odoo; if either is missing, a verified copy in `libs/`
is used **only during a report build of this module** and removed again afterwards, so it
is never visible to Odoo's own code.

## Security

See `SECURITY_REVIEW.md` (delivered next to this module) for the pre-go-live
review: what was found, what was fixed, what needs a business decision, and the
deployment checklist. `tests/test_security.py` keeps every fixed hole covered.

## Claim card colours (light / dark)

The claim kanban cards and the Total Claimed / Paid / Remaining cards on the
claim form are **white in the normal theme and black in dark mode**.
`static/src/js/color_scheme.js` checks the real background behind the cards
and sets `o_ic_dark` on `<html>`, so it works whichever way the backend's dark
mode is implemented (it also follows a theme toggled without a page reload).
The colours are the `--ic-card-*` variables at the top of
`static/src/scss/insurance_claim_kanban.scss`.

## Customer policies

The policy form has status buttons - **Suspend**, **Reactivate**, **Renew (+1
year)**, **Cancel Policy** - plus warning banners (expired / expiring within 30
days / not active), a used-coverage progress bar, an Authorizations smart
button, and **Print Policy** (ReportLab PDF policy card with the recent insured
orders). The list has a search view (Valid Today, Expiring in 30 days,
Suspended, Expired, group by company / plan / status). A daily cron marks
Active policies whose expiry date has passed as Expired. *Renew* does not
reset Used Coverage - a manager can do that with *Reset Used Coverage*.
Authorizations can be printed too (**Print** button).

## Codes

Insurance Company and Plan codes are filled in automatically (`INS001`, `PLN001`, ...)
from a sequence and can be changed freely (they only have to stay unique).

## Who can do what (policies)

Only **Insurance Officers and above** create policies and authorizations; the counter role
(Insurance User) can read them. A customer's **Member ID, Card Number and notes** are visible
to Insurance users only - salespeople and billing users can still select a policy on an order
but do not see those fields (and cannot print the policy card).
