from collections import Counter

from odoo import api, models, _
from odoo.exceptions import AccessError

QUALITY = ('prd_line', 'product_check1', 'product_check', 'filling', 'pack_line', 'product_check2')


class PPDashboard(models.AbstractModel):
    _name = 'pp.dashboard'
    _description = 'Pre-Production Dashboard'

    @api.model
    def _domain(self, f):
        d = []
        if f.get('date_from'):
            d.append(('create_date', '>=', f['date_from'] + ' 00:00:00'))
        if f.get('date_to'):
            d.append(('create_date', '<=', f['date_to'] + ' 23:59:59'))
        for key, field in (('partner_id', 'partner_id'), ('product_id', 'product_id'),
                           ('warehouse_id', 'line_ids.source_warehouse_id'), ('stage_id', 'current_stage_id')):
            if f.get(key):
                d.append((field, '=', int(f[key])))
        if f.get('state'):
            d.append(('state', '=', f['state']))
        if f.get('sale_order'):
            d.append(('sale_order_id.name', 'ilike', f['sale_order']))
        if f.get('lot'):
            d += ['|', '|', ('line_ids.lot_line_ids.lot_id.name', 'ilike', f['lot']),
                  ('lock_ids.lot_id.name', 'ilike', f['lot']),
                  ('lot_producing_id.name', 'ilike', f['lot'])]
        return d

    @api.model
    def get_data(self, filters=None):
        if not self.env.user.has_group('pre_production.group_pp_dashboard'):
            raise AccessError(_("You do not have permission to open the Pre-Production Dashboard."))
        f = filters or {}
        Order = self.env['pp.order']
        dom = self._domain(f)
        orders = Order.search(dom)

        def kpi(key, label, icon, color, extra):
            d = dom + extra
            return {'key': key, 'label': label, 'icon': icon, 'color': color,
                    'value': Order.search_count(d), 'domain': d}

        kpis = [
            kpi('total', _('Total Orders'), 'fa-list-alt', '#714B67', []),
            kpi('draft', _('Draft'), 'fa-pencil', '#8f8f8f', [('state', '=', 'draft')]),
            kpi('progress', _('In Progress'), 'fa-spinner', '#0d6efd', [('state', '=', 'in_progress')]),
            kpi('wait', _('Waiting Approval'), 'fa-hourglass-half', '#fd7e14',
                [('state', '=', 'in_progress'), ('check_ids.state', '=', 'pending')]),
            kpi('issue', _('Material Issue Pending'), 'fa-truck', '#6f42c1',
                [('state', '=', 'in_progress'), ('stage_code', '=', 'material_issue')]),
            kpi('weight', _('Weight Confirmation Pending'), 'fa-balance-scale', '#20c997',
                [('state', '=', 'in_progress'), ('stage_code', '=', 'weight')]),
            kpi('quality', _('Quality Check Pending'), 'fa-flask', '#0dcaf0',
                [('state', '=', 'in_progress'), ('stage_code', 'in', QUALITY)]),
            kpi('rejected', _('Rejected'), 'fa-times-circle', '#dc3545', [('state', '=', 'rejected')]),
            kpi('done', _('Done'), 'fa-check-circle', '#198754', [('state', '=', 'done')]),
            kpi('mo', _('Manufacturing Orders Created'), 'fa-cogs', '#6610f2', [('mo_id', '!=', False)]),
        ]

        active = orders.filtered(lambda o: o.state not in ('draft', 'cancel'))
        stages = self.env['pp.stage'].search([])
        by_stage = {'labels': stages.mapped('name'),
                    'values': [len(active.filtered(lambda o: o.current_stage_id == s)) for s in stages]}

        checks = self.env['pp.quality.check'].search([('order_id', 'in', orders.ids)])
        quality = {'labels': [_('Passed'), _('Rejected'), _('Pending')],
                   'values': [len(checks.filtered(lambda c: c.state == 'approved')),
                              len(checks.filtered(lambda c: c.state == 'rejected')),
                              len(checks.filtered(lambda c: c.state == 'pending'))]}

        logs = self.env['pp.stage.log'].search([('order_id', 'in', orders.ids), ('date_end', '!=', False)])
        dur_stages = stages.filtered(lambda s: s.code not in ('done', 'draft'))
        duration = {'labels': dur_stages.mapped('name'), 'values': []}
        for st in dur_stages:
            sl = logs.filtered(lambda l: l.stage_id == st)
            duration['values'].append(round(sum(sl.mapped('duration_hours')) / len(sl), 2) if sl else 0)

        issuable = orders.filtered(lambda o: o.state != 'cancel')
        issue = {'labels': [_('Pending'), _('Completed')],
                 'values': [len(issuable.filtered(lambda o: not o.material_issue_done)),
                            len(issuable.filtered('material_issue_done'))]}

        prod = Counter(o.product_id.display_name for o in orders).most_common(10)
        wh = Counter(w.name for o in orders for w in o.line_ids.mapped('source_warehouse_id')).most_common(10)

        options = {
            'partners': [{'id': p.id, 'name': p.display_name} for p in Order.search([]).mapped('partner_id')],
            'products': [{'id': p.id, 'name': p.display_name} for p in Order.search([]).mapped('product_id')],
            'warehouses': [{'id': w.id, 'name': w.name} for w in self.env['stock.warehouse'].search([])],
            'stages': [{'id': s.id, 'name': s.name} for s in stages],
            'states': [{'id': k, 'name': v} for k, v in Order._fields['state'].selection],
        }
        return {
            'kpis': kpis, 'options': options,
            'charts': {
                'stage': by_stage, 'duration': duration, 'quality': quality, 'issue': issue,
                'product': {'labels': [p[0] for p in prod], 'values': [p[1] for p in prod]},
                'warehouse': {'labels': [w[0] for w in wh], 'values': [w[1] for w in wh]},
            },
        }
