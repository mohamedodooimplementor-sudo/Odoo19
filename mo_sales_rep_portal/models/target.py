from datetime import date, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

METRICS = [
    # key in rep.performance, target field, label, is money
    ('sales', 'sales_target', 'Sales', True),
    ('collection', 'collection_target', 'Collection', True),
    ('orders', 'orders_target', 'Orders', False),
    ('visits', 'visits_target', 'Visits', False),
    ('new_customers', 'new_customers_target', 'New Customers', False),
]


class SalesTarget(models.Model):
    _name = 'mo.sales.target'
    _description = 'Sales Representative Target'
    _inherit = ['mail.thread']
    _order = 'date_from desc, rep_id'

    rep_id = fields.Many2one('mo.sales.rep', 'Sales Representative', required=True, ondelete='cascade', tracking=True)
    name = fields.Char(compute='_compute_name', store=True)
    date_from = fields.Date('From', required=True, default=lambda s: fields.Date.context_today(s).replace(day=1))
    date_to = fields.Date('To', required=True, default=lambda s: (
        fields.Date.context_today(s).replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1))
    sales_target = fields.Float('Sales Target', tracking=True)
    collection_target = fields.Float('Collection Target', tracking=True)
    orders_target = fields.Integer('Orders Target', tracking=True)
    visits_target = fields.Integer('Visits Target', tracking=True)
    new_customers_target = fields.Integer('New Customers Target', tracking=True)
    company_id = fields.Many2one('res.company', related='rep_id.company_id', store=True)
    notified = fields.Char(copy=False, help='Metrics already announced as achieved.')

    sales_actual = fields.Float(compute='_compute_actuals')
    collection_actual = fields.Float(compute='_compute_actuals')
    orders_actual = fields.Integer(compute='_compute_actuals')
    visits_actual = fields.Integer(compute='_compute_actuals')
    new_customers_actual = fields.Integer(compute='_compute_actuals')
    achievement = fields.Float('Achievement %', compute='_compute_actuals')

    @api.depends('rep_id.name', 'date_from', 'date_to')
    def _compute_name(self):
        for t in self:
            t.name = '%s  %s → %s' % (t.rep_id.name or '', t.date_from or '', t.date_to or '')

    @api.constrains('date_from', 'date_to', 'rep_id')
    def _check_period(self):
        for t in self:
            if t.date_to < t.date_from:
                raise ValidationError(_('The end of the period must be after its start.'))
            clash = self.search_count([('rep_id', '=', t.rep_id.id), ('id', '!=', t.id),
                                       ('date_from', '<=', t.date_to), ('date_to', '>=', t.date_from)])
            if clash:
                raise ValidationError(_('This representative already has a target overlapping this period.'))

    @api.depends('rep_id', 'date_from', 'date_to', 'sales_target', 'collection_target', 'orders_target',
                 'visits_target', 'new_customers_target')
    def _compute_actuals(self):
        for t in self:
            perf = t.rep_id.performance(t.date_from, t.date_to) if t.rep_id and t.date_from and t.date_to else {}
            t.sales_actual = perf.get('sales', 0.0)
            t.collection_actual = perf.get('collection', 0.0)
            t.orders_actual = perf.get('orders', 0)
            t.visits_actual = perf.get('visits', 0)
            t.new_customers_actual = perf.get('new_customers', 0)
            t.achievement = t._achievement(perf)

    def _achievement(self, perf=None):
        """Average achievement % over the metrics that have a target (each capped at 999)."""
        self.ensure_one()
        perf = perf or self.rep_id.performance(self.date_from, self.date_to)
        pcts = [min(999.0, 100.0 * perf.get(key, 0) / getattr(self, tfield))
                for key, tfield, _l, _m in METRICS if getattr(self, tfield)]
        return round(sum(pcts) / len(pcts), 1) if pcts else 0.0

    def progress(self):
        """Rows for the portal: target, actual, achievement %, remaining, for every defined target."""
        self.ensure_one()
        perf = self.rep_id.performance(self.date_from, self.date_to)
        rows = []
        for key, tfield, label, money in METRICS:
            target = getattr(self, tfield)
            if not target:
                continue
            actual = perf.get(key, 0)
            rows.append({'key': key, 'label': label, 'money': money, 'target': target, 'actual': actual,
                         'pct': round(100.0 * actual / target, 1), 'bar': min(100.0, 100.0 * actual / target),
                         'remaining': max(0.0, target - actual)})
        return rows

    def _notify_if_achieved(self):
        for t in self:
            done = set((t.notified or '').split(',')) - {''}
            for row in t.progress():
                if row['pct'] >= 100 and row['key'] not in done:
                    done.add(row['key'])
                    t.rep_id._notify(_('Target achieved'), _('%(m)s target reached (%(p).0f%%)', m=row['label'], p=row['pct']),
                                     '/rep/targets', key='target:%s:%s' % (t.id, row['key']))
            t.sudo().notified = ','.join(sorted(done))

    def action_copy_next_period(self):
        """Create the same targets for the following month."""
        created = self.browse()
        for t in self:
            nxt_from = t.date_to + timedelta(days=1)
            nxt_to = (nxt_from.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            if self.search_count([('rep_id', '=', t.rep_id.id), ('date_from', '<=', nxt_to), ('date_to', '>=', nxt_from)]):
                continue
            created |= t.copy({'date_from': nxt_from, 'date_to': nxt_to, 'notified': False})
        return {'type': 'ir.actions.act_window', 'name': _('Targets'), 'res_model': self._name,
                'view_mode': 'list,form', 'domain': [('id', 'in', created.ids)]} if created else True
