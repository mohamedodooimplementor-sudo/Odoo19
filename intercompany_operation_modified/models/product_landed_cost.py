# -*- coding: utf-8 -*-
# الـ field landed_cost_ok موجود أصلاً في Odoo stock_landed_costs
# بس بنضيفه على product.template لو مش موجود
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # landed_cost_ok موجود في stock_landed_costs على product.template
    # بس بنتأكد إنه موجود وبنعرضه في الـ view
