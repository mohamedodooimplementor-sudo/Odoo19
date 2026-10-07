import base64
import functools
import json
import re
from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz
from werkzeug.urls import url_encode

from odoo import fields, http
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.web.controllers.home import Home
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request
from odoo.tools.misc import format_date

from ..models import analytics
from ..models.geo import nearest_neighbour_order
from .i18n import T, is_ar

MAX_ATTACHMENT = 10 * 1024 * 1024


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------
def _settings(rep=None):
    """Global settings; with a rep, the same settings resolved for that representative's own permissions."""
    glob = request.env['mo.sales.rep.settings'].get_settings()
    return rep.portal_settings() if rep else glob


def _float(value, default=0.0):
    try:
        return float(str(value).replace(',', '.'))
    except (TypeError, ValueError):
        return default


def _date(value, default=None):
    try:
        return fields.Date.to_date(value) if value else default
    except Exception:
        return default


def _today():
    return fields.Date.context_today(request.env.user)


def _day_bounds(day):
    tz = pytz.timezone(request.env.user.tz or 'UTC')
    start = tz.localize(datetime.combine(day, datetime.min.time())).astimezone(pytz.utc).replace(tzinfo=None)
    return start, start + timedelta(days=1)


def _local_dt(value):
    if not value:
        return ''
    tz = pytz.timezone(request.env.user.tz or 'UTC')
    return pytz.utc.localize(value).astimezone(tz).strftime('%Y-%m-%d %H:%M')


def _bucket_label(bucket):
    return {'current': T('Current'), 'd30': T('1-30 Days'), 'd60': T('31-60 Days'), 'd90': T('61-90 Days'),
            'd90p': T('90+ Days')}.get(bucket, bucket)


def _reason(code, value):
    """Why a customer is suggested for a visit (text shown on the dashboard)."""
    if code == 'no_visit':
        return T('Not visited for %s days', value) if value is not None else T('Never visited')
    if code == 'no_order':
        return T('No order for %s days', value) if value is not None else T('No order yet')
    if code == 'outstanding':
        return T('Outstanding %s', _money(value))
    if code == 'overdue':
        return T('Overdue %s', _money(value))
    if code == 'reorder':
        return T('Reorder expected (every ~%s days)', value)
    if code == 'missed':
        return T('Missed the last visit')
    return T('High-value customer')


def _hm(value):
    value = value or 0.0
    return '%02d:%02d' % (int(value), int(round((value % 1) * 60)) % 60)


def _sel(record, field):
    return T(dict(record._fields[field]._description_selection(record.env)).get(record[field], '') or '')


def _line_uom(line):
    uom = line.product_uom_id if 'product_uom_id' in line._fields else line.product_uom
    return uom.name


def _money(value):
    return '{:,.2f}'.format(value or 0.0)


def _redir(url, msg=None, kind='ok'):
    if msg:
        url += ('&' if '?' in url else '?') + url_encode({'msg': msg, 'kind': kind})
    return request.redirect(url)


def _client_time(value):
    """Device timestamp (ISO, UTC) sent by the offline queue; None when absent or malformed."""
    try:
        return datetime.strptime(str(value)[:19], '%Y-%m-%dT%H:%M:%S') if value else None
    except ValueError:
        return None


def _ensure_approved(partner_id):
    partner = request.env['res.partner'].sudo().browse(int(partner_id))
    if partner.mo_approval_state != 'approved':
        raise AccessError(T('This customer is waiting for approval.'))


def order_status(order):
    if order.state == 'cancel':
        return T('Cancelled'), 'cancel'
    if order.invoice_status == 'invoiced':
        return T('Invoiced'), 'invoiced'
    if getattr(order, 'delivery_status', False) == 'full':
        return T('Delivered'), 'delivered'
    if order.state == 'sale':
        return T('Confirmed'), 'confirmed'
    if order.state == 'done':
        return T('Locked'), 'confirmed'
    if order.state == 'sent':
        return T('Quotation Sent'), 'sent'
    return T('Quotation'), 'draft'


def _forbidden():
    return request.render('mo_sales_rep_portal.tpl_no_access', {'T': T, 'is_rtl': is_ar()}, status=403)


def _render(template, rep, active='home', title='Sales Rep', **values):
    env = request.env
    unread = env['mo.sales.rep.notification'].sudo().search_count([('rep_id', '=', rep.id), ('is_read', '=', False)])
    open_visit = env['mo.sales.visit'].sudo().search([('rep_id', '=', rep.id), ('state', '=', 'started')], limit=1)
    ctx = dict(
        rep=rep, S=_settings(rep), uid=request.env.uid, unread=unread, active=active, title=title, active_visit=open_visit,
        msg=request.params.get('msg'), kind=request.params.get('kind', 'ok'),
        T=T, is_rtl=is_ar(), money=_money, dt=_local_dt, hm=_hm, buckets=analytics.BUCKETS,
        bucket_label=_bucket_label, reason=_reason, sel=_sel, line_uom=_line_uom, cur=rep.company_id.currency_id.symbol or '',
        ostatus=order_status, csrf=request.csrf_token(),
    )
    ctx.update(values)
    return request.render(template, ctx)


def rep_required(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kw):
        rep = request.env['mo.sales.rep'].sudo().search(
            [('user_id', '=', request.env.uid), ('active', '=', True)], limit=1)
        if not rep:
            return _forbidden()
        return func(self, rep, *args, **kw)
    return wrapper


def _save_attachments(model, res_id, files):
    if not _settings().enable_attachments:
        return 0
    count = 0
    for f in files:
        if not f or not f.filename:
            continue
        data = f.read()
        if not data or len(data) > MAX_ATTACHMENT:
            continue
        request.env['ir.attachment'].sudo().create({
            'name': f.filename, 'datas': base64.b64encode(data), 'res_model': model, 'res_id': res_id})
        count += 1
    return count


def _mobile(partner):
    return (partner.mobile if 'mobile' in partner._fields and partner.mobile else partner.phone) or ''


def _whatsapp_number(partner):
    number = re.sub(r'\D', '', _mobile(partner))
    code = partner.country_id.phone_code
    if number.startswith('00'):
        number = number[2:]
    elif number.startswith('0') and code:
        number = str(code) + number[1:]
    return number


def _maps_url(partner):
    if partner.partner_latitude or partner.partner_longitude:
        return 'https://www.google.com/maps/search/?api=1&query=%s,%s' % (
            partner.partner_latitude, partner.partner_longitude)
    address = ', '.join(filter(None, [partner.street, partner.city, partner.country_id.name]))
    if address:
        return 'https://www.google.com/maps/search/?api=1&query=' + url_encode({'q': address})[2:]
    return ''


def _product_price(product, partner):
    try:
        pricelist = partner.property_product_pricelist
        if pricelist:
            return pricelist._get_product_price(product, 1.0)
    except Exception:
        pass
    return product.lst_price


def _partner_info(rep, partner):
    env = request.env
    partner = partner.sudo()
    last_visit = env['mo.sales.visit'].sudo().search(
        [('rep_id', '=', rep.id), ('partner_id', '=', partner.id), ('state', '=', 'completed')],
        order='end_time desc', limit=1)
    last_order = env['sale.order'].sudo().search(
        [('partner_id', '=', partner.id), ('state', '!=', 'cancel')], order='date_order desc', limit=1)
    last_pay = env['account.payment'].sudo().search(
        [('partner_id', '=', partner.id), ('payment_type', '=', 'inbound'),
         ('state', 'not in', ('draft', 'canceled', 'rejected'))], order='date desc, id desc', limit=1)
    return {
        'p': partner, 'mobile': _mobile(partner), 'wa': _whatsapp_number(partner), 'maps': _maps_url(partner),
        'outstanding': partner.credit, 'last_visit': last_visit, 'last_order': last_order, 'last_pay': last_pay,
        'address': ', '.join(filter(None, [partner.street, partner.city])),
    }


def _orders_domain(rep):
    return ['|', ('mo_rep_id', '=', rep.id), ('user_id', '=', rep.user_id.id)]


def _invoices_domain(rep):
    customers = rep.get_customers()
    return [('move_type', '=', 'out_invoice'), '|', ('mo_rep_id', '=', rep.id), ('partner_id', 'in', customers.ids)]


def _payments_domain(rep):
    # create_uid is the rep's own user (documents are created with sudo() under the rep's uid), so a
    # payment stays visible even if the audit link could not be written.
    return [('payment_type', '=', 'inbound'), '|', ('mo_rep_id', '=', rep.id), ('create_uid', '=', rep.user_id.id)]


def _pickings_domain(rep):
    return ['|', ('mo_rep_id', '=', rep.id), '&', ('picking_type_code', '=', 'outgoing'),
            ('sale_id.mo_rep_id', '=', rep.id)]


def _parse_lines(rep, S, form, stock=False):
    product_ids = form.getlist('product_id')
    qtys = form.getlist('qty')
    prices = form.getlist('price')
    discounts = form.getlist('discount')
    cap = rep.effective_discount_cap(S)
    can_price = rep.can_change_price(S)
    lines = []
    for i, pid in enumerate(product_ids):
        if not pid:
            continue
        product = request.env['product.product'].sudo().browse(int(pid)).exists()
        if not product:
            raise UserError(T('Product not found.'))
        qty = _float(qtys[i] if i < len(qtys) else 0)
        if qty <= 0:
            raise UserError(T('Quantity must be greater than zero for %s.', product.display_name))
        line = {'product': product, 'qty': qty}
        if not stock:
            disc = _float(discounts[i] if i < len(discounts) else 0)
            if disc < 0 or disc > cap:
                raise UserError(T('Discount for %(p)s cannot exceed %(c)s%%.', p=product.display_name, c=cap))
            line['discount'] = disc
            price = prices[i] if i < len(prices) else ''
            line['price'] = _float(price) if (can_price and price not in ('', None)) else None
        lines.append(line)
    if not lines:
        raise UserError(T('Add at least one product.'))
    return lines


SW_SCRIPT = r"""
const VERSION = 'mo-rep-v2';
const SHELL = ['/mo_sales_rep_portal/static/src/css/portal.css', '/mo_sales_rep_portal/static/src/js/portal.js'];
self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('message', (e) => {
  if (e.data === 'clear') { e.waitUntil(caches.keys().then((keys) => Promise.all(keys.map((k) => caches.delete(k))))); }
});
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') { return; }
  const url = new URL(req.url);
  if (url.origin !== location.origin) { return; }
  if (url.pathname.startsWith('/mo_sales_rep_portal/static/')) {
    e.respondWith(caches.match(req).then((hit) => {
      const net = fetch(req).then((res) => { if (res.ok) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); } return res; });
      return hit || net;
    }));
    return;
  }
  if (url.pathname === '/rep' || url.pathname.startsWith('/rep/')) {
    if (url.pathname.startsWith('/rep/track') || url.pathname.endsWith('.json') || url.pathname.endsWith('/pdf')) { return; }
    e.respondWith(fetch(req).then((res) => {
      if (res.ok && !res.redirected && (req.mode === 'navigate' || req.headers.get('x-mo-warm'))) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); }
      return res;
    }).catch(() => caches.match(req).then((hit) => hit || new Response(
      '<!DOCTYPE html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><body style="font-family:sans-serif;padding:24px"><h2>Offline</h2><p>This page was not saved on this device yet. Open it once while online.</p>',
      { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }))));
  }
});
"""


# ----------------------------------------------------------------------
def _is_rep_user(uid=None):
    return bool(request.env['mo.sales.rep'].sudo().search_count(
        [('user_id', '=', uid or request.env.uid), ('active', '=', True)]))


class RepHome(Home):
    def _login_redirect(self, uid, redirect=None):
        # The portal module sets redirect='/my' before calling super, so treat the usual
        # default landing pages as "no explicit destination".
        landing = (redirect or '').split('?')[0].rstrip('/') in ('', '/my', '/my/home', '/odoo', '/web')
        if landing and _is_rep_user(uid):
            return '/rep'
        return super()._login_redirect(uid, redirect=redirect)


class RepCustomerPortal(CustomerPortal):
    @http.route()
    def home(self, **kw):
        # Sales reps land on their own portal; /my?standard=1 still opens the standard portal home.
        if not kw.get('standard') and _is_rep_user():
            return request.redirect('/rep')
        return super().home(**kw)


class RepPortal(http.Controller):

    # ---------------------------------------------------------------- PWA (installable + offline reading)
    @http.route('/rep/manifest.json', type='http', auth='public')
    def manifest(self, **kw):
        return request.make_json_response({
            'name': 'Sales Rep', 'short_name': 'Sales Rep', 'start_url': '/rep', 'scope': '/rep',
            'display': 'standalone', 'background_color': '#eef2f5', 'theme_color': '#0e6b5c',
            'icons': [
                {'src': '/mo_sales_rep_portal/static/src/img/icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                {'src': '/mo_sales_rep_portal/static/src/img/icon-512.png', 'sizes': '512x512', 'type': 'image/png'},
            ],
        })

    @http.route('/rep/sw.js', type='http', auth='public')
    def service_worker(self, **kw):
        return request.make_response(SW_SCRIPT, headers=[
            ('Content-Type', 'application/javascript; charset=utf-8'),
            ('Service-Worker-Allowed', '/rep'),
            ('Cache-Control', 'no-cache'),
        ])

    # ---------------------------------------------------------------- dashboard
    def _dashboard_payload(self, rep):
        """Everything the dashboard shows, as plain JSON-able data (also served live by /rep/dashboard.json)."""
        env = request.env
        today = _today()
        tz = pytz.timezone(request.env.user.tz or 'UTC')

        def local_date(dt):
            return pytz.utc.localize(dt).astimezone(tz).date()

        start, end = _day_bounds(today)
        month_start = today.replace(day=1)
        days = [today - timedelta(days=i) for i in range(13, -1, -1)]
        win_start, _x = _day_bounds(days[0])
        orders14 = env['sale.order'].sudo().search(_orders_domain(rep) + [
            ('state', 'in', ('sale', 'done')), ('date_order', '>=', win_start), ('date_order', '<', end)])
        pays14 = env['account.payment'].sudo().search(_payments_domain(rep) + [
            ('state', 'not in', ('draft', 'canceled', 'rejected')), ('date', '>=', days[0]), ('date', '<=', today)])
        sales_by, coll_by = defaultdict(float), defaultdict(float)
        for o in orders14:
            sales_by[local_date(o.date_order)] += o.amount_total
        for p in pays14:
            coll_by[p.date] += p.amount
        visits = env['mo.sales.visit'].sudo().search([('rep_id', '=', rep.id), ('visit_date', '=', today)])
        orders_today = env['sale.order'].sudo().search(_orders_domain(rep) + [
            ('create_date', '>=', start), ('create_date', '<', end), ('state', '!=', 'cancel')])
        invoices_today = env['account.move'].sudo().search_count([
            ('mo_rep_id', '=', rep.id), ('move_type', '=', 'out_invoice'),
            ('create_date', '>=', start), ('create_date', '<', end)])
        payments_today = env['account.payment'].sudo().search(_payments_domain(rep) + [
            ('create_date', '>=', start), ('create_date', '<', end)])
        perf = rep.performance(month_start, today)
        target = rep.current_target(today)
        ag = analytics.aging(analytics.open_invoices(env, _invoices_domain(rep)), today)
        month_orders = env['sale.order'].sudo().search(_orders_domain(rep) + [
            ('state', 'in', ('sale', 'done')), ('date_order', '>=', _day_bounds(month_start)[0]), ('date_order', '<', end)])
        by_customer = defaultdict(float)
        for o in month_orders:
            by_customer[o.partner_id.display_name] += o.amount_total
        Follow = env['mo.sales.followup'].sudo()
        fdom = [('rep_id', '=', rep.id), ('state', '=', 'open')]
        return {
            'stats': {
                'sales_today': sum(orders_today.mapped('amount_total')), 'visits': len(visits),
                'done': len(visits.filtered(lambda v: v.state == 'completed')),
                'remaining': len(visits.filtered(lambda v: v.state in ('planned', 'started'))),
                'orders': len(orders_today), 'invoices': invoices_today, 'payments': len(payments_today),
                'collected': sum(payments_today.mapped('amount')), 'outstanding': ag['total'], 'overdue': ag['overdue'],
                'month_sales': perf['sales'], 'month_collection': perf['collection'], 'new_customers': perf['new_customers'],
                'achievement': target._achievement(perf) if target else None,
                'follow_today': Follow.search_count(fdom + [('due_date', '=', today)]),
                'follow_overdue': Follow.search_count(fdom + [('due_date', '<', today)]),
                'follow_upcoming': Follow.search_count(fdom + [('due_date', '>', today)]),
            },
            'series': {'labels': [d.strftime('%d/%m') for d in days],
                       'sales': [round(sales_by.get(d, 0.0), 2) for d in days],
                       'collection': [round(coll_by.get(d, 0.0), 2) for d in days]},
            'visits': {'completed': len(visits.filtered(lambda v: v.state == 'completed')),
                       'started': len(visits.filtered(lambda v: v.state == 'started')),
                       'planned': len(visits.filtered(lambda v: v.state == 'planned')),
                       'missed': len(visits.filtered(lambda v: v.state == 'missed'))},
            'aging': {b: ag[b] for b in analytics.BUCKETS},
            'top': [{'name': n, 'value': round(v, 2)} for n, v in sorted(by_customer.items(), key=lambda kv: -kv[1])[:5]],
            'targets': [{'key': r['key'], 'label': T(r['label']), 'pct': r['pct'], 'actual': r['actual'], 'target': r['target'],
                         'money': r['money']} for r in (target.progress() if target else [])],
            'labels': {
                'sales': T('Sales'), 'collection': T('Collection'), 'completed': T('Completed'), 'started': T('In progress'),
                'planned': T('Planned'), 'missed': T('Missed'), 'visits': T('Visits'), 'none': T('No data yet'),
                'current': T('Current'), 'd30': T('1-30 Days'), 'd60': T('31-60 Days'), 'd90': T('61-90 Days'),
                'd90p': T('90+ Days'), 'live': T('Live'), 'updated': T('Updated'),
            },
            'currency': rep.company_id.currency_id.symbol or '',
        }

    @http.route('/rep', type='http', auth='user')
    @rep_required
    def dashboard(self, rep, **kw):
        S = _settings(rep)
        today = _today()
        rep._generate_visits(today)
        payload = self._dashboard_payload(rep)
        st = payload['stats']
        hour = datetime.now(pytz.timezone(request.env.user.tz or 'UTC')).hour
        greeting = T('Good morning') if hour < 12 else (T('Good afternoon') if hour < 18 else T('Good evening'))
        return _render('mo_sales_rep_portal.tpl_dashboard', rep, 'home', T('Home'), stats={
            'visits': st['visits'], 'done': st['done'], 'remaining': st['remaining'], 'orders': st['orders'],
            'invoices': st['invoices'], 'payments': st['payments'], 'sales': st['sales_today'], 'collected': st['collected'],
            'outstanding': st['outstanding'], 'overdue': st['overdue'], 'month_sales': st['month_sales'],
            'month_collection': st['month_collection'], 'new_customers': st['new_customers'],
            'achievement': st['achievement']},
            follow={'today': st['follow_today'], 'overdue': st['follow_overdue'], 'upcoming': st['follow_upcoming']},
            targets=payload['targets'], greeting=greeting, today_label=format_date(request.env, today, date_format='full'),
            suggestions=analytics.suggestions(request.env, rep, S, today), dash_json=json.dumps(payload))

    @http.route('/rep/dashboard.json', type='http', auth='user')
    @rep_required
    def dashboard_json(self, rep, **kw):
        return request.make_json_response(self._dashboard_payload(rep))

    @http.route('/rep/more', type='http', auth='user')
    @rep_required
    def more(self, rep, **kw):
        return _render('mo_sales_rep_portal.tpl_more', rep, 'more', T('More'))

    # ---------------------------------------------------------------- customers
    CUSTOMER_FILTERS = ('visited_today', 'not_visited', 'outstanding', 'overdue', 'no_order', 'route_today')

    @http.route('/rep/customers', type='http', auth='user')
    @rep_required
    def customers(self, rep, q='', flt='', **kw):
        env = request.env
        S = _settings(rep)
        today = _today()
        Partner = env['res.partner'].sudo()
        domain = rep.customers_domain()
        if q:
            fields_ = ['name', 'phone', 'ref', 'street', 'city', 'mo_whatsapp']
            if 'mobile' in Partner._fields:
                fields_.append('mobile')
            domain = domain + ['|'] * (len(fields_) - 1) + [(f, 'ilike', q) for f in fields_]
        if flt in self.CUSTOMER_FILTERS:
            mine = rep.get_customers().ids
            Visit, Order = env['mo.sales.visit'].sudo(), env['sale.order'].sudo()
            if flt == 'visited_today':
                ids = Visit.search([('rep_id', '=', rep.id), ('visit_date', '=', today),
                                    ('state', 'in', ('started', 'completed'))]).mapped('partner_id').ids
                domain.append(('id', 'in', ids))
            elif flt == 'route_today':
                ids = Visit.search([('rep_id', '=', rep.id), ('visit_date', '=', today),
                                    ('state', '!=', 'cancelled')]).mapped('partner_id').ids
                domain.append(('id', 'in', ids))
            elif flt == 'not_visited':
                since = today - timedelta(days=S.suggest_no_visit_days)
                ids = Visit.search([('rep_id', '=', rep.id), ('state', '=', 'completed'),
                                    ('visit_date', '>=', since)]).mapped('partner_id').ids
                domain.append(('id', 'not in', ids))
            elif flt == 'no_order':
                since = datetime.combine(today - timedelta(days=S.suggest_no_order_days), time.min)
                ids = Order.search([('partner_id', 'in', mine), ('state', 'in', ('sale', 'done')),
                                    ('date_order', '>=', since)]).mapped('partner_id').ids
                domain.append(('id', 'not in', ids))
            else:
                extra = [('partner_id', 'in', mine)]
                if flt == 'overdue':
                    extra.append(('invoice_date_due', '<', today))
                domain.append(('id', 'in', analytics.open_invoices(env, extra).mapped('partner_id').ids))
        partners = Partner.search(domain, limit=60, order='name')
        infos = [_partner_info(rep, p) for p in partners]
        return _render('mo_sales_rep_portal.tpl_customers', rep, 'customers', T('Customers'), infos=infos, q=q, flt=flt)

    @http.route('/rep/customer/<int:partner_id>', type='http', auth='user')
    @rep_required
    def customer(self, rep, partner_id, **kw):
        if not rep.can_access_partner(partner_id):
            return _forbidden()
        env = request.env
        partner = env['res.partner'].sudo().browse(partner_id)
        data = analytics.customer_360(env, rep, partner, _today())
        data['deliveries'] = env['stock.picking'].sudo().search(
            [('partner_id', '=', partner.id), ('picking_type_code', '=', 'outgoing')], order='id desc', limit=8)
        data['returns'] = env['stock.picking'].sudo().search(
            [('partner_id', '=', partner.id), ('picking_type_code', '=', 'incoming')], order='id desc', limit=8)
        data['followups'] = env['mo.sales.followup'].sudo().search(
            [('rep_id', '=', rep.id), ('partner_id', '=', partner.id), ('state', '=', 'open')], order='due_date', limit=8)
        return _render('mo_sales_rep_portal.tpl_customer', rep, 'customers', partner.display_name,
                       info=_partner_info(rep, partner), d=data, approved=(partner.mo_approval_state == 'approved'))

    @http.route('/rep/customer/<int:partner_id>/location', type='http', auth='user', methods=['POST'])
    @rep_required
    def customer_location(self, rep, partner_id, lat=None, lng=None, **kw):
        S = _settings(rep)
        if not S.enable_customer_location or not rep.can_access_partner(partner_id):
            return _redir('/rep/customer/%s' % partner_id, T('Not allowed.'), 'err')
        lat, lng = _float(lat), _float(lng)
        if not lat and not lng:
            return _redir('/rep/customer/%s' % partner_id, T('Location not available. Enable GPS and try again.'), 'err')
        request.env['res.partner'].sudo().browse(partner_id).write({'partner_latitude': lat, 'partner_longitude': lng})
        return _redir('/rep/customer/%s' % partner_id, T('Customer location saved.'))

    @http.route('/rep/customer/<int:partner_id>/invoices.json', type='http', auth='user')
    @rep_required
    def customer_invoices_json(self, rep, partner_id, **kw):
        if not rep.can_access_partner(partner_id):
            return request.make_json_response([])
        moves = request.env['account.move'].sudo().search(
            _invoices_domain(rep) + [('partner_id', '=', partner_id), ('state', '=', 'posted'),
                                     ('amount_residual', '>', 0)], order='invoice_date, id')
        return request.make_json_response([
            {'id': m.id, 'name': m.name, 'total': m.amount_total, 'residual': m.amount_residual} for m in moves])

    @http.route('/rep/products.json', type='http', auth='user')
    @rep_required
    def products_json(self, rep, q='', partner_id=None, stock=None, op=None, all=None, **kw):
        env = request.env
        S = _settings(rep)
        Product = env['product.product'].sudo()
        partner = env['res.partner'].sudo().browse(int(partner_id)).exists() if partner_id else False
        domain = [('sale_ok', '=', True)] if not stock else [('type', '!=', 'service')]
        if q:
            domain += ['|', '|', ('name', 'ilike', q), ('default_code', 'ilike', q), ('barcode', '=', q)]
        # on-hand / free quantity: the van for sales, the source location for stock operations
        wh = S.main_warehouse_id if (stock and op == 'receive') else rep.warehouse_id
        location_domain = [('location_id.usage', '=', 'internal')]
        if wh:
            location_domain = [('location_id', 'child_of', wh.view_location_id.id)] + location_domain
        on_hand, free = {}, {}
        for qt in env['stock.quant'].sudo().search(location_domain):
            pid = qt.product_id.id
            on_hand[pid] = on_hand.get(pid, 0.0) + qt.quantity
            free[pid] = free.get(pid, 0.0) + qt.quantity - qt.reserved_quantity
        # what this customer buys most often goes first
        frequent = {}
        if partner and not stock:
            lines = env['sale.order.line'].sudo().search([
                ('order_id.partner_id', '=', partner.id), ('order_id.state', 'in', ('sale', 'done')),
                ('product_id', '!=', False)], order='id desc', limit=300)
            for l in lines:
                frequent[l.product_id.id] = frequent.get(l.product_id.id, 0) + 1
        limit = 500 if all else 15
        products = Product.search(domain, limit=limit, order='name')
        if all:
            if stock:
                products = products.sorted(key=lambda p: (0 if on_hand.get(p.id, 0) > 0 else 1, p.display_name))
            elif frequent:
                products = products.sorted(key=lambda p: (-frequent.get(p.id, 0), p.display_name))
        result = []
        for p in products:
            price = _product_price(p, partner) if partner else p.lst_price
            item = {'id': p.id, 'name': p.display_name, 'uom': p.uom_id.name, 'price': price,
                    'code': p.default_code or '', 'barcode': p.barcode or '', 'stock': free.get(p.id, 0.0),
                    'disc': round(100.0 * (p.lst_price - price) / p.lst_price, 1) if p.lst_price and price < p.lst_price else 0.0}
            if stock:
                item['qty'] = on_hand.get(p.id, 0.0)
            if p.id in frequent:
                item['frequent'] = True
            result.append(item)
        return request.make_json_response(result)

    # ---------------------------------------------------------------- route & visits
    @http.route('/rep/route', type='http', auth='user')
    @rep_required
    def route(self, rep, date=None, route_id=None, area=None, priority=None, **kw):
        today = _today()
        day = _date(date, today)
        if day >= today:
            rep._generate_visits(day)
        domain = [('rep_id', '=', rep.id), ('visit_date', '=', day)]
        if route_id:
            domain.append(('route_id', '=', int(route_id)))
        if area:
            domain.append(('route_id.area', '=', area))
        if priority not in (None, ''):
            domain.append(('route_line_id.priority', '=', priority))
        visits = request.env['mo.sales.visit'].sudo().search(domain)
        def sort_key(v):
            if v.state in ('completed', 'cancelled', 'missed'):
                return (0, v.route_id.id or 0, v.route_line_id.sequence or 999, v.id)
            if v.day_sequence:
                return (1, 0, v.day_sequence, v.id)
            return (1, v.route_id.id or 0, v.route_line_id.sequence or 999, v.id)

        visits = visits.sorted(key=sort_key)
        routes = request.env['mo.sales.route'].sudo().search([('rep_id', '=', rep.id)])
        areas = sorted({r.area for r in routes if r.area})
        return _render('mo_sales_rep_portal.tpl_route', rep, 'route', T('My Route'), visits=visits, day=day,
                       is_today=(day == today),
                       prev_day=day - timedelta(days=1), next_day=day + timedelta(days=1),
                       routes=routes, areas=areas, f_route=route_id or '', f_area=area or '',
                       f_priority=priority if priority is not None else '')

    @http.route('/rep/route/optimize', type='http', auth='user', methods=['POST'])
    @rep_required
    def route_optimize(self, rep, date=None, lat=None, lng=None, **kw):
        day = _date(date, _today())
        back = '/rep/route?date=%s' % day
        visits = request.env['mo.sales.visit'].sudo().search(
            [('rep_id', '=', rep.id), ('visit_date', '=', day), ('state', '=', 'planned')])
        located = visits.filtered(lambda v: v.partner_id.partner_latitude or v.partner_id.partner_longitude)
        if len(located) < 2:
            return _redir(back, T('Save the location of at least two customers first.'), 'err')
        la, ln = _float(lat), _float(lng)
        start = (la, ln) if (la or ln) else None
        order = nearest_neighbour_order(
            [(v.id, v.partner_id.partner_latitude, v.partner_id.partner_longitude) for v in located], start)
        order += (visits - located).ids
        Visit = request.env['mo.sales.visit'].sudo()
        for idx, vid in enumerate(order, start=1):
            Visit.browse(vid).day_sequence = idx
        return _redir(back, T('Visits re-ordered by distance.'))

    @http.route('/rep/visits', type='http', auth='user')
    @rep_required
    def visits(self, rep, **kw):
        visits = request.env['mo.sales.visit'].sudo().search([('rep_id', '=', rep.id)], limit=60)
        return _render('mo_sales_rep_portal.tpl_visits', rep, 'more', T('Visits'), visits=visits)

    @http.route('/rep/visit/new', type='http', auth='user')
    @rep_required
    def visit_new(self, rep, partner_id=None, **kw):
        return _render('mo_sales_rep_portal.tpl_visit_new', rep, 'route', T('New Visit'),
                       customers=rep.get_customers(), partner_id=int(partner_id) if partner_id else 0)

    @http.route('/rep/visit/<int:visit_id>', type='http', auth='user')
    @rep_required
    def visit(self, rep, visit_id, **kw):
        visit = request.env['mo.sales.visit'].sudo().browse(visit_id).exists()
        if not visit or visit.rep_id != rep:
            return _forbidden()
        attachments = request.env['ir.attachment'].sudo().search(
            [('res_model', '=', 'mo.sales.visit'), ('res_id', '=', visit.id)])
        env = request.env
        today = _today()
        partner = visit.partner_id.sudo()
        ag = analytics.aging(analytics.open_invoices(env, [('partner_id', '=', partner.id)]), today)
        pending = env['mo.sales.visit'].sudo().search([
            ('rep_id', '=', rep.id), ('visit_date', '=', visit.visit_date), ('state', '=', 'planned'),
            ('id', '!=', visit.id)])
        pending = pending.sorted(key=lambda v: (v.day_sequence or 9999, v.route_id.id or 0,
                                                v.route_line_id.sequence or 999, v.id))
        followups = env['mo.sales.followup'].sudo().search(
            [('rep_id', '=', rep.id), ('partner_id', '=', partner.id), ('state', '=', 'open')], order='due_date', limit=6)
        return _render('mo_sales_rep_portal.tpl_visit', rep, 'route', visit.name, visit=visit,
                       info=_partner_info(rep, partner), attachments=attachments, aging=ag,
                       next_visit=pending[:1], followups=followups, can_new_customer_op=rep.permission('allow_customer_return'),
                       results=self._results())

    @staticmethod
    def _results():
        return request.env['mo.sales.visit']._fields['result']._description_selection(request.env)

    @http.route('/rep/visit/start', type='http', auth='user', methods=['POST'])
    @rep_required
    def visit_start(self, rep, partner_id=None, visit_id=None, visit_type='sales', lat=None, lng=None,
                    client_time=None, **kw):
        S = _settings(rep)
        Visit = request.env['mo.sales.visit'].sudo()
        opened = Visit.search([('rep_id', '=', rep.id), ('state', '=', 'started')], limit=1)
        if opened:
            return _redir('/rep/visit/%s' % opened.id, T('End the current visit before starting a new one.'), 'err')
        try:
            if visit_id:
                visit = Visit.browse(int(visit_id)).exists()
                if not visit or visit.rep_id != rep:
                    raise AccessError(T('Not allowed.'))
            else:
                if not partner_id or not rep.can_access_partner(partner_id):
                    raise AccessError(T('Choose one of your customers.'))
                visit = Visit.with_context(no_rep_notify=True).create({
                    'rep_id': rep.id, 'partner_id': int(partner_id), 'visit_type': visit_type,
                    'visit_date': _today(), 'source': 'portal'})
            gps = S.enable_gps
            visit.action_start(_float(lat) if gps else 0.0, _float(lng) if gps else 0.0, _client_time(client_time))
        except (UserError, AccessError) as e:
            return _redir('/rep', str(e), 'err')
        return _redir('/rep/visit/%s' % visit.id, T('Visit started.'))

    @http.route('/rep/visit/<int:visit_id>/end', type='http', auth='user', methods=['POST'])
    @rep_required
    def visit_end(self, rep, visit_id, lat=None, lng=None, result=None, notes=None, next_visit_date=None,
                  next_followup_date=None, client_time=None, **kw):
        S = _settings(rep)
        visit = request.env['mo.sales.visit'].sudo().browse(visit_id).exists()
        if not visit or visit.rep_id != rep:
            return _forbidden()
        nxt = _date(next_visit_date)
        if result not in dict(self._results()):
            return _redir('/rep/visit/%s' % visit.id, T('Choose the visit result before finishing.'), 'err')
        try:
            gps = S.enable_gps
            visit.action_end(_float(lat) if gps else 0.0, _float(lng) if gps else 0.0, result, notes, nxt,
                             _date(next_followup_date), _client_time(client_time))
        except UserError as e:
            return _redir('/rep/visit/%s' % visit.id, str(e), 'err')
        _save_attachments('mo.sales.visit', visit.id, request.httprequest.files.getlist('attachments'))
        if nxt and nxt > _today():
            request.env['mo.sales.visit'].sudo().with_context(no_rep_notify=True).create({
                'rep_id': rep.id, 'partner_id': visit.partner_id.id, 'visit_date': nxt,
                'visit_type': visit.visit_type, 'source': 'portal'})
        return _redir('/rep/visit/%s' % visit.id, T('Visit completed.'))

    @http.route('/rep/visit/<int:visit_id>/cancel', type='http', auth='user', methods=['POST'])
    @rep_required
    def visit_cancel(self, rep, visit_id, **kw):
        visit = request.env['mo.sales.visit'].sudo().browse(visit_id).exists()
        if not visit or visit.rep_id != rep:
            return _forbidden()
        try:
            visit.action_cancel()
        except UserError as e:
            return _redir('/rep/visit/%s' % visit.id, str(e), 'err')
        return _redir('/rep/route', T('Visit cancelled.'))

    @http.route('/rep/visit/<int:visit_id>/attach', type='http', auth='user', methods=['POST'])
    @rep_required
    def visit_attach(self, rep, visit_id, **kw):
        visit = request.env['mo.sales.visit'].sudo().browse(visit_id).exists()
        if not visit or visit.rep_id != rep:
            return _forbidden()
        count = _save_attachments('mo.sales.visit', visit.id, request.httprequest.files.getlist('attachments'))
        return _redir('/rep/visit/%s' % visit.id, T('%s file(s) uploaded.', count) if count else T('No file uploaded.'),
                      'ok' if count else 'err')

    @http.route('/rep/track', type='http', auth='user', methods=['POST'])
    @rep_required
    def track(self, rep, lat=None, lng=None, **kw):
        S = _settings(rep)
        visit = request.env['mo.sales.visit'].sudo().search([('rep_id', '=', rep.id), ('state', '=', 'started')], limit=1)
        if S.enable_tracking and visit and (_float(lat) or _float(lng)):
            request.env['mo.sales.rep.location'].sudo().create({
                'rep_id': rep.id, 'visit_id': visit.id, 'latitude': _float(lat), 'longitude': _float(lng)})
            return request.make_json_response({'ok': True})
        return request.make_json_response({'ok': False})

    # ---------------------------------------------------------------- sales orders
    @staticmethod
    def _confirm_flash(order, rep, S, base, validated, pending):
        """Pick the flash message after a confirmation, depending on the auto-validate outcome."""
        if rep.can_auto_validate(S):
            pickings = order.picking_ids.filtered(lambda p: p.state != 'cancel')
            if pickings and all(p.state == 'done' for p in pickings):
                return validated, 'ok'
            if pickings:
                return pending, 'err'
        return base, 'ok'

    @http.route('/rep/orders', type='http', auth='user')
    @rep_required
    def orders(self, rep, status='', **kw):
        orders = request.env['sale.order'].sudo().search(_orders_domain(rep), order='create_date desc', limit=100)
        if status:
            orders = orders.filtered(lambda o: order_status(o)[1] == status)
        return _render('mo_sales_rep_portal.tpl_orders', rep, 'orders', T('My Orders'), orders=orders, status=status)

    def _get_order(self, rep, order_id):
        return request.env['sale.order'].sudo().search(_orders_domain(rep) + [('id', '=', order_id)], limit=1)

    @http.route('/rep/order/<int:order_id>', type='http', auth='user')
    @rep_required
    def order(self, rep, order_id, **kw):
        order = self._get_order(rep, order_id)
        if not order:
            return _forbidden()
        return _render('mo_sales_rep_portal.tpl_order', rep, 'orders', order.name, order=order)

    @http.route('/rep/order/new', type='http', auth='user')
    @rep_required
    def order_new(self, rep, partner_id=None, visit_id=None, order_mode=None, **kw):
        S = _settings(rep)
        if not (S.allow_quotation or S.allow_sales_order):
            return _redir('/rep', T('Creating orders is disabled.'), 'err')
        return _render('mo_sales_rep_portal.tpl_order_form', rep, 'orders', T('New Sales Order'),
                       customers=rep.get_customers(), partner_id=int(partner_id) if partner_id else 0,
                       visit_id=int(visit_id) if visit_id else 0, order=False, initial='[]',
                       order_mode=order_mode or '',
                       can_price=rep.can_change_price(S), disc_cap=rep.effective_discount_cap(S))

    @http.route('/rep/order/<int:order_id>/edit', type='http', auth='user')
    @rep_required
    def order_edit(self, rep, order_id, **kw):
        S = _settings(rep)
        order = self._get_order(rep, order_id)
        if not order or order.state not in ('draft', 'sent') or order.mo_rep_id != rep \
                or not (S.allow_quotation or S.allow_sales_order):
            return _redir('/rep/orders', T('This order can no longer be edited from the portal.'), 'err')
        initial = json.dumps([{
            'id': l.product_id.id, 'name': l.product_id.display_name, 'qty': l.product_uom_qty,
            'price': l.price_unit, 'discount': l.discount, 'uom': _line_uom(l),
        } for l in order.order_line.filtered(lambda l: not l.display_type and l.product_id)])
        return _render('mo_sales_rep_portal.tpl_order_form', rep, 'orders', T('Edit %s', order.name),
                       customers=order.partner_id, partner_id=order.partner_id.id, visit_id=0,
                       order=order, initial=initial, order_mode='',
                       can_price=rep.can_change_price(S), disc_cap=rep.effective_discount_cap(S))

    @http.route('/rep/order/<int:order_id>/update', type='http', auth='user', methods=['POST'])
    @rep_required
    def order_update(self, rep, order_id, action='save', **kw):
        S = _settings(rep)
        order = self._get_order(rep, order_id)
        if not order or order.state not in ('draft', 'sent') or order.mo_rep_id != rep \
                or not (S.allow_quotation or S.allow_sales_order):
            return _redir('/rep/orders', T('This order can no longer be edited from the portal.'), 'err')
        back = '/rep/order/%s/edit' % order.id
        try:
            if action == 'confirm' and not S.allow_sales_order:
                raise AccessError(T('This action is not allowed.'))
            order_lines = [(5, 0, 0)]
            for l in _parse_lines(rep, S, request.httprequest.form):
                vals = {'product_id': l['product'].id, 'product_uom_qty': l['qty'], 'discount': l['discount']}
                if l['price'] is not None:
                    vals['price_unit'] = l['price']
                order_lines.append((0, 0, vals))
            order.write({'order_line': order_lines})
            if action == 'confirm':
                order.action_confirm()
        except (UserError, AccessError, ValidationError) as e:
            return _redir(back, str(e), 'err')
        msg, kind = T('Order updated.'), 'ok'
        if action == 'confirm':
            msg, kind = self._confirm_flash(
                order, rep, S, T('Order confirmed.'), T('Order confirmed and delivery validated.'),
                T('Order confirmed; the delivery was not validated (not enough stock or manual processing needed).'))
        return _redir('/rep/order/%s' % order.id, msg, kind)

    @http.route('/rep/order/create', type='http', auth='user', methods=['POST'])
    @rep_required
    def order_create(self, rep, partner_id=None, visit_id=None, action='quotation', note=None, client_uid=None, **kw):
        S = _settings(rep)
        back = '/rep/order/new?partner_id=%s&visit_id=%s' % (partner_id or '', visit_id or '')
        if client_uid:      # replayed after an offline period: never create it twice
            done = request.env['sale.order'].sudo().search([('mo_client_uid', '=', client_uid)], limit=1)
            if done:
                return _redir('/rep/order/%s' % done.id, T('Order %s created.', done.name))
        try:
            if not partner_id or not rep.can_access_partner(partner_id):
                raise AccessError(T('Choose one of your customers.'))
            _ensure_approved(partner_id)
            confirm = action == 'confirm'
            if (confirm and not S.allow_sales_order) or (not confirm and not S.allow_quotation):
                raise AccessError(T('This action is not allowed.'))
            visit = request.env['mo.sales.visit'].sudo().browse(int(visit_id)).exists() if visit_id else False
            if visit and visit.rep_id != rep:
                visit = False
            lines = _parse_lines(rep, S, request.httprequest.form)
            order_lines = []
            for l in lines:
                vals = {'product_id': l['product'].id, 'product_uom_qty': l['qty'], 'discount': l['discount']}
                if l['price'] is not None:
                    vals['price_unit'] = l['price']
                order_lines.append((0, 0, vals))
            vals = {
                'partner_id': int(partner_id), 'user_id': rep.user_id.id, 'company_id': rep.company_id.id,
                'mo_source': 'portal', 'mo_rep_id': rep.id, 'mo_visit_id': visit.id if visit else False,
                'mo_client_uid': client_uid or False, 'order_line': order_lines,
            }
            if rep.warehouse_id:
                vals['warehouse_id'] = rep.warehouse_id.id
            order = request.env['sale.order'].sudo().with_company(rep.company_id).create(vals)
            rep._audit(order, T('created the %s from the portal', T('order') if confirm else T('quotation')))
            if note:
                order.message_post(body=note)
            if confirm:
                order.action_confirm()
        except (UserError, AccessError, ValidationError) as e:
            return _redir(back, str(e), 'err')
        msg, kind = T('Order %s created.', order.name), 'ok'
        if confirm:
            msg, kind = self._confirm_flash(
                order, rep, S, msg, T('Order %s created and delivery validated.', order.name),
                T('Order %s created; the delivery was not validated (not enough stock or manual processing needed).', order.name))
        # keep the rep inside the visit flow: back to the visit, which lists the new document
        dest = '/rep/visit/%s' % visit.id if visit else '/rep/order/%s' % order.id
        return _redir(dest, msg, kind)

    @http.route('/rep/order/<int:order_id>/confirm', type='http', auth='user', methods=['POST'])
    @rep_required
    def order_confirm(self, rep, order_id, **kw):
        order = self._get_order(rep, order_id)
        S = _settings(rep)
        if not order or order.state not in ('draft', 'sent') or not S.allow_sales_order:
            return _redir('/rep/orders', T('This order cannot be confirmed.'), 'err')
        try:
            order.action_confirm()
        except (UserError, ValidationError) as e:
            return _redir('/rep/order/%s' % order.id, str(e), 'err')
        msg, kind = self._confirm_flash(
            order, rep, S, T('Order confirmed.'), T('Order confirmed and delivery validated.'),
            T('Order confirmed; the delivery was not validated (not enough stock or manual processing needed).'))
        return _redir('/rep/order/%s' % order.id, msg, kind)

    @http.route('/rep/order/<int:order_id>/cancel', type='http', auth='user', methods=['POST'])
    @rep_required
    def order_cancel(self, rep, order_id, **kw):
        order = self._get_order(rep, order_id)
        if not order or order.state not in ('draft', 'sent'):
            return _redir('/rep/orders', T('This order can no longer be cancelled from the portal.'), 'err')
        try:
            order._action_cancel()
        except (UserError, ValidationError) as e:
            return _redir('/rep/order/%s' % order.id, str(e), 'err')
        return _redir('/rep/orders', T('Order cancelled.'))

    @http.route('/rep/order/<int:order_id>/invoice', type='http', auth='user', methods=['POST'])
    @rep_required
    def order_invoice(self, rep, order_id, **kw):
        order = self._get_order(rep, order_id)
        S = _settings(rep)
        if not order or not S.allow_invoice_creation:
            return _redir('/rep/orders', T('Invoice creation is not allowed.'), 'err')
        if order.state != 'sale' or order.invoice_status != 'to invoice':
            return _redir('/rep/order/%s' % order.id, T('Nothing to invoice on this order.'), 'err')
        try:
            moves = order._create_invoices()
            moves.write({'mo_source': 'portal', 'mo_rep_id': rep.id,
                         'mo_visit_id': order.mo_visit_id.id or False})
            if S.auto_post_invoice:
                moves.action_post()
        except (UserError, ValidationError) as e:
            return _redir('/rep/order/%s' % order.id, str(e), 'err')
        return _redir('/rep/invoice/%s' % moves[:1].id, T('Invoice created.'))

    # ---------------------------------------------------------------- invoices
    def _get_invoice(self, rep, move_id):
        return request.env['account.move'].sudo().search(_invoices_domain(rep) + [('id', '=', move_id)], limit=1)

    @http.route('/rep/invoices', type='http', auth='user')
    @rep_required
    def invoices(self, rep, flt='', **kw):
        domain = _invoices_domain(rep) + [('state', '!=', 'cancel')]
        if flt == 'open':
            domain += [('state', '=', 'posted'), ('amount_residual', '>', 0)]
        elif flt == 'paid':
            domain += [('state', '=', 'posted'), ('amount_residual', '=', 0)]
        elif flt == 'draft':
            domain += [('state', '=', 'draft')]
        moves = request.env['account.move'].sudo().search(domain, order='invoice_date desc, id desc', limit=100)
        return _render('mo_sales_rep_portal.tpl_invoices', rep, 'more', T('My Invoices'), moves=moves, flt=flt)

    @http.route('/rep/invoice/<int:move_id>', type='http', auth='user')
    @rep_required
    def invoice(self, rep, move_id, **kw):
        move = self._get_invoice(rep, move_id)
        if not move:
            return _forbidden()
        return _render('mo_sales_rep_portal.tpl_invoice', rep, 'more', move.name or T('Invoice'), move=move,
                       payments=move._get_reconciled_payments().sorted('id', reverse=True),
                       lines=move.invoice_line_ids.filtered(lambda l: l.display_type == 'product'))

    @http.route('/rep/invoice/<int:move_id>/pdf', type='http', auth='user')
    @rep_required
    def invoice_pdf(self, rep, move_id, **kw):
        move = self._get_invoice(rep, move_id)
        if not move or move.state != 'posted':
            return _forbidden()
        pdf, _fmt = request.env['ir.actions.report'].sudo()._render_qweb_pdf('account.account_invoices', [move.id])
        name = re.sub(r'[^\w\-]+', '_', move.name or 'invoice')
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', 'attachment; filename="%s.pdf"' % name)])

    @http.route('/rep/invoice/new', type='http', auth='user')
    @rep_required
    def invoice_new(self, rep, partner_id=None, visit_id=None, **kw):
        S = _settings(rep)
        if not (S.allow_invoice_creation and S.allow_direct_invoice):
            return _redir('/rep', T('Direct invoicing is disabled. Create invoices from a confirmed order.'), 'err')
        return _render('mo_sales_rep_portal.tpl_invoice_form', rep, 'more', T('New Invoice'),
                       customers=rep.get_customers(), partner_id=int(partner_id) if partner_id else 0,
                       visit_id=int(visit_id) if visit_id else 0,
                       can_price=rep.can_change_price(S), disc_cap=rep.effective_discount_cap(S))

    @http.route('/rep/invoice/create', type='http', auth='user', methods=['POST'])
    @rep_required
    def invoice_create(self, rep, partner_id=None, visit_id=None, **kw):
        S = _settings(rep)
        try:
            if not (S.allow_invoice_creation and S.allow_direct_invoice):
                raise AccessError(T('Direct invoicing is disabled.'))
            if not partner_id or not rep.can_access_partner(partner_id):
                raise AccessError(T('Choose one of your customers.'))
            visit = request.env['mo.sales.visit'].sudo().browse(int(visit_id)).exists() if visit_id else False
            if visit and visit.rep_id != rep:
                visit = False
            lines = []
            for l in _parse_lines(rep, S, request.httprequest.form):
                vals = {'product_id': l['product'].id, 'quantity': l['qty'], 'discount': l['discount']}
                if l['price'] is not None:
                    vals['price_unit'] = l['price']
                lines.append((0, 0, vals))
            move = request.env['account.move'].sudo().with_company(rep.company_id).with_context(
                default_move_type='out_invoice').create({
                    'move_type': 'out_invoice', 'partner_id': int(partner_id), 'company_id': rep.company_id.id,
                    'invoice_date': _today(), 'invoice_user_id': rep.user_id.id, 'mo_source': 'portal',
                    'mo_rep_id': rep.id, 'mo_visit_id': visit.id if visit else False, 'invoice_line_ids': lines})
            if S.auto_post_invoice:
                move.action_post()
        except (UserError, AccessError, ValidationError) as e:
            return _redir('/rep/invoice/new?partner_id=%s' % (partner_id or ''), str(e), 'err')
        return _redir('/rep/invoice/%s' % move.id, T('Invoice created.'))

    # ---------------------------------------------------------------- payments
    @http.route('/rep/payment/new', type='http', auth='user')
    @rep_required
    def payment_new(self, rep, partner_id=None, invoice_id=None, visit_id=None, **kw):
        S = _settings(rep)
        if not S.allow_payment:
            return _redir('/rep', T('Payment registration is disabled.'), 'err')
        move = self._get_invoice(rep, int(invoice_id)) if invoice_id else False
        pid = int(partner_id) if partner_id else (move.partner_id.id if move else 0)
        return _render('mo_sales_rep_portal.tpl_payment_form', rep, 'more', T('Register Payment'),
                       customers=rep.get_customers(), partner_id=pid, invoice_id=move.id if move else 0,
                       visit_id=int(visit_id) if visit_id else 0, methods=rep.payment_method_ids,
                       today=_today())

    @http.route('/rep/payment/create', type='http', auth='user', methods=['POST'])
    @rep_required
    def payment_create(self, rep, invoice_id=None, method_id=None, amount=None, payment_date=None,
                       reference=None, notes=None, visit_id=None, client_uid=None, cheque_number=None,
                       bank_name=None, cheque_date=None, due_date=None, **kw):
        S = _settings(rep)
        back = '/rep/payment/new?invoice_id=%s&visit_id=%s' % (invoice_id or '', visit_id or '')
        if client_uid:
            done = request.env['account.payment'].sudo().search([('mo_client_uid', '=', client_uid)], limit=1)
            if done:
                return _redir('/rep/payment/%s/receipt' % done.id, T('Payment registered.'))
        try:
            if not S.allow_payment:
                raise AccessError(T('Payment registration is disabled.'))
            move = self._get_invoice(rep, int(invoice_id)) if invoice_id else False
            if not move or move.state != 'posted' or move.amount_residual <= 0:
                raise UserError(T('Choose an open invoice.'))
            method = rep.payment_method_ids.filtered(lambda m: str(m.id) == str(method_id))
            if not method:
                raise AccessError(T('Choose one of your allowed payment methods.'))
            is_cheque = method.method_type == 'cheque'
            if is_cheque and not (cheque_number and bank_name and _date(due_date)):
                raise UserError(T('For a cheque, enter the cheque number, the bank and the due date.'))
            amt = _float(amount)
            if amt <= 0:
                raise UserError(T('Payment amount must be greater than zero.'))
            if amt > move.amount_residual + 0.0001:
                raise UserError(T('Payment cannot exceed the remaining amount (%s).', _money(move.amount_residual)))
            Wizard = request.env['account.payment.register'].sudo().with_context(
                active_model='account.move', active_ids=move.ids)
            vals = {'amount': amt, 'payment_date': _date(payment_date, _today()), 'journal_id': method.journal_id.id}
            memo = ' - '.join(filter(None, [move.name, reference]))
            for field_name in ('communication', 'memo'):
                if field_name in Wizard._fields:
                    vals[field_name] = memo
            vals = {k: v for k, v in vals.items() if k in Wizard._fields}
            payments = Wizard.create(vals)._create_payments()
            if not payments:
                payments = move._get_reconciled_payments().sorted('id', reverse=True)[:1]
            if not payments:
                raise UserError(T('The payment could not be created. Please check the journal configuration.'))
            visit = request.env['mo.sales.visit'].sudo().browse(int(visit_id)).exists() if visit_id else False
            payments.write({'mo_source': 'portal', 'mo_rep_id': rep.id, 'mo_method_id': method.id,
                            'mo_client_uid': client_uid or False,
                            'mo_visit_id': visit.id if visit and visit.rep_id == rep else move.mo_visit_id.id or False})
            pay = payments[:1]
            rep._audit(pay, T('registered %(a)s for invoice %(i)s', a=_money(amt), i=move.name))
            rep._audit(move, T('registered a payment of %s from the portal', _money(amt)))
            if notes:
                pay.message_post(body=notes)
            files = request.httprequest.files
            _save_attachments('account.payment', pay.id, files.getlist('attachments'))
            if is_cheque:
                cheque = request.env['mo.sales.cheque'].sudo().create({
                    'payment_id': pay.id, 'rep_id': rep.id, 'partner_id': move.partner_id.id,
                    'cheque_number': cheque_number, 'bank_name': bank_name, 'cheque_date': _date(cheque_date),
                    'due_date': _date(due_date), 'amount': pay.amount, 'currency_id': pay.currency_id.id,
                    'notes': notes or False})
                _save_attachments('mo.sales.cheque', cheque.id, files.getlist('cheque_photo'))
            rep._check_targets()
        except (UserError, AccessError, ValidationError) as e:
            return _redir(back, str(e), 'err')
        dest = '/rep/payment/%s/receipt?visit_id=%s' % (pay.id, visit.id if visit and visit.rep_id == rep else '')
        return _redir(dest, T('Payment registered.'))

    @http.route('/rep/payments', type='http', auth='user')
    @rep_required
    def payments(self, rep, **kw):
        pays = request.env['account.payment'].sudo().search(_payments_domain(rep), order='date desc, id desc', limit=100)
        return _render('mo_sales_rep_portal.tpl_payments', rep, 'more', T('My Payments'), pays=pays)

    @http.route('/rep/payment/<int:payment_id>', type='http', auth='user')
    @rep_required
    def payment(self, rep, payment_id, **kw):
        Payment = request.env['account.payment'].sudo()
        pay = Payment.search(_payments_domain(rep) + [('id', '=', payment_id)], limit=1)
        if not pay:
            candidate = Payment.browse(payment_id).exists()
            if candidate and candidate.payment_type == 'inbound' and any(
                    self._get_invoice(rep, inv.id) for inv in candidate.reconciled_invoice_ids):
                pay = candidate
        if not pay:
            return _forbidden()
        return _render('mo_sales_rep_portal.tpl_payment', rep, 'more', pay.name or T('Payment'), pay=pay,
                       invoices=pay.reconciled_invoice_ids if 'reconciled_invoice_ids' in pay._fields else [])

    @http.route('/rep/collections', type='http', auth='user')
    @rep_required
    def collections(self, rep, **kw):
        today = _today()
        week_start = today - timedelta(days=(today.weekday() + 1) % 7)
        month_start = today.replace(day=1)
        pays = request.env['account.payment'].sudo().search(
            _payments_domain(rep) + [('state', 'not in', ('draft', 'canceled', 'rejected'))],
            order='date desc, id desc')
        total = lambda ps: sum(ps.mapped('amount'))
        by_type = {t: total(pays.filtered(lambda p: (p.mo_method_id.method_type or 'other') == t))
                   for t in ('cash', 'bank', 'cheque', 'other')}
        return _render('mo_sales_rep_portal.tpl_collections', rep, 'more', T('My Collections'), pays=pays[:50],
                       totals={
                           'today': total(pays.filtered(lambda p: p.date == today)),
                           'week': total(pays.filtered(lambda p: p.date and p.date >= week_start)),
                           'month': total(pays.filtered(lambda p: p.date and p.date >= month_start)),
                           'all': total(pays)}, by_type=by_type)

    # ---------------------------------------------------------------- stock
    @http.route('/rep/stock', type='http', auth='user')
    @rep_required
    def stock(self, rep, q='', **kw):
        S = _settings(rep)
        rows = []
        if S.allow_stock_view and rep.warehouse_id:
            quants = request.env['stock.quant'].sudo().search([
                ('location_id', 'child_of', rep.warehouse_id.view_location_id.id),
                ('location_id.usage', '=', 'internal')])
            data = {}
            for qt in quants:
                row = data.setdefault(qt.product_id, {'qty': 0.0, 'reserved': 0.0})
                row['qty'] += qt.quantity
                row['reserved'] += qt.reserved_quantity
            for product, v in sorted(data.items(), key=lambda kv: kv[0].display_name):
                if q and q.lower() not in product.display_name.lower():
                    continue
                if v['qty'] or v['reserved']:
                    rows.append({'product': product, 'qty': v['qty'], 'reserved': v['reserved'],
                                 'available': v['qty'] - v['reserved'], 'uom': product.uom_id.name})
        return _render('mo_sales_rep_portal.tpl_stock', rep, 'more', T('My Stock'), rows=rows, q=q)

    @http.route('/rep/stock/operation', type='http', auth='user')
    @rep_required
    def stock_operation(self, rep, type='receive', **kw):
        S = _settings(rep)
        allowed = []
        if S.allow_internal_transfer:
            allowed += [('receive', T('Receive Stock')), ('transfer', T('Internal Transfer'))]
        if S.allow_return:
            allowed.append(('return', T('Return Stock')))
        if not allowed:
            return _redir('/rep', T('Stock operations are disabled.'), 'err')
        if type not in dict(allowed):
            type = allowed[0][0]
        warehouses = request.env['stock.warehouse'].sudo().search([('id', '!=', rep.warehouse_id.id)])
        return _render('mo_sales_rep_portal.tpl_stock_op', rep, 'more', T('Stock Operation'), allowed=allowed,
                       op=type, warehouses=warehouses, can_price=False, disc_cap=0,
                       can_auto=rep.can_auto_validate(S))

    @http.route('/rep/stock/create', type='http', auth='user', methods=['POST'])
    @rep_required
    def stock_create(self, rep, op='receive', dest_warehouse_id=None, note=None, auto_validate=None, **kw):
        S = _settings(rep)
        back = '/rep/stock/operation?type=%s' % op
        try:
            if not rep.warehouse_id:
                raise UserError(T('No warehouse is assigned to you. Contact your manager.'))
            if (op == 'return' and not S.allow_return) or (op in ('receive', 'transfer') and not S.allow_internal_transfer) \
                    or op not in ('receive', 'return', 'transfer'):
                raise AccessError(T('This operation is not allowed.'))
            van = rep.warehouse_id.lot_stock_id
            main = S.main_warehouse_id.lot_stock_id
            if op in ('receive', 'return') and not main:
                raise UserError(T('The main warehouse is not configured in the portal settings.'))
            if op == 'receive':
                src, dst = main, van
            elif op == 'return':
                src, dst = van, main
            else:
                wh = request.env['stock.warehouse'].sudo().browse(int(dest_warehouse_id or 0)).exists()
                if not wh or wh == rep.warehouse_id:
                    raise UserError(T('Choose a destination warehouse.'))
                src, dst = van, wh.lot_stock_id
            lines = _parse_lines(rep, S, request.httprequest.form, stock=True)
            moves = [(0, 0, {
                'product_id': l['product'].id, 'product_uom_qty': l['qty'], 'product_uom': l['product'].uom_id.id,
                'location_id': src.id, 'location_dest_id': dst.id,
            }) for l in lines]
            picking = request.env['stock.picking'].sudo().with_company(rep.company_id).create({
                'picking_type_id': rep.warehouse_id.int_type_id.id, 'location_id': src.id,
                'location_dest_id': dst.id, 'origin': 'Portal / %s' % rep.name, 'mo_source': 'portal',
                'mo_rep_id': rep.id, 'mo_operation': op, 'move_ids': moves})
            if note:
                picking.message_post(body=note)
            picking.action_confirm()
            picking.action_assign()
            validated, reason = False, ''
            if auto_validate and rep.can_auto_validate(S):
                validated, reason = self._auto_validate(picking)
        except (UserError, AccessError, ValidationError) as e:
            return _redir(back, str(e), 'err')
        if validated:
            return _redir('/rep/picking/%s' % picking.id, T('Operation %s created and validated.', picking.name))
        if auto_validate and rep.can_auto_validate(S):
            return _redir('/rep/picking/%s' % picking.id, T('Operation %(n)s created but not validated: %(r)s', n=picking.name, r=reason), 'err')
        return _redir('/rep/picking/%s' % picking.id, T('Operation %s created.', picking.name))

    @staticmethod
    def _auto_validate(picking):
        """Validate only when every line is fully reserved; never create negative stock silently."""
        if picking.state != 'assigned' or any(m.state != 'assigned' for m in picking.move_ids):
            return False, T('not enough stock to cover all lines')
        res = picking.with_context(skip_backorder=True, skip_sms=True, skip_expired=True).button_validate()
        if isinstance(res, dict):
            return False, T('it needs manual processing in the back office')
        return picking.state == 'done', ('' if picking.state == 'done' else T('validation did not complete'))

    @http.route('/rep/transfers', type='http', auth='user')
    @rep_required
    def transfers(self, rep, kind='', **kw):
        domain = _pickings_domain(rep)
        if kind == 'delivery':
            domain = [('picking_type_code', '=', 'outgoing'), ('sale_id.mo_rep_id', '=', rep.id)]
        elif kind == 'transfer':
            domain = [('mo_rep_id', '=', rep.id)]
        pickings = request.env['stock.picking'].sudo().search(domain, order='id desc', limit=80)
        return _render('mo_sales_rep_portal.tpl_transfers', rep, 'more', T('Transfers & Deliveries'),
                       pickings=pickings, kind=kind)

    def _get_picking(self, rep, picking_id):
        return request.env['stock.picking'].sudo().search(_pickings_domain(rep) + [('id', '=', picking_id)], limit=1)

    @http.route('/rep/picking/<int:picking_id>', type='http', auth='user')
    @rep_required
    def picking(self, rep, picking_id, **kw):
        picking = self._get_picking(rep, picking_id)
        if not picking:
            return _forbidden()
        return _render('mo_sales_rep_portal.tpl_picking', rep, 'more', picking.name, picking=picking,
                       can_validate=_settings(rep).allow_delivery_validation and picking.picking_type_code == 'outgoing'
                       and picking.state in ('assigned', 'confirmed'))

    @http.route('/rep/picking/<int:picking_id>/validate', type='http', auth='user', methods=['POST'])
    @rep_required
    def picking_validate(self, rep, picking_id, **kw):
        picking = self._get_picking(rep, picking_id)
        S = _settings(rep)
        if not picking or not S.allow_delivery_validation or picking.picking_type_code != 'outgoing':
            return _redir('/rep/transfers', T('You cannot validate this transfer.'), 'err')
        try:
            res = picking.with_context(skip_backorder=True, skip_sms=True, skip_expired=True).button_validate()
        except (UserError, ValidationError) as e:
            return _redir('/rep/picking/%s' % picking.id, str(e), 'err')
        if isinstance(res, dict):
            return _redir('/rep/picking/%s' % picking.id,
                          T('This delivery needs manual processing in the back office.'), 'err')
        return _redir('/rep/picking/%s' % picking.id, T('Delivery validated.'))

    # ---------------------------------------------------------------- notifications
    @http.route('/rep/notifications', type='http', auth='user')
    @rep_required
    def notifications(self, rep, **kw):
        notes = request.env['mo.sales.rep.notification'].sudo().search([('rep_id', '=', rep.id)], limit=60)
        unread = notes.filtered(lambda n: not n.is_read)
        response = _render('mo_sales_rep_portal.tpl_notifications', rep, 'more', T('Notifications'),
                           notes=notes, unread_ids=unread.ids)
        unread.write({'is_read': True})
        return response
