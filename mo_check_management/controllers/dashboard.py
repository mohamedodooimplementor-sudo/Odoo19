from dateutil.relativedelta import relativedelta

from odoo import http, fields, _
from odoo.http import request
from odoo.tools.misc import babel_locale_parse

from odoo.addons.mo_check_management.models.check import CLOSED_STATES


class CheckDashboardController(http.Controller):

    @http.route("/mo_check_management/dashboard", type="jsonrpc", auth="user", methods=["POST"])
    def dashboard(self, company_ids=None, filter_company_id=None, **kwargs):
        env = request.env
        # The JS sends the companies ticked in the switcher explicitly (first = main one).
        # Keep only those the user may really access, so this can't be used to peek at others.
        user_company_ids = env.user.company_ids.ids
        active_ids = [
            int(cid) for cid in (company_ids or []) if str(cid).isdigit() and int(cid) in user_company_ids
        ] or [env.company.id]
        available = env["res.company"].browse(active_ids)
        # Optional narrowing to ONE of the companies ticked in the switcher.
        if filter_company_id and int(filter_company_id) in active_ids:
            active_ids = [int(filter_company_id)]
        env = env(context=dict(env.context, allowed_company_ids=active_ids))
        Check = env["check.management"]
        companies = env["res.company"].browse(active_ids)
        company = companies[:1]
        company_currency = company.currency_id
        base = Check.search([("company_id", "in", companies.ids), ("active", "=", True)])
        today = fields.Date.context_today(env.user)

        def amount_of(check):
            """Amount in the company currency so that mixed-currency checks add up."""
            if check.currency_id == company_currency:
                return check.amount
            return check.currency_id._convert(
                check.amount, company_currency, company, check.due_date or today
            )

        def money(records):
            return sum(amount_of(c) for c in records)

        incoming = base.filtered(lambda c: c.check_type == "incoming")
        outgoing = base.filtered(lambda c: c.check_type == "outgoing")
        open_checks = base.filtered(lambda c: c.state not in CLOSED_STATES)
        open_in = open_checks.filtered(lambda c: c.check_type == "incoming")
        open_out = open_checks.filtered(lambda c: c.check_type == "outgoing")
        due_today = open_checks.filtered(lambda c: c.due_date == today)
        overdue = open_checks.filtered(lambda c: c.due_date and c.due_date < today)
        under_collection = base.filtered(lambda c: c.state == "under_collection")
        collected = base.filtered(lambda c: c.state in ("collected", "cleared"))
        bounced = base.filtered(lambda c: c.state == "bounced")

        # ---- status distribution (all statuses but cancelled)
        selection = dict(Check._fields["state"].selection)
        states = {}
        for check in base.filtered(lambda c: c.state != "cancelled"):
            item = states.setdefault(check.state, {
                "key": check.state, "label": selection.get(check.state, check.state),
                "count": 0, "amount": 0.0,
            })
            item["count"] += 1
            item["amount"] += amount_of(check)

        # ---- cash flow: open checks by due month (overdue first)
        try:
            locale = babel_locale_parse(env.user.lang or "en_US")
        except Exception:
            locale = "en_US"
        from babel.dates import format_date as babel_format_date

        first_of_month = today.replace(day=1)
        buckets = [{
            "key": "overdue", "label": _("Overdue"), "date_from": False,
            "date_to": str(today - relativedelta(days=1)),
        }]
        for i in range(6):
            start = first_of_month + relativedelta(months=i)
            end = start + relativedelta(months=1, days=-1)
            if i == 0:
                start = today
            buckets.append({
                "key": "m%d" % i,
                "label": babel_format_date(start, format="MMM yy", locale=locale),
                "date_from": str(start), "date_to": str(end),
            })
        for bucket in buckets:
            d_from = fields.Date.to_date(bucket["date_from"]) if bucket["date_from"] else None
            d_to = fields.Date.to_date(bucket["date_to"])
            inside = open_checks.filtered(
                lambda c: c.due_date and (d_from is None or c.due_date >= d_from) and c.due_date <= d_to
            )
            bucket["incoming"] = money(inside.filtered(lambda c: c.check_type == "incoming"))
            bucket["outgoing"] = money(inside.filtered(lambda c: c.check_type == "outgoing"))

        # ---- banks and partners
        banks = {}
        for check in base.filtered(lambda c: c.bank_id):
            item = banks.setdefault(
                check.bank_id.id, {"name": check.bank_id.display_name, "count": 0, "amount": 0.0}
            )
            item["count"] += 1
            item["amount"] += amount_of(check)

        partners = {}
        for check in open_checks:
            item = partners.setdefault(check.partner_id.id, {
                "name": check.partner_id.display_name, "incoming": 0.0, "outgoing": 0.0, "count": 0})
            item[check.check_type] += amount_of(check)
            item["count"] += 1

        due_soon = open_checks.filtered(
            lambda c: c.due_date and today <= c.due_date <= fields.Date.add(today, days=30)
        ).sorted(key=lambda c: (c.due_date, c.id))[:10]

        return {
            "today": str(today),
            "currency": company_currency.name,
            "companies": companies.mapped("name"),
            "available_companies": [{"id": c.id, "name": c.name} for c in available],
            "selected_company": companies.id if len(companies) == 1 and len(available) > 1 else False,
            "net_open": money(open_in) - money(open_out),
            "cards": {
                "total": {"count": len(base), "amount": money(base)},
                "incoming": {"count": len(incoming), "amount": money(incoming)},
                "outgoing": {"count": len(outgoing), "amount": money(outgoing)},
                "under_collection": {"count": len(under_collection), "amount": money(under_collection)},
                "collected": {"count": len(collected), "amount": money(collected)},
                "bounced": {"count": len(bounced), "amount": money(bounced)},
                "due_today": {"count": len(due_today), "amount": money(due_today)},
                "overdue": {"count": len(overdue), "amount": money(overdue)},
            },
            "states": sorted(states.values(), key=lambda s: -s["amount"]),
            "cashflow": buckets,
            "banks": [
                {"id": key, **value}
                for key, value in sorted(banks.items(), key=lambda x: x[1]["amount"], reverse=True)[:6]
            ],
            "partners": [
                {"id": key, **value}
                for key, value in sorted(
                    partners.items(), key=lambda x: x[1]["incoming"] + x[1]["outgoing"], reverse=True
                )[:6]
            ],
            "due_soon": [{
                "id": c.id, "name": c.name, "check_number": c.check_number,
                "partner": c.partner_id.display_name, "due_date": str(c.due_date),
                "amount": c.amount, "currency": c.currency_id.name,
                "type": c.check_type, "state": c.state,
                "state_label": selection.get(c.state, c.state),
            } for c in due_soon],
        }
