from odoo import models, fields

class ProductCategory(models.Model):
    _inherit = "product.category"

    sequence_id = fields.Many2one(
        'ir.sequence',
        string='Product Sequence',
        help='Sequence used to generate internal reference for products in this category.'
    )
