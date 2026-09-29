import io
import os
import base64
import logging
from datetime import datetime, timedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import arabic_reshaper
    from bidi.algorithm import get_display as bidi_get_display
    ARABIC_LIBS_OK = True
except ImportError:
    ARABIC_LIBS_OK = False

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None

try:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.units import mm as rl_mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
    from reportlab.lib.utils import ImageReader
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.graphics.charts.linecharts import HorizontalLineChart
    REPORTLAB_OK = True
except ImportError:
    REPORTLAB_OK = False


# Arabic translations for the report's fixed labels (headers, section titles,
# table columns, sign-off block, notes). Keys are looked up via
# StockCardWizard._L(key); anything not in this dict simply falls back to
# the English key itself, so a missing translation never breaks the report.
STOCK_CARD_AR_LABELS = {
    'report_title': 'تقرير بطاقة الصنف',
    'report_subtitle': 'كشف حركة وتقييم المخزون',
    'period': 'الفترة',
    'location': 'الموقع',
    'all_locations': 'كل المواقع',
    'company': 'الشركة',
    'currency': 'العملة',
    'generated_on': 'تاريخ الإصدار',
    'executive_summary': 'الملخص التنفيذي',
    'products_reported': 'عدد الأصناف',
    'opening_value': 'قيمة الافتتاح',
    'closing_value': 'قيمة الإقفال',
    'net_change': 'صافي التغيير',
    'cost_valuation_data': 'بيانات التكلفة والتقييم',
    'cost_restricted': 'مقيدة — راجع المدير للاطلاع على البيانات المالية',
    'inventory_value_trend': 'اتجاه قيمة المخزون',
    'negative_stock_warning': 'تحذير: رصيد سالب',
    'negative_stock_body': 'صنف/أصناف برصيد ختامي سالب —',
    'and_more': 'وأصناف أخرى',
    'date': 'التاريخ',
    'reference': 'المرجع',
    'partner': 'الجهة',
    'source_location': 'موقع المصدر',
    'destination_location': 'موقع الوجهة',
    'qty_in': 'وارد',
    'qty_out': 'منصرف',
    'balance': 'الرصيد',
    'unit_cost': 'تكلفة الوحدة',
    'balance_value': 'قيمة الرصيد',
    'avg_cost_in': 'متوسط التكلفة (وارد)',
    'change_percent': 'نسبة التغيير',
    'opening_balance': 'رصيد افتتاحي',
    'closing_balance': 'رصيد ختامي',
    'lot': 'التشغيلة',
    'grand_total': 'الإجمالي الكلي',
    'system_on_hand': 'الرصيد الفعلي (النظام)',
    'report_balance': 'رصيد التقرير',
    'discrepancy': 'الفرق',
    'reconciled': 'مطابق للرصيد الفعلي',
    'note_balance_total': 'ملاحظة: إجمالي الرصيد هو مجموع الكمية الختامية لكل الأصناف — يُرجى الحذر لو الأصناف بوحدات قياس مختلفة.',
    'prepared_by': 'أعدّه',
    'reviewed_by': 'راجعه',
    'approved_by': 'اعتمده',
    'sign_sub': 'الاسم والتوقيع والتاريخ',
    'top_products': 'أعلى 5 أصناف حسب قيمة الإقفال',
    'change_vs_opening': 'التغيير عن الافتتاح',
    'product': 'الصنف',
}

# Candidate TTF fonts (regular, bold) that cover Arabic script, checked in
# order on whatever OS the Odoo server runs on. We can't bundle a font
# ourselves (font files are binary and license-restricted), so we look for
# one already installed on the machine instead — Windows servers (Mohamed's
# own setup) almost always have Arial/Tahoma, which both cover Arabic.
ARABIC_FONT_CANDIDATES = [
    ('Arial', 'C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/arialbd.ttf'),
    ('Tahoma', 'C:/Windows/Fonts/tahoma.ttf', 'C:/Windows/Fonts/tahomabd.ttf'),
    ('NotoNaskhArabic', '/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf',
     '/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf'),
    ('NotoSansArabic', '/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf',
     '/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf'),
    ('NotoNaskhArabic', '/usr/share/fonts/noto/NotoNaskhArabic-Regular.ttf',
     '/usr/share/fonts/noto/NotoNaskhArabic-Bold.ttf'),
    ('Amiri', '/usr/share/fonts/truetype/amiri/Amiri-Regular.ttf',
     '/usr/share/fonts/truetype/amiri/Amiri-Bold.ttf'),
    ('KacstOne', '/usr/share/fonts/truetype/kacst/KacstOne.ttf',
     '/usr/share/fonts/truetype/kacst/KacstOne.ttf'),
    ('ArialUnicode', '/Library/Fonts/Arial Unicode.ttf', '/Library/Fonts/Arial Unicode.ttf'),
]

_ARABIC_FONT_CACHE = {'checked': False, 'regular': None, 'bold': None}

# English counterparts for the same keys, so _L() always returns real display
# text (not the raw dict key) regardless of which language is selected.
STOCK_CARD_EN_LABELS = {
    'report_title': 'Stock Card Report',
    'report_subtitle': 'Inventory Movement & Valuation Statement',
    'period': 'Period',
    'location': 'Location',
    'all_locations': 'All Locations',
    'company': 'Company',
    'currency': 'Currency',
    'generated_on': 'Generated On',
    'executive_summary': 'Executive Summary',
    'products_reported': 'Products Reported',
    'opening_value': 'Opening Value',
    'closing_value': 'Closing Value',
    'net_change': 'Net Change',
    'cost_valuation_data': 'Cost & Valuation Data',
    'cost_restricted': 'Restricted \u2014 contact a manager for financial figures',
    'inventory_value_trend': 'Inventory Value Trend',
    'negative_stock_warning': 'Negative Stock Warning',
    'negative_stock_body': 'product(s) show a negative closing balance \u2014',
    'and_more': 'and more',
    'date': 'Date',
    'reference': 'Reference',
    'partner': 'Partner',
    'source_location': 'Source Location',
    'destination_location': 'Destination Location',
    'qty_in': 'In',
    'qty_out': 'Out',
    'balance': 'Balance',
    'unit_cost': 'Unit Cost',
    'balance_value': 'Balance Value',
    'avg_cost_in': 'Avg. Cost (In)',
    'change_percent': 'Change %',
    'opening_balance': 'Opening Balance',
    'closing_balance': 'Closing Balance',
    'lot': 'Lot',
    'grand_total': 'Grand Total',
    'system_on_hand': 'System On-Hand (live)',
    'report_balance': 'Report Balance',
    'discrepancy': 'Discrepancy',
    'reconciled': 'Reconciled with system on-hand',
    'note_balance_total': 'Note: the Balance total sums the closing quantity of every reported product \u2014 '
                          'treat with care if products use different units of measure.',
    'prepared_by': 'Prepared By',
    'reviewed_by': 'Reviewed By',
    'approved_by': 'Approved By',
    'sign_sub': 'Name, Signature & Date',
    'top_products': 'Top 5 Products by Closing Value',
    'change_vs_opening': 'Change vs Opening',
    'product': 'Product',
}


def _get_arabic_fonts():
    """Find + register (once) a TTF font that covers Arabic script, so the
    PDF can actually draw Arabic glyphs (reportlab's built-in fonts only
    cover Latin script). Returns (regular_name, bold_name) or (None, None)
    if nothing usable was found on this machine."""
    if _ARABIC_FONT_CACHE['checked']:
        return _ARABIC_FONT_CACHE['regular'], _ARABIC_FONT_CACHE['bold']
    _ARABIC_FONT_CACHE['checked'] = True
    if not REPORTLAB_OK:
        return None, None
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        return None, None

    for name, regular_path, bold_path in ARABIC_FONT_CANDIDATES:
        try:
            if not os.path.exists(regular_path):
                continue
            pdfmetrics.registerFont(TTFont(name, regular_path))
            bold_name = name
            if bold_path and bold_path != regular_path and os.path.exists(bold_path):
                bold_name = name + '-Bold'
                pdfmetrics.registerFont(TTFont(bold_name, bold_path))
            _ARABIC_FONT_CACHE['regular'] = name
            _ARABIC_FONT_CACHE['bold'] = bold_name
            return name, bold_name
        except Exception:
            continue
    return None, None


class StockCardWizard(models.TransientModel):
    _name = 'stock.card.wizard'
    _description = 'Stock Card Report Wizard'

    date_from = fields.Date(
        string='Start Date',
        required=True,
        default=lambda self: fields.Date.today().replace(day=1)
    )
    date_to = fields.Date(
        string='End Date',
        required=True,
        default=fields.Date.today
    )
    
    location_ids = fields.Many2many(
        'stock.location',
        'stock_card_wizard_location_rel',
        'wizard_id',
        'location_id',
        string='Locations',
        domain="[('usage', 'in', ['internal', 'transit'])]",
    )
    include_child_locations = fields.Boolean(
        string='Include Child Locations',
        default=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company
    )

    company_ids = fields.Many2many(
        'res.company',
        'stock_card_wizard_company_rel',
        'wizard_id',
        'res_company_id',
        string='Consolidate Companies',
        help='Select two or more companies to generate a single consolidated report '
             'covering all of them (each company gets its own section). When set, this '
             'overrides the single Company/Location above and automatically includes '
             'every internal location of each selected company.'
    )

    consolidation_currency_id = fields.Many2one(
        'res.currency',
        string='Consolidation Currency',
        default=lambda self: self.env.company.currency_id,
        help='When consolidating 2+ companies that use different currencies, every '
             "company's Unit Cost, Value In/Out and Balance Value figures are converted "
             'into this currency (using the exchange rate on the relevant date) before '
             'being combined into a single report. Ignored when a single company is used.'
    )

    report_currency_id = fields.Many2one(
        'res.currency',
        string='Report Currency',
        readonly=True,
        help='The currency the figures in the last generated report are expressed in.'
    )

    preset_id = fields.Many2one(
        'stock.card.preset',
        string='Saved Filter',
        help='Pick a filter set you saved before to instantly re-apply Locations, '
             'Product Filter and Grouping options, without reselecting them. '
             'Only your own saved filters are listed.'
    )
    new_preset_name = fields.Char(
        string='Save Current As',
        help='Type a name and click Save to store the current Location / Product Filter / '
             'Grouping options as a reusable saved filter.'
    )

    report_language = fields.Selection([
        ('en', 'English'),
        ('ar', 'Arabic'),
    ], string='Report Language', default='en', required=True,
        help='Language the generated report should be produced in.'
    )

    scope_warning = fields.Char(string='Scope Warning', readonly=True)
    
    filter_by = fields.Selection([
        ('product', 'Product'),
        ('category', 'Product Category'),
    ], string='Filter By', default='product', required=True)
    
    include_zero_movements = fields.Boolean(
        string='Include Zero Movements',
        default=False
    )
    
    group_by = fields.Selection([
        ('product', 'Product'),
        ('category', 'Category'),
        ('warehouse', 'Warehouse'),
    ], string='Group By', default='product', required=True)

    only_products_with_movement = fields.Boolean(
        string='Only Products With Movement',
        default=False,
        help='Hide products that had no transactions during the selected period, '
             'even if they carry an opening or closing balance.'
    )

    # --- Executive summary (populated when the report is generated) ---
    product_count = fields.Integer(string='Products Reported', readonly=True)
    total_opening_value = fields.Float(string='Total Opening Value', readonly=True)
    total_closing_value = fields.Float(string='Total Closing Value', readonly=True)
    total_net_value = fields.Float(string='Net Value Change', readonly=True)
    total_net_percent = fields.Float(string='Net Value Change %', readonly=True)
    report_generated_at = fields.Datetime(string='Report Generated At', readonly=True)
    
    product_ids = fields.Many2many(
        'product.product',
        'stock_card_wizard_product_rel',
        'wizard_id',
        'product_id',
        string='Products',
        domain="[('type', '=', 'consu')]"
    )
    categ_ids = fields.Many2many(
        'product.category',
        'stock_card_wizard_category_rel',
        'wizard_id',
        'categ_id',
        string='Product Categories'
    )

    picking_type_ids = fields.Many2many(
        'stock.picking.type',
        'stock_card_wizard_picking_type_rel',
        'wizard_id',
        'picking_type_id',
        string='Operation Types',
        help='Leave empty to include all operation types (receipts, deliveries, internal '
             'transfers, manufacturing, ...). Set this to only report moves coming from '
             'specific operation types, e.g. only Deliveries.'
    )

    show_reconciliation = fields.Boolean(
        string='Compare With Live On-Hand Quantity',
        default=True,
        help='When the report period ends today, show a reconciliation column comparing '
             'the calculated closing balance against the real-time quantity in stock.quant. '
             'This check is only meaningful when the End Date is today.'
    )

    print_with_costs = fields.Boolean(
        string='Print With Costs & Valuation',
        default=lambda self: self.user_can_view_costs(),
        help="Untick this to print/export a copy without Unit Cost, Balance Value or any "
             "other financial figures — useful when sharing the report with someone who "
             "shouldn't see cost data (e.g. a client or a warehouse team). This only works "
             "as an extra restriction: if your user group already hides cost data, ticking "
             "this box back on will not reveal it."
    )

    line_ids = fields.One2many('stock.card.line', 'wizard_id', string='Stock Card Lines')

    @api.onchange('location_ids')
    def _onchange_location_ids(self):
        if self.location_ids:
            companies = self.location_ids.mapped('company_id')
            if len(companies) == 1:
                self.company_id = companies

    @api.onchange('company_ids')
    def _onchange_company_ids_currency(self):
        if len(self.company_ids) > 1 and self.company_ids[0].currency_id:
            self.consolidation_currency_id = self.company_ids[0].currency_id

    @api.onchange('filter_by')
    def _onchange_filter_by(self):
        if self.filter_by == 'product':
            self.categ_ids = False
        else:
            self.product_ids = False

    @api.onchange('preset_id')
    def _onchange_preset_id(self):
        if not self.preset_id:
            return
        self._apply_preset_values(self.preset_id)

    def _apply_preset_values(self, preset):
        """Copy a stock.card.preset's saved options onto this wizard (never
        touches Period/dates — a saved filter is meant to be reusable across
        any period)."""
        self.ensure_one()
        if not preset:
            return
        self.location_ids = preset.location_ids
        self.include_child_locations = preset.include_child_locations
        if preset.company_id:
            self.company_id = preset.company_id
        self.company_ids = preset.company_ids
        if preset.consolidation_currency_id:
            self.consolidation_currency_id = preset.consolidation_currency_id
        self.filter_by = preset.filter_by
        self.product_ids = preset.product_ids
        self.categ_ids = preset.categ_ids
        self.picking_type_ids = preset.picking_type_ids
        self.group_by = preset.group_by
        self.show_reconciliation = preset.show_reconciliation
        self.print_with_costs = preset.print_with_costs
        self.include_zero_movements = preset.include_zero_movements
        self.only_products_with_movement = preset.only_products_with_movement

    def _get_current_preset_vals(self):
        """Collect the wizard's current Location / Product Filter / Grouping
        options into a vals dict suitable for creating or updating a
        stock.card.preset record."""
        self.ensure_one()
        return {
            'location_ids': [(6, 0, self.location_ids.ids)],
            'include_child_locations': self.include_child_locations,
            'company_id': self.company_id.id,
            'company_ids': [(6, 0, self.company_ids.ids)],
            'consolidation_currency_id': self.consolidation_currency_id.id,
            'filter_by': self.filter_by,
            'product_ids': [(6, 0, self.product_ids.ids)],
            'categ_ids': [(6, 0, self.categ_ids.ids)],
            'picking_type_ids': [(6, 0, self.picking_type_ids.ids)],
            'group_by': self.group_by,
            'show_reconciliation': self.show_reconciliation,
            'print_with_costs': self.print_with_costs,
            'include_zero_movements': self.include_zero_movements,
            'only_products_with_movement': self.only_products_with_movement,
        }

    def _save_last_used_preset(self):
        """Silently remember the current options as this user's "Last Used
        Settings", so they can be restored later with one click even if the
        person never bothered to save a named filter."""
        self.ensure_one()
        vals = dict(self._get_current_preset_vals(), name='__auto_last_used__',
                    user_id=self.env.uid, is_auto_last_used=True)
        existing = self.env['stock.card.preset'].search([
            ('user_id', '=', self.env.uid), ('is_auto_last_used', '=', True)
        ], limit=1)
        if existing:
            existing.write(vals)
        else:
            self.env['stock.card.preset'].create(vals)

    def _safe_save_last_used(self):
        try:
            self._save_last_used_preset()
        except Exception:
            _logger.exception('Stock Card wizard: failed to save "last used" settings (non-blocking).')

    def action_load_last_used(self):
        """Restore whatever Location / Product Filter / Grouping options were
        used the last time this user generated a report."""
        self.ensure_one()
        last_used = self.env['stock.card.preset'].search([
            ('user_id', '=', self.env.uid), ('is_auto_last_used', '=', True)
        ], limit=1)
        if not last_used:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Nothing Yet'),
                    'message': _("You haven't generated a report yet in this session."),
                    'type': 'warning',
                    'sticky': False,
                },
            }
        self._apply_preset_values(last_used)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _('Loaded'), 'message': _('Last used settings restored.'), 'type': 'success', 'sticky': False},
        }

    def action_save_preset(self):
        """Save the wizard's current Location / Product Filter / Grouping options
        as a reusable named filter, so the person doesn't have to reselect the
        same things every time they open the report."""
        self.ensure_one()
        if not self.new_preset_name or not self.new_preset_name.strip():
            raise UserError(_('Please type a name in "Save Current As" before saving.'))

        name = self.new_preset_name.strip()
        if name == '__auto_last_used__':
            raise UserError(_('That name is reserved. Please choose a different one.'))

        vals = dict(self._get_current_preset_vals(), name=name, user_id=self.env.uid)
        existing = self.env['stock.card.preset'].search(
            [('name', '=', name), ('user_id', '=', self.env.uid)], limit=1
        )
        if existing:
            existing.write(vals)
            preset = existing
            message = _('Updated saved filter "%s".', name)
        else:
            preset = self.env['stock.card.preset'].create(vals)
            message = _('Saved filter "%s". Pick it from the dropdown next time.', name)

        self.preset_id = preset.id
        self.new_preset_name = False
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {'title': _('Saved'), 'message': message, 'type': 'success', 'sticky': False},
        }

    def action_set_default_preset(self):
        """Mark the currently selected saved filter as the Default: it will be
        applied automatically every time a fresh Stock Card Report wizard is
        opened (only the Period is left for the person to set)."""
        self.ensure_one()
        if not self.preset_id:
            raise UserError(_('Pick (or save) a filter first, then mark it as Default.'))
        self.preset_id.is_default = True
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Default Set'),
                'message': _('"%s" will now load automatically every time you open this report.', self.preset_id.name),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_delete_preset(self):
        """Delete the currently selected saved filter."""
        self.ensure_one()
        if self.preset_id:
            name = self.preset_id.name
            self.preset_id.unlink()
            self.preset_id = False
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Deleted'),
                    'message': _('Saved filter "%s" was deleted.', name),
                    'type': 'success',
                    'sticky': False,
                },
            }

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        default_preset = self.env['stock.card.preset'].search([
            ('user_id', '=', self.env.uid), ('is_default', '=', True)
        ], limit=1)
        if default_preset:
            defaults.update({
                'preset_id': default_preset.id,
                'location_ids': [(6, 0, default_preset.location_ids.ids)],
                'include_child_locations': default_preset.include_child_locations,
                'company_ids': [(6, 0, default_preset.company_ids.ids)],
                'filter_by': default_preset.filter_by,
                'product_ids': [(6, 0, default_preset.product_ids.ids)],
                'categ_ids': [(6, 0, default_preset.categ_ids.ids)],
                'picking_type_ids': [(6, 0, default_preset.picking_type_ids.ids)],
                'group_by': default_preset.group_by,
                'show_reconciliation': default_preset.show_reconciliation,
                'print_with_costs': default_preset.print_with_costs,
                'include_zero_movements': default_preset.include_zero_movements,
                'only_products_with_movement': default_preset.only_products_with_movement,
            })
            if default_preset.company_id:
                defaults['company_id'] = default_preset.company_id.id
            if default_preset.consolidation_currency_id:
                defaults['consolidation_currency_id'] = default_preset.consolidation_currency_id.id
        return defaults

    @api.onchange('date_from', 'date_to', 'product_ids', 'categ_ids', 'filter_by', 'company_ids', 'location_ids')
    def _onchange_estimate_scope(self):
        self.scope_warning = False
        if not self.date_from or not self.date_to or self.date_to < self.date_from:
            return
        days = (self.date_to - self.date_from).days + 1

        try:
            base_domain = [('type', '=', 'consu')]
            if self.filter_by == 'product' and self.product_ids:
                product_count = len(self.product_ids)
            elif self.filter_by == 'category' and self.categ_ids:
                product_count = self.env['product.product'].search_count(
                    base_domain + [('categ_id', 'in', self.categ_ids.ids)]
                )
            else:
                product_count = self.env['product.product'].search_count(base_domain)
        except Exception:
            return

        if product_count * days > 50000 or product_count > 800 or days > 366:
            self.scope_warning = _(
                'This report covers about %(count)s product(s) over %(days)s day(s), which can take '
                'a while to generate. If it times out, try narrowing the Product Filter, Locations, '
                'or Period.', count=product_count, days=days
            )

    def _get_locations(self):
        """Get all selected locations, including their children if specified.
        If no location is selected, default to every internal/transit location
        of the wizard's company (matching the "leave empty = everything" pattern
        used by the other filters in this wizard)."""
        self.ensure_one()
        if not self.location_ids:
            return self._get_company_internal_locations(self.company_id)
        if self.include_child_locations:
            return self.env['stock.location'].search([
                ('id', 'child_of', self.location_ids.ids),
                ('usage', 'in', ['internal', 'transit'])
            ])
        return self.location_ids

    def _get_warehouse(self, location):
        """Best-effort resolution of the warehouse a stock location belongs to."""
        if not location:
            return self.env['stock.warehouse']
        if 'warehouse_id' in location._fields and location.warehouse_id:
            return location.warehouse_id
        warehouses = self.env['stock.warehouse'].search([
            ('company_id', '=', location.company_id.id or self.company_id.id)
        ])
        for warehouse in warehouses:
            view_location = warehouse.view_location_id
            if view_location and location.parent_path and view_location.parent_path \
                    and location.parent_path.startswith(view_location.parent_path):
                return warehouse
        return self.env['stock.warehouse']

    def user_can_view_costs(self):
        """Cost/valuation figures (Unit Cost, Balance Value, ...) are only shown
        to users who belong to the dedicated 'View Cost & Valuation Data' group.
        There are no exceptions — not even for Administrators — so a user's
        access to cost data depends solely on this one group."""
        cost_group = self.env.ref(
            'mo_stock_card.group_stock_card_costs', raise_if_not_found=False
        )
        if not cost_group:
            # The group record is missing (e.g. broken install) — fail closed.
            return False
        return cost_group in self.env.user.group_ids

    def effective_show_costs(self):
        """Whether costs should actually be printed: the user must have permission
        AND have left the 'Print With Costs' toggle checked. The toggle can only
        hide costs the user is allowed to see — it can never reveal costs a user
        isn't permitted to see."""
        self.ensure_one()
        return bool(self.user_can_view_costs() and self.print_with_costs)

    def get_negative_stock_lines(self):
        """Closing lines whose calculated balance went negative — usually a sign
        of a data issue (a delivery recorded before its matching receipt, a
        wrong opening balance, etc.). Used to show a warning banner on the
        report so it's never buried silently inside the table."""
        self.ensure_one()
        return self.line_ids.filtered(lambda l: l.line_type == 'closing' and l.is_negative)

    def _L(self, key):
        """Look up a report label in the language set by report_language.
        Always returns real display text (never the raw dict key) as long as
        the key exists in either language dict."""
        self.ensure_one()
        labels = STOCK_CARD_AR_LABELS if self.report_language == 'ar' else STOCK_CARD_EN_LABELS
        return labels.get(key, key)

    def _ar_shape(self, text):
        """Reshape + BiDi-reorder Arabic text so reportlab (which draws raw
        glyphs with no text-shaping engine of its own) renders connected,
        right-to-left Arabic instead of disjointed, reversed characters.
        A no-op for non-Arabic text or when the shaping libraries aren't
        installed (falls back to showing the text as-is)."""
        if not text:
            return text
        if not ARABIC_LIBS_OK:
            return text
        try:
            return bidi_get_display(arabic_reshaper.reshape(str(text)))
        except Exception:
            return text

    def get_value_trend_points(self, max_points=14):
        """Build a compact [(date, cumulative_value), ...] series for the
        "Inventory Value Trend" chart shown at the top of the PDF/Excel report:
        it walks from the opening value on `date_from` to the closing value on
        `date_to`, passing through the net value change of every day that had
        transactions in between. Returns [] when cost data isn't visible to
        the current user (there is nothing meaningful to chart otherwise).

        The series is downsampled to at most `max_points` for chart
        readability — this only affects the chart, never the detailed table,
        which always lists every transaction regardless."""
        self.ensure_one()
        if not self.effective_show_costs():
            return []

        transaction_lines = self.line_ids.filtered(lambda l: l.line_type == 'transaction' and l.date)
        if not transaction_lines:
            if self.total_opening_value == self.total_closing_value:
                return []
            return [(self.date_from, self.total_opening_value), (self.date_to, self.total_closing_value)]

        daily_net = {}
        for line in transaction_lines:
            daily_net[line.date] = daily_net.get(line.date, 0.0) + (line.value_in - line.value_out)

        points = [(self.date_from, self.total_opening_value)]
        running = self.total_opening_value
        for d in sorted(daily_net.keys()):
            running += daily_net[d]
            points.append((d, running))
        if points[-1][0] != self.date_to:
            points.append((self.date_to, self.total_closing_value))

        if len(points) > max_points:
            step = (len(points) - 1) / float(max_points - 1)
            sampled_idx = sorted({int(round(i * step)) for i in range(max_points)})
            points = [points[i] for i in sampled_idx]

        return points

    def get_top_products_summary(self, limit=5):
        """Return the top N products by closing balance value, for the
        executive summary section of the report."""
        self.ensure_one()
        closing_lines = self.line_ids.filtered(lambda l: l.line_type == 'closing')
        closing_lines = closing_lines.sorted(key=lambda l: l.balance_value, reverse=True)
        result = []
        for line in closing_lines[:limit]:
            result.append({
                'product': line.product_id,
                'balance': line.balance,
                'balance_value': line.balance_value,
                'change_percent': line.change_percent,
            })
        return result

    def _get_historical_unit_cost(self, product, move, fallback_cost):
        """Real accounting cost of a specific stock move, taken from its
        stock.valuation.layer(s) rather than today's standard_price. This matters
        whenever the cost has changed since the move happened, or when using
        FIFO/AVCO where the true cost is only known through the valuation layer."""
        if not move or 'stock.valuation.layer' not in self.env:
            return fallback_cost
        layers = self.env['stock.valuation.layer'].sudo().search([
            ('stock_move_id', '=', move.id),
            ('product_id', '=', product.id),
        ])
        if layers:
            total_qty = sum(abs(l.quantity) for l in layers)
            total_value = sum(abs(l.value) for l in layers)
            if total_qty:
                return total_value / total_qty
        return fallback_cost

    def _get_system_on_hand(self, product, locations):
        """Real-time on-hand quantity per stock.quant, used to reconcile the
        report's calculated closing balance against what Odoo currently shows."""
        quants = self.env['stock.quant'].sudo().search([
            ('product_id', '=', product.id),
            ('location_id', 'in', locations.ids),
        ])
        return sum(quants.mapped('quantity'))

    def _get_products(self):
        """Get products based on filter criteria"""
        self.ensure_one()
        domain = [('type', '=', 'consu')]
        
        if self.filter_by == 'product' and self.product_ids:
            domain.append(('id', 'in', self.product_ids.ids))
        elif self.filter_by == 'category' and self.categ_ids:
            domain.append(('categ_id', 'child_of', self.categ_ids.ids))
        
        return self.env['product.product'].search(domain, order='name')

    def _get_opening_balance(self, product, locations):
        """Calculate opening balance for a product before date_from"""
        self.ensure_one()
        location_ids = locations.ids
        
        query = """
            SELECT 
                COALESCE(SUM(CASE 
                    WHEN sml.location_dest_id IN %s AND sml.location_id NOT IN %s 
                    THEN sml.quantity ELSE 0 END), 0) AS qty_in,
                COALESCE(SUM(CASE 
                    WHEN sml.location_id IN %s AND sml.location_dest_id NOT IN %s 
                    THEN sml.quantity ELSE 0 END), 0) AS qty_out
            FROM stock_move_line sml
            JOIN stock_move sm ON sm.id = sml.move_id
            WHERE sml.state = 'done'
            AND sml.product_id = %s
            AND sml.date < %s
            AND (sml.location_id IN %s OR sml.location_dest_id IN %s)
        """
        
        self.env.cr.execute(query, (
            tuple(location_ids), tuple(location_ids),
            tuple(location_ids), tuple(location_ids),
            product.id, self.date_from,
            tuple(location_ids), tuple(location_ids)
        ))
        
        result = self.env.cr.fetchone()
        qty_in = result[0] if result else 0
        qty_out = result[1] if result else 0
        
        return qty_in - qty_out

    def _get_opening_value(self, product, opening_qty):
        """Calculate opening value using the product's real historical accounting
        cost (average cost-to-date from stock valuation layers created before the
        report's start date), instead of blindly applying today's standard_price
        to a balance that may be weeks or months old. Falls back to the current
        cost only when no valuation layers exist for this product/company."""
        self.ensure_one()
        if opening_qty == 0:
            return 0.0

        if 'stock.valuation.layer' not in self.env:
            return opening_qty * product.standard_price

        layers = self.env['stock.valuation.layer'].sudo().search([
            ('product_id', '=', product.id),
            ('company_id', '=', self.company_id.id),
            ('create_date', '<', self.date_from),
        ])
        if layers:
            total_qty = sum(layers.mapped('quantity'))
            total_value = sum(layers.mapped('value'))
            if total_qty:
                historical_unit_cost = total_value / total_qty
                return opening_qty * historical_unit_cost

        return opening_qty * product.standard_price

    def _get_transactions(self, product, locations):
        """Get all stock movements for a product within date range"""
        self.ensure_one()
        location_ids = locations.ids
        
        domain = [
            ('state', '=', 'done'),
            ('product_id', '=', product.id),
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
            '|',
            ('location_id', 'in', location_ids),
            ('location_dest_id', 'in', location_ids),
        ]

        if self.picking_type_ids:
            domain.append(('move_id.picking_type_id', 'in', self.picking_type_ids.ids))
        
        move_lines = self.env['stock.move.line'].search(domain, order='date, id')
        return move_lines

    def _convert_amount(self, amount, from_currency, to_currency, source_company, conv_date):
        """Convert a monetary amount from one company's currency to the report's
        target currency, using the exchange rate as of `conv_date`. A no-op
        (returns amount unchanged) when both currencies are the same, which is
        the case for every non-consolidated report."""
        if not amount or not from_currency or not to_currency or from_currency == to_currency:
            return amount
        return from_currency._convert(
            amount, to_currency, source_company, conv_date or fields.Date.today()
        )

    def _prepare_line_vals(self, line_type, product, **kwargs):
        """Prepare values for stock card line"""
        vals = {
            'wizard_id': self.id,
            'line_type': line_type,
            'product_id': product.id if product else False,
            'date': kwargs.get('date'),
            'reference': kwargs.get('reference', ''),
            'source_document': kwargs.get('source_document', ''),
            'partner_id': kwargs.get('partner_id'),
            'qty_in': kwargs.get('qty_in', 0.0),
            'qty_out': kwargs.get('qty_out', 0.0),
            'balance': kwargs.get('balance', 0.0),
            'initial_balance': kwargs.get('initial_balance', 0.0),
            'unit_cost': kwargs.get('unit_cost', 0.0),
            'value_in': kwargs.get('value_in', 0.0),
            'value_out': kwargs.get('value_out', 0.0),
            'balance_value': kwargs.get('balance_value', 0.0),
            'location_id': kwargs.get('location_id'),
            'location_dest_id': kwargs.get('location_dest_id'),
            'move_id': kwargs.get('move_id'),
            'move_line_id': kwargs.get('move_line_id'),
            'picking_id': kwargs.get('picking_id'),
            'sequence': kwargs.get('sequence', 10),
            'group_name': kwargs.get('group_name', ''),
            'transaction_count': kwargs.get('transaction_count', 0),
            'lot_id': kwargs.get('lot_id'),
            'picking_type_id': kwargs.get('picking_type_id'),
            'is_negative': kwargs.get('is_negative', False),
            'system_qty': kwargs.get('system_qty', 0.0),
            'reconciliation_diff': kwargs.get('reconciliation_diff', 0.0),
            'is_reconciliation_checked': kwargs.get('is_reconciliation_checked', False),
            'currency_id': kwargs.get('currency_id'),
        }
        return vals

    def _build_groups(self, products, all_locations):
        """Build the grouping structure according to `group_by`.
        Each group carries its own `locations` recordset so that warehouse
        grouping can narrow the stock locations considered per group, while
        product/category grouping simply reuses the full location set."""
        grouped = {}
        if self.group_by == 'category':
            for product in products:
                categ = product.categ_id
                grouped.setdefault(categ.id, {
                    'name': categ.complete_name,
                    'products': [],
                    'locations': all_locations,
                })['products'].append(product)

        elif self.group_by == 'warehouse':
            locations_by_wh = {}
            for loc in all_locations:
                warehouse = self._get_warehouse(loc)
                key = warehouse.id if warehouse else 0
                bucket = locations_by_wh.setdefault(key, {
                    'name': warehouse.display_name if warehouse else _('Other Locations'),
                    'locations': self.env['stock.location'],
                })
                bucket['locations'] |= loc

            for key, bucket in locations_by_wh.items():
                grouped[key] = {
                    'name': bucket['name'],
                    'products': list(products),
                    'locations': bucket['locations'],
                }

        else:
            for product in products:
                grouped[product.id] = {
                    'name': product.display_name,
                    'products': [product],
                    'locations': all_locations,
                }
        return grouped

    def _generate_lines_for_scope(self, all_locations, products, sequence_start,
                                   source_company=None, source_currency=None, target_currency=None):
        """Generate stock card lines for one scope (one company's set of locations
        and products). Returns (lines_data, next_sequence, opening_value_sum,
        closing_value_sum, product_count) so the caller can concatenate several
        scopes together for multi-company consolidation.

        When `source_currency` and `target_currency` are both set and differ
        (i.e. we are consolidating companies that use different currencies),
        every monetary figure (unit cost, value in/out, opening/closing value)
        is converted from `source_currency` into `target_currency` using the
        exchange rate on the relevant date, so summing across companies produces
        a meaningful total instead of mixing currencies."""
        self.ensure_one()
        source_company = source_company or self.company_id
        source_currency = source_currency or source_company.currency_id
        target_currency = target_currency or source_currency

        lines_data = []
        grouped_products = self._build_groups(products, all_locations)

        summary_opening_value = 0.0
        summary_closing_value = 0.0
        summary_product_count = 0

        sequence = sequence_start
        for group_key, group_data in grouped_products.items():
            group_products = group_data['products']
            group_locations = group_data.get('locations', all_locations)
            group_location_ids = group_locations.ids
            group_has_movements = False
            group_lines = []
            seen_products_in_group = set()

            for product in group_products:
                opening_qty = self._get_opening_balance(product, group_locations)
                opening_value = self._get_opening_value(product, opening_qty)
                opening_value = self._convert_amount(
                    opening_value, source_currency, target_currency, source_company, self.date_from
                )

                transactions = self._get_transactions(product, group_locations)

                if self.only_products_with_movement and not transactions:
                    continue

                if not transactions and not self.include_zero_movements and opening_qty == 0:
                    continue

                group_has_movements = True
                seen_products_in_group.add(product.id)
                running_balance = opening_qty
                running_value = opening_value

                total_qty_in = 0.0
                total_value_in = 0.0
                total_qty_out = 0.0

                sequence += 1
                group_lines.append(self._prepare_line_vals(
                    'opening',
                    product,
                    date=self.date_from,
                    reference='Opening Balance',
                    balance=opening_qty,
                    balance_value=opening_value,
                    sequence=sequence,
                    currency_id=target_currency.id if target_currency else False,
                ))

                for move_line in transactions:
                    qty_in = 0.0
                    qty_out = 0.0

                    if move_line.location_dest_id.id in group_location_ids and move_line.location_id.id not in group_location_ids:
                        qty_in = move_line.quantity
                    elif move_line.location_id.id in group_location_ids and move_line.location_dest_id.id not in group_location_ids:
                        qty_out = move_line.quantity
                    elif move_line.location_id.id in group_location_ids and move_line.location_dest_id.id in group_location_ids:
                        continue

                    if qty_in == 0 and qty_out == 0:
                        continue

                    initial_balance = running_balance
                    running_balance += qty_in - qty_out

                    move = move_line.move_id
                    move_date = move_line.date.date() if move_line.date else self.date_from
                    unit_cost = self._get_historical_unit_cost(product, move, product.standard_price)
                    unit_cost = self._convert_amount(
                        unit_cost, source_currency, target_currency, source_company, move_date
                    )
                    value_in = qty_in * unit_cost
                    value_out = qty_out * unit_cost
                    running_value += value_in - value_out

                    total_qty_in += qty_in
                    total_value_in += value_in
                    total_qty_out += qty_out

                    reference = move.picking_id.name if move.picking_id else (
                        getattr(move, 'reference', False) or getattr(move, 'description', False) or ''
                    )
                    source_document = move.origin or ''

                    sequence += 1
                    group_lines.append(self._prepare_line_vals(
                        'transaction',
                        product,
                        date=move_line.date.date() if move_line.date else False,
                        reference=reference,
                        source_document=source_document,
                        partner_id=move.partner_id.id if move.partner_id else False,
                        initial_balance=initial_balance,
                        qty_in=qty_in,
                        qty_out=qty_out,
                        balance=running_balance,
                        unit_cost=unit_cost,
                        value_in=value_in,
                        value_out=value_out,
                        balance_value=running_value,
                        location_id=move_line.location_id.id,
                        location_dest_id=move_line.location_dest_id.id,
                        move_id=move.id,
                        move_line_id=move_line.id,
                        picking_id=move.picking_id.id if move.picking_id else False,
                        sequence=sequence,
                        lot_id=move_line.lot_id.id if move_line.lot_id else False,
                        picking_type_id=move.picking_type_id.id if move.picking_type_id else False,
                        is_negative=running_balance < 0,
                        currency_id=target_currency.id if target_currency else False,
                    ))

                # --- per-product analytics for the closing line ---
                avg_cost_in = (
                    (total_value_in / total_qty_in) if total_qty_in
                    else self._convert_amount(
                        product.standard_price, source_currency, target_currency, source_company, self.date_to
                    )
                )
                period_days = max((self.date_to - self.date_from).days + 1, 1)
                average_balance = (opening_qty + running_balance) / 2.0
                turnover_ratio = (total_qty_out / average_balance) if average_balance else 0.0
                days_of_stock = (period_days / turnover_ratio) if turnover_ratio else 0.0
                change_percent = (
                    ((running_value - opening_value) / abs(opening_value)) * 100.0
                    if opening_value else (100.0 if running_value else 0.0)
                )

                # --- live reconciliation vs stock.quant (only meaningful when the
                # report's end date is today, since stock.quant is real-time) ---
                reconciliation_checked = False
                system_qty = 0.0
                reconciliation_diff = 0.0
                if self.show_reconciliation and self.date_to == fields.Date.today():
                    system_qty = self._get_system_on_hand(product, group_locations)
                    reconciliation_diff = running_balance - system_qty
                    reconciliation_checked = True

                sequence += 1
                group_lines.append(self._prepare_line_vals(
                    'closing',
                    product,
                    date=self.date_to,
                    reference='Closing Balance',
                    initial_balance=opening_qty,
                    balance=running_balance,
                    balance_value=running_value,
                    sequence=sequence,
                    is_negative=running_balance < 0,
                    system_qty=system_qty,
                    reconciliation_diff=reconciliation_diff,
                    is_reconciliation_checked=reconciliation_checked,
                    currency_id=target_currency.id if target_currency else False,
                ))
                group_lines[-1]['avg_cost_in'] = avg_cost_in
                group_lines[-1]['turnover_ratio'] = turnover_ratio
                group_lines[-1]['days_of_stock'] = days_of_stock
                group_lines[-1]['change_percent'] = change_percent

                summary_opening_value += opening_value
                summary_closing_value += running_value

            if group_has_movements or self.include_zero_movements:
                if self.group_by in ('category', 'warehouse') and len(seen_products_in_group) > 1:
                    sequence += 1
                    lines_data.append(self._prepare_line_vals(
                        'group_header',
                        None,
                        group_name=f"{group_data['name']} ({len(seen_products_in_group)})",
                        transaction_count=len(group_lines),
                        sequence=sequence,
                    ))

                lines_data.extend(group_lines)
                summary_product_count += len(seen_products_in_group)

        return lines_data, sequence, summary_opening_value, summary_closing_value, summary_product_count

    def _get_company_internal_locations(self, company):
        """All internal/transit stock locations belonging to a company, used for
        multi-company consolidation where we can't rely on a single location_id."""
        return self.env['stock.location'].search([
            ('company_id', '=', company.id),
            ('usage', 'in', ['internal', 'transit']),
        ])

    def _generate_stock_card_data(self):
        """Generate stock card data for all selected products, optionally
        consolidating several companies into one report."""
        self.ensure_one()
        self.line_ids.unlink()

        companies = self.company_ids if len(self.company_ids) > 1 else self.company_id
        consolidated = len(companies) > 1

        # When consolidating, every company's figures are converted into one
        # common currency (chosen by the user, defaulting to the first
        # company's currency) so they can be meaningfully summed together.
        # A single-company report simply keeps that company's own currency.
        if consolidated:
            report_currency = self.consolidation_currency_id or companies[0].currency_id
        else:
            report_currency = self.company_id.currency_id

        master_lines = []
        sequence = 0
        summary_opening_value = 0.0
        summary_closing_value = 0.0
        summary_product_count = 0
        any_products_found = False

        for company in companies:
            if consolidated:
                all_locations = self._get_company_internal_locations(company)
            else:
                all_locations = self._get_locations()

            products = self._get_products()
            if not products or not all_locations:
                continue
            any_products_found = True

            company_lines, sequence, opening_value, closing_value, product_count = \
                self._generate_lines_for_scope(
                    all_locations, products, sequence,
                    source_company=company,
                    source_currency=company.currency_id,
                    target_currency=report_currency,
                )

            if not company_lines:
                continue

            if consolidated:
                sequence += 1
                master_lines.append(self._prepare_line_vals(
                    'group_header',
                    None,
                    group_name=f"🏢 {company.name} ({product_count})",
                    transaction_count=len(company_lines),
                    sequence=sequence,
                ))

            master_lines.extend(company_lines)
            summary_opening_value += opening_value
            summary_closing_value += closing_value
            summary_product_count += product_count

        if not any_products_found:
            raise UserError(_('No products found matching the criteria.'))

        if not master_lines:
            raise UserError(_('No stock movements found for the selected criteria.'))

        self.env['stock.card.line'].create(master_lines)

        net_value = summary_closing_value - summary_opening_value
        net_percent = (
            (net_value / abs(summary_opening_value)) * 100.0
            if summary_opening_value else (100.0 if net_value else 0.0)
        )
        self.write({
            'product_count': summary_product_count,
            'total_opening_value': summary_opening_value,
            'total_closing_value': summary_closing_value,
            'total_net_value': net_value,
            'total_net_percent': net_percent,
            'report_generated_at': fields.Datetime.now(),
            'report_currency_id': report_currency.id if report_currency else False,
        })

        return True

    def action_view_report(self):
        """Generate and view the stock card report"""
        self.ensure_one()
        self._generate_stock_card_data()
        self._safe_save_last_used()
        
        action = {
            'name': _('Stock Card Report'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.card.line',
            'view_mode': 'list,pivot',
            'views': [
                (self.env.ref('mo_stock_card.view_stock_card_line_list').id, 'list'),
                (self.env.ref('mo_stock_card.view_stock_card_line_pivot').id, 'pivot'),
            ],
            'domain': [('wizard_id', '=', self.id)],
            'context': {
                'search_default_group_by_product': self.group_by == 'product',
                'search_default_group_by_category': self.group_by == 'category',
            },
            'target': 'current',
        }
        
        return action

    def action_generate_pdf(self):
        """Generate PDF report.

        Built directly as a PDF table using reportlab (the same engine
        underneath xhtml2pdf) — no HTML-to-PDF conversion step, and no
        wkhtmltopdf system binary. This mirrors exactly how the Excel
        button works: build the file in memory, attach it, and hand the
        browser a direct download link.
        """
        self.ensure_one()

        if not REPORTLAB_OK:
            raise UserError(_(
                'The "reportlab" Python library is required to generate PDF reports. '
                'Please ask your system administrator to install it on the server '
                '(pip install reportlab) and try again.'
            ))

        self._generate_stock_card_data()
        self._safe_save_last_used()
        pdf_bytes = self._build_pdf_bytes()

        attachment = self.env['ir.attachment'].create({
            'name': f'Stock_Card_Report_{self.date_from}_{self.date_to}.pdf',
            'type': 'binary',
            'datas': base64.b64encode(pdf_bytes),
            'mimetype': 'application/pdf',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def _build_pdf_bytes(self):
        """Build the PDF report and return its raw bytes. Assumes
        `_generate_stock_card_data()` has already populated `line_ids`.

        Mirrors the Excel report's structure and colors exactly. All cell
        text is wrapped in reportlab Paragraph objects (never plain strings)
        so long values wrap inside their own column instead of overflowing
        into the next one.
        """
        self.ensure_one()

        is_arabic = self.report_language == 'ar'
        ar_font, ar_font_bold = (_get_arabic_fonts() if is_arabic else (None, None))
        use_arabic = is_arabic and ar_font and ARABIC_LIBS_OK
        base_font = ar_font if use_arabic else 'Helvetica'
        base_font_bold = ar_font_bold if use_arabic else 'Helvetica-Bold'
        # Arabic TTF fonts we auto-detect (Arial/Tahoma/Noto...) don't ship a
        # distinct oblique/italic variant we can register, so italics simply
        # fall back to the regular weight in Arabic mode.
        base_font_oblique = ar_font if use_arabic else 'Helvetica-Oblique'
        arabic_fallback_notice = is_arabic and not use_arabic

        navy = rl_colors.HexColor('#1f3a5f')
        light_grey = rl_colors.HexColor('#f4f6f8')
        border_grey = rl_colors.HexColor('#c9d3dd')
        red = rl_colors.HexColor('#b5452b')
        green = rl_colors.HexColor('#2f6b4c')
        opening_bg = rl_colors.HexColor('#eefaf0')
        closing_bg = rl_colors.HexColor('#eaf2fb')
        product_header_bg = rl_colors.HexColor('#eef2f6')
        recon_ok_bg = rl_colors.HexColor('#f2f9f4')
        recon_mismatch_bg = rl_colors.HexColor('#fdf1ee')

        styles = getSampleStyleSheet()
        default_align = 2 if use_arabic else 0  # 2 = right, 0 = left
        normal = ParagraphStyle('sc_normal', parent=styles['Normal'], fontSize=11, leading=14,
                                 fontName=base_font, alignment=default_align)
        normal_right = ParagraphStyle('sc_normal_right', parent=normal, alignment=2)
        normal_center = ParagraphStyle('sc_normal_center', parent=normal, alignment=1)
        in_cell = ParagraphStyle('sc_in_cell', parent=normal_right, textColor=green, fontName=base_font_bold)
        out_cell = ParagraphStyle('sc_out_cell', parent=normal_right, textColor=red, fontName=base_font_bold)
        balance_cell = ParagraphStyle('sc_balance_cell', parent=normal_right, fontName=base_font_bold)
        negative_cell = ParagraphStyle('sc_negative_cell', parent=normal_right, textColor=red, fontName=base_font_bold)
        header_cell = ParagraphStyle('sc_header_cell', parent=normal_center, fontSize=12, textColor=rl_colors.white,
                                      fontName=base_font_bold)
        product_cell = ParagraphStyle('sc_product_cell', parent=normal, fontSize=13, textColor=navy, fontName=base_font_bold)
        group_cell = ParagraphStyle('sc_group_cell', parent=header_cell, alignment=default_align)
        opening_cell = ParagraphStyle('sc_opening_cell', parent=normal, textColor=green, fontName=base_font_oblique)
        opening_cell_right = ParagraphStyle('sc_opening_cell_r', parent=opening_cell, alignment=2, fontName=base_font_oblique)
        closing_cell = ParagraphStyle('sc_closing_cell', parent=normal, textColor=navy, fontName=base_font_bold)
        closing_cell_right = ParagraphStyle('sc_closing_cell_r', parent=closing_cell, alignment=2)
        recon_ok_cell = ParagraphStyle('sc_recon_ok', parent=normal, textColor=green, fontName=base_font_oblique)
        recon_bad_cell = ParagraphStyle('sc_recon_bad', parent=normal, textColor=red, fontName=base_font_bold)
        total_cell = ParagraphStyle('sc_total_cell', parent=normal, textColor=rl_colors.white, fontName=base_font_bold)
        total_cell_right = ParagraphStyle('sc_total_cell_r', parent=total_cell, alignment=2)
        sign_label_style = ParagraphStyle('sc_sign_label', parent=normal_center, fontSize=12, fontName=base_font_bold, textColor=navy)
        sign_sub_style = ParagraphStyle('sc_sign_sub', parent=normal_center, fontSize=10, textColor=rl_colors.HexColor('#8a8f98'),
                                         fontName=base_font_oblique)
        note_style = ParagraphStyle('sc_note', parent=normal, fontSize=10, textColor=rl_colors.HexColor('#6b7280'),
                                     fontName=base_font_oblique)
        title_style = ParagraphStyle('sc_title', parent=styles['Title'], fontSize=23, textColor=navy, spaceAfter=0,
                                      fontName=base_font_bold, alignment=default_align)
        subtitle_style = ParagraphStyle('sc_subtitle', parent=normal, fontSize=12, textColor=rl_colors.HexColor('#5b6b7c'))
        section_style = ParagraphStyle('sc_section', parent=styles['Heading3'], fontSize=15, textColor=navy,
                                        spaceBefore=0, spaceAfter=6, fontName=base_font_bold, alignment=default_align)

        def T(key):
            """Translate a fixed report-label key via self._L(). Shaping for
            Arabic display happens uniformly inside P() below, not here."""
            return self._L(key)

        def P(text, style=normal):
            if text in (None, ''):
                text = '&nbsp;'
            elif use_arabic:
                text = self._ar_shape(text)
            return Paragraph(text, style)

        show_costs = self.effective_show_costs()

        # ---------- main data table (headers/columns mirror the Excel sheet) ----------
        headers = [T('date'), T('reference'), T('partner'), T('source_location'), T('destination_location'),
                   T('qty_in'), T('qty_out'), T('balance')]
        widths_mm = [24, 46, 40, 44, 44, 20, 20, 30]
        if show_costs:
            headers += [T('unit_cost'), T('balance_value'), T('avg_cost_in'), T('change_percent')]
            widths_mm = [20, 34, 28, 30, 30, 16, 16, 22, 18, 22, 20, 16]
        ncols = len(headers)
        col_widths = [w * rl_mm for w in widths_mm]

        data = [[P(h, header_cell) for h in headers]]
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), navy),
            ('GRID', (0, 0), (-1, -1), 0.4, border_grey),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 7),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ('LEFTPADDING', (0, 0), (-1, -1), 5),
            ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ]

        total_in = 0.0
        total_out = 0.0
        total_balance_qty = 0.0
        total_balance_value = 0.0

        r = 0  # header occupies row 0
        for line in self.line_ids:
            if line.line_type == 'group_header':
                r += 1
                data.append([P(line.group_name, group_cell)] + [''] * (ncols - 1))
                style_cmds += [
                    ('SPAN', (0, r), (ncols - 1, r)),
                    ('BACKGROUND', (0, r), (-1, r), navy),
                ]

            elif line.line_type == 'opening':
                r += 1
                label = line.product_id.display_name or ''
                extra = []
                if line.categ_id:
                    extra.append(line.categ_id.complete_name)
                if line.product_id.default_code:
                    extra.append(line.product_id.default_code)
                if extra:
                    label += '  (%s)' % ' \u00b7 '.join(extra)
                data.append([P(label, product_cell)] + [''] * (ncols - 1))
                style_cmds += [
                    ('SPAN', (0, r), (ncols - 1, r)),
                    ('BACKGROUND', (0, r), (-1, r), product_header_bg),
                ]

                r += 1
                row = [P(str(self.date_from or ''), opening_cell), P(T('opening_balance'), opening_cell), '', '', '',
                       '', '', P('%.2f' % (line.balance or 0.0), opening_cell_right)]
                if show_costs:
                    row += [P('%.2f' % (line.product_id.standard_price or 0.0), opening_cell_right),
                            P('%.2f' % (line.balance_value or 0.0), opening_cell_right), '', '']
                data.append(row)
                style_cmds += [
                    ('SPAN', (1, r), (4, r)),
                    ('BACKGROUND', (0, r), (-1, r), opening_bg),
                ]

            elif line.line_type == 'transaction':
                r += 1
                total_in += line.qty_in
                total_out += line.qty_out

                reference_label = line.reference or ''
                if line.lot_id:
                    reference_label += ' \u00b7 %s: %s' % (T('lot'), line.lot_id.name)

                balance_style = negative_cell if line.is_negative else balance_cell
                row = [
                    P(str(line.date or ''), normal_center),
                    P(reference_label, normal),
                    P(line.partner_id.display_name or '', normal),
                    P(line.location_id.complete_name or '', normal),
                    P(line.location_dest_id.complete_name or '', normal),
                    P(('%.2f' % line.qty_in) if line.qty_in else '', in_cell),
                    P(('%.2f' % line.qty_out) if line.qty_out else '', out_cell),
                    P('%.2f' % (line.balance or 0.0), balance_style),
                ]
                if show_costs:
                    row += [
                        P('%.2f' % (line.unit_cost or 0.0), normal_right),
                        P('%.2f' % (line.balance_value or 0.0), normal_right),
                        '', '',
                    ]
                data.append(row)

            elif line.line_type == 'closing':
                r += 1
                total_balance_qty += line.balance
                total_balance_value += line.balance_value

                closing_balance_style = negative_cell if line.is_negative else closing_cell_right
                row = [P(str(self.date_to or ''), closing_cell), P(T('closing_balance'), closing_cell), '', '', '',
                       '', '', P('%.2f' % (line.balance or 0.0), closing_balance_style)]
                if show_costs:
                    row += ['', P('%.2f' % (line.balance_value or 0.0), closing_cell_right),
                            P('%.2f' % (line.avg_cost_in or 0.0), closing_cell_right),
                            P('%+.1f%%' % (line.change_percent or 0.0), closing_cell_right)]
                data.append(row)
                style_cmds += [
                    ('SPAN', (1, r), (4, r)),
                    ('BACKGROUND', (0, r), (-1, r), closing_bg),
                ]

                if line.is_reconciliation_checked:
                    r += 1
                    if line.reconciliation_diff:
                        recon_text = ('%s: %.2f &nbsp;\u00b7&nbsp; %s: %.2f &nbsp;\u00b7&nbsp; '
                                      '\u26a0 %s: %.2f' % (T('system_on_hand'), line.system_qty, T('report_balance'),
                                                            line.balance, T('discrepancy'), line.reconciliation_diff))
                        recon_style, recon_row_bg = recon_bad_cell, recon_mismatch_bg
                    else:
                        recon_text = ('%s: %.2f &nbsp;\u00b7&nbsp; %s: %.2f &nbsp;\u00b7&nbsp; '
                                      '\u2713 %s' % (T('system_on_hand'), line.system_qty, T('report_balance'),
                                                      line.balance, T('reconciled')))
                        recon_style, recon_row_bg = recon_ok_cell, recon_ok_bg
                    data.append([P(recon_text, recon_style)] + [''] * (ncols - 1))
                    style_cmds += [
                        ('SPAN', (0, r), (ncols - 1, r)),
                        ('BACKGROUND', (0, r), (-1, r), recon_row_bg),
                    ]

        # ---------- grand total row ----------
        r += 1
        grand_total_label = T('grand_total') if use_arabic else T('grand_total').upper()
        total_row = [P(grand_total_label, total_cell), '', '', '',
                     P('%.2f' % total_in, total_cell_right), P('%.2f' % total_out, total_cell_right),
                     P('%.2f' % total_balance_qty, total_cell_right)]
        if show_costs:
            total_row += ['', P('%.2f' % total_balance_value, total_cell_right), '', '']
        data.append(total_row)
        style_cmds += [
            ('SPAN', (0, r), (3, r)),
            ('BACKGROUND', (0, r), (-1, r), navy),
        ]

        if use_arabic:
            # Full right-to-left layout: mirror the column order itself (not
            # just text alignment), so the first logical column (Date) ends
            # up on the right, matching how an Arabic reader scans the page.
            col_widths = list(reversed(col_widths))
            data = [list(reversed(row)) for row in data]

            def _remap_cmd(cmd):
                op, start, end = cmd[0], cmd[1], cmd[2]
                # A command using -1 ("to the last column") already describes
                # a full-width range, which is unchanged by mirroring — and
                # mixing a resolved -1 with a resolved explicit index here
                # would wrongly collapse the range, so leave these as-is.
                if start[0] == -1 or end[0] == -1:
                    return cmd
                a, b = ncols - 1 - start[0], ncols - 1 - end[0]
                lo, hi = min(a, b), max(a, b)
                return (op, (lo, start[1]), (hi, end[1])) + tuple(cmd[3:])

            style_cmds = [_remap_cmd(cmd) for cmd in style_cmds]

        table = Table(data, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle(style_cmds))

        note = P(T('note_balance_total'), note_style)

        # ---------- signature block (mirrors the Excel sheet) ----------
        sign_row1 = [P(T('prepared_by'), sign_label_style), P(T('reviewed_by'), sign_label_style), P(T('approved_by'), sign_label_style)]
        sign_row2 = [P(T('sign_sub'), sign_sub_style), P(T('sign_sub'), sign_sub_style), P(T('sign_sub'), sign_sub_style)]
        if use_arabic:
            sign_row1 = list(reversed(sign_row1))
            sign_row2 = list(reversed(sign_row2))
        sign_table = Table(
            [sign_row1, sign_row2],
            colWidths=[sum(col_widths) / 3.0] * 3,
        )
        sign_table.setStyle(TableStyle([
            ('LINEABOVE', (0, 0), (-1, 0), 0.75, navy),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ]))

        def LP(label_key, value, style=None):
            """Build a '<b>Label</b><br/>Value' paragraph. Label and value are
            shaped/translated SEPARATELY before being wrapped in markup tags —
            running BiDi reordering over the whole '<b>...</b><br/>...' string
            at once would scramble the tag characters themselves."""
            label = T(label_key)
            val = '' if value in (None, '') else str(value)
            if use_arabic:
                label = self._ar_shape(label)
                val = self._ar_shape(val)
            return Paragraph('<b>%s</b><br/>%s' % (label, val), style or normal)

        # ---------- meta + executive summary ----------
        currency_name = self.report_currency_id.name or self.company_id.currency_id.name or ''
        meta_cells = [
            LP('period', '%s \u2014 %s' % (self.date_from, self.date_to)),
            LP('location', ', '.join(self.location_ids.mapped('complete_name')) or T('all_locations')),
            LP('company', self.company_id.name or ''),
            LP('currency', currency_name),
            LP('generated_on', self.report_generated_at or ''),
        ]
        meta_widths = [52 * rl_mm] * 5
        if use_arabic:
            meta_cells = list(reversed(meta_cells))
            meta_widths = list(reversed(meta_widths))
        meta = Table([meta_cells], colWidths=meta_widths)
        meta.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))

        if show_costs:
            summary_cells = [
                LP('products_reported', self.product_count),
                LP('opening_value', '%.2f %s' % (self.total_opening_value or 0.0, currency_name)),
                LP('closing_value', '%.2f %s' % (self.total_closing_value or 0.0, currency_name)),
                LP('net_change', '%+.1f%%' % (self.total_net_percent or 0.0)),
            ]
            summary_widths = [65 * rl_mm] * 4
        else:
            summary_cells = [
                LP('products_reported', self.product_count),
                LP('cost_valuation_data', T('cost_restricted')),
            ]
            summary_widths = [65 * rl_mm, 195 * rl_mm]
        if use_arabic:
            summary_cells = list(reversed(summary_cells))
            summary_widths = list(reversed(summary_widths))
        summary = Table([summary_cells], colWidths=summary_widths)
        summary.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), light_grey),
            ('BOX', (0, 0), (-1, -1), 0.5, border_grey),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ]))

        # ---------- assemble document ----------
        output = io.BytesIO()
        doc = SimpleDocTemplate(
            output, pagesize=landscape(A4),
            leftMargin=10 * rl_mm, rightMargin=10 * rl_mm, topMargin=10 * rl_mm, bottomMargin=10 * rl_mm,
            title='Stock Card Report',
        )

        header_text = [
            P(self.company_id.name or '', normal),
            P(T('report_title'), title_style),
            P(T('report_subtitle'), subtitle_style),
        ]

        logo_flowable = None
        if self.company_id.logo:
            try:
                logo_bytes = base64.b64decode(self.company_id.logo)
                logo_buf = io.BytesIO(logo_bytes)
                iw, ih = ImageReader(logo_buf).getSize()
                max_h, max_w = 22 * rl_mm, 48 * rl_mm
                scale = min(max_h / ih, max_w / iw, 1.0)
                logo_buf.seek(0)
                logo_flowable = Image(logo_buf, width=iw * scale, height=ih * scale)
            except Exception:
                logo_flowable = None  # a corrupt/unsupported logo image must never break the report

        if logo_flowable:
            header_block = Table(
                [[logo_flowable, header_text]],
                colWidths=[52 * rl_mm, sum(col_widths) - 52 * rl_mm],
            )
            header_block.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (0, 0), 'LEFT'),
                ('LEFTPADDING', (0, 0), (0, 0), 0),
                ('LEFTPADDING', (1, 0), (1, 0), 14),
            ]))
            elements = [header_block]
        else:
            elements = list(header_text)

        negative_lines = self.get_negative_stock_lines()
        if negative_lines:
            names = ', '.join(negative_lines.mapped('product_id.display_name')[:6])
            more = len(negative_lines) - 6
            if more > 0:
                names += ' %s %s' % (T('and_more'), more) if use_arabic else _(' and %s more', more)
            warning_style = ParagraphStyle(
                'NegativeWarning', parent=normal, textColor=rl_colors.HexColor('#7a0d0d'),
                backColor=rl_colors.HexColor('#fde8e8'), borderColor=rl_colors.HexColor('#b3261e'),
                borderWidth=1, borderPadding=8, fontSize=9.5,
            )
            warning_title = T('negative_stock_warning')
            warning_body = '%s %s' % (len(negative_lines), T('negative_stock_body'))
            if use_arabic:
                warning_title = self._ar_shape(warning_title)
                warning_body = self._ar_shape(warning_body)
                names = self._ar_shape(names)
            elements += [
                Spacer(1, 6),
                Paragraph(
                    '<b>\u26a0 %s:</b> %s %s.' % (warning_title, warning_body, names),
                    warning_style,
                ),
            ]

        if arabic_fallback_notice:
            elements += [
                Spacer(1, 4),
                Paragraph(
                    'Note: Arabic was selected, but no Arabic-capable font (or the arabic-reshaper / '
                    'python-bidi libraries) was found on this server, so this report was produced in '
                    'English instead. Ask your administrator to install a font such as Arial/Tahoma '
                    '(or the python packages) to enable Arabic PDF output.',
                    ParagraphStyle('sc_ar_fallback', parent=note_style, textColor=rl_colors.HexColor('#8a6d00')),
                ),
            ]

        chart_elements = []
        trend_points = self.get_value_trend_points()
        if len(trend_points) >= 2:
            chart_drawing = self._build_pdf_trend_chart(trend_points, chart_width=sum(col_widths))
            if chart_drawing:
                chart_elements = [
                    P(T('inventory_value_trend'), section_style),
                    chart_drawing,
                    Spacer(1, 10),
                ]

        elements += [
            Spacer(1, 10),
            meta,
            Spacer(1, 12),
            Paragraph('Executive Summary', section_style),
            summary,
            Spacer(1, 14),
        ]
        elements += chart_elements
        elements += [
            table,
            Spacer(1, 6),
            note,
            Spacer(1, 16),
            sign_table,
        ]

        doc.build(elements)
        return output.getvalue()

    def _build_pdf_trend_chart(self, points, chart_width, chart_height=95):
        """Build a reportlab Drawing containing a simple line chart of the
        cumulative inventory value across the period, for the PDF report.
        Uses reportlab's built-in graphics/charts, so no extra Python
        dependency (like matplotlib) is required beyond reportlab itself."""
        if len(points) < 2:
            return None

        values = [p[1] for p in points]
        v_min, v_max = min(values), max(values)
        pad = (v_max - v_min) * 0.15 or (abs(v_max) * 0.1 or 1.0)

        drawing = Drawing(chart_width, chart_height)
        chart = HorizontalLineChart()
        chart.x = 55
        chart.y = 12
        chart.width = chart_width - 80
        chart.height = chart_height - 34
        chart.data = [values]
        chart.categoryAxis.categoryNames = [str(p[0]) for p in points]
        chart.categoryAxis.labels.fontSize = 6.5
        chart.categoryAxis.labels.angle = 20
        chart.categoryAxis.labels.dy = -12
        chart.categoryAxis.labels.dx = -4
        chart.valueAxis.valueMin = v_min - pad
        chart.valueAxis.valueMax = v_max + pad
        chart.valueAxis.labelTextFormat = '%0.0f'
        chart.valueAxis.labels.fontSize = 7
        chart.lines[0].strokeColor = rl_colors.HexColor('#1f3a5f')
        chart.lines[0].strokeWidth = 2.2
        drawing.add(chart)
        return drawing

    def action_generate_excel(self):
        """Generate Excel report"""
        self.ensure_one()

        if not xlsxwriter:
            raise UserError(_('xlsxwriter library is required for Excel export. Please install it.'))

        self._generate_stock_card_data()
        self._safe_save_last_used()
        excel_bytes = self._build_excel_bytes()

        attachment = self.env['ir.attachment'].create({
            'name': f'Stock_Card_Report_{self.date_from}_{self.date_to}.xlsx',
            'type': 'binary',
            'datas': base64.b64encode(excel_bytes),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }

    def _build_excel_bytes(self):
        """Build the Excel workbook and return its raw bytes. Assumes
        `_generate_stock_card_data()` has already populated `line_ids`."""
        self.ensure_one()
        if not xlsxwriter:
            raise UserError(_('xlsxwriter library is required for Excel export. Please install it.'))

        show_costs = self.effective_show_costs()
        # 8 base columns; +4 analytics columns when cost data is visible
        last_col = 11 if show_costs else 7

        is_arabic = self.report_language == 'ar'
        # Excel shapes/reorders Arabic text natively (unlike the PDF engine),
        # so no reshaping library is needed here — just translated labels +
        # right-to-left sheet direction. Text labels align to the "start" of
        # the reading direction; numbers stay right-aligned either way (that's
        # the normal convention in both LTR and RTL spreadsheets).
        align_start = 'right' if is_arabic else 'left'

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # ---------- shared formats (navy theme, matches the PDF) ----------
        navy = '#1f3a5f'
        header_format = workbook.add_format({
            'bold': True, 'align': 'center', 'valign': 'vcenter',
            'bg_color': navy, 'font_color': 'white', 'border': 1,
        })
        title_format = workbook.add_format({'bold': True, 'font_size': 16, 'font_color': navy})
        subtitle_format = workbook.add_format({'italic': True, 'font_color': '#6b7280', 'font_size': 9})
        meta_label_format = workbook.add_format({'font_color': '#6b7280', 'font_size': 8})
        meta_value_format = workbook.add_format({'bold': True, 'font_color': navy})
        date_format = workbook.add_format({'num_format': 'yyyy-mm-dd', 'align': 'center', 'border': 1})
        number_format = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'border': 1})
        percent_format = workbook.add_format({'num_format': '+#,##0.0%;-#,##0.0%', 'align': 'right', 'border': 1})
        text_format = workbook.add_format({'align': align_start, 'border': 1})
        in_format = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'border': 1, 'font_color': '#2f6b4c'})
        out_format = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'border': 1, 'font_color': '#b5452b'})
        opening_format = workbook.add_format({'bg_color': '#eefaf0', 'align': align_start, 'border': 1, 'italic': True, 'font_color': '#2f6b4c'})
        opening_number_format = workbook.add_format({'bg_color': '#eefaf0', 'num_format': '#,##0.00', 'align': 'right', 'border': 1, 'font_color': '#2f6b4c'})
        closing_format = workbook.add_format({'bg_color': '#eaf2fb', 'bold': True, 'align': align_start, 'border': 1, 'font_color': navy})
        closing_number_format = workbook.add_format({'bg_color': '#eaf2fb', 'bold': True, 'num_format': '#,##0.00', 'align': 'right', 'border': 1, 'font_color': navy})
        group_header_format = workbook.add_format({'bold': True, 'bg_color': navy, 'font_color': 'white', 'border': 1})
        product_header_format = workbook.add_format({'bold': True, 'bg_color': '#eef2f6', 'border': 1, 'font_color': navy})
        kpi_label_format = workbook.add_format({'font_color': '#6b7280', 'font_size': 8, 'bold': True})
        kpi_value_format = workbook.add_format({'font_color': navy, 'font_size': 13, 'bold': True})
        total_format = workbook.add_format({
            'bold': True, 'bg_color': navy, 'font_color': 'white', 'border': 1, 'num_format': '#,##0.00',
        })
        negative_format = workbook.add_format({'num_format': '#,##0.00', 'align': 'right', 'border': 1, 'font_color': '#b5452b', 'bold': True})
        closing_negative_format = workbook.add_format({'bg_color': '#eaf2fb', 'bold': True, 'num_format': '#,##0.00', 'align': 'right', 'border': 1, 'font_color': '#b5452b'})
        recon_ok_format = workbook.add_format({'bg_color': '#f2f9f4', 'font_color': '#2f6b4c', 'italic': True, 'border': 1})
        recon_mismatch_format = workbook.add_format({'bg_color': '#fdf1ee', 'font_color': '#b5452b', 'bold': True, 'border': 1})
        sign_label_format = workbook.add_format({'bold': True, 'font_color': navy, 'top': 1, 'align': 'center'})
        sign_sub_format = workbook.add_format({'italic': True, 'font_color': '#8a8f98', 'font_size': 8, 'align': 'center'})
        warning_banner_format = workbook.add_format({
            'bold': True, 'font_color': '#7a0d0d', 'bg_color': '#fde8e8', 'border': 1,
            'font_size': 10, 'text_wrap': True, 'valign': 'vcenter',
        })

        # ================= SUMMARY SHEET =================
        summary = workbook.add_worksheet('Summary')
        if is_arabic:
            summary.right_to_left()
        summary.set_column(0, 0, 26)
        summary.set_column(1, 1, 22)
        summary.merge_range('A1:D1', '%s \u2014 %s' % (self._L('report_title'), self._L('executive_summary')), title_format)
        summary.write('A2', self._L('report_subtitle'), subtitle_format)

        negative_lines = self.get_negative_stock_lines()
        if negative_lines:
            names = ', '.join(negative_lines.mapped('product_id.display_name')[:6])
            more = len(negative_lines) - 6
            if more > 0:
                names += f" {self._L('and_more')} {more}" if is_arabic else f' and {more} more'
            summary.set_row(2, 30)
            summary.merge_range(
                'A3:D3',
                f"\u26a0 {self._L('negative_stock_warning')}: {len(negative_lines)} {self._L('negative_stock_body')} "
                f'{names}.',
                warning_banner_format,
            )

        summary.write('A4', self._L('period'), meta_label_format)
        summary.write('B4', f'{self.date_from} \u2014 {self.date_to}', meta_value_format)
        summary.write('A5', self._L('location'), meta_label_format)
        summary.write('B5', ', '.join(self.location_ids.mapped('complete_name')) or self._L('all_locations'), meta_value_format)
        summary.write('A6', self._L('company'), meta_label_format)
        summary.write('B6', self.company_id.name, meta_value_format)
        summary.write('A7', self._L('currency'), meta_label_format)
        summary.write('B7', self.report_currency_id.name or self.company_id.currency_id.name or '', meta_value_format)

        summary.write('A8', self._L('products_reported'), kpi_label_format)
        summary.write('B8', self.product_count, kpi_value_format)

        chart_anchor_row = 9
        if show_costs:
            summary.write('A9', self._L('opening_value'), kpi_label_format)
            summary.write('B9', self.total_opening_value, kpi_value_format)
            summary.write('A10', self._L('closing_value'), kpi_label_format)
            summary.write('B10', self.total_closing_value, kpi_value_format)
            summary.write('A11', self._L('net_change'), kpi_label_format)
            summary.write('B11', f'{self.total_net_percent:+.1f}%', kpi_value_format)

            top_products = self.get_top_products_summary()
            chart_anchor_row = 13
            if top_products:
                summary.write('A13', self._L('top_products'), kpi_label_format)
                headers = ['#', self._L('product'), self._L('balance'), self._L('balance_value'), self._L('change_vs_opening')]
                for col, h in enumerate(headers):
                    summary.write(14, col, h, header_format)
                for i, tp in enumerate(top_products):
                    r = 15 + i
                    summary.write(r, 0, i + 1, text_format)
                    summary.write(r, 1, tp['product'].display_name, text_format)
                    summary.write(r, 2, tp['balance'], number_format)
                    summary.write(r, 3, tp['balance_value'], number_format)
                    summary.write(r, 4, f"{tp['change_percent']:+.1f}%", text_format)
                chart_anchor_row = 15 + len(top_products) + 2

            trend_points = self.get_value_trend_points()
            if len(trend_points) >= 2:
                chart_data_ws = workbook.add_worksheet('Chart Data')
                chart_data_ws.hide()
                chart_data_ws.write(0, 0, self._L('date'))
                chart_data_ws.write(0, 1, self._L('inventory_value_trend'))
                for i, (d, v) in enumerate(trend_points):
                    chart_data_ws.write(i + 1, 0, str(d))
                    chart_data_ws.write(i + 1, 1, v)
                last_row = len(trend_points)

                value_chart = workbook.add_chart({'type': 'line'})
                value_chart.add_series({
                    'name': self._L('inventory_value_trend'),
                    'categories': ['Chart Data', 1, 0, last_row, 0],
                    'values': ['Chart Data', 1, 1, last_row, 1],
                    'line': {'color': '#1f3a5f', 'width': 2.25},
                    'marker': {'type': 'circle', 'size': 5, 'fill': {'color': '#1f3a5f'}},
                })
                value_chart.set_title({'name': self._L('inventory_value_trend')})
                value_chart.set_legend({'none': True})
                value_chart.set_x_axis({'name': self._L('date')})
                value_chart.set_y_axis({'name': f'{self._L("balance_value")} ({self.report_currency_id.name or ""})'})
                value_chart.set_size({'width': 620, 'height': 300})
                summary.insert_chart(chart_anchor_row, 0, value_chart)
        else:
            summary.write('A9', self._L('cost_restricted'), subtitle_format)

        # ================= DETAIL SHEET =================
        worksheet = workbook.add_worksheet('Stock Card')
        if is_arabic:
            worksheet.right_to_left()

        worksheet.merge_range(0, 0, 0, last_col, self._L('report_title'), title_format)
        worksheet.merge_range(1, 0, 1, last_col, self._L('report_subtitle'), subtitle_format)
        worksheet.write(2, 0, f"{self._L('period')}: {self.date_from} \u2014 {self.date_to}")
        worksheet.write(3, 0, f"{self._L('location')}: {', '.join(self.location_ids.mapped('complete_name')) or self._L('all_locations')}")
        worksheet.write(4, 0, f"{self._L('company')}: {self.company_id.name}")

        headers = [
            self._L('date'), self._L('reference'), self._L('partner'),
            self._L('source_location'), self._L('destination_location'),
            self._L('qty_in'), self._L('qty_out'), self._L('balance'),
        ]
        col_widths = [12, 22, 20, 22, 22, 12, 12, 14]
        if show_costs:
            headers += [self._L('unit_cost'), self._L('balance_value'), self._L('avg_cost_in'), self._L('change_percent')]
            col_widths += [12, 15, 14, 10]

        for col, width in enumerate(col_widths):
            worksheet.set_column(col, col, width)

        row = 6
        for col, header in enumerate(headers):
            worksheet.write(row, col, header, header_format)

        total_in = 0.0
        total_out = 0.0
        total_balance_value = 0.0
        total_balance_qty = 0.0

        row += 1
        for line in self.line_ids:
            if line.line_type == 'group_header':
                worksheet.merge_range(row, 0, row, last_col, line.group_name or '', group_header_format)
                row += 1

            elif line.line_type == 'opening':
                product_label = line.product_id.display_name
                if line.categ_id:
                    product_label += f" ({line.categ_id.complete_name})"
                if line.product_id.default_code:
                    product_label += f" [{line.product_id.default_code}]"
                worksheet.merge_range(row, 0, row, last_col, product_label, product_header_format)
                row += 1

                worksheet.write(row, 0, self.date_from, date_format)
                worksheet.merge_range(row, 1, row, 4, self._L('opening_balance'), opening_format)
                worksheet.write(row, 5, '', opening_format)
                worksheet.write(row, 6, '', opening_format)
                worksheet.write(row, 7, line.balance, opening_number_format)
                if show_costs:
                    worksheet.write(row, 8, line.product_id.standard_price, opening_number_format)
                    worksheet.write(row, 9, line.balance_value, opening_number_format)
                    worksheet.write(row, 10, '', opening_format)
                    worksheet.write(row, 11, '', opening_format)
                row += 1

            elif line.line_type == 'transaction':
                total_in += line.qty_in
                total_out += line.qty_out

                reference_label = line.reference or ''
                if line.lot_id:
                    reference_label += f" \u00b7 {self._L('lot')}: {line.lot_id.name}"

                worksheet.write(row, 0, line.date, date_format)
                worksheet.write(row, 1, reference_label, text_format)
                worksheet.write(row, 2, line.partner_id.display_name or '', text_format)
                worksheet.write(row, 3, line.location_id.complete_name or '', text_format)
                worksheet.write(row, 4, line.location_dest_id.complete_name or '', text_format)
                worksheet.write(row, 5, line.qty_in or '', in_format)
                worksheet.write(row, 6, line.qty_out or '', out_format)
                worksheet.write(row, 7, line.balance, negative_format if line.is_negative else number_format)
                if show_costs:
                    worksheet.write(row, 8, line.unit_cost, number_format)
                    worksheet.write(row, 9, line.balance_value, number_format)
                    worksheet.write(row, 10, '', number_format)
                    worksheet.write(row, 11, '', number_format)
                row += 1

            elif line.line_type == 'closing':
                total_balance_value += line.balance_value
                total_balance_qty += line.balance

                worksheet.write(row, 0, self.date_to, date_format)
                worksheet.merge_range(row, 1, row, 4, self._L('closing_balance'), closing_format)
                worksheet.write(row, 5, '', closing_format)
                worksheet.write(row, 6, '', closing_format)
                worksheet.write(row, 7, line.balance, closing_negative_format if line.is_negative else closing_number_format)
                if show_costs:
                    worksheet.write(row, 8, '', closing_format)
                    worksheet.write(row, 9, line.balance_value, closing_number_format)
                    worksheet.write(row, 10, line.avg_cost_in, closing_number_format)
                    worksheet.write(row, 11, line.change_percent / 100.0, percent_format)
                row += 1

                if line.is_reconciliation_checked:
                    recon_fmt = recon_mismatch_format if line.reconciliation_diff else recon_ok_format
                    recon_text = (
                        f"{self._L('system_on_hand')}: {line.system_qty:.2f}  \u00b7  "
                        f"{self._L('report_balance')}: {line.balance:.2f}  \u00b7  "
                        + (f"\u26a0 {self._L('discrepancy')}: {line.reconciliation_diff:.2f}" if line.reconciliation_diff
                           else f"\u2713 {self._L('reconciled')}")
                    )
                    worksheet.merge_range(row, 0, row, last_col, recon_text, recon_fmt)
                    row += 1

        grand_total_label = self._L('grand_total') if is_arabic else self._L('grand_total').upper()
        worksheet.merge_range(row, 0, row, 4, grand_total_label, total_format)
        worksheet.write(row, 5, total_in, total_format)
        worksheet.write(row, 6, total_out, total_format)
        worksheet.write(row, 7, total_balance_qty, total_format)
        if show_costs:
            worksheet.write(row, 8, '', total_format)
            worksheet.write(row, 9, total_balance_value, total_format)
            worksheet.write(row, 10, '', total_format)
            worksheet.write(row, 11, '', total_format)
        row += 1
        worksheet.merge_range(row, 0, row, last_col, self._L('note_balance_total'), subtitle_format)

        # ---------- signature rows ----------
        sign_row = row + 3
        sign_cols = [(0, 2), (3, 5), (6, last_col)] if last_col >= 6 else [(0, 0), (1, 1), (2, 2)]
        labels = [self._L('prepared_by'), self._L('reviewed_by'), self._L('approved_by')]
        sign_sub_label = self._L('sign_sub')
        for (c1, c2), label in zip(sign_cols, labels):
            if c2 > c1:
                worksheet.merge_range(sign_row, c1, sign_row, c2, '', sign_label_format)
                worksheet.write(sign_row, c1, label, sign_label_format)
                worksheet.merge_range(sign_row + 1, c1, sign_row + 1, c2, sign_sub_label, sign_sub_format)
            else:
                worksheet.write(sign_row, c1, label, sign_label_format)
                worksheet.write(sign_row + 1, c1, sign_sub_label, sign_sub_format)

        workbook.close()
        output.seek(0)
        excel_bytes = output.read()
        output.close()
        return excel_bytes
