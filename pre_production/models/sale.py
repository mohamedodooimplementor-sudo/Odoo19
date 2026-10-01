from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    pp_allowed = fields.Boolean(compute='_compute_pp_allowed')
    pp_enabled = fields.Boolean('Pre-Production')
    pp_bom_id = fields.Many2one('mrp.bom', 'BOM', domain="[('product_tmpl_id', '=', product_template_id)]")
    pp_order_ids = fields.One2many('pp.order', 'sale_line_id')

    @api.depends('product_id', 'product_id.is_storable', 'product_id.type', 'product_id.categ_id',
                'product_id.categ_id.pp_enabled', 'product_id.categ_id.parent_id.pp_enabled')
    def _compute_pp_allowed(self):
        for l in self:
            p = l.product_id
            l.pp_allowed = bool(p and p.type == 'consu' and p.is_storable and p.categ_id._pp_categ())

    @api.onchange('pp_enabled')
    def _onchange_pp_enabled(self):
        for l in self:
            if l.pp_enabled and not l.pp_bom_id and l.product_id:
                bom = self.env['mrp.bom']._bom_find(l.product_id, company_id=l.company_id.id, bom_type='normal')
                l.pp_bom_id = bom.get(l.product_id)

    @api.constrains('pp_enabled', 'pp_bom_id', 'product_id')
    def _check_pp(self):
        for l in self.filtered('pp_enabled'):
            p = l.product_id
            if not (p.type == 'consu' and p.is_storable):
                raise ValidationError(_("Pre-Production applies only to storable products: %s is not storable.", p.display_name))
            if not p.categ_id._pp_categ():
                raise ValidationError(_("The category %s (and its parent categories) is not enabled for Pre-Production. "
                                        "Enable it from the product category form.", p.categ_id.display_name))
            bom = l.pp_bom_id
            if not bom:
                raise ValidationError(_("Please select a BOM for the Pre-Production line."))
            if bom.product_tmpl_id != l.product_id.product_tmpl_id or (bom.product_id and bom.product_id != l.product_id):
                raise ValidationError(_("The selected BOM does not belong to the product."))


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    pp_order_count = fields.Integer(compute='_compute_pp_order_count')

    def _compute_pp_order_count(self):
        for o in self:
            o.pp_order_count = self.env['pp.order'].search_count([('sale_order_id', '=', o.id)])

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            for line in order.order_line.filtered(lambda l: l.pp_enabled and l.pp_allowed and not l.pp_order_ids):
                self.env['pp.order'].create({
                    'sale_order_id': order.id,
                    'sale_line_id': line.id,
                    'partner_id': order.partner_id.id,
                    'product_id': line.product_id.id,
                    'product_qty': line.product_uom_qty,
                    'product_uom_id': line.product_uom.id,
                    'bom_id': line.pp_bom_id.id,
                    'company_id': order.company_id.id,
                })
        return res

    def action_view_pp_orders(self):
        return {'type': 'ir.actions.act_window', 'name': _('Pre-Production Orders'), 'res_model': 'pp.order',
                'view_mode': 'list,form', 'domain': [('sale_order_id', '=', self.id)]}
