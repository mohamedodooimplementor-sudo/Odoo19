from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    pp_manufacturing_warehouse_id = fields.Many2one('stock.warehouse', 'Manufacturing Warehouse')
    pp_lot_required = fields.Boolean('Lot Number Required', default=True)
    pp_material_issue_required = fields.Boolean('Material Issue Required', default=True)
    pp_packaging_issue_required = fields.Boolean('Packaging Issue Required', default=True)
    pp_weight_required = fields.Boolean('Weight Confirmation Required', default=True)
    pp_auto_validate_issue = fields.Boolean('Auto-validate Issue Transfers', default=True)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pp_manufacturing_warehouse_id = fields.Many2one(related='company_id.pp_manufacturing_warehouse_id', readonly=False)
    pp_lot_required = fields.Boolean(related='company_id.pp_lot_required', readonly=False)
    pp_material_issue_required = fields.Boolean(related='company_id.pp_material_issue_required', readonly=False)
    pp_packaging_issue_required = fields.Boolean(related='company_id.pp_packaging_issue_required', readonly=False)
    pp_weight_required = fields.Boolean(related='company_id.pp_weight_required', readonly=False)
    pp_auto_validate_issue = fields.Boolean(related='company_id.pp_auto_validate_issue', readonly=False)
