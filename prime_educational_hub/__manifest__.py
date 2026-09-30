# -*- coding: utf-8 -*-
{
    'name': 'Prime Educational Hub',
    'version': '19.0.1.9.0',
    'category': 'Education',
    'summary': 'Standalone Education / Private Lessons Management System',
    'description': """
Prime Educational Hub
===========================
A complete, standalone education-center operating system for Odoo 19.

Academic: academic years/terms, subjects, levels, groups with schedules,
waitlists with capacity control, teacher assignment.

Attendance: QR-based public self-check-in with PIN authentication, rate
limiting, bilingual Arabic/English responses, and a cron that auto-marks
no-shows absent.

Exams & Grading: reusable question bank, configurable grade scales,
per-student results with automatic ranking, assignment grading rubrics.

Fees & Financial Controls: installment plans, FIFO payment allocation,
automatic reuse of leftover payment credit on future fees, exact refund
reversal (and precise undo if a refund is cancelled), a discount-approval
workflow above a configurable threshold, late-payment penalties,
early-settlement discounts, and a daily ledger reconciliation check that
alerts admins the moment installments and allocations drift apart.

Standalone Accounting: expense entry with a full Draft/Submitted/Approved/
Paid approval workflow, cash/bank accounts with live running balances, and
Income Statement (P&L) & Cash Book reports -- no Odoo Accounting app
dependency required.

Rooms & Scheduling: a Free/Occupied Kanban dashboard of every classroom
(auto-refreshed every 5 minutes), and a dedicated Sessions Calendar that
auto-generates any upcoming session that's due but not yet created.

Certificates: templated PDF certificates with public QR verification.

Live Dashboard: a weekly planner, KPI cards, and interactive charts (every
card and chart segment is clickable through to the underlying records),
matching Odoo's light/dark mode automatically.

Portals: token-based Student and Guardian portals for grades, attendance,
and fee status.

Reports: PDF/Excel collection, aging, cashier-closing, report-card, and a
full per-student financial-audit timeline for dispute resolution.

Security: role-based groups (Admin, Supervisor, Cashier, Reception,
Teacher, Read-only), multi-company record rules, and hard server-side
checks that a fee/payment/refund can never attach to the wrong student.

No dependency on Accounting, HR, Payroll or external education modules.

Uninstall note: uninstalling this module removes all of its tables and data
(students, groups, fees, payments, certificates, etc.) per standard Odoo
behavior — export/back up any data you need to keep before uninstalling.
    """,
    'author': 'Eng. M.Aboelmagde',
    'website': 'https://www.youtube.com/@odoolab',
    'license': 'OPL-1',
    'price': 349.00,
    'currency': 'USD',
    'support': 'odoolabtech.offical',
    'images': ['static/description/banner.png', 'static/description/areas.png', 'static/description/fee_flow.png', 'static/description/setup_steps.png', 'static/description/roles.png'],
    'depends': ['base', 'web', 'mail', 'payment'],
    'external_dependencies': {
        'python': ['reportlab', 'xlsxwriter', 'qrcode'],
    },
    'data': [
        # security
        'security/education_security_groups.xml',
        'security/ir.model.access.csv',
        'security/education_record_rules.xml',

        # data
        'data/education_sequences.xml',
        'data/education_default_data.xml',
        'data/education_lead_stage_data.xml',
        'data/education_cron.xml',

        # views - phase 1
        'views/education_academic_year_views.xml',
        'views/education_term_views.xml',
        'views/education_subject_views.xml',
        'views/education_level_views.xml',
        'views/education_syllabus_topic_views.xml',
        'views/education_lead_views.xml',
        'views/education_feedback_views.xml',
        'views/education_branch_views.xml',
        'views/education_guardian_views.xml',
        'views/education_student_views.xml',
        'views/education_student_promotion_wizard_views.xml',
        'views/education_room_views.xml',
        'views/education_quick_enroll_wizard_views.xml',
        'views/education_group_views.xml',
        'views/education_teacher_views.xml',
        'views/education_teacher_leave_request_views.xml',
        'views/education_teacher_payout_views.xml',
        'views/education_enrollment_views.xml',
        'views/education_group_waitlist_views.xml',
        'views/education_session_generate_wizard_views.xml',
        'views/education_session_views.xml',
        'views/education_session_quick_checkin_wizard_views.xml',
        'views/education_session_cancel_wizard_views.xml',
        'views/res_users_views.xml',
        'views/education_attendance_views.xml',
        'views/education_attendance_public_templates.xml',
        'views/education_grade_scale_views.xml',
        'views/education_question_bank_views.xml',
        'views/education_exam_views.xml',
        'views/education_exam_result_views.xml',
        'views/education_assignment_views.xml',
        'views/education_assignment_submission_views.xml',
        'views/education_fee_plan_views.xml',
        'views/education_holiday_views.xml',
        'views/education_public_access_log_views.xml',
        'views/education_certificate_template_views.xml',
        'views/education_grading_rubric_views.xml',
        'views/education_fee_views.xml',
        'views/education_payment_views.xml',
        'views/education_refund_views.xml',
        'views/education_expense_views.xml',
        'views/education_cash_transfer_views.xml',
        'views/education_cashier_shift_views.xml',
        'views/education_accounting_wizards_views.xml',
        'views/education_reconciliation_log_views.xml',
        'views/education_certificate_public_templates.xml',
        'views/education_student_portal_templates.xml',
        'views/education_teacher_portal_templates.xml',
        'views/education_certificate_views.xml',
        'views/education_certificate_revoke_wizard_views.xml',
        'views/education_dashboard_views.xml',
        'views/education_dashboard_menu_item_views.xml',
        'views/education_dashboard_stat_card_views.xml',
        'views/education_report_wizards_views.xml',
        'views/res_config_settings_views.xml',
        'views/education_menus.xml',
        'data/education_dashboard_config_data.xml',
        'views/website_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'prime_educational_hub/static/src/css/education_dashboard.css',
            'prime_educational_hub/static/src/css/education_session_calendar.css',
            'prime_educational_hub/static/src/css/education_buttons.css',
            'prime_educational_hub/static/src/js/education_dashboard.js',
            'prime_educational_hub/static/src/js/education_session_calendar.js',
            'prime_educational_hub/static/src/xml/education_dashboard.xml',
            'prime_educational_hub/static/src/xml/education_session_calendar.xml',
        ],
        'web.assets_frontend': [
            'prime_educational_hub/static/src/css/education_website.css',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}
