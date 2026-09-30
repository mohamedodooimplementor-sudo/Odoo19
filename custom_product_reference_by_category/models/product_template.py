from odoo import models, api

class ProductTemplate(models.Model):
    _inherit = "product.template"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('default_code'):
                categ_id = vals.get('categ_id')
                if categ_id:
                    category = self.env['product.category'].browse(categ_id)
                    if category.sequence_id:
                        seq = category.sequence_id.next_by_id()
                        if seq:
                            vals['default_code'] = seq
        return super().create(vals_list)
