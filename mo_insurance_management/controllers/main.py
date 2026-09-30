# -*- coding: utf-8 -*-
from odoo import http
from odoo.exceptions import AccessError
from odoo.http import content_disposition, request

from ..report.claim_statement import ClaimStatement
from ..report.document_builder import build_document_pdf

# Records that can be printed with /insurance_management/print/<model>/<id>;
# each of these models implements `_pdf_document_data()`.
PRINTABLE_MODELS = ("insurance.policy", "insurance.authorization")
PRINT_GROUP = "insurance_management.group_insurance_user"

# These PDFs contain personal / insurance data: never cache them in shared
# proxies or browsers, and never let a browser "sniff" them as another type.
_PDF_SECURITY_HEADERS = (
    ("Cache-Control", "no-store, private"),
    ("Pragma", "no-cache"),
    ("X-Content-Type-Options", "nosniff"),
)


class InsuranceClaimStatementController(http.Controller):
    @http.route("/insurance_management/claim_statement/<int:claim_id>", type="http", auth="user")
    def claim_statement(self, claim_id, **kwargs):
        """Claim collection statement, rendered straight with ReportLab and
        sent as a download. It is not an Odoo report action, so it does not
        depend on wkhtmltopdf and does not touch Odoo's own reports."""
        claim = request.env["insurance.claim"].browse(claim_id).exists()
        if not claim:
            return request.not_found()
        claim.check_access("read")
        pdf = ClaimStatement(request.env).render(claim)
        filename = f"Claim Statement - {claim.name}.pdf".replace("/", "-")
        return request.make_response(
            pdf,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Length", str(len(pdf))),
                ("Content-Disposition", content_disposition(filename)),
                *_PDF_SECURITY_HEADERS,
            ],
        )

    @http.route("/insurance_management/print/<string:model>/<int:record_id>", type="http", auth="user")
    def print_document(self, model, record_id, **kwargs):
        """Policy card / authorization form as a ReportLab PDF download."""
        if model not in PRINTABLE_MODELS:
            return request.not_found()
        if not request.env.user.has_group(PRINT_GROUP):
            raise AccessError("Only Insurance users can print policies and authorizations.")
        record = request.env[model].browse(record_id).exists()
        if not record:
            return request.not_found()
        record.check_access("read")
        data = record._pdf_document_data()
        pdf = build_document_pdf(data)
        return request.make_response(
            pdf,
            headers=[
                ("Content-Type", "application/pdf"),
                ("Content-Length", str(len(pdf))),
                ("Content-Disposition", content_disposition(data["filename"])),
                *_PDF_SECURITY_HEADERS,
            ],
        )
