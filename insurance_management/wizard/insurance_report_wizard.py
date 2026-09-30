# -*- coding: utf-8 -*-
"""Filter wizard behind the "Claims Report" and "Product Coverage" PDF /
Excel reports (Insurance > Reporting).

The wizard only gathers the records and turns them into plain rows; the
actual PDF (ReportLab) and Excel (XlsxWriter) files are produced by
``report/report_builders.py``.
"""
from collections import OrderedDict
from datetime import datetime, time

import pytz

from odoo import fields, models
from odoo.exceptions import UserError

from ..models.insurance_claim import EFFECTIVE_PAYMENT_STATES, STATE_LABELS
from ..report import report_builders as rb

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MIME = "application/pdf"


class InsuranceReportWizard(models.TransientModel):
    _name = "insurance.report.wizard"
    _description = "Insurance Report (PDF / Excel)"

    report_type = fields.Selection(
        [
            ("claims", "Claims Report"),
            ("coverage", "Product Coverage Report"),
            ("aging", "Insurance Aging Report"),
        ],
        required=True,
        default="claims",
    )
    date_from = fields.Date(string="Date From")
    date_to = fields.Date(string="Date To")
    insurance_company_id = fields.Many2one("insurance.company", string="Insurance Company")
    insurance_plan_id = fields.Many2one(
        "insurance.plan",
        string="Plan",
        domain="[('insurance_company_id', '=', insurance_company_id)]",
    )
    partner_id = fields.Many2one("res.partner", string="Customer / Patient")
    claim_state = fields.Selection(STATE_LABELS, string="Claim Status")
    product_id = fields.Many2one("product.product", string="Product")

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_print_pdf(self):
        self.ensure_one()
        data = self._collect()
        content = rb.build_pdf(data)
        return self._deliver(content, "pdf", PDF_MIME)

    def action_export_xlsx(self):
        self.ensure_one()
        data = self._collect()
        content = rb.build_xlsx(data)
        return self._deliver(content, "xlsx", XLSX_MIME)

    def _deliver(self, content, extension, mimetype):
        title = dict(self._fields["report_type"].selection)[self.report_type]
        filename = f"Insurance {title} - {fields.Date.context_today(self)}.{extension}"
        attachment = self.env["ir.attachment"].create(
            {
                "name": filename,
                "raw": content,
                "mimetype": mimetype,
                "type": "binary",
                "res_model": self._name,
                "res_id": self.id,
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }

    # ------------------------------------------------------------------
    # Common
    # ------------------------------------------------------------------
    def _collect(self):
        self.ensure_one()
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise UserError("'Date From' must be before 'Date To'.")
        company = self.env.company
        lang = self.env["res.lang"]._lang_get(self.env.lang)
        base = {
            "company": company.name,
            "currency": company.currency_id.name or "",
            "generated": fields.Datetime.to_string(fields.Datetime.context_timestamp(self, fields.Datetime.now())),
            "user": self.env.user.name,
            "rtl": bool(lang and lang.direction == "rtl"),
        }
        if self.report_type == "claims":
            base.update(self._claims_data())
        elif self.report_type == "aging":
            base.update(self._aging_data())
        else:
            base.update(self._coverage_data())
        return base

    def _period_label(self):
        if self.date_from and self.date_to:
            return f"{self.date_from} to {self.date_to}"
        if self.date_from:
            return f"From {self.date_from}"
        if self.date_to:
            return f"Up to {self.date_to}"
        return "All dates"

    def _common_filters(self):
        return [
            ("Period", self._period_label()),
            ("Insurance Company", self.insurance_company_id.display_name or "All"),
            ("Plan", self.insurance_plan_id.display_name or "All"),
            ("Customer / Patient", self.partner_id.display_name or "All"),
        ]

    # ------------------------------------------------------------------
    # Claims report
    # ------------------------------------------------------------------
    def _claims_data(self):
        domain = ["|", ("company_id", "=", False), ("company_id", "in", self.env.companies.ids)]
        # A claim covers a date range: keep every claim whose range overlaps
        # the requested one.
        if self.date_from:
            domain.append(("date_to", ">=", self.date_from))
        if self.date_to:
            domain.append(("date_from", "<=", self.date_to))
        if self.insurance_company_id:
            domain.append(("insurance_company_id", "=", self.insurance_company_id.id))
        if self.insurance_plan_id:
            domain += ["|", ("insurance_plan_id", "=", self.insurance_plan_id.id),
                       ("claim_line_ids.insurance_plan_id", "=", self.insurance_plan_id.id)]
        if self.partner_id:
            domain += ["|", ("partner_id", "=", self.partner_id.id),
                       ("claim_line_ids.insurance_patient_id", "=", self.partner_id.id)]
        if self.claim_state:
            domain.append(("state", "=", self.claim_state))

        claims = self.env["insurance.claim"].search(
            domain, order="insurance_company_id, date_from, id"
        )
        state_labels = dict(STATE_LABELS)

        rows, invoice_rows, payment_rows = [], [], []
        for claim in claims:
            rows.append(
                {
                    "company": claim.insurance_company_id.display_name,
                    "name": claim.name,
                    "period": f"{claim.date_from} - {claim.date_to}",
                    "partner": claim.partner_id.display_name or "All customers",
                    "plan": claim.insurance_plan_id.display_name or "All plans",
                    "invoice_count": claim.invoice_count,
                    "total_claimed": claim.total_claimed,
                    "total_paid": claim.total_paid,
                    "rejected": claim.total_rejected,
                    "remaining": claim.remaining_balance,
                    "state": state_labels.get(claim.state, claim.state),
                }
            )
            for line in claim.claim_line_ids.filtered("include"):
                invoice_rows.append(
                    {
                        "company": claim.insurance_company_id.display_name,
                        "claim": claim.name,
                        "invoice": line.move_id.name or "",
                        "patient": line.insurance_patient_id.display_name or "",
                        "plan": line.insurance_plan_id.display_name or "",
                        "invoice_date": str(line.invoice_date or ""),
                        "amount_due": line.amount_due - line.credit_note_amount,
                        "paid": line.paid_amount,
                        "rejected": line.rejected_amount if line.rejection_move_id else 0.0,
                        "reason": line.rejection_reason or "",
                        "residual": line.residual,
                    }
                )
            for payment in claim.payment_ids.filtered(lambda p: p.state in EFFECTIVE_PAYMENT_STATES):
                payment_rows.append(
                    {
                        "company": claim.insurance_company_id.display_name,
                        "claim": claim.name,
                        "payment": payment.name or "",
                        "date": str(payment.date or ""),
                        "journal": payment.journal_id.display_name or "",
                        "memo": payment.memo or "",
                        "amount": payment.amount,
                    }
                )

        filters = self._common_filters() + [
            ("Claim Status", state_labels.get(self.claim_state, "All")),
        ]
        columns = [
            {"key": "company", "label": "Insurance Company", "kind": "text", "width": 40, "pdf": False},
            {"key": "name", "label": "Claim #", "kind": "text", "width": 30},
            {"key": "period", "label": "Period", "kind": "text", "width": 46},
            {"key": "partner", "label": "Customer Filter", "kind": "text", "width": 40},
            {"key": "plan", "label": "Plan Filter", "kind": "text", "width": 32},
            {"key": "invoice_count", "label": "Invoices", "kind": "int", "width": 18, "sum": True},
            {"key": "total_claimed", "label": "Total Claimed", "kind": "money", "width": 30, "sum": True},
            {"key": "total_paid", "label": "Total Paid", "kind": "money", "width": 30, "sum": True},
            {"key": "rejected", "label": "Rejected", "kind": "money", "width": 26, "sum": True},
            {"key": "remaining", "label": "Remaining", "kind": "money", "width": 30, "sum": True},
            {"key": "state", "label": "Status", "kind": "text", "width": 26},
        ]
        invoice_columns = [
            {"key": "company", "label": "Insurance Company", "kind": "text"},
            {"key": "claim", "label": "Claim #", "kind": "text"},
            {"key": "invoice", "label": "Invoice", "kind": "text"},
            {"key": "patient", "label": "Patient / Customer", "kind": "text"},
            {"key": "plan", "label": "Plan", "kind": "text"},
            {"key": "invoice_date", "label": "Invoice Date", "kind": "text"},
            {"key": "amount_due", "label": "Insurance Share", "kind": "money", "sum": True},
            {"key": "paid", "label": "Paid", "kind": "money", "sum": True},
            {"key": "rejected", "label": "Rejected", "kind": "money", "sum": True},
            {"key": "reason", "label": "Rejection Reason", "kind": "text"},
            {"key": "residual", "label": "Residual", "kind": "money", "sum": True},
        ]
        payment_columns = [
            {"key": "company", "label": "Insurance Company", "kind": "text"},
            {"key": "claim", "label": "Claim #", "kind": "text"},
            {"key": "payment", "label": "Payment", "kind": "text"},
            {"key": "date", "label": "Date", "kind": "text"},
            {"key": "journal", "label": "Journal", "kind": "text"},
            {"key": "memo", "label": "Memo", "kind": "text"},
            {"key": "amount", "label": "Amount", "kind": "money", "sum": True},
        ]
        return {
            "title": "Insurance Claims Report",
            "sheet_name": "Claims",
            "filters": filters,
            "group_by": "company",
            "columns": columns,
            "rows": rows,
            "sheets": [
                {"name": "Invoices", "columns": invoice_columns, "rows": invoice_rows},
                {"name": "Payments", "columns": payment_columns, "rows": payment_rows},
            ],
        }

    # ------------------------------------------------------------------
    # Aging report (open insurance company invoices)
    # ------------------------------------------------------------------
    def _aging_data(self):
        today = fields.Date.context_today(self)
        domain = [
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("insurance_invoice_role", "=", "insurance"),
            ("amount_residual", ">", 0),
            ("company_id", "in", self.env.companies.ids),
        ]
        if self.date_from:
            domain.append(("invoice_date", ">=", self.date_from))
        if self.date_to:
            domain.append(("invoice_date", "<=", self.date_to))
        if self.insurance_company_id:
            domain.append(("partner_id", "=", self.insurance_company_id.partner_id.id))
        if self.insurance_plan_id:
            domain.append(("insurance_sale_order_id.insurance_plan_id", "=", self.insurance_plan_id.id))
        if self.partner_id:
            domain.append(("insurance_patient_id", "=", self.partner_id.id))

        moves = self.env["account.move"].search(
            domain, order="partner_id, invoice_date_due, invoice_date, id"
        )

        bucket_keys = ("current", "d30", "d60", "d90", "d90p")

        def bucket_of(days_overdue):
            if days_overdue <= 0:
                return "current"
            if days_overdue <= 30:
                return "d30"
            if days_overdue <= 60:
                return "d60"
            if days_overdue <= 90:
                return "d90"
            return "d90p"

        rows = []
        for move in moves:
            due = move.invoice_date_due or move.invoice_date or today
            overdue = (today - due).days
            residual = abs(move.amount_residual_signed)
            row = {
                "company": move.partner_id.display_name or "-",
                "invoice": move.name or "",
                "patient": move.insurance_patient_id.display_name or "",
                "plan": move.insurance_sale_order_id.insurance_plan_id.display_name or "",
                "invoice_date": str(move.invoice_date or ""),
                "due_date": str(due),
                "days": max(overdue, 0),
                "total": residual,
            }
            for key in bucket_keys:
                row[key] = 0.0
            row[bucket_of(overdue)] = residual
            rows.append(row)

        summary = OrderedDict()
        for row in rows:
            bucket = summary.setdefault(
                row["company"], {"company": row["company"], "count": 0, "total": 0.0, **{k: 0.0 for k in bucket_keys}}
            )
            bucket["count"] += 1
            bucket["total"] += row["total"]
            for key in bucket_keys:
                bucket[key] += row[key]

        bucket_columns = [
            {"key": "current", "label": "Not Due", "kind": "money", "width": 24, "sum": True, "blank_zero": True},
            {"key": "d30", "label": "1 - 30", "kind": "money", "width": 24, "sum": True, "blank_zero": True},
            {"key": "d60", "label": "31 - 60", "kind": "money", "width": 24, "sum": True, "blank_zero": True},
            {"key": "d90", "label": "61 - 90", "kind": "money", "width": 24, "sum": True, "blank_zero": True},
            {"key": "d90p", "label": "Over 90", "kind": "money", "width": 24, "sum": True, "blank_zero": True},
            {"key": "total", "label": "Total Open", "kind": "money", "width": 26, "sum": True},
        ]
        columns = [
            {"key": "company", "label": "Insurance Company", "kind": "text", "width": 40, "pdf": False},
            {"key": "invoice", "label": "Invoice", "kind": "text", "width": 30},
            {"key": "patient", "label": "Patient / Customer", "kind": "text", "width": 44},
            {"key": "invoice_date", "label": "Invoice Date", "kind": "text", "width": 22},
            {"key": "due_date", "label": "Due Date", "kind": "text", "width": 22},
            {"key": "days", "label": "Days", "kind": "int", "width": 14},
            *bucket_columns,
            {"key": "plan", "label": "Plan", "kind": "text", "width": 24, "pdf": False},
        ]
        summary_columns = [
            {"key": "company", "label": "Insurance Company", "kind": "text"},
            {"key": "count", "label": "Open Invoices", "kind": "int", "sum": True},
            *[{k: v for k, v in col.items() if k != "width"} for col in bucket_columns],
        ]
        filters = self._common_filters() + [("Aging measured at", str(today))]
        return {
            "title": "Insurance Aging Report",
            "sheet_name": "Aging Detail",
            "filters": filters,
            "group_by": "company",
            "columns": columns,
            "rows": rows,
            "sheets": [
                {"name": "By Insurance Company", "columns": summary_columns, "rows": list(summary.values())},
            ],
        }

    # ------------------------------------------------------------------
    # Product coverage report
    # ------------------------------------------------------------------
    def _order_datetime_bounds(self):
        """Date filters are entered in the user's own timezone, but
        sale.order.date_order is stored in UTC."""
        tz = pytz.timezone(self.env.user.tz or "UTC")
        start = end = None
        if self.date_from:
            start = tz.localize(datetime.combine(self.date_from, time.min)).astimezone(pytz.utc)
            start = start.replace(tzinfo=None)
        if self.date_to:
            end = tz.localize(datetime.combine(self.date_to, time.max)).astimezone(pytz.utc)
            end = end.replace(tzinfo=None)
        return start, end

    def _coverage_data(self):
        domain = [
            ("order_id.insurance_enabled", "=", True),
            ("order_id.state", "!=", "cancel"),
            ("insurance_amount", ">", 0),
            ("order_id.company_id", "in", self.env.companies.ids),
        ]
        start, end = self._order_datetime_bounds()
        if start:
            domain.append(("order_id.date_order", ">=", start))
        if end:
            domain.append(("order_id.date_order", "<=", end))
        if self.insurance_company_id:
            domain.append(("order_id.insurance_company_id", "=", self.insurance_company_id.id))
        if self.insurance_plan_id:
            domain.append(("order_id.insurance_plan_id", "=", self.insurance_plan_id.id))
        if self.partner_id:
            domain.append(("order_id.partner_id", "=", self.partner_id.id))
        if self.product_id:
            domain.append(("product_id", "=", self.product_id.id))

        lines = self.env["sale.order.line"].search(domain)
        lines = lines.sorted(
            key=lambda l: (
                l.order_id.insurance_company_id.display_name or "",
                l.order_id.date_order or datetime.min,
                l.order_id.id,
                l.id,
            )
        )

        rows = []
        for line in lines:
            order = line.order_id
            order_date = order.date_order and fields.Datetime.context_timestamp(self, order.date_order).date()
            rows.append(
                {
                    "company": order.insurance_company_id.display_name or "-",
                    "order": order.name,
                    "date": str(order_date or ""),
                    "partner": order.partner_id.display_name or "",
                    "plan": order.insurance_plan_id.display_name or "",
                    "product": line.product_id.display_name or line.name or "",
                    "qty": line.product_uom_qty,
                    "sale_value": line.full_sale_amount,
                    "insurance": line.insurance_amount,
                    "customer": line.customer_copay_amount,
                    "not_covered": line.amount_not_covered,
                    "coverage_pct": line.insurance_coverage_percent_report,
                    "invoice": line.insurance_invoice_report_id.name or "",
                }
            )

        filters = self._common_filters() + [("Product", self.product_id.display_name or "All")]
        columns = [
            {"key": "company", "label": "Insurance Company", "kind": "text", "width": 40, "pdf": False},
            {"key": "order", "label": "Sales Order", "kind": "text", "width": 24},
            {"key": "date", "label": "Date", "kind": "text", "width": 22},
            {"key": "partner", "label": "Customer / Patient", "kind": "text", "width": 40},
            {"key": "product", "label": "Product", "kind": "text", "width": 44},
            {"key": "qty", "label": "Qty", "kind": "qty", "width": 12, "sum": True},
            {"key": "sale_value", "label": "Sale Value", "kind": "money", "width": 26, "sum": True},
            {"key": "insurance", "label": "Insurance Covered", "kind": "money", "width": 32, "sum": True},
            {"key": "customer", "label": "Customer Share", "kind": "money", "width": 30, "sum": True},
            {"key": "not_covered", "label": "Not Covered", "kind": "money", "width": 26, "sum": True},
            {"key": "coverage_pct", "label": "Coverage %", "kind": "pct", "width": 24},
            {"key": "plan", "label": "Plan", "kind": "text", "width": 24, "pdf": False},
            {"key": "invoice", "label": "Customer Invoice", "kind": "text", "width": 26, "pdf": False},
        ]

        def summary(key_field, label):
            grouped = OrderedDict()
            for row in rows:
                bucket = grouped.setdefault(
                    row[key_field],
                    {"name": row[key_field], "qty": 0.0, "sale_value": 0.0, "insurance": 0.0,
                     "customer": 0.0, "not_covered": 0.0},
                )
                for k in ("qty", "sale_value", "insurance", "customer", "not_covered"):
                    bucket[k] += row[k] or 0.0
            out = sorted(grouped.values(), key=lambda b: (-b["insurance"], b["name"]))
            for bucket in out:
                bucket["coverage_pct"] = (
                    bucket["insurance"] / bucket["sale_value"] * 100.0 if bucket["sale_value"] else 0.0
                )
            cols = [
                {"key": "name", "label": label, "kind": "text"},
                {"key": "qty", "label": "Qty", "kind": "qty", "sum": True},
                {"key": "sale_value", "label": "Sale Value", "kind": "money", "sum": True},
                {"key": "insurance", "label": "Insurance Covered", "kind": "money", "sum": True},
                {"key": "customer", "label": "Customer Share", "kind": "money", "sum": True},
                {"key": "not_covered", "label": "Not Covered", "kind": "money", "sum": True},
                {"key": "coverage_pct", "label": "Coverage %", "kind": "pct"},
            ]
            return cols, out

        company_cols, company_rows = summary("company", "Insurance Company")
        product_cols, product_rows = summary("product", "Product")
        return {
            "title": "Insurance Product Coverage Report",
            "sheet_name": "Coverage Lines",
            "filters": filters,
            "group_by": "company",
            "columns": columns,
            "rows": rows,
            "sheets": [
                {"name": "By Insurance Company", "columns": company_cols, "rows": company_rows},
                {"name": "By Product", "columns": product_cols, "rows": product_rows},
            ],
        }
