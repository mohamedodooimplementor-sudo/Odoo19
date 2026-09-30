# -*- coding: utf-8 -*-
import pytz

from odoo import api, fields, models, _

from .education_dependency_utils import check_and_install_dependencies


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # --- Academic defaults ------------------------------------------------
    education_default_academic_year_id = fields.Many2one(
        'education.academic.year', string='Default Academic Year',
        config_parameter='prime_educational_hub.default_academic_year_id')

    # --- Attendance ---------------------------------------------------------
    education_default_attendance_status = fields.Selection([
        ('present', 'Present'),
        ('absent', 'Absent'),
    ], string='Default Attendance Status', default='present',
        config_parameter='prime_educational_hub.default_attendance_status')
    education_attendance_excused_excluded = fields.Boolean(
        string='Exclude Excused Absences From Attendance %',
        help='If enabled, excused absences are removed from the denominator '
             'when computing attendance percentages, instead of counting '
             'against the student like a normal absence.',
        config_parameter='prime_educational_hub.attendance_excused_excluded')

    # --- Grading -----------------------------------------------------------
    education_exam_tie_break_mode = fields.Selection([
        ('same_rank', 'Same Rank for Ties (1,2,2,4)'),
        ('sequential', 'Sequential Rank (1,2,3,4)'),
    ], string='Default Exam Tie-Break Rule', default='same_rank',
        config_parameter='prime_educational_hub.default_exam_tie_break_mode')

    # --- Fees / Payments -----------------------------------------------------
    education_default_payment_method_id = fields.Many2one(
        'education.payment.method', string='Default Payment Method',
        config_parameter='prime_educational_hub.default_payment_method_id')
    education_default_cash_account_id = fields.Many2one(
        'education.cash.account', string='Default Cash/Bank Account',
        help='Used as the default "Paid From" account on new expenses, refunds, '
             'and teacher payouts.',
        config_parameter='prime_educational_hub.default_cash_account_id')
    education_auto_session_horizon_days = fields.Integer(
        string='Auto-Generate Sessions X Days Ahead', default=14,
        help='Every day, groups with an active weekly schedule automatically get their '
             'missing sessions created up to this many days ahead — no manual '
             '"Generate Sessions" click needed.',
        config_parameter='prime_educational_hub.auto_session_horizon_days')
    education_school_timezone = fields.Selection(
        selection='_selection_school_timezone', string="School's Timezone",
        help='Group schedule times (e.g. "2:30 PM") are always interpreted in this timezone '
             'before being generated as actual sessions -- set this once so generated session '
             'times are correct no matter who (or which scheduled job) creates them.',
        config_parameter='prime_educational_hub.school_timezone')

    @api.model
    def _selection_school_timezone(self):
        return [(tz, tz) for tz in sorted(pytz.all_timezones)]

    # --- Dashboard as home page ---------------------------------------------
    education_dashboard_as_home_page = fields.Boolean(
        string='Prime Education Hub Dashboard as Home Page',
        config_parameter='prime_educational_hub.dashboard_as_home_page',
        help='When enabled, users who belong to a Prime Educational Hub group land on the '
             'Prime Education Hub Dashboard right after login instead of the Odoo Apps '
             'switcher (uses the standard "Home Action" field on each user, same as Settings '
             '> Users > a user > Home Action - nothing in Odoo core is modified). New users '
             'added to a Prime Educational Hub group afterwards get it automatically too; use '
             'the button below to (re)apply it to everyone right now.')

    def action_apply_dashboard_as_home_page(self):
        """Bulk-sets the Prime Education Hub Dashboard as the Home Action for every current
        member of the module (any Prime Educational Hub group), and turns the setting on so
        it also applies automatically to users added to the module later."""
        self.env['ir.config_parameter'].sudo().set_param(
            'prime_educational_hub.dashboard_as_home_page', 'True')
        self.env['res.users']._education_apply_dashboard_home_action()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_reset_dashboard_home_page(self):
        """Turns the setting off and clears the Home Action back to the default Odoo Apps
        switcher for every Prime Educational Hub user (only for users whose Home Action was
        this dashboard - a user's own unrelated custom Home Action, if any, is left alone)."""
        self.env['ir.config_parameter'].sudo().set_param(
            'prime_educational_hub.dashboard_as_home_page', 'False')
        dashboard_action = self.env.ref('prime_educational_hub.action_education_dashboard', raise_if_not_found=False)
        if dashboard_action:
            self.env['res.users'].sudo().search([('action_id', '=', dashboard_action.id)]).write({
                'action_id': False,
            })
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    education_require_pin_for_checkin = fields.Boolean(
        string='Require PIN for Self Check-in', default=True,
        help="When on (default), a student checking in on the public QR page must enter their "
             "Student Code AND their personal PIN — this is what proves who's checking in, since "
             "nobody is logged into Odoo on that page. Turning it off lets the code alone check "
             "a student in; only do this if you're comfortable with anyone who knows/guesses a "
             "student's code being able to check them in.",
        config_parameter='prime_educational_hub.require_pin_for_checkin')

    education_default_discount_policy = fields.Selection([
        ('none', 'No Discount'),
        ('fixed', 'Fixed Amount'),
        ('percent', 'Percentage'),
    ], string='Default Discount Policy', default='none',
        config_parameter='prime_educational_hub.default_discount_policy')
    education_default_discount_value = fields.Float(
        string='Default Discount Value',
        config_parameter='prime_educational_hub.default_discount_value')
    education_default_currency_id = fields.Many2one(
        'res.currency', string='Default Fee Currency',
        help='Used as the default currency on new fees, payments, and fee '
             'plans. Falls back to the company currency if left empty.',
        config_parameter='prime_educational_hub.default_currency_id')
    education_discount_approval_threshold = fields.Float(
        string='Discount Approval Threshold (%)', default=20.0,
        help='Fees with a discount at or above this percentage of the gross '
             'amount cannot be confirmed until a Supervisor/Admin explicitly '
             'approves the discount on the Fee record. Set to 0 to require '
             'approval on every discounted fee, or leave high to effectively '
             'disable the workflow.',
        config_parameter='prime_educational_hub.discount_approval_threshold')
    education_late_penalty_type = fields.Selection([
        ('none', 'No Penalty'),
        ('fixed', 'Fixed Amount'),
        ('percent', 'Percentage of Remaining Amount'),
    ], string='Late Penalty Type', default='none',
        config_parameter='prime_educational_hub.late_penalty_type')
    education_late_penalty_value = fields.Float(
        string='Late Penalty Value',
        config_parameter='prime_educational_hub.late_penalty_value')
    education_late_penalty_grace_days = fields.Integer(
        string='Late Penalty Grace Period (days)', default=3,
        help='Number of days after the due date before a late penalty is applied.',
        config_parameter='prime_educational_hub.late_penalty_grace_days')
    education_early_discount_type = fields.Selection([
        ('none', 'No Discount'),
        ('fixed', 'Fixed Amount'),
        ('percent', 'Percentage of Remaining Amount'),
    ], string='Early Settlement Discount Type', default='none',
        config_parameter='prime_educational_hub.early_discount_type')
    education_early_discount_value = fields.Float(
        string='Early Settlement Discount Value',
        config_parameter='prime_educational_hub.early_discount_value')
    education_early_discount_days_before = fields.Integer(
        string='Early Settlement Discount Window (days before due date)', default=7,
        help='An installment qualifies for the early-settlement discount if it is being '
             'settled at least this many days before its due date.',
        config_parameter='prime_educational_hub.early_discount_days_before')

    # --- Reports & Certificates ---------------------------------------------
    education_report_language = fields.Selection([
        ('en', 'English'),
        ('ar', 'Arabic'),
    ], string='Report Language', default='en',
        config_parameter='prime_educational_hub.report_language')
    education_report_company_name = fields.Char(
        string='Report Header Name',
        help='Shown in the header band of every generated PDF report. '
             'Falls back to the company name if left empty.',
        config_parameter='prime_educational_hub.report_company_name')
    education_report_footer_text = fields.Char(
        string='Report Footer Text',
        config_parameter='prime_educational_hub.report_footer_text')
    education_certificate_verification_enabled = fields.Boolean(
        string='Enable Public Certificate Verification', default=True,
        help='If disabled, the public /education/certificate/verify/<token> '
             'page will not confirm or deny any certificate, regardless of '
             'the token supplied.',
        config_parameter='prime_educational_hub.certificate_verification_enabled')
    education_student_portal_enabled = fields.Boolean(
        string='Enable Public Student Portal Links', default=True,
        help='If disabled, generated student portal links stop working '
             '(the page will show "not available") without deleting the '
             'underlying tokens.',
        config_parameter='prime_educational_hub.student_portal_enabled')

    # --- System / Required Libraries ---------------------------------------
    education_dependencies_status = fields.Char(
        string='Required Libraries Status', compute='_compute_dependencies_status')

    def _compute_dependencies_status(self):
        status = self.env['ir.config_parameter'].sudo().get_param(
            'prime_educational_hub.dependencies_status',
            'Not checked yet — click "Check / Install Libraries" below.')
        for rec in self:
            rec.education_dependencies_status = status

    def action_check_install_dependencies(self):
        """Manual re-run of the same check used at install time — handy if
        the server had no internet access during installation and the libs
        need to be (re)installed later once connectivity is available."""
        results = check_and_install_dependencies(self.env)
        missing = [name for name, ok in results.items() if not ok]
        if missing:
            message = _('Still missing: %s. Install manually on the server with pip, '
                        'then click this button again.') % ', '.join(missing)
        else:
            message = _('All required libraries (reportlab, XlsxWriter, qrcode) are installed.')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Dependency Check'),
                'message': message,
                'sticky': bool(missing),
                'type': 'warning' if missing else 'success',
            },
        }
