{
    'name': 'Odoo Auditor',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Auditing',
    'summary': 'Enterprise-wide internal audit, continuous monitoring, findings, evidence and corrective actions',
    'description': """
Odoo Auditor 19
===============
Read-only audit and internal-control layer: configurable rule registry, audit runs,
findings workflow, immutable evidence snapshots, corrective actions, audit plans,
programs, workpapers, risk & control register and a protected audit log.
Integrations with Accounting, Sales, Purchase and Inventory are conditional
(rules are skipped with a warning when the required app is not installed).
    """,
    'author': 'Eng. M.Aboelmagde',
    'license': 'OPL-1',
    'price': 249.00,
    'currency': 'USD',
    'website': 'https://www.youtube.com/@odoolab',
    'images': [
        'static/description/banner.png',
        'static/description/dashboard.png',
        'static/description/workflow.png',
        'static/description/rules.png',
        'static/description/safety.png',
        'static/description/pipeline.png',
    ],
    'depends': ['base', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'security/record_rules.xml',
        'data/audit_sequences.xml',
        'data/audit_rule_data.xml',
        'data/audit_cron.xml',
        'data/audit_email_templates.xml',
        'views/audit_rule_views.xml',
        'views/audit_run_views.xml',
        'views/audit_finding_views.xml',
        'views/audit_action_views.xml',
        'views/audit_evidence_views.xml',
        'views/audit_plan_views.xml',
        'views/audit_risk_views.xml',
        'views/audit_log_views.xml',
        'views/audit_access_review_views.xml',
        'views/audit_dashboard_views.xml',
        'views/audit_exclusion_views.xml',
        'views/audit_menus.xml',
        'reports/audit_finding_report.xml',
        'reports/audit_summary_report.xml',
        'reports/audit_plan_report.xml',
        'reports/audit_action_report.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'odoo_auditor/static/src/js/dashboard.js',
            'odoo_auditor/static/src/xml/dashboard.xml',
            'odoo_auditor/static/src/scss/dashboard.scss',
        ],
    },
    'application': True,
    'installable': True,
}
