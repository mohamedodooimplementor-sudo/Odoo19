from odoo import fields, models


class ProductCategory(models.Model):
    _inherit = 'product.category'

    pp_enabled = fields.Boolean('Pre-Production')
    pp_warehouse_ids = fields.Many2many('stock.warehouse', 'pp_category_warehouse_rel', 'categ_id', 'warehouse_id',
                                        string='Pre-Production Warehouses')

    def _pp_categ(self):
        """The category itself or its nearest parent that has Pre-Production enabled (settings are inherited)."""
        categ = self[:1]
        while categ:
            if categ.pp_enabled:
                return categ
            categ = categ.parent_id
        return self.browse()

