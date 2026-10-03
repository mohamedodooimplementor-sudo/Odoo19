# -*- coding: utf-8 -*-
import io

from odoo import http
from odoo.http import request


class BranchSalesDashboardController(http.Controller):

    def _get_data(self, date_from, date_to, branch_id, partner_id, user_id):
        return request.env['branch.sales.report'].get_dashboard_data(
            date_from=date_from or False,
            date_to=date_to or False,
            branch_id=int(branch_id) if branch_id else False,
            partner_id=int(partner_id) if partner_id else False,
            user_id=int(user_id) if user_id else False,
        )

    @http.route('/branch_management/export_xlsx', type='http', auth='user')
    def export_xlsx(self, date_from=None, date_to=None, branch_id=None,
                     partner_id=None, user_id=None, **kwargs):
        import xlsxwriter

        data = self._get_data(date_from, date_to, branch_id, partner_id, user_id)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Branch Sales')
        bold = workbook.add_format({'bold': True})
        money = workbook.add_format({'num_format': '#,##0.00'})

        headers = ['Branch', 'Sales Amount', 'Paid Amount',
                   'Outstanding Amount', 'Orders Count', 'Customers Count']
        for col, header in enumerate(headers):
            sheet.write(0, col, header, bold)
            sheet.set_column(col, col, 20)

        row = 1
        for line in data['lines']:
            sheet.write(row, 0, line['branch_name'])
            sheet.write(row, 1, line['sales_amount'], money)
            sheet.write(row, 2, line['paid_amount'], money)
            sheet.write(row, 3, line['outstanding_amount'], money)
            sheet.write(row, 4, line['orders_count'])
            sheet.write(row, 5, line['customers_count'])
            row += 1

        totals = data['totals']
        sheet.write(row, 0, 'Total', bold)
        sheet.write(row, 1, totals['sales_amount'], bold)
        sheet.write(row, 2, totals['paid_amount'], bold)
        sheet.write(row, 3, totals['outstanding_amount'], bold)
        sheet.write(row, 4, totals['orders_count'], bold)
        sheet.write(row, 5, totals['customers_count'], bold)

        workbook.close()
        output.seek(0)
        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type',
                 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', 'attachment; filename="branch_sales_report.xlsx"'),
            ],
        )

    @http.route('/branch_management/export_pdf', type='http', auth='user')
    def export_pdf(self, date_from=None, date_to=None, branch_id=None,
                    partner_id=None, user_id=None, **kwargs):
        data = self._get_data(date_from, date_to, branch_id, partner_id, user_id)
        report_data = {
            'date_from': date_from,
            'date_to': date_to,
            'lines': data['lines'],
            'totals': data['totals'],
        }
        pdf_content, _content_type = request.env['ir.actions.report']._render_qweb_pdf(
            'branch_management.report_branch_sales_dashboard',
            res_ids=None, data={'dashboard': report_data})
        return request.make_response(
            pdf_content,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', 'attachment; filename="branch_sales_report.pdf"'),
            ],
        )


class BranchPurchaseDashboardController(http.Controller):

    def _get_data(self, date_from, date_to, branch_id, partner_id):
        return request.env['branch.purchase.report'].get_dashboard_data(
            date_from=date_from or False,
            date_to=date_to or False,
            branch_id=int(branch_id) if branch_id else False,
            partner_id=int(partner_id) if partner_id else False,
        )

    @http.route('/branch_management/purchase/export_xlsx', type='http', auth='user')
    def export_xlsx(self, date_from=None, date_to=None, branch_id=None,
                     partner_id=None, **kwargs):
        import xlsxwriter

        data = self._get_data(date_from, date_to, branch_id, partner_id)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Branch Purchases')
        bold = workbook.add_format({'bold': True})
        money = workbook.add_format({'num_format': '#,##0.00'})

        headers = ['Branch', 'Purchase Amount', 'Paid Amount',
                   'Outstanding Amount', 'Orders Count', 'Vendors Count']
        for col, header in enumerate(headers):
            sheet.write(0, col, header, bold)
            sheet.set_column(col, col, 20)

        row = 1
        for line in data['lines']:
            sheet.write(row, 0, line['branch_name'])
            sheet.write(row, 1, line['purchase_amount'], money)
            sheet.write(row, 2, line['paid_amount'], money)
            sheet.write(row, 3, line['outstanding_amount'], money)
            sheet.write(row, 4, line['orders_count'])
            sheet.write(row, 5, line['vendors_count'])
            row += 1

        totals = data['totals']
        sheet.write(row, 0, 'Total', bold)
        sheet.write(row, 1, totals['purchase_amount'], bold)
        sheet.write(row, 2, totals['paid_amount'], bold)
        sheet.write(row, 3, totals['outstanding_amount'], bold)
        sheet.write(row, 4, totals['orders_count'], bold)
        sheet.write(row, 5, totals['vendors_count'], bold)

        workbook.close()
        output.seek(0)
        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type',
                 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', 'attachment; filename="branch_purchase_report.xlsx"'),
            ],
        )

    @http.route('/branch_management/purchase/export_pdf', type='http', auth='user')
    def export_pdf(self, date_from=None, date_to=None, branch_id=None,
                    partner_id=None, **kwargs):
        data = self._get_data(date_from, date_to, branch_id, partner_id)
        report_data = {
            'date_from': date_from,
            'date_to': date_to,
            'lines': data['lines'],
            'totals': data['totals'],
        }
        pdf_content, _content_type = request.env['ir.actions.report']._render_qweb_pdf(
            'branch_management.report_branch_purchase_dashboard',
            res_ids=None, data={'dashboard': report_data})
        return request.make_response(
            pdf_content,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', 'attachment; filename="branch_purchase_report.pdf"'),
            ],
        )


class BranchPaymentDashboardController(http.Controller):

    def _get_data(self, date_from, date_to, branch_id):
        return request.env['branch.payment.report'].get_dashboard_data(
            date_from=date_from or False,
            date_to=date_to or False,
            branch_id=int(branch_id) if branch_id else False,
        )

    @http.route('/branch_management/payment/export_xlsx', type='http', auth='user')
    def export_xlsx(self, date_from=None, date_to=None, branch_id=None, **kwargs):
        import xlsxwriter

        data = self._get_data(date_from, date_to, branch_id)

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Branch Payments')
        bold = workbook.add_format({'bold': True})
        money = workbook.add_format({'num_format': '#,##0.00'})

        headers = ['Branch', 'Received', 'Paid Out', 'Net', 'Payments Count']
        for col, header in enumerate(headers):
            sheet.write(0, col, header, bold)
            sheet.set_column(col, col, 20)

        row = 1
        for line in data['lines']:
            sheet.write(row, 0, line['branch_name'])
            sheet.write(row, 1, line['inbound_amount'], money)
            sheet.write(row, 2, line['outbound_amount'], money)
            sheet.write(row, 3, line['net_amount'], money)
            sheet.write(row, 4, line['payments_count'])
            row += 1

        totals = data['totals']
        sheet.write(row, 0, 'Total', bold)
        sheet.write(row, 1, totals['inbound_amount'], bold)
        sheet.write(row, 2, totals['outbound_amount'], bold)
        sheet.write(row, 3, totals['net_amount'], bold)
        sheet.write(row, 4, totals['payments_count'], bold)

        workbook.close()
        output.seek(0)
        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type',
                 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', 'attachment; filename="branch_payment_report.xlsx"'),
            ],
        )

    @http.route('/branch_management/payment/export_pdf', type='http', auth='user')
    def export_pdf(self, date_from=None, date_to=None, branch_id=None, **kwargs):
        data = self._get_data(date_from, date_to, branch_id)
        report_data = {
            'date_from': date_from,
            'date_to': date_to,
            'lines': data['lines'],
            'totals': data['totals'],
        }
        pdf_content, _content_type = request.env['ir.actions.report']._render_qweb_pdf(
            'branch_management.report_branch_payment_dashboard',
            res_ids=None, data={'dashboard': report_data})
        return request.make_response(
            pdf_content,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Disposition', 'attachment; filename="branch_payment_report.pdf"'),
            ],
        )
