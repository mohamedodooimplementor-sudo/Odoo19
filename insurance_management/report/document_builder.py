# -*- coding: utf-8 -*-
"""Small generic PDF "document" builder (policy card, authorization form...).

Plain Python, no Odoo imports: the models hand over a dict and get PDF bytes.

    doc = {
        "company":   "My Clinic",
        "title":     "Insurance Policy",
        "subtitle":  "POL-0001",
        "status":    ("Active", "#16A34A"),          # optional coloured badge
        "currency":  "EGP",
        "generated": "2026-09-21 10:00",
        "user":      "Mohamed",
        "sections":  [{"title": "Customer", "rows": [("Name", "Ahmed"), ...]}],
        "table":     {"title": "Recent orders",
                      "columns": [{"label": "Order", "kind": "text", "width": 30}, ...],
                      "rows": [["S0001", ...], ...]},                 # optional
        "texts":     [("Notes", "free text, may be multi-line / Arabic")],
        "signatures": ["Requested by", "Approved by"],                # optional
    }

Arabic text is shaped with ``arabic_text.shape`` and drawn with the bundled
DejaVu Sans font, exactly like the other reports of this module.
"""
from io import BytesIO
from xml.sax.saxutils import escape

from .arabic_text import _is_arabic, shape
from .report_builders import LIGHT, LINE, MUTED, NAVY, SLATE, _fit, _register_fonts, uses_bundled_libs


def _wrap(text, font, size, max_width):
    """Greedy word wrap in *logical* order; each returned line is shaped
    separately afterwards, so Arabic lines break at the right place."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    lines = []
    for paragraph in str(text or "").splitlines() or [""]:
        current = ""
        for word in paragraph.split():
            candidate = f"{current} {word}".strip()
            if current and stringWidth(shape(candidate), font, size) > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        lines.append(current)
    return lines


def _is_rtl(text):
    for char in str(text or ""):
        if char.isalpha():
            return _is_arabic(char)
    return False


@uses_bundled_libs
def build_document_pdf(doc):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font, font_bold = _register_fonts()
    left = right = 16 * mm
    usable = A4[0] - left - right
    pad = 3

    def para(text, size=10, bold=False, color=NAVY, align=TA_LEFT):
        style = ParagraphStyle(
            "p", fontName=font_bold if bold else font, fontSize=size, leading=size * 1.35,
            textColor=colors.HexColor(color), alignment=align,
        )
        return Paragraph(escape(shape(str(text if text not in (None, False) else "-"))), style)

    story = []

    # ---- title block --------------------------------------------------
    status = doc.get("status")
    left_cell = [
        para(doc["company"], 17, True),
        para(doc["title"], 11, False, MUTED),
    ]
    right_cell = [para(doc.get("subtitle") or "", 13, True, NAVY, TA_RIGHT)]
    if status:
        right_cell.append(para(status[0], 10, True, status[1], TA_RIGHT))
    head = Table([[left_cell, right_cell]], colWidths=[usable * 0.62, usable * 0.38])
    head.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.HexColor(NAVY)),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story += [head, Spacer(1, 6 * mm)]

    # ---- key / value sections (two pairs per row) ------------------------
    label_w, value_w = 38 * mm, usable / 2 - 38 * mm
    for section in doc.get("sections", []):
        rows = [
            (label, value) for label, value in section["rows"] if value not in (None, False, "")
        ] or [("-", "-")]
        table_rows = []
        for index in range(0, len(rows), 2):
            pair = rows[index : index + 2]
            cells = []
            for label, value in pair:
                cells += [
                    _fit(label, font, 8, label_w - 2 * pad),
                    _fit(str(value), font_bold, 9, value_w - 2 * pad),
                ]
            while len(cells) < 4:
                cells.append("")
            table_rows.append(cells)
        grid = Table(table_rows, colWidths=[label_w, value_w, label_w, value_w])
        grid.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor(MUTED)),
                    ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor(MUTED)),
                    ("FONTNAME", (1, 0), (1, -1), font_bold),
                    ("FONTNAME", (3, 0), (3, -1), font_bold),
                    ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor(NAVY)),
                    ("TEXTCOLOR", (3, 0), (3, -1), colors.HexColor(NAVY)),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LEFTPADDING", (0, 0), (-1, -1), pad),
                    ("RIGHTPADDING", (0, 0), (-1, -1), pad),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor(LINE)),
                ]
            )
        )
        story.append(KeepTogether([para(section["title"], 11, True, SLATE), Spacer(1, 2 * mm), grid]))
        story.append(Spacer(1, 5 * mm))

    # ---- optional table ----------------------------------------------------
    table = doc.get("table")
    if table:
        columns = table["columns"]
        total = sum(c["width"] for c in columns)
        widths = [usable * c["width"] / total for c in columns]
        data = [[_fit(c["label"], font_bold, 8, widths[i] - 2 * pad) for i, c in enumerate(columns)]]
        for row in table["rows"]:
            data.append([_fit(value, font, 8, widths[i] - 2 * pad) for i, value in enumerate(row)])
        if not table["rows"]:
            data.append([_fit(table.get("empty", "No records"), font, 8, usable)] + [""] * (len(columns) - 1))
        grid = Table(data, colWidths=widths, repeatRows=1)
        style = [
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("FONTNAME", (0, 0), (-1, 0), font_bold),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor(LINE)),
            ("LEFTPADDING", (0, 0), (-1, -1), pad),
            ("RIGHTPADDING", (0, 0), (-1, -1), pad),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        for i, c in enumerate(columns):
            if c.get("kind") in ("money", "qty", "int"):
                style.append(("ALIGN", (i, 0), (i, -1), "RIGHT"))
        if not table["rows"]:
            style.append(("SPAN", (0, 1), (-1, 1)))
        grid.setStyle(TableStyle(style))
        story += [para(table["title"], 11, True, SLATE), Spacer(1, 2 * mm), grid, Spacer(1, 5 * mm)]

    # ---- free text blocks (wrapped per logical line, Arabic-safe) ---------
    for title, text in doc.get("texts", []):
        if not text:
            continue
        block = [para(title, 11, True, SLATE), Spacer(1, 1.5 * mm)]
        for line in _wrap(text, font, 9, usable - 2 * pad):
            block.append(para(line or " ", 9, False, NAVY, TA_RIGHT if _is_rtl(line) else TA_LEFT))
        story += [KeepTogether(block), Spacer(1, 5 * mm)]

    # ---- signatures -----------------------------------------------------------
    signatures = doc.get("signatures")
    if signatures:
        story.append(Spacer(1, 10 * mm))
        width = usable / len(signatures)
        sign = Table(
            [[para(name, 8, False, MUTED) for name in signatures]],
            colWidths=[width] * len(signatures),
            rowHeights=[10 * mm],
        )
        sign.setStyle(
            TableStyle(
                [
                    ("LINEABOVE", (0, 0), (-1, 0), 0.6, colors.HexColor(SLATE)),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 18),
                ]
            )
        )
        story.append(sign)

    def footer(canvas, page_doc):
        canvas.saveState()
        canvas.setFont(font, 7)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(left, 8 * mm, shape(f"{doc['company']}  |  {doc.get('generated', '')}  |  {doc.get('user', '')}"))
        canvas.drawRightString(A4[0] - right, 8 * mm, f"Page {page_doc.page}")
        canvas.restoreState()

    buffer = BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=left,
        rightMargin=right,
        topMargin=14 * mm,
        bottomMargin=16 * mm,
        title=f"{doc['title']} {doc.get('subtitle') or ''}".strip(),
        author=doc.get("user") or "",
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
