def migrate(cr, version):
    """The default stages (Approved, In Progress, Closed) were originally
    loaded with noupdate="1", so simply changing their is_approved value in
    data/budget_stage_data.xml has no effect on databases that already
    installed an earlier version - noupdate records are never re-applied on
    upgrade. Set it directly here instead, for exactly those three stages.
    """
    xmlids = (
        "construction_project_budget.budget_stage_approved",
        "construction_project_budget.budget_stage_in_progress",
        "construction_project_budget.budget_stage_closed",
    )
    cr.execute("""
        UPDATE construction_budget_stage s
        SET is_approved = true
        FROM ir_model_data d
        WHERE d.model = 'construction.budget.stage'
          AND d.res_id = s.id
          AND (d.module || '.' || d.name) IN %s
    """, (xmlids,))
