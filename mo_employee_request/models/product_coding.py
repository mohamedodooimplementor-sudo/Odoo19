# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ProductCategory(models.Model):
    _inherit = 'product.category'

    er_code = fields.Char(
        string='Code', copy=False,
        help="Code of the category. The product code is built with the code of every level "
             "of the product's category, then the codes of the variant values.")


class ProductAttributeValue(models.Model):
    _inherit = 'product.attribute.value'

    er_code = fields.Char(
        string='Code', copy=False,
        help="Added to the code of every variant that has this value "
             "(category code + the code of each of its values).")

    _er_code_uniq = models.Constraint(
        'unique(attribute_id, er_code)',
        'The code of a value must be unique inside its attribute.')

    @api.model
    def _er_clean_vals(self, vals):
        if 'er_code' in vals:
            vals['er_code'] = (vals['er_code'] or '').strip().upper() or False
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([self._er_clean_vals(dict(v)) for v in vals_list])

    def write(self, vals):
        return super().write(self._er_clean_vals(dict(vals)))


class ProductProduct(models.Model):
    _inherit = 'product.product'

    er_generated_code = fields.Char(string='Generated Code', compute='_compute_er_generated_code')

    def _er_values(self):
        """Attribute values of the variant, in the order of the attributes."""
        self.ensure_one()
        ptavs = self.product_template_variant_value_ids.sorted(
            lambda v: (v.attribute_id.sequence, v.attribute_id.id, v.id))
        return ptavs.product_attribute_value_id

    @api.depends('product_tmpl_id.categ_id.parent_path', 'product_tmpl_id.categ_id.er_code',
                 'product_tmpl_id.categ_id.parent_id.er_code',
                 'product_tmpl_id.categ_id.parent_id.parent_id.er_code',
                 'product_template_variant_value_ids.product_attribute_value_id.er_code')
    def _compute_er_generated_code(self):
        for rec in self:
            values = rec._er_values()
            rec.er_generated_code = (rec.product_tmpl_id.er_category_code or "") + "".join(
                v.er_code or "" for v in values)

    def _er_duplicate(self, code, exclude):
        return self.sudo().with_context(active_test=False).search(
            [('default_code', '=', code), ('id', 'not in', exclude.ids)], limit=1)

    def _er_auto_code(self):
        """Fill the Internal Reference of the variants that have none with their generated code.

        Used on save and on import. It never raises and never replaces a code that is already
        there: when the category or a value has no code, or the code is already used by
        another product, the variant is left alone (the Generate Code button explains why).
        """
        for rec in self.filtered(lambda r: not r.default_code):
            if not rec.product_tmpl_id.er_category_code:
                continue
            if rec._er_values().filtered(lambda v: not v.er_code):
                continue
            code = rec.er_generated_code
            if code and not rec._er_duplicate(code, rec):
                rec.default_code = code

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._er_auto_code()
        return records

    def action_er_generate_code(self):
        """Variant code: category codes + the code of every attribute value of the variant."""
        codes = {}
        for rec in self:
            rec.product_tmpl_id._er_check_coding()
            missing = rec._er_values().filtered(lambda v: not v.er_code)
            if missing:
                raise UserError(_(
                    "%(product)s: these values have no code: %(values)s.\n"
                    "Set it on the attribute (Inventory > Configuration > Attributes).",
                    product=rec.display_name,
                    values=", ".join("%s / %s" % (v.attribute_id.name, v.name) for v in missing)))
            codes[rec] = rec.er_generated_code
        seen = {}
        for rec, code in codes.items():
            if code in seen:
                raise UserError(_("%(a)s and %(b)s would get the same code %(code)s.",
                                  a=seen[code].display_name, b=rec.display_name, code=code))
            seen[code] = rec
            other = self._er_duplicate(code, self)
            if other:
                raise UserError(_("The code %(code)s is already used by %(product)s.",
                                  code=code, product=other.display_name))
        for rec, code in codes.items():
            rec.default_code = code
        return True


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    er_category_levels = fields.Char(string='Category Path', compute='_compute_er_coding')
    er_category_code = fields.Char(string='Category Code', compute='_compute_er_coding')

    # --- building blocks ------------------------------------------------------------------
    def _er_category_chain(self):
        """The product's category and every parent above it, top first."""
        self.ensure_one()
        categ = self.categ_id
        if not categ:
            return categ
        ids = [int(i) for i in (categ.parent_path or '').split('/') if i]
        return self.env['product.category'].browse(ids or categ.ids)

    @api.depends('categ_id.parent_path', 'categ_id.er_code', 'categ_id.parent_id.er_code',
                 'categ_id.parent_id.parent_id.er_code')
    def _compute_er_coding(self):
        for rec in self:
            chain = rec._er_category_chain()
            rec.er_category_levels = " / ".join(
                "%s (%s)" % (c.name, c.er_code or "-") for c in chain)
            rec.er_category_code = "".join(chain.filtered('er_code').mapped('er_code'))

    def _er_check_coding(self):
        self.ensure_one()
        if not self.er_category_code:
            raise UserError(_(
                "No code found on the category of %(product)s. Set the Code on its category "
                "(or on a parent category).", product=self.display_name))

    def write(self, vals):
        res = super().write(vals)
        if 'categ_id' in vals or 'attribute_line_ids' in vals:
            # new category / new variants: products still without a code get theirs
            self.product_variant_ids._er_auto_code()
        return res

    @api.onchange('categ_id')
    def _onchange_er_coding(self):
        """A product without variants gets its category code as soon as it is chosen.
        With variants the code of each one is made by Generate Code."""
        if not self.categ_id or not self.er_category_code or self.attribute_line_ids:
            return
        code = self.er_category_code
        self.default_code = code
        other = self.env['product.product']._er_duplicate(code, self.product_variant_ids)
        if other:
            return {'warning': {
                'title': _("Code already used"),
                'message': _("The code %(code)s is already used by %(product)s.",
                             code=code, product=other.display_name)}}

    def action_er_generate_code(self):
        """Product code: category path + the code of each value of the variant."""
        self.product_variant_ids.action_er_generate_code()
        return True
