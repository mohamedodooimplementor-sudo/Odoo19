from odoo import models, fields, api
from odoo.exceptions import UserError
from odoo.tools.translate import _


class ProductTemplate(models.Model):
    _inherit = "product.template"

    categ_id = fields.Many2one(required=True)

    # Tracks whether default_code was generated automatically by this
    # module, so we know when it is safe to protect it from casual edits.
    code_auto_generated = fields.Boolean(
        string='Reference Auto-Generated',
        default=False,
        copy=False,
        help='Technical field: True when the Internal Reference was set '
             'automatically from the category sequence.',
    )

    _sql_constraints = [
        (
            'default_code_unique',
            'unique(default_code, company_id)',
            'The Internal Reference must be unique per company! '
            'If you are upgrading this module on a database that already '
            'has duplicate Internal References, clean up the data first, '
            'otherwise the module update will fail.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('default_code'):
                categ_id = vals.get('categ_id')
                if categ_id:
                    category = self.env['product.category'].browse(categ_id)
                    sequence = category._get_reference_sequence()
                    if sequence:
                        seq = sequence.next_by_id()
                        if seq:
                            vals['default_code'] = seq
                            vals['code_auto_generated'] = True
        return super().create(vals_list)

    def write(self, vals):
        if 'default_code' in vals and not self.env.user.has_group('base.group_system'):
            for product in self:
                if (
                    product.code_auto_generated
                    and product.default_code
                    and vals.get('default_code') != product.default_code
                ):
                    raise UserError(_(
                        "The Internal Reference '%(code)s' was generated "
                        "automatically from the product category and cannot "
                        "be changed manually. Ask an administrator if you "
                        "really need to override it.",
                        code=product.default_code,
                    ))
        return super().write(vals)
