# -*- coding: utf-8 -*-
"""
Shared ReportLab PDF engine for Prime Educational Hub.

Mirrors the mo_stock_card architecture: every printable document in this
module is generated with ReportLab (not wkhtmltopdf/QWeb-PDF), with optional
Arabic shaping + RTL layout when arabic_reshaper / python-bidi are installed
on the server. If those two optional libraries aren't present, Arabic text
is still printed (just without ligature reshaping) rather than failing.
"""
import io
import logging
import os

from odoo import models, fields

from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
)
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.graphics import renderPDF
from reportlab.pdfgen import canvas as pdfcanvas

_logger = logging.getLogger(__name__)

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    ARABIC_SUPPORT = True
except ImportError:
    ARABIC_SUPPORT = False
    _logger.info(
        'arabic_reshaper / python-bidi not installed: Arabic reports will '
        'print unshaped text. Install both packages on the server for '
        'proper Arabic ligatures and RTL shaping.'
    )

HEADER_COLOR = colors.HexColor('#2c3e50')
ACCENT_COLOR = colors.HexColor('#2980b9')
LIGHT_GREY = colors.HexColor('#f4f6f7')

_LOGO_READER = 'unset'  # sentinel: not yet attempted. False = attempted and failed. Else an ImageReader.


def _get_logo_reader():
    """Lazily loads and caches the module logo as a ReportLab ImageReader.
    Deliberately does nothing at import time: locating the module resource
    and decoding the image only happens on first actual use (i.e. the first
    time a PDF is generated), and any failure here must never prevent the
    module's Python code from importing or the server from starting."""
    global _LOGO_READER
    if _LOGO_READER != 'unset':
        return _LOGO_READER or None
    try:
        logo_path = None
        try:
            # Odoo 17+ preferred API
            from odoo.tools.misc import file_path
            logo_path = file_path('prime_educational_hub/static/description/icon.png')
        except Exception:
            try:
                # Older API, kept for backward compatibility (removed in Odoo 19)
                from odoo.modules.module import get_module_resource
                logo_path = get_module_resource(
                    'prime_educational_hub', 'static', 'description', 'icon.png')
            except Exception:
                try:
                    # Last-resort fallback: locate the module folder directly on disk
                    from odoo.modules.module import get_module_path
                    module_dir = get_module_path('prime_educational_hub')
                    if module_dir:
                        candidate = os.path.join(module_dir, 'static', 'description', 'icon.png')
                        logo_path = candidate if os.path.isfile(candidate) else None
                except Exception:
                    logo_path = None
        _LOGO_READER = ImageReader(logo_path) if logo_path else False
    except Exception:  # noqa: BLE001 - a broken/missing logo must never break report generation
        _logger.warning('Prime Educational Hub: could not load module logo for PDF headers.', exc_info=True)
        _LOGO_READER = False
    return _LOGO_READER or None


class EducationReportUtils(models.AbstractModel):
    _name = 'education.report.utils'
    _description = 'Shared ReportLab PDF Engine'

    # ------------------------------------------------------------------
    # Text shaping
    # ------------------------------------------------------------------
    def get_logo_reader(self):
        """Returns the cached ImageReader for the module logo (static/description/icon.png),
        or None if it couldn't be found/loaded. Used to stamp the same brand mark on every
        PDF this module generates, whether through build_simple_report's shared header bar
        or a bespoke canvas layout like the certificate."""
        return _get_logo_reader()

    def shape_text(self, text, lang='en'):
        """Reshape + reorder Arabic text for correct RTL rendering in
        ReportLab (which has no native BiDi/ligature support)."""
        if not text:
            return ''
        text = str(text)
        if lang == 'ar' and ARABIC_SUPPORT:
            reshaped = arabic_reshaper.reshape(text)
            return get_display(reshaped)
        return text

    def get_styles(self, lang='en'):
        styles = getSampleStyleSheet()
        align = TA_RIGHT if lang == 'ar' else TA_LEFT
        styles.add(ParagraphStyle(
            name='EduTitle', fontSize=18, leading=22, textColor=HEADER_COLOR,
            alignment=TA_CENTER, spaceAfter=4,
        ))
        styles.add(ParagraphStyle(
            name='EduSubtitle', fontSize=11, leading=14, textColor=colors.grey,
            alignment=TA_CENTER, spaceAfter=12,
        ))
        styles.add(ParagraphStyle(
            name='EduMeta', fontSize=9, leading=13, alignment=align,
        ))
        styles.add(ParagraphStyle(
            name='EduSectionHead', fontSize=12, leading=16, textColor=ACCENT_COLOR,
            spaceBefore=10, spaceAfter=6, alignment=align,
        ))
        return styles

    # ------------------------------------------------------------------
    # Header / footer (drawn on every page canvas)
    # ------------------------------------------------------------------
    def _make_header_footer(self, company_name, report_title, lang='en'):
        ICP = self.env['ir.config_parameter'].sudo()
        company_name = company_name or ICP.get_param(
            'prime_educational_hub.report_company_name') or self.env.company.name
        footer_text = ICP.get_param('prime_educational_hub.report_footer_text')

        def _draw(canvas, doc):
            canvas.saveState()
            width, height = A4
            canvas.setFillColor(HEADER_COLOR)
            canvas.rect(0, height - 1.6 * cm, width, 1.6 * cm, stroke=0, fill=1)

            logo_size = 1.1 * cm
            logo_margin = 1.5 * cm
            text_margin = 1.5 * cm
            logo_reader = _get_logo_reader()
            if logo_reader is not None:
                logo_y = height - 1.6 * cm + (1.6 * cm - logo_size) / 2.0
                logo_x = width - logo_margin - logo_size if lang == 'ar' else logo_margin
                try:
                    canvas.drawImage(logo_reader, logo_x, logo_y, width=logo_size, height=logo_size,
                                      mask='auto', preserveAspectRatio=True)
                except Exception:  # noqa: BLE001 - never let a logo render issue break the report
                    _logger.warning('Prime Educational Hub: failed drawing logo on PDF header.', exc_info=True)
                else:
                    text_margin = logo_margin + logo_size + 0.35 * cm

            canvas.setFillColor(colors.white)
            canvas.setFont('Helvetica-Bold', 12)
            text = self.shape_text(company_name, lang)
            if lang == 'ar':
                canvas.drawRightString(width - text_margin, height - 1.05 * cm, text)
            else:
                canvas.drawString(text_margin, height - 1.05 * cm, text)

            canvas.setFillColor(colors.HexColor('#95a5a6'))
            canvas.setFont('Helvetica', 8)
            footer_line = footer_text or report_title
            canvas.drawCentredString(width / 2.0, 0.9 * cm, self.shape_text(footer_line, lang))
            canvas.drawRightString(width - 1.5 * cm, 0.9 * cm, 'Page %d' % canvas.getPageNumber())
            canvas.restoreState()
        return _draw

    # ------------------------------------------------------------------
    # Generic tabular report builder — reused by every report in this module
    # ------------------------------------------------------------------
    def build_simple_report(self, title, subtitle, meta_pairs, table_header, table_rows,
                             lang='en', totals=None, company_name=None, extra_tables=None):
        """
        title / subtitle: strings shown at the top of the document.
        meta_pairs: list of (label, value) tuples shown as a compact info block.
        table_header: list of column headers for the main table.
        table_rows: list of row-lists (already formatted strings).
        totals: optional list of (label, value) shown after the main table.
        extra_tables: optional list of (section_title, header, rows) tuples for
                      additional tables after the main one (e.g. payments + refunds).
        Returns: PDF bytes.
        """
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            topMargin=2.2 * cm, bottomMargin=1.6 * cm,
            leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        )
        styles = self.get_styles(lang)
        elements = []

        elements.append(Paragraph(self.shape_text(title, lang), styles['EduTitle']))
        if subtitle:
            elements.append(Paragraph(self.shape_text(subtitle, lang), styles['EduSubtitle']))

        if meta_pairs:
            meta_rows = []
            row = []
            for i, (label, value) in enumerate(meta_pairs):
                cell = Paragraph(
                    '<b>%s:</b> %s' % (self.shape_text(label, lang), self.shape_text(value, lang)),
                    styles['EduMeta']
                )
                row.append(cell)
                if len(row) == 2:
                    meta_rows.append(row)
                    row = []
            if row:
                row.append('')
                meta_rows.append(row)
            meta_table = Table(meta_rows, colWidths=[8.7 * cm, 8.7 * cm])
            meta_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            elements.append(meta_table)
            elements.append(Spacer(1, 10))

        if table_header and table_rows is not None:
            elements.extend(self._build_table(table_header, table_rows, lang, styles))
        elif table_header and not table_rows:
            elements.append(Paragraph(self.shape_text('No records found.', lang), styles['EduMeta']))

        if totals:
            elements.append(Spacer(1, 8))
            totals_rows = [[
                Paragraph('<b>%s</b>' % self.shape_text(label, lang), styles['EduMeta']),
                Paragraph('<b>%s</b>' % self.shape_text(value, lang), styles['EduMeta']),
            ] for label, value in totals]
            totals_table = Table(totals_rows, colWidths=[8.7 * cm, 8.7 * cm])
            totals_table.setStyle(TableStyle([
                ('LINEABOVE', (0, 0), (-1, 0), 0.5, colors.grey),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
            ]))
            elements.append(totals_table)

        for section_title, header, rows in (extra_tables or []):
            elements.append(Spacer(1, 14))
            elements.append(Paragraph(self.shape_text(section_title, lang), styles['EduSectionHead']))
            elements.extend(self._build_table(header, rows, lang, styles))

        header_footer = self._make_header_footer(company_name, title, lang)
        doc.build(elements, onFirstPage=header_footer, onLaterPages=header_footer)
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes

    def _build_table(self, header, rows, lang, styles):
        if not rows:
            return [Paragraph(self.shape_text('No records found.', lang), styles['EduMeta'])]
        shaped_header = [self.shape_text(h, lang) for h in header]
        data = [shaped_header] + [
            [self.shape_text(cell, lang) for cell in row] for row in rows
        ]
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HEADER_COLOR),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, LIGHT_GREY]),
            ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#dcdde1')),
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT' if lang == 'ar' else 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        return [table]

    def get_report_language(self):
        """Reads the module-wide default report language from settings
        (falls back to English). Wired up fully in the Configuration phase."""
        param = self.env['ir.config_parameter'].sudo().get_param(
            'prime_educational_hub.report_language', 'en')
        return param if param in ('en', 'ar') else 'en'

    # ------------------------------------------------------------------
    # QR code drawing (native ReportLab — no external qrcode/PIL dependency)
    # ------------------------------------------------------------------
    def draw_qr_code(self, canvas_obj, value, x, y, size=90):
        """Draws a QR code directly on a ReportLab canvas at (x, y) with the
        given side length, using ReportLab's built-in QR widget (no external
        qrcode/Pillow dependency needed)."""
        if not value:
            return
        qr_widget = QrCodeWidget(value)
        bounds = qr_widget.getBounds()
        qr_width = bounds[2] - bounds[0]
        qr_height = bounds[3] - bounds[1]
        drawing = Drawing(size, size, transform=[size / qr_width, 0, 0, size / qr_height, 0, 0])
        drawing.add(qr_widget)
        renderPDF.draw(drawing, canvas_obj, x, y)

    # ------------------------------------------------------------------
    # ID Card (CR80 credit-card size, front side)
    # ------------------------------------------------------------------
    def build_id_card_pdf(self, name, code, role_label, qr_value, photo_bytes=None,
                           company_name=None, valid_until=None):
        """Builds a single CR80-sized (85.6mm x 54mm) ID card PDF: brand
        header strip, photo, name/code/role, and a QR code linking to the
        person's portal so the card can be scanned to pull up their record.
        Used identically by education.student and education.teacher - only
        the values passed in differ."""
        CARD_W, CARD_H = 85.6 * mm, 54 * mm
        buffer = io.BytesIO()
        c = pdfcanvas.Canvas(buffer, pagesize=(CARD_W, CARD_H))

        # Background
        c.setFillColor(colors.HexColor('#ffffff'))
        c.rect(0, 0, CARD_W, CARD_H, stroke=0, fill=1)

        # Header strip (brand gradient approximated with a flat color band)
        header_h = 14 * mm
        c.setFillColor(colors.HexColor('#4c1470'))
        c.rect(0, CARD_H - header_h, CARD_W, header_h, stroke=0, fill=1)

        logo_reader = self.get_logo_reader()
        if logo_reader is not None:
            logo_size = 9 * mm
            try:
                c.drawImage(logo_reader, 3 * mm, CARD_H - header_h + (header_h - logo_size) / 2,
                            width=logo_size, height=logo_size, mask='auto', preserveAspectRatio=True)
            except Exception:  # noqa: BLE001
                pass

        c.setFillColor(colors.white)
        c.setFont('Helvetica-Bold', 8.5)
        c.drawString(14 * mm, CARD_H - header_h / 2 - 1.5, (company_name or 'Prime Educational Hub')[:28])
        c.setFont('Helvetica', 6.5)
        c.drawRightString(CARD_W - 3 * mm, CARD_H - header_h / 2 - 1.5, role_label.upper())

        # Photo box
        photo_w, photo_h = 20 * mm, 24 * mm
        photo_x, photo_y = 4 * mm, CARD_H - header_h - photo_h - 3 * mm
        c.setStrokeColor(colors.HexColor('#e5e7eb'))
        c.setFillColor(colors.HexColor('#f3f4f6'))
        c.rect(photo_x, photo_y, photo_w, photo_h, stroke=1, fill=1)
        if photo_bytes:
            try:
                photo_reader = ImageReader(io.BytesIO(photo_bytes))
                c.drawImage(photo_reader, photo_x, photo_y, width=photo_w, height=photo_h,
                            preserveAspectRatio=True, anchor='c', mask='auto')
            except Exception:  # noqa: BLE001 - a broken photo must never block card generation
                pass

        # Name / code / validity
        text_x = photo_x + photo_w + 4 * mm
        c.setFillColor(colors.HexColor('#1b1330'))
        c.setFont('Helvetica-Bold', 10)
        c.drawString(text_x, CARD_H - header_h - 7 * mm, self.shape_text(name, 'en')[:26])
        c.setFont('Helvetica', 7.5)
        c.setFillColor(colors.HexColor('#6b6f85'))
        c.drawString(text_x, CARD_H - header_h - 12 * mm, 'ID: %s' % (code or '-'))
        if valid_until:
            c.drawString(text_x, CARD_H - header_h - 16.5 * mm, 'Valid until: %s' % valid_until)

        # QR code (bottom-right)
        qr_size = 16 * mm
        self.draw_qr_code(c, qr_value, CARD_W - qr_size - 3 * mm, 3 * mm, size=qr_size)

        c.showPage()
        c.save()
        return buffer.getvalue()

    # ------------------------------------------------------------------
    # Free-form single-page canvas document (used for decorative documents
    # like Certificates, where a plain table-based layout isn't suitable)
    # ------------------------------------------------------------------
    def new_canvas_document(self, pagesize=A4):
        """Returns (buffer, canvas, width, height) for free-form drawing.
        Caller must call canvas_obj.showPage() + canvas_obj.save() and then
        read buffer.getvalue() to obtain the final PDF bytes."""
        buffer = io.BytesIO()
        width, height = pagesize
        canvas_obj = pdfcanvas.Canvas(buffer, pagesize=pagesize)
        return buffer, canvas_obj, width, height
