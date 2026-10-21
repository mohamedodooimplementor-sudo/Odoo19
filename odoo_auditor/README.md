# Odoo Auditor (odoo_auditor) - Odoo 19.0

Read-only enterprise audit & internal-control layer. Never posts, cancels, approves or edits business records.

## Implemented (v19.0.1.0.0)
- Rule registry (37 built-in rules, controlled implementations only - no eval / user SQL / user Python)
- Audit runs (manual / scheduled), per-company advisory lock, idempotent retry, config + rule-version snapshot
- Findings workflow New > Triaged > Under Investigation > Awaiting Mgmt Response > Action Required >
  Pending Verification > Closed; Rejected (justification + manager) and Reopened (manual or on recurrence)
- Immutable, SHA-256-hashed historical evidence snapshots; attachments; confidentiality classes
- Corrective actions with segregation of duties and overdue escalation cron
- Audit plans, programs, workpapers (preparer != reviewer), risk & control register with documented scoring
- Protected audit log (append-only) for the Auditor's own records
- Groups: Auditor, Audit Manager, Confidential (HR/Payroll) access; multi-company record rules
- OWL dashboard (KPIs, bars, drill-down) + graph/pivot analysis; run-summary email template; activities for high/critical findings
- Quick Setup wizard, Kanban findings, one-click corrective action, 'Ignore in future' exclusions, Excel export,
  background runs with live progress, PDF reports (finding, run summary, plan, actions), full Arabic translation
- Access reviews (SoD snapshot with decisions) and period / year-end checklists
- Conditional integration: rules are skipped with a warning if account / sale / purchase / stock is missing

## Built-in rules
FIN001 draft entries aged, FIN002 large manual entries, FIN003/FIN004 duplicate vendor bills / customer invoices,
FIN005 large credit notes, FIN006 backdated postings, FIN007 overdue receivables/payables, INV001 negative stock, INV002 stalled transfers,
INV003 large inventory adjustments, SAL001 high discounts, SAL002 below-cost / low margin,
PUR001 high-value POs, PUR002 POs split around the approval limit, MRP001 excess component consumption,
MRP002 stale manufacturing orders, HR001 duplicate employees, HR002 missing employee master data (HR findings are
confidential and carry no salary data), SOD001 conflicting access rights (configurable group pairs),
FIN008 repeated round amounts, FIN009 suspense balances (needs account codes; disabled by default), FIN010
period-over-period movements, FIN011 stale bank lines, INV004 deliveries without SO, SAL003 orders just below
threshold, SAL004 archived customers, PUR003 bills without PO, PUR004 price vs vendor history,
FIN012 tax changes, PUR005 vendor bank change before payment, INV005 expiry, SAL005 credit limit,
HR007 payroll rule changes, HR003 duplicate expenses, HR004 expense limit, HR005 missing receipts, HR006 payroll deviation (% only).

## Not implemented yet
Rules not yet covered from the spec: valuation/costing settings changes, lot/serial consistency, project stock
allocation, price-list changes (these need field-level history that standard Odoo does not keep). Spec text after 5.6 was
never received. Arabic .po was generated from the source strings (not exported from a live database): after install run
`-u odoo_auditor --i18n-overwrite -l ar` and report any untranslated term. No Apps Store screenshots (see docs/VIDEO_SCRIPT_AR.md).
See docs/USER_GUIDE.md.

## Limitations
- Cost-based rules use the line cost when available, otherwise CURRENT product cost (stated in each finding).
- Duplicate-bill matching is exact (partner + reference + amount + currency).
- Findings are de-duplicated by a fingerprint; a closed finding is reopened if the condition is detected again.
- System administrators are made Audit Managers for setup; remove that link for strict audit independence.
- Tested only statically; run the test suite on your Odoo 19 install: `odoo -d db -i odoo_auditor --test-tags odoo_auditor`.
