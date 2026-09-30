# -*- coding: utf-8 -*-
"""Insurance Claim collection statement, drawn directly with ReportLab.

This is plain Python - it does NOT inherit or override any Odoo model
(in particular not ``ir.actions.report``), so it cannot interfere with
Odoo's own QWeb/wkhtmltopdf reports. It is served by the
``/insurance_management/claim_statement/<id>`` download route
(controllers/main.py, reached from the claim's *Print Statement* button).

Text is drawn with the bundled DejaVu Sans font and run through
``arabic_text.shape`` so Arabic names print connected and in the right
order (plain ReportLab would print them as disconnected, reversed letters).
"""
from io import BytesIO
from xml.sax.saxutils import escape

from .arabic_text import shape
from .report_builders import _fit, _register_fonts, uses_bundled_libs


class ClaimStatement:
    def __init__(self, env):
        self.env = env

    # ------------------------------------------------------------------
    # ReportLab document
    # ------------------------------------------------------------------
    @uses_bundled_libs
    def render(self, claims):
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import PageBreak, SimpleDocTemplate

        font, font_bold = _register_fonts()
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            topMargin=16 * mm,
            bottomMargin=16 * mm,
            leftMargin=16 * mm,
            rightMargin=16 * mm,
            title="Insurance Claim Collection Statement",
        )

        story = []
        for index, claim in enumerate(claims):
            if index:
                story.append(PageBreak())
            story.extend(self._build_claim_story(claim, font, font_bold, colors, mm))
        doc.build(story)
        return buffer.getvalue()

    def _build_claim_story(self, claim, font, font_bold, colors, mm):
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "ClaimTitle", parent=styles["Heading1"], fontName=font_bold, fontSize=18, spaceAfter=2,
            textColor=colors.HexColor("#1E293B"),
        )
        subtitle_style = ParagraphStyle(
            "ClaimSubtitle", parent=styles["Normal"], fontName=font, fontSize=10, textColor=colors.HexColor("#64748B")
        )
        section_style = ParagraphStyle(
            "SectionHeader", parent=styles["Heading3"], fontName=font_bold, fontSize=11, spaceBefore=10,
            spaceAfter=4, textColor=colors.HexColor("#334155"),
        )
        label_style = ParagraphStyle(
            "Label", parent=styles["Normal"], fontName=font, fontSize=9, textColor=colors.HexColor("#64748B")
        )
        value_style = ParagraphStyle(
            "Value", parent=styles["Normal"], fontName=font, fontSize=10, textColor=colors.HexColor("#1E293B")
        )

        def para(text, style):
            return Paragraph(escape(shape(text or "-")), style)

        currency = claim.currency_id.name or ""

        def money(value):
            return f"{value:,.2f}"

        def field(label, value):
            return [para(label, label_style), para(value, value_style)]

        state_label = dict(claim._fields["state"].selection).get(claim.state, claim.state)

        story = [
            para(self.env.company.name, title_style),
            para(f"Insurance Claim Collection Statement - {claim.name}", subtitle_style),
            Spacer(1, 10 * mm),
        ]

        header_table = Table(
            [
                field("Insurance Company", claim.insurance_company_id.display_name)
                + field("Status", state_label),
                field("Period", f"{claim.date_from} to {claim.date_to}")
                + field("Customer Filter", claim.partner_id.display_name if claim.partner_id else "All Customers"),
                field("Plan Filter", claim.insurance_plan_id.display_name if claim.insurance_plan_id else "All Plans")
                + field("Payment Journal", claim.journal_id.display_name),
            ],
            colWidths=[34 * mm, 58 * mm, 34 * mm, 48 * mm],
            hAlign="LEFT",
        )
        header_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
                ]
            )
        )
        story += [header_table, Spacer(1, 8 * mm)]

        # ---- included invoices --------------------------------------
        story.append(para(f"Included Invoices (amounts in {currency})", section_style))
        widths = [26 * mm, 32 * mm, 20 * mm, 32 * mm, 22 * mm, 22 * mm, 20 * mm]
        pad = 3
        size = 8

        def cell(text, index, bold=False):
            return _fit(text, font_bold if bold else font, size, widths[index] - 2 * pad)

        header = ["Invoice", "Customer", "Plan", "Insurance Share", "Paid", "Rejected", "Residual"]
        rows = [[cell(label, i, bold=True) for i, label in enumerate(header)]]
        included = claim._lines_oldest_first()
        for line in included:
            rejected = line.rejected_amount if line.rejection_move_id else 0.0
            rows.append(
                [
                    cell(line.move_id.name or "-", 0),
                    cell(line.partner_id.display_name or "-", 1),
                    cell(line.insurance_plan_id.display_name or "-", 2),
                    money(line.amount_due - line.credit_note_amount),
                    money(line.paid_amount),
                    money(rejected),
                    money(line.residual),
                ]
            )
        if not included:
            rows.append(["-"] * 7)

        lines_table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
        lines_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font),
                    ("FONTNAME", (0, 0), (-1, 0), font_bold),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), size),
                    ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
                    ("ALIGN", (0, 0), (2, -1), "LEFT"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
                    ("LEFTPADDING", (0, 0), (-1, -1), pad),
                    ("RIGHTPADDING", (0, 0), (-1, -1), pad),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        story += [lines_table, Spacer(1, 8 * mm)]

        # ---- summary --------------------------------------------------
        story.append(para("Summary", section_style))
        summary_rows = [
            ["Invoices Included", str(claim.invoice_count)],
            ["Total Claimed", money(claim.total_claimed)],
        ]
        if claim.total_rejected:
            summary_rows.append(["Total Rejected", money(claim.total_rejected)])
        summary_rows += [
            ["Total Paid", money(claim.total_paid)],
            ["Remaining Balance", money(claim.remaining_balance)],
        ]
        summary_table = Table(summary_rows, colWidths=[80 * mm, 40 * mm], hAlign="LEFT")
        summary_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.HexColor("#E2E8F0")),
                    ("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.HexColor("#334155")),
                    ("FONTNAME", (0, -1), (-1, -1), font_bold),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(summary_table)

        # ---- payments -------------------------------------------------
        payments = claim.payment_ids.filtered(lambda p: p.state in ("in_process", "paid"))
        if payments:
            story.append(para("Payments", section_style))
            payment_rows = []
            for payment in payments.sorted(lambda p: (p.date or claim.date_from, p.id)):
                date_str = payment.date and payment.date.strftime("%Y-%m-%d") or "-"
                payment_rows.append(
                    [_fit(f"{payment.name or '-'}  ({date_str})", font, 9, 76 * mm), money(payment.amount)]
                )
            payments_table = Table(payment_rows, colWidths=[80 * mm, 40 * mm], hAlign="LEFT")
            payments_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), font),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story.append(payments_table)

        return story
