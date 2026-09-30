# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError


class InsuranceDashboard(models.AbstractModel):
    _name = "insurance.dashboard"
    _description = "Insurance Dashboard Data Provider"

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    @api.model
    def _check_dashboard_access(self):
        """The two public methods below are reachable through the web client's
        RPC by ANY logged-in user (portal users included), and part of the
        data is read with sudo(). Do not rely on model access rights alone:
        only Insurance users may use the dashboard."""
        if not self.env.user.has_group("insurance_management.group_insurance_user"):
            raise AccessError("The Insurance Dashboard is only available to Insurance users.")

    @api.model
    def get_filters_meta(self):
        self._check_dashboard_access()
        companies = self.env["insurance.company"].search_read([], ["id", "name"])
        plans = self.env["insurance.plan"].search_read(
            [], ["id", "name", "insurance_company_id"]
        )
        return {"companies": companies, "plans": plans}

    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None, company_ids=None, plan_ids=None, mode=None):
        """``mode`` is "cards", "charts" or None (everything). The two
        dashboard pages share the same filters but each only asks for what
        it actually shows, so neither pays for the other's queries."""
        self._check_dashboard_access()
        want_cards = mode in (None, "cards")
        want_charts = mode in (None, "charts")

        date_from, date_to = self._normalize_dates(date_from, date_to)
        sale_domain = self._build_sale_domain(date_from, date_to, company_ids, plan_ids)
        orders = self.env["sale.order"].search(sale_domain)
        claims = self._search_claims(date_from, date_to, company_ids)

        kpis = self._compute_kpis(orders, claims)
        # The aging snapshot feeds KPI cards (Open / Overdue Receivable) as
        # well as the aging chart, so both pages get it.
        aging = self._compute_aging(company_ids, plan_ids)
        result = {
            "date_from": fields.Date.to_string(date_from),
            "date_to": fields.Date.to_string(date_to),
            "kpis": kpis,
            "sales_trend": self._compute_sales_trend(orders, date_from, date_to),
            "aging": aging,
            "snapshot": aging["snapshot"],
            "currency_symbol": self.env.company.currency_id.symbol or "",
        }

        if want_cards:
            # Previous period of equal length, immediately before date_from,
            # so every KPI card can show a "vs previous period" trend badge.
            period_days = (date_to - date_from).days + 1
            prev_date_to = date_from - relativedelta(days=1)
            prev_date_from = prev_date_to - relativedelta(days=period_days - 1)
            prev_sale_domain = self._build_sale_domain(prev_date_from, prev_date_to, company_ids, plan_ids)
            prev_orders = self.env["sale.order"].search(prev_sale_domain)
            prev_claims = self._search_claims(prev_date_from, prev_date_to, company_ids)
            prev_kpis = self._compute_kpis(prev_orders, prev_claims)
            result["kpi_deltas"] = self._compute_kpi_deltas(kpis, prev_kpis)
            result["top_patients"] = self._compute_top_patients(orders)
            result["recent_claims"] = self._compute_recent_claims(claims)

        if want_charts:
            result["claim_status"] = self._compute_claim_status(claims)
            result["coverage_split"] = self._compute_coverage_split(orders)
            result["top_products"] = self._compute_top_products(orders)
            result["outstanding_by_company"] = self._compute_outstanding_by_company(claims)
            result["top_companies"] = self._compute_top_grouping(orders, "insurance_company_id")
            result["top_plans"] = self._compute_top_grouping(orders, "insurance_plan_id")

        return result

    def _compute_kpi_deltas(self, kpis, prev_kpis):
        deltas = {}
        for key, curr in kpis.items():
            prev = prev_kpis.get(key) or 0.0
            if prev:
                deltas[key] = round((curr - prev) / prev * 100.0, 1)
            elif curr:
                deltas[key] = None  # no previous data to compare against ("New")
            else:
                deltas[key] = 0.0
        return deltas

    def _search_claims(self, date_from, date_to, company_ids):
        domain = [("date_from", "<=", date_to), ("date_to", ">=", date_from)]
        if company_ids:
            domain.append(("insurance_company_id", "in", company_ids))
        return self.env["insurance.claim"].search(domain)

    # ------------------------------------------------------------------
    # Domains
    # ------------------------------------------------------------------
    def _normalize_dates(self, date_from, date_to):
        today = fields.Date.context_today(self)
        if not date_to:
            date_to = today
        else:
            date_to = fields.Date.from_string(date_to)
        if not date_from:
            date_from = date_to - relativedelta(months=11, day=1)
        else:
            date_from = fields.Date.from_string(date_from)
        return date_from, date_to

    def _build_sale_domain(self, date_from, date_to, company_ids, plan_ids):
        # date_order is a Datetime field: bound it explicitly to the full
        # day range so the last day of the period isn't cut off at midnight.
        domain = [
            ("insurance_enabled", "=", True),
            ("state", "in", ("sale", "done")),
            ("date_order", ">=", f"{fields.Date.to_string(date_from)} 00:00:00"),
            ("date_order", "<=", f"{fields.Date.to_string(date_to)} 23:59:59"),
        ]
        if company_ids:
            domain.append(("insurance_company_id", "in", company_ids))
        if plan_ids:
            domain.append(("insurance_plan_id", "in", plan_ids))
        return domain

    # ------------------------------------------------------------------
    # KPIs
    # ------------------------------------------------------------------
    def _compute_kpis(self, orders, claims):
        total_sales = sum(orders.mapped("amount_total"))
        total_covered = sum(orders.mapped("amount_insurance_covered"))
        total_customer = sum(orders.mapped("amount_customer_responsibility"))

        total_claimed = sum(claims.mapped("total_claimed"))
        total_collected = sum(claims.mapped("total_paid"))
        total_outstanding = sum(claims.mapped("remaining_balance"))
        open_claims = claims.filtered(lambda c: c.state not in ("paid", "cancelled", "rejected"))

        return {
            "orders_count": len(orders),
            "total_sales": total_sales,
            "total_covered": total_covered,
            "total_customer": total_customer,
            "coverage_ratio": (total_covered / total_sales * 100.0) if total_sales else 0.0,
            "total_claimed": total_claimed,
            "total_collected": total_collected,
            "total_outstanding": total_outstanding,
            "collection_rate": (total_collected / total_claimed * 100.0) if total_claimed else 0.0,
            "open_claims_count": len(open_claims),
            "claims_count": len(claims),
            "total_rejected": sum(claims.mapped("total_rejected")),
            "avg_order_value": (total_sales / len(orders)) if orders else 0.0,
            "patients_count": len(orders.mapped("partner_id")),
        }

    # ------------------------------------------------------------------
    # Charts
    # ------------------------------------------------------------------
    def _compute_sales_trend(self, orders, date_from, date_to):
        # Grouped by hand (instead of read_group's locale-dependent month
        # label) so the month buckets line up exactly with the labels below.
        by_month = {}
        for order in orders:
            if not order.date_order:
                continue
            key = (order.date_order.year, order.date_order.month)
            bucket = by_month.setdefault(
                key, {"total": 0.0, "covered": 0.0, "customer": 0.0, "count": 0}
            )
            bucket["total"] += order.amount_total
            bucket["covered"] += order.amount_insurance_covered
            bucket["customer"] += order.amount_customer_responsibility
            bucket["count"] += 1

        labels, insured_total, covered, customer, counts, months = [], [], [], [], [], []
        cursor = date_from.replace(day=1)
        end_cursor = date_to.replace(day=1)
        while cursor <= end_cursor:
            bucket = by_month.get((cursor.year, cursor.month))
            labels.append(cursor.strftime("%b %Y"))
            months.append(fields.Date.to_string(cursor))
            insured_total.append(bucket["total"] if bucket else 0.0)
            covered.append(bucket["covered"] if bucket else 0.0)
            customer.append(bucket["customer"] if bucket else 0.0)
            counts.append(bucket["count"] if bucket else 0)
            cursor = cursor + relativedelta(months=1)

        return {
            "labels": labels,
            "months": months,
            "order_counts": counts,
            "series": [
                {"key": "total", "label": "Total Sales", "color": "#6366F1", "data": insured_total},
                {"key": "covered", "label": "Insurance Covered", "color": "#22C55E", "data": covered},
                {"key": "customer", "label": "Customer Share", "color": "#F59E0B", "data": customer},
            ],
        }

    def _compute_outstanding_by_company(self, claims):
        totals = {}
        for claim in claims:
            if claim.remaining_balance <= 0:
                continue
            company = claim.insurance_company_id
            totals[company] = totals.get(company, 0.0) + claim.remaining_balance
        ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:8]
        return {
            "labels": [rec.name for rec, _ in ranked],
            "values": [amount for _, amount in ranked],
            "ids": [rec.id for rec, _ in ranked],
        }

    def _compute_top_grouping(self, orders, field_name):
        totals = {}
        for order in orders:
            record = order[field_name]
            if not record:
                continue
            totals[record] = totals.get(record, 0.0) + order.amount_insurance_covered
        ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:8]
        return {
            "labels": [rec.name for rec, _ in ranked],
            "values": [amount for _, amount in ranked],
            "ids": [rec.id for rec, _ in ranked],
        }

    # ------------------------------------------------------------------
    # Detail widgets
    # ------------------------------------------------------------------
    _STATE_COLORS = {
        "draft": "#94A3B8",
        "submitted": "#6366F1",
        "partial_paid": "#F59E0B",
        "paid": "#22C55E",
        "rejected": "#EF4444",
        "cancelled": "#64748B",
    }

    def _compute_claim_status(self, claims):
        labels = dict(self.env["insurance.claim"]._fields["state"].selection)
        buckets = {}
        for claim in claims:
            bucket = buckets.setdefault(claim.state, {"count": 0, "amount": 0.0})
            bucket["count"] += 1
            bucket["amount"] += claim.total_claimed
        keys = [key for key in labels if key in buckets]
        return {
            "keys": keys,
            "labels": [labels[key] for key in keys],
            "counts": [buckets[key]["count"] for key in keys],
            "amounts": [buckets[key]["amount"] for key in keys],
            "colors": [self._STATE_COLORS.get(key, "#64748B") for key in keys],
        }

    def _compute_coverage_split(self, orders):
        covered = sum(orders.mapped("amount_insurance_covered"))
        customer = sum(orders.mapped("amount_customer_responsibility"))
        return {
            "labels": ["Insurance Covered", "Customer Share"],
            "values": [covered, customer],
            "colors": ["#22C55E", "#F59E0B"],
        }

    def _compute_aging(self, company_ids, plan_ids):
        """Open insurance-company invoices bucketed by days past due (a
        point-in-time snapshot, independent of the period filter)."""
        today = fields.Date.context_today(self)
        base = [
            ("move_type", "=", "out_invoice"),
            ("state", "=", "posted"),
            ("insurance_invoice_role", "=", "insurance"),
            ("amount_residual", ">", 0),
        ]
        if company_ids:
            partners = self.env["insurance.company"].browse(company_ids).exists().mapped("partner_id").ids
            base.append(("partner_id", "in", partners))
        if plan_ids:
            base.append(("insurance_sale_order_id.insurance_plan_id", "in", plan_ids))

        # (label, first overdue day, last overdue day, colour)
        definitions = [
            ("Not Due", None, 0, "#22C55E"),
            ("1-30 days", 1, 30, "#84CC16"),
            ("31-60 days", 31, 60, "#F59E0B"),
            ("61-90 days", 61, 90, "#FB923C"),
            ("Over 90 days", 91, None, "#EF4444"),
        ]

        def due_domain(first, last):
            # overdue days d = today - due_date, so d >= first  <=>  due <= today - first
            domain = []
            if first is not None:
                domain.append(("invoice_date_due", "<=", fields.Date.to_string(today - relativedelta(days=first))))
            if last is not None:
                domain.append(("invoice_date_due", ">=", fields.Date.to_string(today - relativedelta(days=last))))
            return domain

        moves = self.env["account.move"].sudo().search(base)
        values = [0.0] * len(definitions)
        counts = [0] * len(definitions)
        weighted_age = 0.0
        for move in moves:
            due = move.invoice_date_due or move.invoice_date or today
            overdue = (today - due).days
            residual = abs(move.amount_residual_signed)
            for idx, (_label, first, last, _color) in enumerate(definitions):
                if (first is None or overdue >= first) and (last is None or overdue <= last):
                    values[idx] += residual
                    counts[idx] += 1
                    break
            weighted_age += residual * max((today - (move.invoice_date or today)).days, 0)

        total_open = sum(values)
        return {
            "labels": [d[0] for d in definitions],
            "values": values,
            "counts": counts,
            "colors": [d[3] for d in definitions],
            "domains": [base + due_domain(d[1], d[2]) for d in definitions],
            "base_domain": base,
            "overdue_domain": base + [("invoice_date_due", "<", fields.Date.to_string(today))],
            "snapshot": {
                "open_amount": total_open,
                "open_invoices": sum(counts),
                "overdue_amount": sum(values[1:]),
                "overdue_invoices": sum(counts[1:]),
                "avg_age_days": (weighted_age / total_open) if total_open else 0.0,
            },
        }

    def _compute_top_products(self, orders):
        totals = {}
        for line in orders.order_line:
            if not line.product_id or line.insurance_amount <= 0:
                continue
            totals[line.product_id] = totals.get(line.product_id, 0.0) + line.insurance_amount
        ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:8]
        return {
            "labels": [rec.display_name for rec, _ in ranked],
            "values": [amount for _, amount in ranked],
            "ids": [rec.id for rec, _ in ranked],
        }

    def _compute_top_patients(self, orders):
        totals = {}
        for order in orders:
            bucket = totals.setdefault(
                order.partner_id, {"orders": 0, "covered": 0.0, "customer": 0.0}
            )
            bucket["orders"] += 1
            bucket["covered"] += order.amount_insurance_covered
            bucket["customer"] += order.amount_customer_responsibility
        ranked = sorted(totals.items(), key=lambda kv: kv[1]["covered"], reverse=True)[:6]
        return [
            {"id": partner.id, "name": partner.display_name, **bucket} for partner, bucket in ranked
        ]

    def _compute_recent_claims(self, claims):
        labels = dict(claims._fields["state"].selection) if claims else {}
        recent = claims.sorted(lambda c: c.write_date or c.create_date, reverse=True)[:8]
        return [
            {
                "id": claim.id,
                "name": claim.name,
                "company": claim.insurance_company_id.name,
                "state": claim.state,
                "state_label": labels.get(claim.state, claim.state),
                "color": self._STATE_COLORS.get(claim.state, "#64748B"),
                "total_claimed": claim.total_claimed,
                "total_paid": claim.total_paid,
                "remaining": claim.remaining_balance,
            }
            for claim in recent
        ]
