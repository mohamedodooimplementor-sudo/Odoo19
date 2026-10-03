# -*- coding: utf-8 -*-
{
    'name': 'Prime Construction Suite',
    'version': '19.0.33.0.0',
    'category': 'Construction',
    'summary': 'All-in-one construction ERP: Projects, Contracts, BOQ, Billing, Cost Control, Equipment, Labor, Risk & Safety',
    'description': """
Prime Construction Suite
==============================
A complete, end-to-end Odoo application covering the full lifecycle of a construction project.

Core
----
* Projects, Contracts and Bill of Quantities (BOQ)
* Change Orders workflow (auto-updates BOQ and contract value)
* Reusable BOQ Templates and standardized Cost Codes (WBS)

Finance
-------
* Progress Invoices integrated with Odoo Accounting
* Retention and advance-payment handling, with a Release Retention action
* Withholding tax and social-insurance deduction tracking
* Delay-penalty computation from contract terms
* Actual Cost tracking with multi-level, threshold-based approval
* Overhead cost allocation across running projects
* Subcontractor management with retention, WHT and AP Aging

Field Operations
-----------------
* Equipment register: usage logs, fuel cost, maintenance reminders, breakdown log
* Daily Labor attendance: overtime, advances, deductions, cost postable per BOQ line
* Site Diary: weather, workforce, equipment on site, daily issues
* Schedule / Gantt chart (native Canvas, no Enterprise dependency) with delay analysis

Compliance, Risk & Safety
--------------------------
* Bank Guarantees and Insurance Policies with expiry reminders
* Defects Liability Period tracking with a Snagging List
* Risk Register with automatic probability x impact scoring
* Site Incidents, Work Permits, and Safety Equipment Inspections (HSE)

Reporting
---------
* Interactive dashboard: KPIs, profitability, alerts, cash-flow forecast, EVM
* Earned Value Management: Planned Value, Earned Value, Actual Cost, CPI, SPI
* PDF portfolio snapshot report

See the full illustrated description below for screenshots of every module.
    """,
    'author': 'Eng. M.Aboelmagde',
    'depends': ['base','project','account','purchase','stock','hr','analytic','mail'],
    'data': [
        'security/construction_security.xml',
        'security/ir.model.access.csv',
        'data/construction_sequence.xml',
        'data/construction_cron.xml',
        'views/construction_project_views.xml',
        'views/construction_cost_code_views.xml',
        'views/construction_boq_template_views.xml',
        'views/construction_contract_views.xml',
        'views/construction_boq_views.xml',
        'views/construction_change_order_views.xml',
        'views/construction_progress_invoice_views.xml',
        'views/construction_final_account_views.xml',
        'views/construction_approval_rule_views.xml',
        'views/construction_measurement_sheet_views.xml',
        'views/construction_subcontractor_views.xml',
        'views/construction_actual_cost_views.xml',
        'views/construction_guarantee_views.xml',
        'views/construction_insurance_views.xml',
        'views/construction_snag_views.xml',
        'views/construction_activity_views.xml',
        'views/construction_overhead_views.xml',
        'views/construction_ap_aging_views.xml',
        'views/construction_document_views.xml',
        'views/construction_settings_views.xml',
        'views/res_users_views.xml',
        'views/construction_equipment_views.xml',
        'views/construction_labor_views.xml',
        'views/construction_risk_views.xml',
        'views/construction_site_diary_views.xml',
        'views/construction_hse_views.xml',
        'views/construction_drawing_views.xml',
        'views/construction_tender_views.xml',
        'views/construction_prequalification_views.xml',
        'views/construction_estimate_views.xml',
        'views/construction_resource_views.xml',
        'views/construction_program_views.xml',
        'views/construction_rfi_views.xml',
        'views/construction_quality_inspection_views.xml',
        'views/construction_quality_ncr_views.xml',
        'views/construction_quality_capa_views.xml',
        'views/construction_quality_test_result_views.xml',
        'views/construction_material_request_views.xml',
        'views/construction_rfq_views.xml',
        'views/construction_site_issue_views.xml',
        'views/construction_material_return_views.xml',
        'views/construction_transmittal_views.xml',
        'views/construction_kpi_views.xml',
        'wizard/construction_resource_leveling_wizard_view.xml',
        'views/construction_menu.xml',
        'wizard/change_order_reject_wizard_view.xml',
        'wizard/construction_boq_purchase_wizard_view.xml',
        'wizard/construction_boq_import_wizard_view.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'prime_construction_suite/static/src/css/construction_dashboard.css',
            'prime_construction_suite/static/src/js/construction_dashboard.js',
            'prime_construction_suite/static/src/xml/construction_dashboard.xml',
            'prime_construction_suite/static/src/js/construction_gantt.js',
            'prime_construction_suite/static/src/xml/construction_gantt.xml',
            'prime_construction_suite/static/src/js/construction_drawing_viewer.js',
            'prime_construction_suite/static/src/xml/construction_drawing_viewer.xml',
            'prime_construction_suite/static/src/js/construction_risk_heatmap.js',
            'prime_construction_suite/static/src/xml/construction_risk_heatmap.xml',
        ],
    },
    'installable': True,
    'application': True,
    'post_init_hook': '_post_init_hook',
    'auto_install': False,
    'license': 'OPL-1',
    'price': 999.00,
    'currency': 'USD',
    'support': 'odoolabtech.offical',
    'images': ['static/description/banner.png', 'static/description/dashboard_preview.png', 'static/description/gantt_preview.png', 'static/description/module_map.png'],
}
