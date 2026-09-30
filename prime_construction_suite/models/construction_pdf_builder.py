# -*- coding: utf-8 -*-
"""Shared ReportLab helpers for Prime Construction Suite PDF reports.

All PDF reports in this module are generated directly with ReportLab (no wkhtmltopdf
dependency), the same approach used in the Stock Card module. Each report builds a
"story" (a list of flowables) using the helpers below, which BuildPDF() then renders
to bytes.
"""
import io

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether,
    )
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

# ── Brand palette (matches the app's dark dashboard theme) ──
PRIMARY = colors.HexColor('#4f46e5')
PRIMARY_DARK = colors.HexColor('#312e81')
SUCCESS = colors.HexColor('#059669')
DANGER = colors.HexColor('#dc2626')
WARNING = colors.HexColor('#d97706')
MUTED = colors.HexColor('#64748b')
LIGHT_BG = colors.HexColor('#f1f5f9')
BORDER = colors.HexColor('#cbd5e1')
TEXT_DARK = colors.HexColor('#1e293b')


def require_reportlab():
    if not REPORTLAB_AVAILABLE:
        from odoo.exceptions import UserError
        from odoo import _
        raise UserError(_(
            'The "reportlab" Python library is required to generate PDF reports. '
            'Please ask your administrator to install it on the server (pip install reportlab).'))


def get_styles():
    require_reportlab()
    return {
        'title': ParagraphStyle('title', fontName='Helvetica-Bold', fontSize=20,
                                 textColor=PRIMARY, alignment=TA_CENTER, spaceAfter=4),
        'subtitle': ParagraphStyle('subtitle', fontName='Helvetica', fontSize=12,
                                    textColor=TEXT_DARK, alignment=TA_CENTER, spaceAfter=2),
        'meta': ParagraphStyle('meta', fontName='Helvetica', fontSize=9,
                                textColor=MUTED, alignment=TA_CENTER, spaceAfter=10),
        'h2': ParagraphStyle('h2', fontName='Helvetica-Bold', fontSize=13,
                              textColor=PRIMARY_DARK, spaceBefore=14, spaceAfter=6),
        'normal': ParagraphStyle('normal', fontName='Helvetica', fontSize=9.5,
                                  textColor=TEXT_DARK, leading=13),
        'normal_muted': ParagraphStyle('normal_muted', fontName='Helvetica', fontSize=8.5,
                                        textColor=MUTED, leading=12),
        'cell': ParagraphStyle('cell', fontName='Helvetica', fontSize=8.5,
                                textColor=TEXT_DARK, leading=11),
        'cell_bold': ParagraphStyle('cell_bold', fontName='Helvetica-Bold', fontSize=8.5,
                                     textColor=TEXT_DARK, leading=11),
        'cell_right': ParagraphStyle('cell_right', fontName='Helvetica', fontSize=8.5,
                                      textColor=TEXT_DARK, alignment=TA_RIGHT, leading=11),
        'signature': ParagraphStyle('signature', fontName='Helvetica', fontSize=9,
                                     textColor=TEXT_DARK, alignment=TA_CENTER),
    }


def fmt(value, decimals=0):
    try:
        return '{:,.{}f}'.format(value or 0.0, decimals)
    except (TypeError, ValueError):
        return str(value or '')


def build_pdf_bytes(story, landscape_mode=False, title=''):
    """Render a list of ReportLab flowables to PDF bytes."""
    require_reportlab()
    buf = io.BytesIO()
    pagesize = landscape(A4) if landscape_mode else A4
    doc = SimpleDocTemplate(
        buf, pagesize=pagesize,
        leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=16 * mm,
        title=title or 'Prime Construction Suite Report',
    )

    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(16 * mm, 8 * mm, 'Prime Construction Suite')
        canvas.drawRightString(pagesize[0] - 16 * mm, 8 * mm, 'Page %d' % doc_.page)
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def header_block(title, subtitle='', meta=''):
    styles = get_styles()
    story = [Paragraph(title, styles['title'])]
    if subtitle:
        story.append(Paragraph(subtitle, styles['subtitle']))
    if meta:
        story.append(Paragraph(meta, styles['meta']))
    story.append(Spacer(1, 6))
    return story


def kpi_row(items, col_width=None):
    """items: list of (label, value, color) tuples, rendered as a row of boxed stat cards."""
    styles = get_styles()
    n = len(items)
    cells = []
    for label, value, color in items:
        label_style = ParagraphStyle('kpi_label', fontName='Helvetica-Bold', fontSize=7.5,
                                      textColor=MUTED, alignment=TA_CENTER)
        value_style = ParagraphStyle('kpi_value', fontName='Helvetica-Bold', fontSize=13,
                                      textColor=color or TEXT_DARK, alignment=TA_CENTER)
        cell_content = [Paragraph(label.upper(), label_style), Paragraph(str(value), value_style)]
        cells.append(cell_content)
    width = col_width or (170 * mm / n)
    table = Table([cells], colWidths=[width] * n)
    table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, BORDER),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER),
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
    ]))
    return table


def section_title(text):
    styles = get_styles()
    return Paragraph(text, styles['h2'])


def data_table(headers, rows, col_widths=None, align_right_cols=None):
    """headers: list[str]; rows: list[list[str]] (already formatted strings)."""
    styles = get_styles()
    align_right_cols = align_right_cols or []
    header_cells = [Paragraph(h, ParagraphStyle('th', fontName='Helvetica-Bold', fontSize=8.5,
                                                  textColor=colors.white, alignment=TA_CENTER)) for h in headers]
    table_data = [header_cells]
    for row in rows:
        row_cells = []
        for i, val in enumerate(row):
            style = styles['cell_right'] if i in align_right_cols else styles['cell']
            row_cells.append(Paragraph(str(val), style))
        table_data.append(row_cells)

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    style_cmds = [
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('GRID', (0, 0), (-1, -1), 0.4, BORDER),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_BG]),
    ]
    table.setStyle(TableStyle(style_cmds))
    return table


def signature_block(labels):
    styles = get_styles()
    cells = [[Paragraph(l, styles['signature'])] for l in labels]
    table = Table([[c[0] for c in cells]], colWidths=[170 * mm / len(labels)] * len(labels))
    table.setStyle(TableStyle([
        ('LINEABOVE', (0, 0), (-1, 0), 0.6, TEXT_DARK),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))
    return table
