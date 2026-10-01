# Tender Management & BOM Manufacturing Costing (Odoo 19)

Author: Eng. M.Aboelmagde

## Setup
1. Install the module (depends on: sale, mrp, mrp_account).
2. Tenders > Configuration > Settings: set default Labour / Overhead / Other accounts (optional, each BOM line can override). Saving settings needs an administrator.
3. BOM > "Manufacturing Costs" tab: add Labour / Overhead / Other lines.

## How costs flow (no double counting)
* BOM Total = Materials + Labour + Overhead + Other (shown at the bottom of the tab).
* Tender line cost/unit = BOM Total per unit. Tender additional costs are separate.
* MO: BOM Labour+Overhead+Other per unit is added ONCE to the standard MO "Extra Cost" -> finished product valuation = Materials + Manufacturing costs.
* On Mark as Done: one reclass entry (Dr valuation counterpart / Cr BOM accounts) moves the credit that standard valuation left on the counterpart account to Labour / Overhead / Other accounts. Inventory accounts are not touched.
* Do NOT also enter the same labour as Work Center cost on the same BOM.

## Test scenario
Component cost 450 + Labour 50 + Overhead 70 + Other 20 => BOM 590. Tender qty 10 @ sale 750: cost 5,900 / sale 7,500 / profit 1,600.
Produce 10 via MO: finished valuation 5,900; cost accounts credited 500 / 700 / 200.

## Dashboard / Kanban / Reports
* Tenders > Dashboard: OWL + Canvas, uses only Bootstrap CSS variables (light/dark mode).
* Kanban is grouped by a fixed stage model (tm.tender.stage), so all 7 columns always show. Stages follow the workflow buttons (no drag and drop).
* Ribbon color = state. Smart buttons: BOMs, Sales Orders, Manufacturing Orders (tender); Tenders (BOM); Tender (sale order).
* Reports: Tender Proposal (no costs), Tender Costing Sheet, Tenders Summary, BOM Cost Sheet, and Tenders > Reports > Tenders Report (PDF + Excel).

## Delivery & Invoicing
* Stages after Won: Delivered (all outgoing deliveries of the tender's sales orders are done) and Invoiced (delivered and every sales order fully invoiced). They move automatically when a delivery is validated or an invoice is posted; buttons Mark as Delivered / Mark as Invoiced exist as a manual fallback.
* Smart buttons: Deliveries and Invoices on the tender; Tender on the delivery order and on the invoice.
* Dashboard cards: To Deliver, To Invoice (plus Invoiced). Reports: Product Analysis, delivery/invoicing columns in the summary PDF and Excel.

## Paid stage, Revisions, Actual vs Estimated, Arabic
* Stage Paid: after Invoiced, when every posted customer invoice of the tender's sales orders is paid. Moves on reconciliation (hook on partial reconcile) and by an hourly cron; manual button Mark as Paid.
* Revisions: New Revision copies the tender as NAME-R1, NAME-R2... (draft, prices and BOMs kept, BOM costs re-read) and cancels the previous version. Not allowed while a quotation exists.
* Actual vs Estimated: tab on the tender (once there are manufacturing orders) + PDF. Estimated = produced qty x tender BOM cost/unit. Actual = value of the finished product of the done MOs.
* Arabic: i18n/ar.po (and ar_001.po). Generated from the module sources; if a term is missing use Settings > Translations > Export/Import for the module.

## Margin <-> sale price (tender lines)
* Margin % is the profit as a percentage of the BOM COST (markup): cost 120 and 50% gives a sale price of 180. It is editable: typing it sets Sale Price = BOM Cost x (1 + %); changing the Sale Price recalculates it.
* Tender level Margin % = Profit / Tender Total Cost (BOM costs + additional costs).

## Target margin in the header
* Header field Target Margin % (was Minimum Margin %): typing it sets the Sale Price of ALL lines = BOM cost x (1 + %), so no need to type line by line. No button needed: new lines take the target margin automatically when a product is chosen (price = BOM cost x (1 + %)); Refresh Costs re-applies it. Products without a BOM cost are skipped with a warning.
* It is still the alert threshold: a warning shows if the tender margin (after tender additional costs) is below it. Line margins can still be edited one by one.

## Configuration menus
* Tenders > Configuration > Settings: standard Odoo settings page (block Manufacturing Cost Accounts).
* Tenders > Configuration > Stages: rename stages, reorder (drag), fold columns in the kanban. Stages cannot be created/deleted (they map to the workflow states); the code column is read-only. Renaming changes the kanban column titles only; the status bar / ribbon keep the workflow names.

## Usability additions
* Add Products: header button (draft only) opens a wizard to add several products at once, or import them from an .xlsx file (columns: Product, Quantity, Sale Price). Download Template gives a ready file. Product is matched by internal reference, barcode, then name.
* Send by Email: header button opens the mail composer with the Tender Proposal PDF attached, using the "Tender: Send Proposal" template.
* Activities: Submit schedules a "Tender Approval" activity for every Tender Manager; Approve closes it and schedules "Create Quotation" for the tender's responsible; both are closed on Draft/Cancel and when the quotation is created.
* Cost Breakdown: an info button next to BOM Cost / Unit on each tender line opens Materials/Labour/Overhead/Other per unit. A warning banner (and an orange line color) shows when the BOM cost has changed since the line was priced (draft/submitted only) — Refresh Costs re-reads it.
* Lost Reason: Mark as Lost opens a wizard (reason + notes) instead of setting the state directly; Lost Reasons list in Configuration; dashboard chart "Lost Reasons".
* Payment Terms and Quotation Validity (days) on the tender header are copied to the sales order (payment_term_id, validity_date) when the quotation is created, and printed on the Tender Proposal.
* Tags (Configuration > Tags, colored) and Priority (stars) on the tender, shown in the list, kanban and search.
* Attachments tab on the tender (many2many_binary), independent of the chatter attachments.

## Last Price Sold
* Tender line has an optional column "Last Price Sold" (hidden by default, enable it from the list's column picker): the unit price on the most recent confirmed sales order for the same customer and the same product. Read-only, does not change the tender price automatically.

## Fixes: live BOM cost, override permissions
* Total BOM Cost / Materials-Labour-Overhead-Other per unit on a tender line now react automatically to changes made directly on the linked BOM (its cost lines, its components, their quantities or standard cost) — not only to the line's own product/BOM/UoM. Previously this required pressing "Refresh Costs". A migration recomputes existing draft/submitted lines once.
* "Refresh Costs" is still useful to re-apply the target margin to the (now current) cost, i.e. to re-price the Sale Price — it is no longer needed just to see the correct cost.
* Security: Mark as Delivered / Mark as Invoiced / Mark as Paid (the manual overrides) now require the Tender Manager group, since they can misrepresent real fulfillment/payment status if used freely.

## Create Purchase Orders (manager only)
* Header button "Create Purchase Orders" sits right next to "Create Quotation" (Tender Manager group only, hidden in Draft) and explodes the direct components of each tender line's BOM (one level, not through sub-BOMs), scaled to the tender quantity, and groups the needed quantities by the product's preferred vendor (standard Odoo `_select_seller`, same mechanism Odoo's own replenishment uses).
* One purchase order (RFQ) is created per vendor, with tender_id set and origin = the tender number; a "Purchases" smart button (manager only) shows them. Products with no vendor configured are skipped and listed in a chatter message instead of blocking the rest.
* Adds a dependency on the `purchase` app. The button always creates a fresh batch of POs: clicking it twice creates two batches, there is no duplicate/idempotency check (mirrors "Create Quotation", which does block duplicates, but purchasing may legitimately need repeated runs).
* Simplification: pricing/quantity use the product's own unit of measure (not a separate purchase UoM), and only the first level of the BOM is used — sub-assemblies are ordered as themselves, their own sub-components are not exploded. Say if you want recursive explosion or per-BOM-line vendor overrides instead.

## Smart buttons: hidden until they have something
* BOMs, Sales Orders, Manufacturing, Deliveries, Invoices, Payments (and the existing Revisions, Purchases) are now hidden on the tender form until their count is greater than zero, instead of always showing as an empty 0. Purchase Orders is also manager-only.

## Additional costs now count toward the target margin
* Applying the header "Target Margin %" (and typing a line's own Margin %) now prices each line off BOM cost PLUS that line's share of the tender's Additional Costs (allocated proportionally to each line's BOM cost), so the tender's overall margin, after additional costs, actually reaches the typed target.
* The per-line "Margin %" / "Profit" columns stay based on BOM cost only, on purpose (per-product profitability, unmixed with tender-wide costs, as originally specified) — so once additional costs exist, a line's own displayed margin will read a bit ABOVE the typed target margin (it is also recovering its share of the overhead); the tender's bottom-of-form Margin % (full cost basis) is the one that matches the typed target.

## Additional Cost -> real Odoo Landed Cost
* Each Additional Cost line now also has an Account (defaults from Settings, like BOM cost lines) and a Split Method (Equal / By Quantity / By Current Cost / By Weight / By Volume) — required to validate a Landed Cost.
* Header button "Additional Cost" (Tender Manager only) turns the tender's Additional Cost lines into a real `stock.landed.cost` record: picking_ids = this tender's own done delivery transfers only (never another tender's), cost_lines = one per Additional Cost (using a generic internal "Tender Additional Cost" service product, with account/amount/split method taken from your line), origin = the tender's invoice number(s). Nothing is computed or validated automatically — open the created record and press Compute then Validate yourself, exactly like any Landed Cost in Odoo, so the amounts land on Inventory Valuation / product cost through Odoo's own standard mechanism (no custom journal entry).
* Checks before creating (in this order, each with a clear message): at least one Additional Cost line; the tender's Manufacturing Orders exist; they are all Done; at least one delivery transfer is Done; the tender has a posted invoice; no Landed Cost already exists for it (if one does, a notification lets you open it instead of creating a duplicate).
* Smart button "Landed Costs" (manager only) opens the tender's own landed cost(s); a "Tender" stat button was added to the standard Landed Cost form too.
* This is fully separate from, and does not change, the existing BOM Manufacturing Costs (Materials/Labour/Overhead/Other) that already land on the Manufacturing Order's own cost.
* Adds a dependency on Odoo's `stock_landed_costs` app.
