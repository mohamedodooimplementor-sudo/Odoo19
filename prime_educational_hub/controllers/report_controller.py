# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

# Maps a URL-safe report key to (model, method-that-returns-pdf-bytes).
# Student/Group/Payment/Exam reports operate directly on the record id.
# The three wizard-based reports (filters needed) operate on the wizard's own id.
REPORT_METHODS = {
    'student_profile': ('education.student', 'get_profile_report_pdf'),
    'student_academic': ('education.student', 'get_academic_report_pdf'),
    'student_exam_result': ('education.student', 'get_exam_result_report_pdf'),
    'student_attendance': ('education.student', 'get_attendance_report_pdf'),
    'student_financial': ('education.student', 'get_financial_statement_pdf'),
    'payment_receipt': ('education.payment', 'get_receipt_pdf'),
    'group_student_list': ('education.group', 'get_student_list_pdf'),
    'group_financial_summary': ('education.group', 'get_financial_summary_pdf'),
    'group_result': ('education.exam', 'get_group_result_pdf'),
    'certificate': ('education.certificate', 'get_certificate_pdf'),
    'teacher_performance': ('education.teacher', 'get_performance_report_pdf'),
    'group_attendance_sheet': ('education.group.attendance.sheet.wizard', 'get_pdf'),
    'collection_report': ('education.collection.report.wizard', 'get_pdf'),
    'outstanding_fees': ('education.outstanding.fees.report.wizard', 'get_pdf'),
    'aging_report': ('education.aging.report.wizard', 'get_pdf'),
    'report_card': ('education.report.card.wizard', 'get_pdf'),
    'cashier_closing': ('education.cashier.closing.wizard', 'get_pdf'),
    'financial_audit': ('education.financial.audit.wizard', 'get_pdf'),
    'student_id_card': ('education.student', 'get_id_card_pdf'),
    'teacher_id_card': ('education.teacher', 'get_id_card_pdf'),
    'income_statement': ('education.income.statement.wizard', 'get_pdf'),
    'cash_book': ('education.cash.book.wizard', 'get_pdf'),
    'expense_report': ('education.expense.report.wizard', 'get_pdf'),
}

# Excel (.xlsx) exports — currently offered for the two tabular wizard reports.
EXCEL_REPORT_METHODS = {
    'collection_report': ('education.collection.report.wizard', 'get_excel'),
    'outstanding_fees': ('education.outstanding.fees.report.wizard', 'get_excel'),
    'aging_report': ('education.aging.report.wizard', 'get_excel'),
    'financial_audit': ('education.financial.audit.wizard', 'get_excel'),
    'income_statement': ('education.income.statement.wizard', 'get_excel'),
    'cash_book': ('education.cash.book.wizard', 'get_excel'),
    'expense_report': ('education.expense.report.wizard', 'get_excel'),
}


class EducationReportController(http.Controller):

    @http.route(['/education/report/pdf/<string:report_key>/<int:res_id>'],
                type='http', auth='user')
    def print_report(self, report_key, res_id, **kwargs):
        entry = REPORT_METHODS.get(report_key)
        if not entry:
            return request.not_found()
        model_name, method_name = entry
        record = request.env[model_name].browse(res_id).exists()
        if not record:
            return request.not_found()
        pdf_bytes = getattr(record, method_name)()
        filename = '%s_%s.pdf' % (report_key, res_id)
        headers = [
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf_bytes)),
            ('Content-Disposition', 'inline; filename="%s"' % filename),
        ]
        return request.make_response(pdf_bytes, headers=headers)

    @http.route(['/education/report/xlsx/<string:report_key>/<int:res_id>'],
                type='http', auth='user')
    def export_excel(self, report_key, res_id, **kwargs):
        entry = EXCEL_REPORT_METHODS.get(report_key)
        if not entry:
            return request.not_found()
        model_name, method_name = entry
        record = request.env[model_name].browse(res_id).exists()
        if not record:
            return request.not_found()
        xlsx_bytes = getattr(record, method_name)()
        filename = '%s_%s.xlsx' % (report_key, res_id)
        headers = [
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Length', len(xlsx_bytes)),
            ('Content-Disposition', 'attachment; filename="%s"' % filename),
        ]
        return request.make_response(xlsx_bytes, headers=headers)
