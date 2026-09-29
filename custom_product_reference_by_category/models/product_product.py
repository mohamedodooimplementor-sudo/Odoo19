from odoo import models, api


class ProductProduct(models.Model):
    _inherit = "product.product"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for product in records:
            template = product.product_tmpl_id
            # Only touch variants that still carry the exact same code as
            # their template (i.e. nobody set a specific code for them)
            # and only when the template actually has more than one
            # variant, otherwise the plain template code is enough.
            if (
                template.code_auto_generated
                and template.default_code
                and product.default_code == template.default_code
                and template.product_variant_count > 1
            ):
                index = list(template.product_variant_ids.ids).index(product.id) + 1
                product.with_context(skip_code_protection=True).default_code = \
                    "%s-%02d" % (template.default_code, index)
        return records

    def write(self, vals):
        # The template-level protection lives on product.template.write();
        # variants store their own default_code so no extra restriction is
        # enforced here beyond what Odoo already does. Kept as a hook point
        # for future variant-specific rules.
        return super().write(vals)
