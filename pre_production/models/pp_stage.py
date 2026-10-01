from odoo import api, fields, models, _
from odoo.exceptions import UserError

STAGE_CODES = [
    ('material_issue', 'Material Issue'),
    ('weight', 'Weight Confirmation'),
    ('prd_line', 'PRD Line Check'),
    ('product_check1', 'Product Check 1'),
    ('product_check', 'Product Check'),
    ('filling', 'Filling Line Check'),
    ('pack_line', 'Pack Line Check'),
    ('product_check2', 'Product Check 2'),
    ('done', 'Done'),
]
QUALITY_STAGES = ['prd_line', 'product_check1', 'product_check', 'filling', 'pack_line', 'product_check2']
STAGE_GROUPS = {
    'material_issue': 'pre_production.group_pp_issue',
    'weight': 'pre_production.group_pp_weight',
    'prd_line': 'pre_production.group_pp_prd',
    'product_check1': 'pre_production.group_pp_check1',
    'product_check': 'pre_production.group_pp_check',
    'filling': 'pre_production.group_pp_filling',
    'pack_line': 'pre_production.group_pp_pack',
    'product_check2': 'pre_production.group_pp_check2',
    'done': 'pre_production.group_pp_final',
}


class PPStage(models.Model):
    _name = 'pp.stage'
    _description = 'Pre-Production Stage'
    _order = 'sequence, id'

    name = fields.Char('Displayed Name', required=True, translate=True)
    code = fields.Selection(STAGE_CODES, 'Technical Stage', required=True, readonly=True)
    sequence = fields.Integer(default=10)
    fold = fields.Boolean('Folded in Kanban', help="Folded stages are collapsed by default in the orders Kanban view.")
    is_quality = fields.Boolean(compute='_compute_is_quality')

    _sql_constraints = [('code_uniq', 'unique(code)', 'Each technical stage can only exist once.')]

    @api.depends('code')
    def _compute_is_quality(self):
        for s in self:
            s.is_quality = s.code in QUALITY_STAGES

    def unlink(self):
        raise UserError(_("Stages are part of the technical workflow and cannot be deleted. Rename them instead."))
