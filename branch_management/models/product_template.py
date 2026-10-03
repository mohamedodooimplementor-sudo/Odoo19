# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    branch_ids = fields.Many2many(
        'res.branch', 'product_template_res_branch_rel', 'product_tmpl_id', 'branch_id',
        string='Branches',
        help='Restrict this product to specific branches: it will only be '
             'selectable on Sales/Purchase Orders of those branches. '
             'Leave empty to make it available in every branch.')
