from odoo import models, fields


class ProductCategory(models.Model):
    _inherit = "product.category"

    sequence_id = fields.Many2one(
        'ir.sequence',
        string='Product Sequence',
        help='Sequence used to generate internal reference for products in this category.'
    )

    def _get_reference_sequence(self):
        """Return the sequence to use for this category, walking up the
        parent category tree if this category has none set."""
        self.ensure_one()
        category = self
        while category:
            if category.sequence_id:
                return category.sequence_id
            category = category.parent_id
        return self.env['ir.sequence']
