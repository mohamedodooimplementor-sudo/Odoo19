{
    "name": "Construction Project Budget",
    "version": "19.0.14.0.0",
    "category": "Project",
    "summary": "Plan, track and control construction project budgets with a live dashboard and profitability report",
    "description": """
Construction Project Budget
============================
Plan project budgets by category (materials, labor, equipment, subcontractors, expenses,
transportation), and follow Planned vs Committed vs Actual vs Remaining from a single
unified dashboard. Actual cost can come from several sources, not only Vendor Bills.

Key Features
------------
* Budget lines per category with planned / committed / actual / remaining amounts.
* Unified Budget Actual ledger with cost-source tracking (manual, vendor bill, journal
  entry, labor, stock consumption, ...) and one-click access back to the source document.
* Manual Project Expense document with its own Draft / Confirmed / Cancelled workflow.
* Labor Cost entries (hours x hourly rate) posted to the Labor category.
* Purchase Orders linked to a project/budget/category expose an open "Committed" amount
  (not yet invoiced); posting the related Vendor Bill converts it into an Actual cost.
* Plain journal entries (Accounting > Journal Entries) can also be linked to a project's
  budget/category and posted as Actual cost, for costs that don't go through a bill.
* Automatic actual-cost entries generated when stock pickings linked to a project are
  validated - works with or without perpetual/automated inventory valuation.
* Duplicate-safe: every automated source is tagged so the same document can never post
  twice, and un-posting/cancelling a source document removes its Budget Actual entry.
* Visual OWL dashboard with a project filter, Planned/Committed/Actual KPIs, a
  Planned/Committed/Actual chart by category, and a cost-by-source breakdown chart.
* Project Profitability Report: an accounting-statement-style screen (with a printable
  PDF) comparing Planned vs Committed vs Actual vs Variance, either as an overview across
  all projects or drilled down by category with every posted entry for one project.
* Pivot and graph analysis of spending by project, category and month.
* Smart buttons on the budget for linked Stock Transfers, Purchase Orders, Vendor Bills
  and Journal Entries.
* Multi-stage budget pipeline (Draft → Pending Approval → Approved → In Progress →
  Closed by default, fully configurable) shown as draggable Kanban columns, with
  approval/closing restricted to Construction Budget Managers.
""",
    "author": "Eng. M.Aboelmagde",
    "license": "OPL-1",
    "price": 149.00,
    "currency": "USD",
    "website": "https://www.youtube.com/@odoolab",
    "support": "odoolabtech.offical",
    "images": [
        "static/description/banner.png",
        "static/description/cost_flow.png",
        "static/description/approval_pipeline.png",
        "static/description/setup_steps.png",
    ],
    "depends": ["project", "purchase", "stock", "stock_account", "account", "hr"],
    "data": [
        "security/construction_budget_security.xml",
        "security/ir.model.access.csv",
        "data/budget_category_data.xml",
        "data/budget_stage_data.xml",
        "data/ir_cron_data.xml",
        "wizard/copy_budget_categories_wizard_views.xml",
        "views/project_budget_views.xml",
        "views/project_budget_dashboard_views.xml",
        "views/project_views.xml",
        "views/purchase_views.xml",
        "views/stock_views.xml",
        "views/account_move_views.xml",
        "views/project_budget_menus.xml",
        "views/res_config_settings_views.xml"
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
    "post_init_hook": "post_init_hook",
    "assets": {
        "web.assets_backend": [
            "construction_project_budget/static/src/scss/budget_dashboard.scss",
            "construction_project_budget/static/src/scss/budget_kanban.scss",
            "construction_project_budget/static/src/scss/budget_form.scss",
            "construction_project_budget/static/src/js/budget_dashboard.js",
            "construction_project_budget/static/src/xml/budget_dashboard_templates.xml",
            "construction_project_budget/static/src/scss/profitability_report.scss",
            "construction_project_budget/static/src/js/profitability_report.js",
            "construction_project_budget/static/src/xml/profitability_report_templates.xml",
        ],
    }
}
