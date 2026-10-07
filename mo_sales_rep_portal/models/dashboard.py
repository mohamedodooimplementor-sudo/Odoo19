from collections import defaultdict
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError

from . import analytics


class SalesRepDashboardMixin(models.Model):
    _inherit = 'mo.sales.rep'

    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None, rep_id=False, team_id=False, route_id=False,
                           partner_name=False):
        if not self.env.user.has_group('mo_sales_rep_portal.group_mo_rep_manager'):
            raise AccessError(_('Only sales managers can open the management dashboard.'))
        env = self.env
        today = fields.Date.context_today(self)
        d_to = fields.Date.to_date(date_to) if date_to else today
        d_from = fields.Date.to_date(date_from) if date_from else d_to.replace(day=1)
        if d_from > d_to:
            d_from, d_to = d_to, d_from
        week_start = today - timedelta(days=(today.weekday() + 1) % 7)
        month_start = today.replace(day=1)

        # ---- filters
        rep_domain = []
        if rep_id:
            rep_domain.append(('id', '=', int(rep_id)))
        if team_id:
            rep_domain.append(('team_id', '=', int(team_id)))
        if route_id:
            route = env['mo.sales.route'].browse(int(route_id)).exists()
            rep_domain.append(('id', '=', route.rep_id.id if route else 0))
        reps = self.search(rep_domain)
        partners = env['res.partner'].search([('name', 'ilike', partner_name)]) if partner_name else env['res.partner']
        route = env['mo.sales.route'].browse(int(route_id)).exists() if route_id else env['mo.sales.route']

        Order, Pay, Visit = env['sale.order'], env['account.payment'], env['mo.sales.visit']

        def day_dt(d, end=False):
            return datetime.combine(d, datetime.max.time() if end else datetime.min.time())

        def partner_filter(domain, field='partner_id'):
            return domain + [(field, 'in', partners.ids)] if partner_name else domain

        def orders_of(rep, a, b):
            return Order.search(partner_filter([
                ('state', 'in', ('sale', 'done')), '|', ('mo_rep_id', '=', rep.id), ('user_id', '=', rep.user_id.id),
                ('date_order', '>=', day_dt(a)), ('date_order', '<=', day_dt(b, True))]))

        rows, all_orders, all_pays = [], Order, Pay
        aging_total = {b: 0.0 for b in analytics.BUCKETS}
        for rep in reps:
            vdom = [('rep_id', '=', rep.id), ('visit_date', '>=', d_from), ('visit_date', '<=', d_to)]
            if route:
                vdom.append(('route_id', '=', route.id))
            visits = Visit.search(partner_filter(vdom))
            orders = orders_of(rep, d_from, d_to)
            pays = Pay.search(partner_filter([
                ('mo_rep_id', '=', rep.id), ('payment_type', '=', 'inbound'),
                ('state', 'not in', ('draft', 'canceled', 'rejected')), ('date', '>=', d_from), ('date', '<=', d_to)]))
            all_orders |= orders
            all_pays |= pays
            by_type = {'cash': 0.0, 'bank': 0.0, 'cheque': 0.0, 'other': 0.0}
            for p in pays:
                by_type[p.mo_method_id.method_type or 'other'] += p.amount
            customers = rep.get_customers()
            if partner_name:
                customers = customers & partners
            completed = visits.filtered(lambda v: v.state == 'completed')
            visited = completed.mapped('partner_id')
            sales = sum(orders.mapped('amount_total'))
            collection = sum(by_type.values())
            timed = completed.filtered(lambda v: v.duration > 0)
            converted = completed.filtered(lambda v: v.sale_order_ids.filtered(lambda o: o.state != 'cancel'))
            ag = analytics.aging(analytics.open_invoices(env, [('partner_id', 'in', customers.ids)]), today)
            for bucket in analytics.BUCKETS:
                aging_total[bucket] += ag[bucket]
            perf = rep.performance(d_from, d_to)
            target = rep.current_target(d_to)
            expenses = env['mo.sales.expense'].search([('rep_id', '=', rep.id), ('date', '>=', d_from), ('date', '<=', d_to),
                                                       ('state', 'in', ('submitted', 'approved'))])
            returns = env['stock.picking'].search_count([
                ('mo_rep_id', '=', rep.id), ('mo_operation', '=', 'customer_return'),
                ('create_date', '>=', day_dt(d_from)), ('create_date', '<=', day_dt(d_to, True))])
            rows.append({
                'id': rep.id, 'name': rep.name, 'user_id': rep.user_id.id,
                'visited_ids': customers.filtered(lambda c: c in visited).ids[:1000],
                'not_visited_ids': (customers - visited).ids[:1000],
                'planned': len(visits.filtered(lambda v: v.state in ('planned', 'started'))),
                'completed': len(completed),
                'missed': len(visits.filtered(lambda v: v.state == 'missed')),
                'sales': sales, 'collection': collection,
                'cash': by_type['cash'], 'bank': by_type['bank'], 'cheque': by_type['cheque'],
                'orders': len(orders),
                'avg_order': sales / len(orders) if orders else 0.0,
                'conversion': round(100.0 * len(converted) / len(completed), 1) if completed else 0.0,
                'avg_minutes': round(sum(timed.mapped('duration')) * 60.0 / len(timed), 1) if timed else 0.0,
                'collection_ratio': round(100.0 * collection / sales, 1) if sales else 0.0,
                'customers': len(customers),
                'active_customers': len(customers.filtered(lambda c: c in visited)),
                'not_visited': len(customers - visited),
                'new_customers': perf['new_customers'],
                'outstanding': ag['total'], 'overdue': ag['overdue'],
                'target_pct': target._achievement(perf) if target else None,
                'expenses': sum(expenses.mapped('amount')),
                'expenses_pending': len(expenses.filtered(lambda e: e.state == 'submitted')),
                'returns': returns,
            })

        def sales_between(a, b):
            return sum(sum(orders_of(r, a, b).mapped('amount_total')) for r in reps)

        kpi = {'sales_today': sales_between(today, today), 'sales_week': sales_between(week_start, today),
               'sales_month': sales_between(month_start, today)}
        sum_keys = ('planned', 'completed', 'missed', 'sales', 'collection', 'cash', 'bank', 'cheque', 'orders',
                    'customers', 'active_customers', 'not_visited', 'new_customers', 'outstanding', 'overdue',
                    'expenses', 'expenses_pending', 'returns')
        totals = {k: sum(r[k] for r in rows) for k in sum_keys}
        done = totals['completed']
        totals['avg_order'] = totals['sales'] / totals['orders'] if totals['orders'] else 0.0
        totals['collection_ratio'] = round(100.0 * totals['collection'] / totals['sales'], 1) if totals['sales'] else 0.0
        totals['conversion'] = round(sum(r['conversion'] * r['completed'] for r in rows) / done, 1) if done else 0.0
        timed_rows = [r for r in rows if r['avg_minutes']]
        totals['avg_minutes'] = round(sum(r['avg_minutes'] for r in timed_rows) / len(timed_rows), 1) if timed_rows else 0.0
        pcts = [r['target_pct'] for r in rows if r['target_pct'] is not None]
        totals['target_pct'] = round(sum(pcts) / len(pcts), 1) if pcts else None

        by_customer = defaultdict(float)
        for o in all_orders:
            by_customer[o.partner_id] += o.amount_total
        top_customers = [{'id': p.id, 'name': p.display_name, 'sales': amt}
                         for p, amt in sorted(by_customer.items(), key=lambda kv: -kv[1])[:5]]

        span = min((d_to - d_from).days + 1, 31)
        first = d_to - timedelta(days=span - 1)
        sales_by_day, coll_by_day = defaultdict(float), defaultdict(float)
        for o in all_orders:
            sales_by_day[fields.Datetime.context_timestamp(self, o.date_order).date()] += o.amount_total
        for p in all_pays:
            coll_by_day[p.date] += p.amount
        trend = []
        for i in range(span):
            d = first + timedelta(days=i)
            trend.append({'date': d.strftime('%m-%d'), 'full': str(d),
                          'sales': sales_by_day.get(d, 0.0), 'collection': coll_by_day.get(d, 0.0)})
        every = self.search([])
        return {
            'date_from': str(d_from), 'date_to': str(d_to), 'rows': rows, 'totals': totals, 'kpi': kpi,
            'top_customers': top_customers, 'trend': trend, 'aging': aging_total,
            'rep_user_ids': reps.mapped('user_id').ids, 'rep_ids': reps.ids, 'today': str(today),
            'week_start': str(week_start), 'month_start': str(month_start),
            'all_customer_ids': sorted({i for r in rows for i in r['visited_ids'] + r['not_visited_ids']})[:2000],
            'all_active_ids': sorted({i for r in rows for i in r['visited_ids']})[:2000],
            'all_not_visited_ids': sorted({i for r in rows for i in r['not_visited_ids']})[:2000],
            'options': {
                'reps': [{'id': r.id, 'name': r.name} for r in every],
                'teams': [{'id': t.id, 'name': t.name} for t in every.mapped('team_id')],
                'routes': [{'id': r.id, 'name': '%s (%s)' % (r.name, r.rep_id.name)}
                           for r in env['mo.sales.route'].search([])],
            },
            'filters': {'rep_id': rep_id or '', 'team_id': team_id or '', 'route_id': route_id or '',
                        'partner_name': partner_name or ''},
        }
