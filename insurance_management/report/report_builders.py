# -*- coding: utf-8 -*-
"""PDF (ReportLab) and Excel (XlsxWriter) builders for the insurance reports.

Everything in here is plain Python: the wizard collects the records into
simple dicts/lists and hands them over, so these functions know nothing
about the ORM and can be run and tested on their own.

A report is described by:

    data = {
        "title":      "Insurance Claims Report",
        "company":    "My Company",
        "currency":   "EGP",
        "generated":  "2026-09-20 14:05",
        "user":       "Mohamed",
        "filters":    [("Period", "2026-01-01 to 2026-01-31"), ...],
        "rtl":        False,                 # mirror Excel sheets for RTL languages
        "group_by":   "company",             # key used for PDF sections + subtotals
        "columns":    [column, ...],         # see COLUMN below
        "rows":       [{key: value, ...}],
        "sheets":     [{"name", "columns", "rows"}, ...]   # extra Excel sheets
    }

    column = {"key", "label", "kind": text|int|qty|money|pct,
              "width": PDF width in mm, "sum": bool (adds a total),
              "pdf": False (skip in PDF), "xlsx": False (skip in Excel)}
"""
import os
from io import BytesIO

from .arabic_text import shape
try:
    from .._libs import uses_bundled_libs
except ImportError:  # loaded outside the Odoo package (standalone tests): nothing to wrap

    def uses_bundled_libs(func):
        return func

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "fonts")

NAVY = "#1E293B"
SLATE = "#334155"
MUTED = "#64748B"
LIGHT = "#F1F5F9"
LINE = "#E2E8F0"


# ----------------------------------------------------------------------
# formatting helpers
# ----------------------------------------------------------------------
def _fmt(value, kind, blank_zero=False):
    # NB: `0 in (None, False, "")` is True in Python - test identity, so a real
    # zero amount is printed as 0.00 instead of being blanked out.
    if value is None or value is False or value == "":
        return ""
    if blank_zero and not value:
        return ""
    if kind == "money":
        return f"{value:,.2f}"
    if kind == "qty":
        text = f"{value:,.2f}".rstrip("0").rstrip(".")
        return text or "0"
    if kind == "int":
        return f"{int(value):,}"
    if kind == "pct":
        return f"{value:.1f}%"
    return str(value)


def _is_number_kind(kind):
    return kind in ("money", "qty", "int", "pct")


def _totals(rows, columns):
    totals = {}
    for col in columns:
        if col.get("sum"):
            totals[col["key"]] = sum((row.get(col["key"]) or 0.0) for row in rows)
    return totals


# ----------------------------------------------------------------------
# PDF
# ----------------------------------------------------------------------
def _register_fonts():
    """Register DejaVu Sans (has Arabic glyphs). Falls back to Helvetica."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    regular = os.path.join(FONT_DIR, "DejaVuSans.ttf")
    bold = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")
    if os.path.exists(regular) and os.path.exists(bold):
        registered = pdfmetrics.getRegisteredFontNames()
        if "IMDejaVu" not in registered:
            pdfmetrics.registerFont(TTFont("IMDejaVu", regular))
        if "IMDejaVu-Bold" not in registered:
            pdfmetrics.registerFont(TTFont("IMDejaVu-Bold", bold))
        return "IMDejaVu", "IMDejaVu-Bold"
    return "Helvetica", "Helvetica-Bold"


def _fit(text, font, size, max_width):
    """Shape (Arabic) and truncate with an ellipsis so it fits the column."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    text = "" if text is None else str(text)
    if stringWidth(shape(text), font, size) <= max_width:
        return shape(text)
    while text and stringWidth(shape(text + "…"), font, size) > max_width:
        text = text[:-1]
    return shape(text + "…")


@uses_bundled_libs
def build_pdf(data):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Spacer, Table, TableStyle
    from reportlab.platypus.flowables import Flowable

    font, font_bold = _register_fonts()
    columns = [c for c in data["columns"] if c.get("pdf", True)]
    rows = data["rows"]
    group_by = data.get("group_by")
    pad = 2 * mm  # horizontal cell padding

    page = landscape(A4)
    left = right = 10 * mm
    usable = page[0] - left - right
    body_size, head_size = 8, 8

    from reportlab.pdfbase.pdfmetrics import stringWidth

    def shown(col, value):
        return _fmt(value, col["kind"], col.get("blank_zero")) if _is_number_kind(col["kind"]) else shape(str(value or ""))

    # Column widths: start from the declared proportions, but never wider
    # than the content needs and never narrower than the header label, then
    # stretch/shrink the result to exactly the printable width.
    declared_total = sum(c["width"] for c in columns) * mm
    declared_scale = usable / declared_total if declared_total else 1.0
    minimum, natural = [], []
    totals_all = _totals(rows, columns)
    for c in columns:
        header_w = stringWidth(c["label"], font_bold, head_size) + 2 * pad + 1 * mm
        content_w = max(
            [stringWidth(shown(c, r.get(c["key"])), font, body_size) for r in rows]
            + [stringWidth(_fmt(totals_all.get(c["key"]), c["kind"], c.get("blank_zero")), font_bold, body_size)],
            default=0,
        ) + 2 * pad + 1 * mm
        wanted = c["width"] * mm * declared_scale
        minimum.append(header_w)
        natural.append(max(header_w, min(wanted, content_w)))
    grand = sum(natural)
    if grand <= usable:
        widths = [w * usable / grand for w in natural]
    else:
        widths = list(natural)
        overflow = grand - usable
        shrinkable = [i for i, c in enumerate(columns) if not _is_number_kind(c["kind"])]
        room = sum(widths[i] - minimum[i] for i in shrinkable)
        if room > 0:
            ratio = min(1.0, overflow / room)
            for i in shrinkable:
                widths[i] -= (widths[i] - minimum[i]) * ratio
        # still too wide (very many numeric columns): scale everything down
        current = sum(widths)
        if current > usable:
            widths = [w * usable / current for w in widths]

    def cell(text, col_index, bold=False):
        width = widths[col_index] - 2 * pad
        return _fit(text, font_bold if bold else font, body_size, width)

    def money_row(values_by_key, label=None):
        out = []
        for idx, col in enumerate(columns):
            key = col["key"]
            if idx == 0 and label is not None:
                out.append(cell(label, idx, bold=True))
            elif key in values_by_key:
                out.append(_fmt(values_by_key[key], col["kind"], col.get("blank_zero")))
            else:
                out.append("")
        return out

    table_rows = [[_fit(c["label"], font_bold, head_size, widths[i] - 2 * pad) for i, c in enumerate(columns)]]
    style = [
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), body_size),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), font_bold),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), pad),
        ("RIGHTPADDING", (0, 0), (-1, -1), pad),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor(LINE)),
    ]
    for idx, col in enumerate(columns):
        if _is_number_kind(col["kind"]):
            style.append(("ALIGN", (idx, 0), (idx, -1), "RIGHT"))

    # The label of a total row spans every text column in front of the
    # first number column, so "Grand Total" is never cut by a narrow column.
    first_number = next((i for i, c in enumerate(columns) if _is_number_kind(c["kind"])), len(columns))

    def add_total_row(values, label, background):
        row_index = len(table_rows)
        table_rows.append(money_row(values, label=label))
        if first_number > 1:
            style.append(("SPAN", (0, row_index), (first_number - 1, row_index)))
        style.extend(
            [
                ("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor(background)),
                ("FONTNAME", (0, row_index), (-1, row_index), font_bold),
                ("LINEABOVE", (0, row_index), (-1, row_index), 0.6, colors.HexColor(SLATE)),
            ]
        )

    if group_by:
        groups = []
        for row in rows:
            name = row.get(group_by) or "-"
            if not groups or groups[-1][0] != name:
                groups.append((name, []))
            groups[-1][1].append(row)
    else:
        groups = [(None, rows)]

    for name, group_rows in groups:
        if name is not None:
            row_index = len(table_rows)
            table_rows.append(
                [_fit(name, font_bold, body_size, usable - 2 * pad)] + [""] * (len(columns) - 1)
            )
            style.extend(
                [
                    ("SPAN", (0, row_index), (-1, row_index)),
                    ("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor(LIGHT)),
                    ("FONTNAME", (0, row_index), (-1, row_index), font_bold),
                ]
            )
        for row in group_rows:
            line = []
            for idx, col in enumerate(columns):
                value = row.get(col["key"])
                if _is_number_kind(col["kind"]):
                    line.append(_fmt(value, col["kind"], col.get("blank_zero")))
                else:
                    line.append(cell(value, idx))
            table_rows.append(line)
        if name is not None and len(groups) > 1 and any(c.get("sum") for c in columns):
            add_total_row(_totals(group_rows, columns), "Subtotal", "#F8FAFC")

    if not rows:
        row_index = len(table_rows)
        table_rows.append([cell("No records match the selected filters.", 0)] + [""] * (len(columns) - 1))
        style.append(("SPAN", (0, row_index), (-1, row_index)))
    elif any(c.get("sum") for c in columns):
        add_total_row(_totals(rows, columns), "Grand Total", "#E2E8F0")

    table = Table(table_rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle(style))

    class _Header(Flowable):
        """Company name, report title and the applied filters."""

        def __init__(self):
            super().__init__()
            self.width = usable
            self.line_height = 4.6 * mm
            self.height = (14 + 4.4 * len(data.get("filters", []))) * mm

        def wrap(self, avail_w, avail_h):
            return self.width, self.height

        def draw(self):
            c = self.canv
            y = self.height - 6 * mm
            c.setFillColor(colors.HexColor(NAVY))
            c.setFont(font_bold, 15)
            c.drawString(0, y, shape(data["company"]))
            y -= 6 * mm
            c.setFillColor(colors.HexColor(MUTED))
            c.setFont(font, 10)
            c.drawString(0, y, shape(data["title"]))
            c.drawRightString(self.width, y, f"Amounts in {data['currency']}")
            y -= 6 * mm
            c.setFont(font, 8)
            for label, value in data.get("filters", []):
                c.setFillColor(colors.HexColor(MUTED))
                c.drawString(0, y, label)
                c.setFillColor(colors.HexColor(NAVY))
                c.drawString(38 * mm, y, shape(value))
                y -= self.line_height

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 7)
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.drawString(left, 6 * mm, shape(f"{data['company']}  |  {data['generated']}  |  {data['user']}"))
        canvas.drawRightString(page[0] - right, 6 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page,
        leftMargin=left,
        rightMargin=right,
        topMargin=10 * mm,
        bottomMargin=14 * mm,
        title=data["title"],
        author=data.get("user") or "",
    )
    doc.build([_Header(), Spacer(1, 3 * mm), table], onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


# ----------------------------------------------------------------------
# Excel
# ----------------------------------------------------------------------
def _col_letter(index):
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _safe_sheet_name(name, used):
    for bad in "[]:*?/\\":
        name = name.replace(bad, " ")
    name = name.strip()[:31] or "Sheet"
    base, counter = name, 2
    while name.lower() in used:
        suffix = f" {counter}"
        name = base[: 31 - len(suffix)] + suffix
        counter += 1
    used.add(name.lower())
    return name


@uses_bundled_libs
def build_xlsx(data):
    import xlsxwriter

    buffer = BytesIO()
    # Data in these sheets comes from user-editable records (customer / product
    # names, memos, rejection reasons...). XlsxWriter's generic write() turns a
    # string that starts with "=" into a live formula and one that looks like a
    # URL into a hyperlink - a classic spreadsheet-injection hole (e.g. a
    # customer named =HYPERLINK(...) or a DDE payload). Everything textual is
    # therefore written with write_string(), and the automatic conversions are
    # switched off as a second line of defence.
    workbook = xlsxwriter.Workbook(
        buffer,
        {
            "in_memory": True,
            "strings_to_formulas": False,
            "strings_to_urls": False,
            "strings_to_numbers": False,
        },
    )
    workbook.set_properties({"title": data["title"], "author": data.get("user") or "", "company": data["company"]})

    base = {"font_name": "Calibri", "font_size": 10, "valign": "vcenter"}
    f_company = workbook.add_format({**base, "bold": True, "font_size": 14, "font_color": NAVY})
    f_title = workbook.add_format({**base, "font_size": 11, "font_color": MUTED})
    f_flabel = workbook.add_format({**base, "font_color": MUTED})
    f_fvalue = workbook.add_format({**base, "font_color": NAVY})
    f_head = workbook.add_format(
        {**base, "bold": True, "font_color": "#FFFFFF", "bg_color": NAVY, "border": 1, "border_color": LINE,
         "text_wrap": True, "align": "center"}
    )
    cell_fmt = {
        "text": workbook.add_format({**base, "border": 1, "border_color": LINE}),
        "int": workbook.add_format({**base, "border": 1, "border_color": LINE, "num_format": "#,##0"}),
        "qty": workbook.add_format({**base, "border": 1, "border_color": LINE, "num_format": "#,##0.##"}),
        "money": workbook.add_format({**base, "border": 1, "border_color": LINE, "num_format": "#,##0.00"}),
        "pct": workbook.add_format({**base, "border": 1, "border_color": LINE, "num_format": "0.0%"}),
    }
    total_fmt = {
        kind: workbook.add_format(
            {**base, "bold": True, "bg_color": LIGHT, "top": 2, "border_color": SLATE,
             "num_format": {"int": "#,##0", "qty": "#,##0.##", "money": "#,##0.00", "pct": "0.0%", "text": "@"}[kind]}
        )
        for kind in cell_fmt
    }

    sheets = [{"name": data.get("sheet_name", "Report"), "columns": data["columns"], "rows": data["rows"]}]
    sheets += data.get("sheets", [])
    used_names = set()

    for spec in sheets:
        columns = [c for c in spec["columns"] if c.get("xlsx", True)]
        rows = spec["rows"]
        sheet = workbook.add_worksheet(_safe_sheet_name(spec["name"], used_names))
        if data.get("rtl"):
            sheet.right_to_left()
        sheet.hide_gridlines(2)

        row = 0
        sheet.write_string(row, 0, str(data["company"]), f_company)
        row += 1
        sheet.write_string(
            row, 0, f"{data['title']}  -  {spec['name']}  (amounts in {data['currency']})", f_title
        )
        row += 1
        for label, value in data.get("filters", []):
            sheet.write_string(row, 0, str(label), f_flabel)
            sheet.write_string(row, 1, str(value), f_fvalue)
            row += 1
        row += 1

        header_row = row
        widths = []
        for idx, col in enumerate(columns):
            sheet.write_string(header_row, idx, str(col["label"]), f_head)
            widths.append(len(col["label"]) + 2)
        sheet.set_row(header_row, 28)

        first_data = header_row + 1
        for r_idx, item in enumerate(rows):
            excel_row = first_data + r_idx
            for idx, col in enumerate(columns):
                value = item.get(col["key"])
                kind = col["kind"]
                if value is None or value is False:
                    value = 0 if _is_number_kind(kind) else ""
                elif kind == "pct":
                    value = value / 100.0
                if _is_number_kind(kind):
                    sheet.write_number(excel_row, idx, float(value or 0), cell_fmt[kind])
                else:
                    sheet.write_string(excel_row, idx, str(value), cell_fmt[kind])
                shown = _fmt(item.get(col["key"]), kind) if _is_number_kind(kind) else str(value)
                widths[idx] = max(widths[idx], min(len(shown) + 2, 48))

        last_data = first_data + len(rows) - 1
        if rows:
            sheet.autofilter(header_row, 0, last_data, len(columns) - 1)
            totals = _totals(rows, columns)
            if totals:
                total_row = last_data + 1
                sheet.write_string(total_row, 0, "Total", total_fmt["text"])
                for idx, col in enumerate(columns):
                    if col["key"] in totals:
                        letter = _col_letter(idx)
                        sheet.write_formula(
                            total_row, idx, f"=SUBTOTAL(109,{letter}{first_data + 1}:{letter}{last_data + 1})",
                            total_fmt[col["kind"]], totals[col["key"]],
                        )
                    elif idx:
                        sheet.write_blank(total_row, idx, None, total_fmt["text"])

        if data.get("filters"):
            widths[0] = max(widths[0], max(len(label) for label, _value in data["filters"]) + 2)
        for idx, width in enumerate(widths):
            sheet.set_column(idx, idx, max(width, 10))
        sheet.freeze_panes(first_data, 0)
        sheet.set_landscape()
        sheet.set_paper(9)
        sheet.fit_to_pages(1, 0)
        sheet.repeat_rows(header_row)

    workbook.close()
    return buffer.getvalue()
