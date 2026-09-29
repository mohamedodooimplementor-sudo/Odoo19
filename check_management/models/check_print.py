import base64
import re

from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from . import tafqeet

FONT_STACKS = {
    "tahoma": "Tahoma, 'DejaVu Sans', 'Noto Sans Arabic', sans-serif",
    "arial": "Arial, 'Liberation Sans', 'DejaVu Sans', 'Noto Sans Arabic', sans-serif",
    "naskh": "'Noto Naskh Arabic', 'Amiri', Tahoma, 'DejaVu Sans', sans-serif",
    "times": "'Times New Roman', 'Liberation Serif', 'DejaVu Serif', serif",
    "courier": "'Courier New', 'Liberation Mono', 'DejaVu Sans Mono', monospace",
}
ARABIC_RE = re.compile("[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")
ARABIC_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")

def ascii_html(text):
    """Escape `text` and write every non-ASCII character as a numeric entity.

    wkhtmltopdf builds sometimes read the report page with the wrong charset, which turns
    Arabic into mojibake; entities render correctly whatever the charset is.
    """
    return Markup("".join(c if ord(c) < 128 else "&#%d;" % ord(c) for c in str(escape(text or ""))))


PREVIEW_DEPENDS = (
    "width", "height", "offset_x", "offset_y", "font_family", "font_size", "text_color",
    "date_source", "date_x", "date_y", "date_format", "date_spacing",
    "payee_x", "payee_y", "payee_width", "payee_align",
    "words_x", "words_y", "words_width", "words_line_height", "words_lang", "words_prefix", "words_suffix",
    "amount_x", "amount_y", "amount_width", "amount_prefix", "amount_suffix", "arabic_digits",
    "crossed", "crossed_text", "cross_x", "cross_y", "background_image",
)


class CheckPrintTemplate(models.Model):
    _name = "check.print.template"
    _description = "Check Print Template"
    _order = "sequence, name"
    _check_company_auto = True

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    design_mode = fields.Selection(
        [("overlay", "Overlay on Bank's Pre-Printed Leaf"), ("full", "Full Check Design (blank paper)")],
        default="overlay", required=True,
        help="Overlay: prints only the variable text, positioned over a check leaf already printed by the "
             "bank. Full Design: prints a complete check face (border, bank header, field labels, "
             "signature line) on blank paper.",
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    bank_id = fields.Many2one(
        "check.bank", string="Bank", check_company=True,
        help="Checks of this bank use this template automatically. "
             "Leave empty for a template that fits any bank.",
    )

    # ---- page
    paper_preset = fields.Selection(
        [
            ("me_leaf", "Middle East Bank Leaf (175 x 80 mm)"),
            ("us_business", "US Business Check (215.9 x 88.9 mm / 8.5\" x 3.5\")"),
            ("us_personal", "US Personal Check (152.4 x 82.55 mm / 6\" x 3.25\")"),
            ("custom", "Custom"),
        ],
        default="me_leaf", required=True, string="Paper Size Preset",
        help="Quick sizes for the most common check leaves. Pick Custom to type any Width / Height.",
    )
    width = fields.Float("Check Width (mm)", default=175.0, required=True)
    height = fields.Float("Check Height (mm)", default=80.0, required=True)
    offset_x = fields.Float("Shift Right (mm)", default=0.0, help="Moves everything to the right (negative = left). Use it to calibrate the printer.")
    offset_y = fields.Float("Shift Down (mm)", default=0.0, help="Moves everything down (negative = up). Use it to calibrate the printer.")
    font_family = fields.Selection(
        [("tahoma", "Tahoma"), ("arial", "Arial"), ("naskh", "Naskh (Arabic)"),
         ("times", "Times New Roman"), ("courier", "Courier")],
        default="tahoma", required=True,
    )
    font_size = fields.Float("Font Size (pt)", default=12.0, required=True)
    text_color = fields.Char("Text Color", default="#000000")
    accent_color = fields.Char(
        "Accent Color", default="#1e3a5f",
        help="Used for the border, bank header bar and security pattern in Full Check Design mode.",
    )

    # ---- date
    date_source = fields.Selection(
        [("due_date", "Due Date"), ("issue_date", "Issue Date")], default="due_date", required=True,
        string="Date to Print",
    )
    date_x = fields.Float("Date X (mm)", default=122.0)
    date_y = fields.Float("Date Y (mm)", default=10.0)
    date_format = fields.Char("Date Format", default="%d/%m/%Y", help="Python format, e.g. %d/%m/%Y, %d-%m-%Y or %d %m %Y.")
    date_spacing = fields.Float("Letter Spacing (mm)", default=0.4, help="Spread the date over boxed cells printed on the check.")

    # ---- payee
    payee_x = fields.Float("Payee X (mm)", default=20.0)
    payee_y = fields.Float("Payee Y (mm)", default=27.0)
    payee_width = fields.Float("Payee Width (mm)", default=140.0)
    payee_align = fields.Selection(
        [("auto", "Automatic (start of text)"), ("left", "Left"), ("right", "Right"), ("center", "Center")],
        default="auto", required=True, string="Payee / Words Alignment",
    )

    # ---- amount in words
    words_x = fields.Float("Words X (mm)", default=20.0)
    words_y = fields.Float("Words Y (mm)", default=37.0)
    words_width = fields.Float("Words Width (mm)", default=140.0)
    words_line_height = fields.Float("Words Line Height", default=1.8)
    words_lang = fields.Selection([("ar", "Arabic"), ("en", "English")], default="ar", required=True, string="Words Language")
    words_prefix = fields.Char("Words Prefix", default="فقط")
    words_suffix = fields.Char("Words Suffix", default="لا غير")

    # ---- amount in figures
    amount_x = fields.Float("Amount X (mm)", default=125.0)
    amount_y = fields.Float("Amount Y (mm)", default=50.0)
    amount_width = fields.Float("Amount Width (mm)", default=42.0)
    amount_prefix = fields.Char("Amount Prefix", default="#")
    amount_suffix = fields.Char("Amount Suffix", default="#")
    arabic_digits = fields.Boolean("Arabic-Indic Digits", help="Print ١٢٣ instead of 123 for the date and the amount.")

    # ---- crossing
    crossed = fields.Boolean("Cross the Check", help="Print the crossing text (account payee only).")
    crossed_text = fields.Char("Crossing Text", default="A/C Payee Only")
    cross_x = fields.Float("Crossing X (mm)", default=8.0)
    cross_y = fields.Float("Crossing Y (mm)", default=8.0)

    # ---- calibration
    show_labels = fields.Boolean(
        "Field Labels", default=True,
        help="Full Check Design only: print small labels ('Date', 'Pay to the Order of', "
             "'Amount in Words', 'Amount') above each box.",
    )
    show_signature_line = fields.Boolean("Signature Line", default=True, help="Full Check Design only.")
    show_micr_line = fields.Boolean(
        "MICR-style Line", default=True,
        help="Full Check Design only: decorative line at the bottom with the check and bank codes "
             "(cosmetic only, not a real magnetic MICR line).",
    )
    background_image = fields.Image(
        "Scanned Check (preview only)", max_width=1600, max_height=900,
        help="Scan of a blank check leaf: shown behind the preview to place the fields. It is never printed.",
    )
    preview_html = fields.Html(compute="_compute_preview_html", sanitize=False, readonly=True)
    wkhtml_warning = fields.Boolean(compute="_compute_wkhtml_warning")

    # ------------------------------------------------------------------
    _PAPER_PRESETS = {
        "me_leaf": (175.0, 80.0),
        "us_business": (215.9, 88.9),
        "us_personal": (152.4, 82.55),
    }

    @api.onchange("paper_preset")
    def _onchange_paper_preset(self):
        size = self._PAPER_PRESETS.get(self.paper_preset)
        if size:
            self.width, self.height = size

    @api.constrains("width", "height", "font_size")
    def _check_positive(self):
        for rec in self:
            if rec.width <= 0 or rec.height <= 0 or rec.font_size <= 0:
                raise UserError(_("Width, height and font size must be positive."))

    def _layout(self):
        """Inline CSS of every printed block (positions in mm from the top-left corner)."""
        self.ensure_one()

        def n(value):
            return "%.2f" % (value or 0.0)

        def box(x, y, width=None, extra=""):
            style = "left:%smm;top:%smm;" % (n(x + self.offset_x), n(y + self.offset_y))
            if width:
                style += "width:%smm;" % n(width)
            return style + extra

        full = self.design_mode == "full"
        accent = self.accent_color or "#1e3a5f"
        W, H = self.width, self.height

        def label(x, y, text, extra=""):
            # a small caption printed just above the field it describes
            return {"style": box(x, y - 4.6, extra="font-size:7pt;letter-spacing:.3mm;opacity:.65;" + extra), "text": text}

        if full:
            # A self-contained, auto-computed layout (ignores the manual overlay X/Y fields, which
            # only make sense when printing over a bank's pre-printed leaf) so the result always
            # looks like a real, properly proportioned check regardless of paper size chosen.
            margin = 6.0
            header_h = 9.0
            row1_y = header_h + 4.0          # Check No. box + Date box
            row1_h = 9.0
            payee_y = row1_y + row1_h + 5.0  # Pay to the Order of
            words_y = payee_y + 11.0         # Amount in Words
            bottom_row_y = H - 19.0          # Memo (left) + Signature (right)
            checkno_w, date_w, amount_w = 38.0, 30.0, 40.0

            layout = {
                "page": "width:%smm;height:%smm;font-family:%s;font-size:%spt;color:%s;" % (
                    n(W), n(H), FONT_STACKS.get(self.font_family, FONT_STACKS["tahoma"]),
                    n(self.font_size), self.text_color or "#000000"),
                "date": box(W - margin - checkno_w - 4.0 - date_w, row1_y, date_w,
                            "text-align:center;letter-spacing:%smm;" % n(self.date_spacing)),
                "payee": box(margin, payee_y, W - margin * 2 - amount_w - 4.0),
                "words": box(margin, words_y, W - margin * 2,
                             "line-height:%s;white-space:normal;" % n(self.words_line_height)),
                "amount": box(W - margin - amount_w, payee_y, amount_w, "text-align:center;"),
                "crossed": box(margin, header_h + 2.0) if self.crossed else False,
                "full": True,
                "accent": accent,
                "border": "border-color:%s;" % accent,
                "header": "background:%s;" % accent,
                "checkno_wrap": box(W - margin - checkno_w, row1_y, checkno_w),
                "amount_box": box(W - margin - amount_w, payee_y - 1.0, amount_w, "height:%smm;border-color:%s;" % (n(row1_h + 1.0), accent)),
                "payee_rule": box(margin, payee_y + 7.5, W - margin * 2 - amount_w - 4.0),
                "words_rule": box(margin, words_y + 7.5, W - margin * 2),
                "memo": box(margin, bottom_row_y, 60.0),
                "memo_rule": box(margin, bottom_row_y + 6.5, 60.0),
            }
            layout["labels"] = [
                label(W - margin - checkno_w - 4.0 - date_w, row1_y, _("Date")),
                {"style": box(margin, payee_y - 4.6, extra="font-size:7pt;letter-spacing:.3mm;opacity:.65;"), "text": _("Pay to the Order of")},
                {"style": box(margin, words_y - 4.6, extra="font-size:7pt;letter-spacing:.3mm;opacity:.65;"), "text": _("Amount in Words")},
                {"style": box(W - margin - amount_w, payee_y - 4.6, extra="font-size:7pt;letter-spacing:.3mm;opacity:.65;text-align:center;"), "text": _("Amount")},
                {"style": box(margin, bottom_row_y - 4.6, extra="font-size:7pt;letter-spacing:.3mm;opacity:.65;"), "text": _("Memo")},
            ] if self.show_labels else []
            if self.show_signature_line:
                sig_width = 46.0
                layout["signature"] = box(W - margin - sig_width, bottom_row_y, sig_width)
            if self.show_micr_line:
                layout["micr"] = box(margin, H - 8.0)
            return layout

        layout = {
            "page": "width:%smm;height:%smm;font-family:%s;font-size:%spt;color:%s;" % (
                n(W), n(H), FONT_STACKS.get(self.font_family, FONT_STACKS["tahoma"]),
                n(self.font_size), self.text_color or "#000000"),
            "date": box(self.date_x, self.date_y, extra="letter-spacing:%smm;" % n(self.date_spacing)),
            "payee": box(self.payee_x, self.payee_y, self.payee_width),
            "words": box(self.words_x, self.words_y, self.words_width,
                         "line-height:%s;white-space:normal;" % n(self.words_line_height)),
            "amount": box(self.amount_x, self.amount_y, self.amount_width),
            "crossed": box(self.cross_x, self.cross_y) if self.crossed else False,
            "full": False,
        }
        return layout

    def _align(self, text):
        self.ensure_one()
        rtl = bool(ARABIC_RE.search(text or ""))
        align = self.payee_align
        if align == "auto":
            align = "right" if rtl else "left"
        return "rtl" if rtl else "ltr", align

    def _digits(self, text):
        return text.translate(ARABIC_DIGITS) if self.arabic_digits else text

    def _values_for(self, payee, amount, currency, date, bank_name=None, check_number=None, reference=None):
        """Texts printed on the leaf for the given data."""
        self.ensure_one()
        decimals = currency.decimal_places
        words = tafqeet.amount_to_words(
            amount, decimals, currency.name, currency.currency_unit_label,
            currency.currency_subunit_label, self.words_lang,
        )
        words = " ".join(p for p in (self.words_prefix, words, self.words_suffix) if p)
        figures = "{:,.{d}f}".format(amount, d=decimals)
        amount_text = self._digits("%s%s%s" % (self.amount_prefix or "", figures, self.amount_suffix or ""))
        payee_dir, payee_align = self._align(payee)
        words_dir, words_align = self._align(words)
        date_text = self._digits(date.strftime(self.date_format or "%d/%m/%Y")) if date else ""
        return {
            "date": ascii_html(date_text),
            "payee": ascii_html(payee),
            "payee_dir": payee_dir, "payee_align": payee_align,
            "words": ascii_html(words),
            "words_dir": words_dir, "words_align": words_align,
            "amount": ascii_html(amount_text),
            "crossed_text": ascii_html(self.crossed_text),
            "bank_name": ascii_html(bank_name or ""),
            "check_number": ascii_html(check_number or ""),
            "reference": ascii_html(reference or ""),
        }

    def _sample_values(self):
        self.ensure_one()
        currency = self.company_id.currency_id
        payee = "شركة النيل للتجارة" if self.words_lang == "ar" else "Nile Trading Company"
        bank_name = self.bank_id.display_name or self.company_id.name
        return self._values_for(
            payee, 12345.50, currency, fields.Date.context_today(self),
            bank_name=bank_name, check_number="000123", reference="CHK-OUT/2026/00001",
        )

    @api.depends(*PREVIEW_DEPENDS)
    def _compute_preview_html(self):
        for rec in self:
            background = False
            if rec.background_image:
                background = "data:image/png;base64,%s" % rec.background_image.decode()
            rec.preview_html = self.env["ir.qweb"]._render("check_management.check_print_preview", {
                "tpl": rec, "layout": rec._layout(), "values": rec._sample_values(), "background": background,
            })

    def _compute_wkhtml_warning(self):
        """True when wkhtmltopdf is missing or is not the official build with patched Qt.

        Unpatched builds (e.g. the Debian/Ubuntu package) shrink the page to ~77%, so the
        printed positions would not match the millimetres configured on the template.
        """
        try:
            from odoo.addons.base.models.ir_actions_report import _wkhtml
            info = _wkhtml()
            warning = not (info.bin and info.is_patched_qt)
        except Exception:  # pragma: no cover - defensive: never block the form
            warning = True
        for rec in self:
            rec.wkhtml_warning = warning

    def action_print_sample(self):
        self.ensure_one()
        return self.env.ref("check_management.action_report_check_print_sample").with_context(
            discard_logo_check=True).report_action(self)


class ReportCheckPrintSample(models.AbstractModel):
    _name = "report.check_management.report_check_print_sample"
    _description = "Check Print Sample Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        templates = self.env["check.print.template"].browse(docids)
        pages = [{"tpl": t, "layout": t._layout(), "values": t._sample_values()} for t in templates]
        self.env["report.check_management.report_check_print"]._sync_paperformat(pages)
        return {"doc_ids": docids, "doc_model": "check.print.template", "docs": templates, "pages": pages}


class ReportCheckPrint(models.AbstractModel):
    _name = "report.check_management.report_check_print"
    _description = "Check Print Report"

    @api.model
    def _get_report_values(self, docids, data=None):
        checks = self.env["check.management"].browse(docids)
        bad = checks.filtered(lambda c: c.state in ("draft", "cancelled"))
        if bad:
            raise UserError(_(
                "Draft or cancelled checks cannot be printed: %s", ", ".join(bad.mapped("name")),
            ))
        pages = []
        for check in checks:
            template = check._get_print_template()
            pages.append({
                "check": check, "tpl": template, "layout": template._layout(),
                "values": check._print_values(template),
            })
        self._sync_paperformat(pages)
        # Only counted here, once the leaf is actually being rendered (as opposed to when the
        # Print button is merely clicked) — see action_print_check on check.management.
        now = fields.Datetime.now()
        for check in checks:
            check.sudo().with_context(tracking_disable=True).write({
                "print_count": check.print_count + 1, "last_print_date": now,
            })
            check.message_post(body=_("Check printed (%s time(s)).", check.print_count))
        return {"doc_ids": docids, "doc_model": "check.management", "docs": checks, "pages": pages}

    def _sync_paperformat(self, pages):
        """The PDF page size comes from a single shared report.paperformat record, while the
        check size is configurable per template (paper_preset / width / height). Keep the two in
        sync for the common case of printing checks that share one template/size; when several
        sizes are mixed in the same batch, the first one wins (a single PDF can only have one
        page size per wkhtmltopdf run)."""
        paperformat = self.env.ref("check_management.paperformat_check_leaf", raise_if_not_found=False)
        if not paperformat or not pages:
            return
        width, height = pages[0]["tpl"].width, pages[0]["tpl"].height
        if round(paperformat.page_width, 2) != round(width, 2) or round(paperformat.page_height, 2) != round(height, 2):
            paperformat.sudo().write({"page_width": width, "page_height": height})
