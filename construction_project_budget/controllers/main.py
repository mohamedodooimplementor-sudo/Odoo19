from odoo import http
from odoo.http import request

from ..report.profitability_report_pdf import build_profitability_pdf


class ConstructionProfitabilityReportController(http.Controller):

    @http.route(
        "/construction_project_budget/profitability_report.pdf",
        type="http", auth="user",
    )
    def profitability_report_pdf(self, project_id=None, date_from=None, date_to=None, **kwargs):
        """Serve the Project Profitability Report as a PDF built with
        ReportLab. Kept as a plain controller (rather than an
        ir.actions.report / QWeb template) because QWeb PDF rendering
        depends on wkhtmltopdf being correctly installed on the server,
        which is a common source of printing failures - ReportLab is a
        pure-Python library with no external binary dependency.
        """
        Budget = request.env["construction.project.budget"]
        data = Budget.get_profitability_data(
            project_id=int(project_id) if project_id else None,
            date_from=date_from or None,
            date_to=date_to or None,
        )
        pdf_content = build_profitability_pdf(data)
        filename = "Project Profitability Report.pdf"
        headers = [
            ("Content-Type", "application/pdf"),
            ("Content-Length", len(pdf_content)),
            ("Content-Disposition", 'inline; filename="%s"' % filename),
        ]
        return request.make_response(pdf_content, headers=headers)
