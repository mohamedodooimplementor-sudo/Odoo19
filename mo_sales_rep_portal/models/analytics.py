"""Read-only analytics used by the portal and the dashboards (aging, customer 360, suggestions, ranking)."""
from collections import defaultdict
from datetime import datetime, time, timedelta

from odoo import fields

BUCKETS = ('current', 'd30', 'd60', 'd90', 'd90p')


def aging(invoices, today):
    """Bucket open invoices by days past due. Returns totals and the invoices of each bucket."""
    res = {'total': 0.0, 'overdue': 0.0, 'invoices': defaultdict(list)}
    for b in BUCKETS:
        res[b] = 0.0
    for inv in invoices:
        due = inv.invoice_date_due or inv.invoice_date or today
        days = (today - due).days
        amount = inv.amount_residual_signed
        if days <= 0:
            bucket = 'current'
        elif days <= 30:
            bucket = 'd30'
        elif days <= 60:
            bucket = 'd60'
        elif days <= 90:
            bucket = 'd90'
        else:
            bucket = 'd90p'
        res[bucket] += amount
        res['total'] += amount
        if days > 0:
            res['overdue'] += amount
        res['invoices'][bucket].append((inv, days))
    return res


def open_invoices(env, domain_extra):
    return env['account.move'].sudo().search(
        [('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('amount_residual', '>', 0)] + domain_extra,
        order='invoice_date_due, id')


def customer_360(env, rep, partner, today):
    """Everything the representative needs to know about one customer."""
    Order, Move, Pay, Visit, Line = (env['sale.order'].sudo(), env['account.move'].sudo(), env['account.payment'].sudo(),
                                     env['mo.sales.visit'].sudo(), env['sale.order.line'].sudo())
    partner = partner.sudo()
    confirmed = Order.search([('partner_id', '=', partner.id), ('state', 'in', ('sale', 'done'))], order='date_order desc')
    quotations = Order.search([('partner_id', '=', partner.id), ('state', 'in', ('draft', 'sent'))], order='date_order desc', limit=15)
    invoices = Move.search([('partner_id', '=', partner.id), ('move_type', '=', 'out_invoice'), ('state', '=', 'posted')],
                           order='invoice_date desc, id desc', limit=15)
    payments = Pay.search([('partner_id', '=', partner.id), ('payment_type', '=', 'inbound'),
                           ('state', 'not in', ('draft', 'canceled', 'rejected'))], order='date desc, id desc')
    visits = Visit.search([('partner_id', '=', partner.id), ('rep_id', '=', rep.id)], order='visit_date desc, id desc', limit=10)
    last_visit = visits.filtered(lambda v: v.state == 'completed')[:1]
    ag = aging(open_invoices(env, [('partner_id', '=', partner.id)]), today)
    # products previously bought: most recently bought first, with quantity and last price
    products = {}
    for line in Line.search([('order_id.partner_id', '=', partner.id), ('order_id.state', 'in', ('sale', 'done')),
                             ('product_id', '!=', False), ('display_type', '=', False)], order='id desc', limit=400):
        row = products.setdefault(line.product_id, {'product': line.product_id, 'qty': 0.0, 'orders': set(),
                                                    'last_price': line.price_unit, 'last_date': line.order_id.date_order})
        row['qty'] += line.product_uom_qty
        row['orders'].add(line.order_id.id)
    top_products = sorted(products.values(), key=lambda r: (-len(r['orders']), -r['qty']))[:15]
    return {
        'partner': partner, 'confirmed': confirmed[:15], 'quotations': quotations, 'invoices': invoices,
        'payments': payments[:15], 'visits': visits, 'aging': ag,
        'total_sales': sum(confirmed.mapped('amount_total')), 'total_collected': sum(payments.mapped('amount')),
        'last_order': confirmed[:1], 'last_visit': last_visit, 'products': top_products,
        'outstanding': ag['total'], 'overdue': ag['overdue'],
    }


def suggestions(env, rep, settings, today, limit=8):
    """Customers worth visiting today, each with the reasons why (codes, translated by the portal)."""
    partners = rep.get_customers()[:300]
    if not partners:
        return []
    ids = partners.ids
    Order, Visit = env['sale.order'].sudo(), env['mo.sales.visit'].sudo()
    since = datetime.combine(today - timedelta(days=180), time.min)
    orders = Order.search([('partner_id', 'in', ids), ('state', 'in', ('sale', 'done')), ('date_order', '>=', since)],
                          order='date_order')
    by_partner = defaultdict(list)
    spent = defaultdict(float)
    for o in orders:
        by_partner[o.partner_id.id].append(o.date_order.date())
        spent[o.partner_id.id] += o.amount_total
    visits = Visit.search([('partner_id', 'in', ids), ('rep_id', '=', rep.id), ('visit_date', '<=', today)],
                          order='visit_date desc, id desc')
    last_done, last_state = {}, {}
    for v in visits:
        last_state.setdefault(v.partner_id.id, v.state)
        if v.state == 'completed':
            last_done.setdefault(v.partner_id.id, v.visit_date)
    ag = defaultdict(lambda: {'total': 0.0, 'overdue': 0.0})
    for inv in open_invoices(env, [('partner_id', 'in', ids)]):
        due = inv.invoice_date_due or inv.invoice_date or today
        ag[inv.partner_id.id]['total'] += inv.amount_residual_signed
        if due < today:
            ag[inv.partner_id.id]['overdue'] += inv.amount_residual_signed
    top_value = {pid for pid, _v in sorted(spent.items(), key=lambda kv: -kv[1])[:5]}
    out = []
    for p in partners:
        reasons, score = [], 0
        lv = last_done.get(p.id)
        if not lv or (today - lv).days >= settings.suggest_no_visit_days:
            reasons.append(('no_visit', (today - lv).days if lv else None)); score += 2
        dates = by_partner.get(p.id, [])
        if not dates or (today - dates[-1]).days >= settings.suggest_no_order_days:
            reasons.append(('no_order', (today - dates[-1]).days if dates else None)); score += 2
        if ag[p.id]['total'] >= (settings.suggest_outstanding_min or 0) and ag[p.id]['total'] > 0:
            reasons.append(('outstanding', ag[p.id]['total'])); score += 3
        if ag[p.id]['overdue'] > 0:
            reasons.append(('overdue', ag[p.id]['overdue'])); score += 4
        if len(dates) >= 3:
            gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
            avg = sum(gaps) / len(gaps)
            if avg > 0 and (today - dates[-1]).days >= avg:
                reasons.append(('reorder', int(avg))); score += 3
        if last_state.get(p.id) == 'missed':
            reasons.append(('missed', None)); score += 3
        if p.id in top_value and reasons:
            reasons.append(('high_value', None)); score += 1
        if reasons:
            out.append({'partner': p, 'reasons': reasons, 'score': score})
    out.sort(key=lambda r: -r['score'])
    return out[:limit]


def ranking(env, settings, d_from, d_to):
    """Score every representative on the configured metric. Score % is relative to the leader
    (or the target achievement when the metric is 'target')."""
    metric = settings.ranking_metric or 'target'
    rows = []
    for rep in env['mo.sales.rep'].sudo().search([]):
        perf = rep.performance(d_from, d_to)
        if metric == 'target':
            target = rep.current_target(d_to)
            value = target._achievement(perf) if target else 0.0
        else:
            value = perf.get({'sales': 'sales', 'collection': 'collection', 'visits': 'visits',
                              'new_customers': 'new_customers'}[metric], 0)
        rows.append({'rep': rep, 'value': value, 'perf': perf})
    rows.sort(key=lambda r: -r['value'])
    top = rows[0]['value'] if rows else 0
    for i, r in enumerate(rows, start=1):
        r['rank'] = i
        r['score'] = round(r['value'] if metric == 'target' else (100.0 * r['value'] / top if top else 0.0), 1)
    return rows
