from collections import defaultdict
from datetime import date, datetime, time, timedelta

import pytz

from odoo import api, fields, models
from odoo.exceptions import AccessError
from odoo.tools import format_date


class RcExamConsumptionLineAnalytics(models.Model):
    _inherit = 'rc.exam.consumption.line'

    analytics_company_id = fields.Many2one(
        related='consumption_id.company_id', store=True, readonly=True, index=True)
    analytics_room_id = fields.Many2one(
        related='consumption_id.room_id', store=True, readonly=True, index=True, string='Room')
    analytics_exam_id = fields.Many2one(
        related='consumption_id.service_product_id', store=True, readonly=True, index=True, string='Exam')
    analytics_date = fields.Datetime(
        related='consumption_id.date', store=True, readonly=True, index=True, string='Exam Date')
    analytics_state = fields.Selection(
        related='consumption_id.state', store=True, readonly=True, string='Exam Status')
    analytics_currency_id = fields.Many2one(
        related='consumption_id.company_id.currency_id', store=True, readonly=True)
    actual_unit_cost = fields.Monetary(
        string='Actual Unit Cost', compute='_compute_actual_cost', store=True,
        help='Cost captured when the related internal transfer is validated. Uses stock valuation layers when available; otherwise snapshots the product standard cost.' ,
        currency_field='analytics_currency_id',
        groups='radiology_consumables.group_rc_analytics')
    actual_cost = fields.Monetary(
        string='Actual Consumables Cost', compute='_compute_actual_cost', store=True,
        currency_field='analytics_currency_id',
        groups='radiology_consumables.group_rc_analytics')
    cost_method = fields.Selection([
        ('valuation', 'Stock Valuation'),
        ('standard', 'Product Cost Fallback'),
        ('pending', 'Pending Stock Validation'),
    ], string='Cost Source', compute='_compute_actual_cost', store=True,
        groups='radiology_consumables.group_rc_analytics')

    @api.depends(
        'move_id', 'move_id.state', 'move_id.quantity', 'picking_id.state',
        'qty_transferred', 'product_id', 'consumption_id.company_id')
    def _compute_actual_cost(self):
        for line in self:
            qty = line.qty_transferred if line.picking_id and line.picking_id.state == 'done' else 0.0
            if not qty:
                line.actual_unit_cost = 0.0
                line.actual_cost = 0.0
                line.cost_method = 'pending'
                continue

            unit_cost = 0.0
            method = 'standard'
            move = line.move_id
            if move and 'stock_valuation_layer_ids' in move._fields:
                layers = move.stock_valuation_layer_ids
                layer_qty = sum(abs(layer.quantity) for layer in layers)
                layer_value = sum(abs(layer.value) for layer in layers)
                if layer_qty:
                    unit_cost = layer_value / layer_qty
                    method = 'valuation'
            if not unit_cost:
                unit_cost = line.product_id.with_company(line.consumption_id.company_id).standard_price
            line.actual_unit_cost = unit_cost
            line.actual_cost = unit_cost * qty
            line.cost_method = method


class RcExamConsumptionAnalytics(models.Model):
    _inherit = 'rc.exam.consumption'

    actual_consumables_qty = fields.Float(
        string='Validated Consumed Quantity', compute='_compute_actual_analytics', store=True,
        groups='radiology_consumables.group_rc_analytics')
    actual_consumables_cost = fields.Monetary(
        string='Actual Consumables Cost', compute='_compute_actual_analytics', store=True,
        currency_field='currency_id',
        groups='radiology_consumables.group_rc_analytics')
    currency_id = fields.Many2one(related='company_id.currency_id', store=True, readonly=True,
                                  groups='radiology_consumables.group_rc_analytics')

    @api.depends('line_ids.actual_cost', 'line_ids.qty_transferred', 'line_ids.picking_id.state')
    def _compute_actual_analytics(self):
        for exam in self:
            valid_lines = exam.line_ids.filtered(
                lambda line: line.picking_id and line.picking_id.state == 'done')
            exam.actual_consumables_qty = sum(valid_lines.mapped('qty_transferred'))
            exam.actual_consumables_cost = sum(valid_lines.mapped('actual_cost'))

    # ------------------------------------------------------------------
    # Interactive Cost & Performance dashboard
    # ------------------------------------------------------------------
    _RC_AN_FIELDS = [
        'consumption_id', 'analytics_date', 'analytics_room_id', 'analytics_exam_id',
        'product_id', 'qty_transferred', 'actual_cost', 'cost_method']

    @api.model
    def _rc_an_date(self, value):
        try:
            return date.fromisoformat(value) if value else None
        except (TypeError, ValueError):
            return None

    @api.model
    def _rc_an_line_domain(self, filters, d_from=None, d_to=None):
        """Validated, non-cancelled consumption lines of the active company."""
        domain = [
            ('analytics_company_id', '=', self.env.company.id),
            ('analytics_state', '!=', 'cancel'),
            ('picking_id.state', '=', 'done'),
            ('actual_cost', '>', 0),
        ]
        if filters:
            for key, field in (('room_ids', 'analytics_room_id'), ('exam_ids', 'analytics_exam_id'),
                               ('product_ids', 'product_id')):
                ids = [int(i) for i in (filters.get(key) or []) if str(i).lstrip('-').isdigit()]
                if ids:
                    domain.append((field, 'in', ids))
            sources = [x for x in (filters.get('sources') or []) if x in ('valuation', 'standard')]
            if sources:
                domain.append(('cost_method', 'in', sources))
        tz = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')

        def to_utc(day):
            return tz.localize(datetime.combine(day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        if d_from:
            domain.append(('analytics_date', '>=', to_utc(d_from)))
        if d_to:
            domain.append(('analytics_date', '<', to_utc(d_to + timedelta(days=1))))
        return domain

    @api.model
    def _rc_an_totals(self, rows):
        exams = {r['consumption_id'][0] for r in rows if r['consumption_id']}
        cost = sum(r['actual_cost'] for r in rows)
        qty = sum(r['qty_transferred'] for r in rows)
        return {'cost': cost, 'qty': qty, 'exams': len(exams),
                'average': cost / len(exams) if exams else 0.0}

    @api.model
    def _rc_an_group(self, rows, key_field, limit=10):
        groups = {}
        for r in rows:
            val = r[key_field]
            gid, name = (val[0], val[1]) if val else (False, 'Unassigned')
            g = groups.setdefault(gid, {'id': gid, 'name': name, 'cost': 0.0, 'qty': 0.0, 'exam_ids': set()})
            g['cost'] += r['actual_cost']
            g['qty'] += r['qty_transferred']
            if r['consumption_id']:
                g['exam_ids'].add(r['consumption_id'][0])
        total = sum(g['cost'] for g in groups.values()) or 1.0
        out = []
        for g in sorted(groups.values(), key=lambda x: x['cost'], reverse=True)[:limit]:
            n = len(g['exam_ids'])
            out.append({'id': g['id'], 'name': g['name'], 'cost': g['cost'], 'qty': g['qty'],
                        'exams': n, 'average': g['cost'] / n if n else 0.0,
                        'share': g['cost'] / total * 100.0})
        return out

    @api.model
    def _rc_an_bucket_start(self, day, gran):
        if gran == 'day':
            return day
        if gran == 'week':
            return day - timedelta(days=day.weekday())
        return day.replace(day=1)

    @api.model
    def _rc_an_bucket_end(self, start, gran):
        if gran == 'day':
            return start
        if gran == 'week':
            return start + timedelta(days=6)
        return (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)

    @api.model
    def _rc_an_trend(self, rows, gran, d_from, d_to):
        buckets = {}
        for r in rows:
            if not r['analytics_date']:
                continue
            day = fields.Datetime.context_timestamp(
                self, fields.Datetime.to_datetime(r['analytics_date'])).date()
            start = self._rc_an_bucket_start(day, gran)
            b = buckets.setdefault(start, {'cost': 0.0, 'qty': 0.0, 'exam_ids': set()})
            b['cost'] += r['actual_cost']
            b['qty'] += r['qty_transferred']
            if r['consumption_id']:
                b['exam_ids'].add(r['consumption_id'][0])
        if not buckets:
            return []
        first = self._rc_an_bucket_start(d_from, gran) if d_from else min(buckets)
        last = self._rc_an_bucket_start(d_to, gran) if d_to else max(buckets)
        starts, cur = [], first
        while cur <= last and len(starts) < 400:
            starts.append(cur)
            cur = self._rc_an_bucket_end(cur, gran) + timedelta(days=1)
        if cur <= last:  # range too long to zero-fill: only populated buckets
            starts = sorted(buckets)
        pattern = 'MMM yyyy' if gran == 'month' else 'd MMM'
        out = []
        for start in starts:
            end = self._rc_an_bucket_end(start, gran)
            b = buckets.get(start) or {'cost': 0.0, 'qty': 0.0, 'exam_ids': set()}
            n = len(b['exam_ids'])
            label = format_date(self.env, start, date_format=pattern)
            if gran == 'week':
                label = '%s – %s' % (label, format_date(self.env, end, date_format='d MMM'))
            out.append({'key': start.isoformat(), 'label': label,
                        'start': start.isoformat(), 'end': end.isoformat(),
                        'cost': b['cost'], 'qty': b['qty'], 'exams': n,
                        'average': b['cost'] / n if n else 0.0})
        return out

    @api.model
    def get_analytics_dashboard_data(self, filters=None):
        """Read-only analytics endpoint; access is intentionally independent."""
        if not self.env.user.has_group('radiology_consumables.group_rc_analytics'):
            raise AccessError(self.env._('You are not allowed to access Cost & Performance Analytics.'))
        filters = filters if isinstance(filters, dict) else {}
        d_from = self._rc_an_date(filters.get('date_from'))
        d_to = self._rc_an_date(filters.get('date_to'))
        gran = filters.get('granularity') if filters.get('granularity') in ('day', 'week', 'month') else 'month'
        # Read-only aggregation, already gated by the analytics group check above and
        # scoped to the active company in the domain. sudo() is needed because analysts
        # have no stock.move / stock.picking access, which the domain (picking_id.state)
        # and the computed qty_transferred read through.
        Line = self.env['rc.exam.consumption.line'].sudo()

        rows = Line.search_read(self._rc_an_line_domain(filters, d_from, d_to), self._RC_AN_FIELDS)
        totals = self._rc_an_totals(rows)

        previous = None
        if d_from and d_to and d_to >= d_from:
            span = (d_to - d_from).days + 1
            p_from, p_to = d_from - timedelta(days=span), d_from - timedelta(days=1)
            previous = self._rc_an_totals(Line.search_read(
                self._rc_an_line_domain(filters, p_from, p_to), self._RC_AN_FIELDS))
            previous.update({'date_from': p_from.isoformat(), 'date_to': p_to.isoformat()})

        sources = defaultdict(lambda: {'cost': 0.0, 'lines': 0})
        for r in rows:
            sources[r['cost_method']]['cost'] += r['actual_cost']
            sources[r['cost_method']]['lines'] += 1
        labels = {'valuation': self.env._('Stock valuation'), 'standard': self.env._('Product cost fallback')}
        total_cost = totals['cost'] or 1.0
        source_rows = [{'id': k, 'name': labels.get(k, k), 'cost': v['cost'], 'lines': v['lines'],
                        'share': v['cost'] / total_cost * 100.0} for k, v in sources.items()]

        # Filter option lists ignore the user's own filters so nothing disappears.
        base = self._rc_an_line_domain(None)
        rooms = sorted(({'id': rec.id, 'name': rec.display_name}
                        for rec, _count in Line._read_group(base, ['analytics_room_id'], ['__count']) if rec),
                       key=lambda x: x['name'])
        exams = sorted(({'id': rec.id, 'name': rec.display_name}
                        for rec, _count in Line._read_group(base, ['analytics_exam_id'], ['__count']) if rec),
                       key=lambda x: x['name'])

        exam_ids = sorted({r['consumption_id'][0] for r in rows if r['consumption_id']})
        return {
            'currency': self.env.company.currency_id.symbol,
            'kpis': totals,
            'previous': previous,
            'trend': self._rc_an_trend(rows, gran, d_from, d_to),
            'rooms': self._rc_an_group(rows, 'analytics_room_id', 12),
            'exams_by_type': self._rc_an_group(rows, 'analytics_exam_id', 10),
            'products': self._rc_an_group(rows, 'product_id', 10),
            'sources': source_rows,
            'options': {'rooms': rooms, 'exams': exams},
            'exam_ids': exam_ids[:5000],
        }
