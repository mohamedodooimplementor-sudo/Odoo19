import io
import logging
import subprocess
import sys

_logger = logging.getLogger(__name__)

# GREEN/RED/... are assigned lazily inside build_profitability_pdf() once
# reportlab is confirmed importable - see ensure_reportlab() below. Keeping
# every `reportlab` import out of this module's top level means the module
# (and the addon that imports it) always loads fine even before reportlab is
# installed; only actually generating a PDF requires it.


def ensure_reportlab():
    """Import reportlab, installing it with pip first if it's missing.

    Called both from the module's post_init_hook (fresh installs) and lazily
    here on every PDF build (covers upgrades of an already-installed module,
    where post_init_hook does not run again, and self-heals if the hook's
    install attempt failed for any reason - e.g. no network at install time).
    """
    try:
        import reportlab  # noqa: F401
        return
    except ImportError:
        pass
    _logger.info("construction_project_budget: reportlab not found, installing it now...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "reportlab"])
    _logger.info("construction_project_budget: reportlab installed successfully.")


def _fmt(amount, symbol, position):
    text = "{:,.2f}".format(amount or 0.0)
    return f"{symbol}{text}" if position == "before" else f"{text} {symbol}"


def build_profitability_pdf(data):
    """Build the Project Profitability Report as PDF bytes using ReportLab.

    `data` is the same dict produced by
    construction.project.budget.get_profitability_data().
    """
    ensure_reportlab()
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    GREEN = colors.HexColor("#17a673")
    RED = colors.HexColor("#e34850")
    HEADER_BG = colors.HexColor("#f0f0f0")
    INCOME_BG = colors.HexColor("#e8f8f2")
    BORDER = colors.HexColor("#d0d0d0")

    def _variance_color(value):
        return RED if (value or 0) < 0 else GREEN

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        topMargin=16 * mm, bottomMargin=14 * mm, leftMargin=14 * mm, rightMargin=14 * mm,
        title="Project Profitability Report",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("CBTitle", parent=styles["Title"], fontSize=16, spaceAfter=2)
    subtitle_style = ParagraphStyle("CBSubtitle", parent=styles["Normal"], fontSize=11, textColor=colors.grey)
    section_title_style = ParagraphStyle("CBSection", parent=styles["Heading3"], spaceBefore=10, spaceAfter=4)

    symbol = data.get("currency_symbol") or ""
    position = data.get("currency_position") or "after"

    def money(v):
        return _fmt(v, symbol, position)

    story = []
    story.append(Paragraph("Project Profitability Report", title_style))
    story.append(Paragraph(data.get("title") or "", subtitle_style))
    period = "All Dates"
    if data.get("date_from") or data.get("date_to"):
        period = "Period: %s - %s" % (data.get("date_from") or "...", data.get("date_to") or "...")
    story.append(Paragraph(period, subtitle_style))
    story.append(Spacer(1, 10))

    header_row = ["Category", "Planned", "Committed", "Actual", "Variance", "Var %"]

    def cost_table(sections):
        rows = [header_row]
        row_styles = []
        for i, section in enumerate(sections, start=1):
            rows.append([
                section["label"],
                money(section["planned"]),
                money(section["committed"]),
                money(section["actual"]),
                money(section["variance"]),
                "{:.1f}%".format(section.get("variance_pct") or 0.0),
            ])
            row_styles.append(("TEXTCOLOR", (4, i), (4, i), _variance_color(section["variance"])))
        totals = data["totals"]
        rows.append([
            "Total", money(totals["planned"]), money(totals["committed"]),
            money(totals["actual"]), money(totals["variance"]),
            "{:.1f}%".format(totals.get("variance_pct") or 0.0),
        ])
        table = Table(rows, colWidths=[70 * mm, 34 * mm, 34 * mm, 34 * mm, 34 * mm, 24 * mm], repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (4, -1), (4, -1), _variance_color(totals["variance"])),
        ] + row_styles
        table.setStyle(TableStyle(style))
        return table

    if data.get("grouped_by") == "project" and data.get("groups") is not None:
        for group in data["groups"]:
            story.append(Paragraph(group["label"], section_title_style))
            if group["sections"]:
                rows = [header_row]
                row_styles = []
                for i, section in enumerate(group["sections"], start=1):
                    rows.append([
                        section["label"], money(section["planned"]), money(section["committed"]),
                        money(section["actual"]), money(section["variance"]),
                        "{:.1f}%".format(section.get("variance_pct") or 0.0),
                    ])
                    row_styles.append(("TEXTCOLOR", (4, i), (4, i), _variance_color(section["variance"])))
                rows.append([
                    "Subtotal", money(group["planned"]), money(group["committed"]),
                    money(group["actual"]), money(group["variance"]),
                    "{:.1f}%".format(group.get("variance_pct") or 0.0),
                ])
                table = Table(rows, colWidths=[70 * mm, 34 * mm, 34 * mm, 34 * mm, 34 * mm, 24 * mm], repeatRows=1)
                style = [
                    ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("TEXTCOLOR", (4, -1), (4, -1), _variance_color(group["variance"])),
                ] + row_styles
                table.setStyle(TableStyle(style))
                story.append(table)
            else:
                story.append(Paragraph("No budget categories configured.", styles["Normal"]))
            story.append(Spacer(1, 6))
        story.append(Spacer(1, 6))
        story.append(Paragraph("Grand Total", section_title_style))
        story.append(cost_table([]))
    else:
        story.append(cost_table(data.get("sections") or []))

    if data.get("income_sections"):
        story.append(Spacer(1, 14))
        story.append(Paragraph("Income", section_title_style))
        rows = [["Category", "Amount"]]
        for section in data["income_sections"]:
            rows.append([section["label"], money(section["actual"])])
        rows.append(["Total Income", money(data["totals"]["income"])])
        table = Table(rows, colWidths=[70 * mm, 34 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), INCOME_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), GREEN),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.append(table)

    story.append(Spacer(1, 16))
    totals = data["totals"]
    profit_rows = [
        ["Total Income", money(totals.get("income", 0.0))],
        ["Total Cost", money(totals["actual"])],
        ["Net Profit", money(totals.get("net_profit", 0.0))],
    ]
    profit_table = Table(profit_rows, colWidths=[50 * mm, 40 * mm], hAlign="RIGHT")
    profit_table.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.black),
        ("TEXTCOLOR", (1, -1), (1, -1), _variance_color(totals.get("net_profit", 0.0))),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
    ]))
    story.append(profit_table)

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Planned and Committed reflect the budget's current state; Actual is restricted to the selected period.",
        ParagraphStyle("CBFoot", parent=styles["Normal"], fontSize=8, textColor=colors.grey, fontName="Helvetica-Oblique"),
    ))

    doc.build(story)
    return buffer.getvalue()
