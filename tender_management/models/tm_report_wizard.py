# -*- coding: utf-8 -*-
import base64
import io

from odoo import _, fields, models
from odoo.exceptions import UserError


class TmTenderReportWizard(models.TransientModel):
    _name = 'tm.tender.report.wizard'
    _description = 'Tenders Report'

    date_from = fields.Date('From')
    date_to = fields.Date('To')
    state = fields.Selection([
        ('all', 'All'),
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('quotation', 'Quotation'),
        ('won', 'Won'),
        ('delivered', 'Delivered'),
        ('invoiced', 'Invoiced'),
        ('paid', 'Paid'),
        ('lost', 'Lost'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='all', required=True)
    partner_ids = fields.Many2many('res.partner', string='Customers')

    def _get_tenders(self):
        self.ensure_one()
        domain = []
        if self.date_from:
            domain.append(('tender_date', '>=', self.date_from))
        if self.date_to:
            domain.append(('tender_date', '<=', self.date_to))
        if self.state != 'all':
            domain.append(('state', '=', self.state))
        if self.partner_ids:
            domain.append(('partner_id', 'in', self.partner_ids.ids))
        tenders = self.env['tm.tender'].search(domain, order='tender_date, id')
        if not tenders:
            raise UserError(_('No tenders match the selected filters.'))
        return tenders

    def action_print_pdf(self):
        tenders = self._get_tenders()
        return self.env.ref('tender_management.action_report_tender_summary').report_action(tenders)

    def action_export_xlsx(self):
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_('The Python library xlsxwriter is not installed on the server.'))
        tenders = self._get_tenders()
        labels = dict(self.env['tm.tender']._fields['state'].selection)
        output = io.BytesIO()
        book = xlsxwriter.Workbook(output, {'in_memory': True})
        head = book.add_format({'bold': True, 'font_color': '#FFFFFF', 'bg_color': '#1E3A5F',
                                'border': 1, 'align': 'center', 'valign': 'vcenter', 'text_wrap': True})
        text = book.add_format({'border': 1})
        money = book.add_format({'border': 1, 'num_format': '#,##0.00'})
        pct = book.add_format({'border': 1, 'num_format': '0.00"%"'})
        bold_money = book.add_format({'border': 1, 'bold': True, 'num_format': '#,##0.00', 'bg_color': '#E8EDF3'})
        bold = book.add_format({'border': 1, 'bold': True, 'bg_color': '#E8EDF3'})

        sheet = book.add_worksheet('Tenders')
        titles = ['Number', 'Customer', 'Date', 'Deadline', 'Status', 'Delivery', 'Invoicing',
                  'Total Sale', 'BOM Costs', 'Additional Costs', 'Total Cost', 'Profit', 'Margin %']
        for col, title in enumerate(titles):
            sheet.write(0, col, title, head)
        delivery_labels = dict(self.env['tm.tender']._fields['delivery_status'].selection)
        invoicing_labels = dict(self.env['tm.tender']._fields['invoicing_status'].selection)
        amount_fields = ('amount_sale', 'amount_bom_cost', 'amount_extra_cost', 'amount_total_cost', 'profit')
        for row, t in enumerate(tenders, start=1):
            sheet.write(row, 0, t.name, text)
            sheet.write(row, 1, t.partner_id.display_name, text)
            sheet.write(row, 2, str(t.tender_date or ''), text)
            sheet.write(row, 3, str(t.deadline or ''), text)
            sheet.write(row, 4, labels.get(t.state, t.state), text)
            sheet.write(row, 5, delivery_labels.get(t.delivery_status, ''), text)
            sheet.write(row, 6, invoicing_labels.get(t.invoicing_status, ''), text)
            for col, name in enumerate(amount_fields, start=7):
                sheet.write(row, col, t[name], money)
            sheet.write(row, 12, t.margin_percent, pct)
        last = len(tenders) + 1
        sheet.write(last, 0, 'Total', bold)
        for col in range(1, 7):
            sheet.write(last, col, '', bold)
        for col, name in enumerate(amount_fields, start=7):
            letter = chr(ord('A') + col)
            sheet.write_formula(last, col, '=SUM(%s2:%s%d)' % (letter, letter, last), bold_money,
                                sum(tenders.mapped(name)))
        sheet.write(last, 12, '', bold)
        sheet.set_column(0, 0, 16)
        sheet.set_column(1, 1, 30)
        sheet.set_column(2, 6, 15)
        sheet.set_column(7, 12, 16)
        sheet.freeze_panes(1, 0)
        sheet.autofilter(0, 0, last - 1, 12)

        lines = book.add_worksheet('Products')
        titles = ['Tender', 'Customer', 'Product', 'Qty', 'UoM', 'BOM', 'Materials / Unit',
                  'Labour / Unit', 'Overhead / Unit', 'Other / Unit', 'BOM Cost / Unit',
                  'Total BOM Cost', 'Sale Price', 'Total Sale', 'Profit', 'Margin %']
        for col, title in enumerate(titles):
            lines.write(0, col, title, head)
        row = 1
        for t in tenders:
            for line in t.line_ids:
                lines.write(row, 0, t.name, text)
                lines.write(row, 1, t.partner_id.display_name, text)
                lines.write(row, 2, line.product_id.display_name, text)
                lines.write(row, 3, line.quantity, money)
                lines.write(row, 4, line.uom_id.name or '', text)
                lines.write(row, 5, line.bom_id.display_name or '', text)
                for col, value in enumerate((
                        line.material_cost_unit, line.labour_cost_unit, line.overhead_cost_unit,
                        line.other_cost_unit, line.bom_cost_unit, line.total_bom_cost,
                        line.price_unit, line.total_price, line.profit), start=6):
                    lines.write(row, col, value, money)
                lines.write(row, 15, line.margin_percent, pct)
                row += 1
        lines.set_column(0, 1, 22)
        lines.set_column(2, 2, 30)
        lines.set_column(3, 15, 15)
        lines.freeze_panes(1, 0)
        book.close()

        attachment = self.env['ir.attachment'].create({
            'name': 'Tenders_Report.xlsx',
            'datas': base64.b64encode(output.getvalue()),
            'type': 'binary',
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }
