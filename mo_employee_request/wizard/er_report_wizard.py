# -*- coding: utf-8 -*-
import base64
import io
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

REPORT_ACTIONS = {
    'request': 'mo_employee_request.action_er_report_request',
    'purchase': 'mo_employee_request.action_er_report_purchase',
    'project_stock': 'mo_employee_request.action_er_project_stock',
    'expiry': 'mo_employee_request.action_er_expiry',
}


def _blank(value):
    """Empty cell (a real 0.0 is not empty)."""
    return value is None or value is False or value == ''


class ErReportWizard(models.TransientModel):
    """One screen for every report: filters, then View on screen / PDF / Excel.
    The three outputs read the same data (`_get_report_data`), so they always agree."""
    _name = 'er.report.wizard'
    _description = 'Employee Request Reports'

    report_type = fields.Selection([
        ('request', 'Employee Request Report'),
        ('purchase', 'Purchase Report'),
        ('project_stock', 'Project Stock Report'),
        ('expiry', 'Expiry Date Report'),
    ], string='Report', required=True, default='request')
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company)
    date_from = fields.Date(string='From')
    date_to = fields.Date(string='To')
    project_ids = fields.Many2many('project.project', string='Projects')
    only_held = fields.Boolean(string='Only Stock Still Held', default=True)
    expiry_state = fields.Selection([
        ('all', 'All'), ('expired', 'Expired'), ('soon', 'Expiring Soon'), ('ok', 'Valid'),
    ], string='Expiry Status', default='all')
    xlsx_file = fields.Binary(attachment=False, readonly=True)
    xlsx_name = fields.Char(readonly=True)

    # ------------------------------------------------------------------
    # Data (shared by screen, PDF and Excel)
    # ------------------------------------------------------------------
    def _domain(self):
        self.ensure_one()
        t = self.report_type
        dom = []
        if t == 'request':
            dom = [('request_state', 'not in', ('draft', 'cancelled'))]
            if self.date_from:
                dom.append(('request_id.request_date', '>=', self.date_from))
            if self.date_to:
                dom.append(('request_id.request_date', '<=', self.date_to))
            if self.project_ids:
                dom.append(('project_id', 'in', self.project_ids.ids))
        elif t == 'purchase':
            dom = [('order_state', 'not in', ('draft', 'cancelled', 'rejected'))]
            if self.date_from:
                dom.append(('order_id.date_order', '>=', fields.Datetime.to_datetime(self.date_from)))
            if self.date_to:
                dom.append(('order_id.date_order', '<',
                            fields.Datetime.to_datetime(self.date_to) + timedelta(days=1)))
            if self.project_ids:
                dom.append(('project_id', 'in', self.project_ids.ids))
        elif t == 'project_stock':
            dom = [('company_id', 'in', self.env.companies.ids)]
            if self.only_held:
                dom.append(('qty_held', '>', 0))
            if self.project_ids:
                dom.append(('project_id', 'in', self.project_ids.ids))
        elif t == 'expiry':
            dom = [('company_id', 'in', self.env.companies.ids)]
            if self.expiry_state != 'all':
                dom.append(('state', '=', self.expiry_state))
        return dom

    def _filters_text(self):
        self.ensure_one()
        parts = []
        if self.report_type in ('request', 'purchase'):
            if self.date_from:
                parts.append(_("From %s", self.date_from))
            if self.date_to:
                parts.append(_("To %s", self.date_to))
        if self.report_type != 'expiry' and self.project_ids:
            parts.append(_("Projects: %s", ", ".join(self.project_ids.mapped('display_name'))))
        if self.report_type == 'project_stock' and self.only_held:
            parts.append(_("Only stock still held"))
        if self.report_type == 'expiry' and self.expiry_state != 'all':
            parts.append(_("Status: %s", dict(self._fields['expiry_state'].selection)[self.expiry_state]))
        return "  |  ".join(parts) or _("No filter")

    def _get_report_data(self):
        """{'title', 'filters', 'kpis': [(label, value, color)], 'columns': [(label, kind)],
        'rows': [[...]], 'totals': [...] or None}. kind: text | float | money | date"""
        self.ensure_one()
        return getattr(self, '_data_%s' % self.report_type)(self._domain())

    def _data_request(self, domain):
        lines = self.env['employee.request.line'].search(
            domain, order='request_id desc, sequence, id')
        cols = [(_("Request"), 'text'), (_("Date"), 'date'), (_("Employee"), 'text'),
                (_("Department"), 'text'), (_("Project"), 'text'), (_("Location"), 'text'),
                (_("Product"), 'text'), (_("Requested"), 'float'), (_("Issued"), 'float'),
                (_("Purchased"), 'float'), (_("Received"), 'float'), (_("Remaining"), 'float'),
                (_("Status"), 'text')]
        rows = [[l.request_id.name, l.request_id.request_date, l.employee_id.name or '',
                 l.department_id.name or '', l.project_id.name or '',
                 l.location_id.display_name or '', l.product_id.display_name,
                 l.product_uom_qty, l.qty_issued, l.qty_purchase_planned, l.qty_received,
                 l.qty_remaining, l.request_id._stage_label()] for l in lines]
        tot = [sum(r[i] for r in rows) for i in range(7, 12)]
        return {
            'title': _("Employee Request Report"), 'filters': self._filters_text(),
            'kpis': [(_("Requests"), len(set(lines.request_id.ids)), '#2b6cb0'),
                     (_("Requested"), tot[0], '#2b6cb0'), (_("Issued"), tot[1], '#2f855a'),
                     (_("Purchased"), tot[2], '#b7791f'), (_("Received"), tot[3], '#2c7a7b'),
                     (_("Remaining"), tot[4], '#c53030')],
            'columns': cols, 'rows': rows,
            'totals': [_("Total")] + [''] * 6 + tot + [''],
        }

    def _data_purchase(self, domain):
        lines = self.env['employee.purchase.order.line'].search(
            domain, order='order_id desc, id')
        cols = [(_("Order"), 'text'), (_("Date"), 'date'), (_("Vendor"), 'text'),
                (_("Project"), 'text'), (_("Location"), 'text'), (_("Product"), 'text'),
                (_("Quantity"), 'float'), (_("Unit Price"), 'money'), (_("Disc. %"), 'float'),
                (_("Subtotal"), 'money'), (_("Received"), 'float'), (_("Currency"), 'text'),
                (_("Status"), 'text')]
        rows = [[l.order_id.name, fields.Datetime.to_datetime(l.order_id.date_order).date()
                 if l.order_id.date_order else False, l.order_id.partner_id.name or '',
                 l.project_id.name or '', l.location_id.display_name or '',
                 l.product_id.display_name, l.product_uom_qty, l.price_unit, l.discount,
                 l.price_subtotal, l.received_qty, l.order_id.currency_id.name or '',
                 l.order_id._stage_label()] for l in lines]
        qty = sum(r[6] for r in rows)
        recv = sum(r[10] for r in rows)
        currencies = {r[11] for r in rows}
        amount = sum(r[9] for r in rows)
        single = len(currencies) <= 1
        return {
            'title': _("Purchase Report"), 'filters': self._filters_text(),
            'kpis': [(_("Orders"), len(set(lines.order_id.ids)), '#2b6cb0'),
                     (_("Quantity"), qty, '#b7791f'), (_("Received"), recv, '#2c7a7b'),
                     (_("Amount"), amount if single else _("Mixed currencies"), '#2f855a')],
            'columns': cols, 'rows': rows,
            'totals': [_("Total")] + [''] * 5 + [qty, '', '', amount if single else '',
                                                  recv, next(iter(currencies), '') if single else '', ''],
        }

    def _data_project_stock(self, domain):
        recs = self.env['er.project.stock.report'].sudo().search(domain)
        cols = [(_("Project"), 'text'), (_("Location"), 'text'), (_("Product"), 'text'),
                (_("UoM"), 'text'), (_("Received"), 'float'), (_("Allocated"), 'float'),
                (_("Issued"), 'float'), (_("Held for Project"), 'float'), (_("Value Held"), 'money')]
        rows = [[r.project_id.name or '', r.location_id.display_name or '',
                 r.product_id.display_name, r.product_uom_id.name or '', r.qty_received,
                 r.qty_allocated, r.qty_issued, r.qty_held, r.value_held] for r in recs]
        tot = [sum(r[i] for r in rows) for i in range(4, 9)]
        return {
            'title': _("Project Stock Report"), 'filters': self._filters_text(),
            'kpis': [(_("Projects"), len(set(recs.project_id.ids)), '#2b6cb0'),
                     (_("Received"), tot[0], '#2c7a7b'), (_("Issued"), tot[2], '#b7791f'),
                     (_("Held for Project"), tot[3], '#2f855a'),
                     (_("Value Held"), tot[4], '#6b46c1')],
            'columns': cols, 'rows': rows, 'totals': [_("Total")] + [''] * 3 + tot,
        }

    def _data_expiry(self, domain):
        recs = self.env['er.expiry.report'].sudo().search(domain)
        labels = dict(recs._fields['state'].selection)
        cols = [(_("Product"), 'text'), (_("Lot / Serial"), 'text'), (_("Location"), 'text'),
                (_("Quantity"), 'float'), (_("Expiry Date"), 'date'), (_("Days Left"), 'float'),
                (_("Status"), 'text')]
        rows = [[r.product_id.display_name, r.lot_id.name or '', r.location_id.display_name or '',
                 r.quantity, r.expiration_date.date() if r.expiration_date else False,
                 r.days_left, labels.get(r.state, r.state)] for r in recs]
        count = lambda st: len(recs.filtered(lambda r: r.state == st))
        return {
            'title': _("Expiry Date Report"), 'filters': self._filters_text(),
            'kpis': [(_("Expired"), count('expired'), '#c53030'),
                     (_("Expiring Soon"), count('soon'), '#b7791f'),
                     (_("Valid"), count('ok'), '#2f855a'),
                     (_("Quantity"), sum(r[3] for r in rows), '#2b6cb0')],
            'columns': cols, 'rows': rows,
            'totals': [_("Total"), '', '', sum(r[3] for r in rows), '', '', ''],
        }

    @api.model
    def _fmt_cell(self, value, kind='text'):
        """Text shown in the PDF for one value."""
        if _blank(value):
            return ''
        if kind in ('float', 'money') and isinstance(value, (int, float)):
            return '{:,.2f}'.format(value)
        return str(value)

    @api.model
    def _fmt_kpi(self, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return str(value)
        return ('{:,.2f}'.format(value)).rstrip('0').rstrip('.')

    # ------------------------------------------------------------------
    # Outputs
    # ------------------------------------------------------------------
    def action_view(self):
        """Open the report on screen: chart first, then pivot and list."""
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(REPORT_ACTIONS[self.report_type])
        action['domain'] = self._domain()
        action['context'] = {}
        action['target'] = 'current'
        return action

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref('mo_employee_request.action_report_er_generic').report_action(self)

    def action_export_xlsx(self):
        self.ensure_one()
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_("The Python library 'xlsxwriter' is not installed."))
        data = self._get_report_data()
        buf = io.BytesIO()
        wb = xlsxwriter.Workbook(buf, {'in_memory': True, 'default_date_format': 'yyyy-mm-dd'})
        ws = wb.add_worksheet(str(data['title'])[:31])
        ws.hide_gridlines(2)
        title = wb.add_format({'bold': True, 'font_size': 16, 'font_color': '#1a365d'})
        sub = wb.add_format({'font_color': '#718096', 'italic': True})
        head = wb.add_format({'bold': True, 'font_color': '#ffffff', 'bg_color': '#2c5282',
                              'border': 1, 'border_color': '#1a365d', 'align': 'center',
                              'valign': 'vcenter', 'text_wrap': True})
        base = {'border': 1, 'border_color': '#e2e8f0', 'valign': 'vcenter'}
        zebra = {'bg_color': '#f7fafc'}
        fmts = {}
        for kind, num in (('text', None), ('float', '#,##0.00'), ('money', '#,##0.00'),
                          ('date', 'yyyy-mm-dd')):
            for z in (0, 1):
                f = dict(base, **(zebra if z else {}))
                if num:
                    f['num_format'] = num
                if kind == 'date':
                    f['align'] = 'center'
                fmts[(kind, z)] = wb.add_format(f)
        tot_f = wb.add_format({'bold': True, 'bg_color': '#bee3f8', 'top': 2,
                               'border_color': '#2c5282', 'num_format': '#,##0.00'})
        ncol = len(data['columns'])
        ws.merge_range(0, 0, 0, max(ncol - 1, 1), data['title'], title)
        ws.merge_range(1, 0, 1, max(ncol - 1, 1), data['filters'], sub)
        ws.set_row(0, 24)
        # KPI band: two columns per card
        ws.set_row(3, 30)
        ws.set_row(4, 22)
        col = 0
        for label, value, color in data['kpis']:
            lab = wb.add_format({'font_size': 9, 'font_color': '#ffffff', 'bold': True,
                                 'bg_color': color, 'align': 'center', 'valign': 'vcenter'})
            val = wb.add_format({'font_size': 14, 'bold': True, 'font_color': color,
                                 'align': 'center', 'valign': 'vcenter', 'border': 1,
                                 'border_color': color, 'num_format': '#,##0.##'})
            if col + 1 >= ncol:
                break
            ws.merge_range(3, col, 3, col + 1, label, lab)
            ws.merge_range(4, col, 4, col + 1, value, val)
            col += 2
        hrow = 6
        ws.set_row(hrow, 30)
        for c, (label, _kind) in enumerate(data['columns']):
            ws.write(hrow, c, label, head)
        widths = [len(str(label)) + 4 for label, _k in data['columns']]
        for i, row in enumerate(data['rows']):
            z = i % 2
            for c, value in enumerate(row):
                kind = data['columns'][c][1]
                fmt = fmts[(kind, z)]
                if _blank(value):
                    ws.write_blank(hrow + 1 + i, c, None, fmt)
                elif kind == 'date':
                    ws.write_datetime(hrow + 1 + i, c, fields.Date.to_date(value)
                                      if not hasattr(value, 'year') else value, fmt)
                elif kind in ('float', 'money'):
                    ws.write_number(hrow + 1 + i, c, value, fmt)
                else:
                    ws.write(hrow + 1 + i, c, str(value), fmt)
                widths[c] = min(max(widths[c], len(str(value)) + 2), 45)
        last = hrow + len(data['rows'])
        if data.get('totals') and data['rows']:
            for c, value in enumerate(data['totals']):
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    ws.write_number(last + 1, c, value, tot_f)
                else:
                    ws.write(last + 1, c, value, tot_f)
        for c, w in enumerate(widths):
            ws.set_column(c, c, w)
        ws.freeze_panes(hrow + 1, 0)
        if data['rows']:
            ws.autofilter(hrow, 0, last, ncol - 1)
        ws.set_landscape()
        ws.fit_to_pages(1, 0)
        ws.repeat_rows(hrow)
        wb.close()
        self.write({
            'xlsx_file': base64.b64encode(buf.getvalue()),
            'xlsx_name': "%s.xlsx" % str(data['title']).replace(' ', '_'),
        })
        return {
            'type': 'ir.actions.act_url', 'target': 'self',
            'url': '/web/content/?model=%s&id=%s&field=xlsx_file&filename_field=xlsx_name'
                   '&download=true' % (self._name, self.id),
        }
