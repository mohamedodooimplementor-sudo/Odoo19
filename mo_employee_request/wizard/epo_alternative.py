# -*- coding: utf-8 -*-
"""Purchase Alternatives for Employee Purchase Orders (same idea as Odoo's RFQ alternatives).

  * Create Alternative : copies an RFQ for one or more other vendors and links them together
  * Warning on confirm : when an RFQ with open alternatives is sent for approval, ask whether
                         the remaining alternatives should be cancelled
"""
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class EmployeePurchaseOrderAlternative(models.TransientModel):
    _name = 'employee.purchase.order.alternative'
    _description = 'Create Alternative Purchase Order'

    order_id = fields.Many2one(
        'employee.purchase.order', required=True, ondelete='cascade',
        default=lambda self: self.env.context.get('default_order_id')
        or self.env.context.get('active_id'))
    partner_ids = fields.Many2many('res.partner', string='Vendors', required=True)
    copy_products = fields.Boolean(
        string='Copy Products', default=True,
        help="Copy the lines of the current order to the alternatives.")

    def _vendor_price(self, line, partner):
        """(price, discount) of `line`'s product for `partner`, from the product's Purchase tab."""
        product = line.product_id
        price, discount = product.standard_price, 0.0
        seller = product._select_seller(
            partner_id=partner, quantity=line.product_uom_qty, uom_id=line.product_uom_id)
        if seller:
            price = seller.price
            seller_uom = seller.product_uom_id if 'product_uom_id' in seller._fields else False
            if seller_uom and line.product_uom_id and seller_uom != line.product_uom_id:
                try:
                    price = seller_uom._compute_price(price, line.product_uom_id)
                except Exception:
                    pass
            discount = seller.discount if 'discount' in seller._fields else 0.0
        return price, discount

    def action_create_alternatives(self):
        self.ensure_one()
        order = self.order_id
        order._check_user_rights()
        if order.state != 'draft':
            raise UserError(_("Alternatives can only be created while the order is in RFQ."))
        taken = order.partner_id | order.alternative_ids.partner_id
        new_orders = self.env['employee.purchase.order']
        sources = order.line_ids.sorted(lambda l: (l.sequence, l.id))
        for partner in self.partner_ids - taken:
            new = order.copy({
                'partner_id': partner.id,
                'request_id': order.request_id.id,
                'alt_excluded': True,
            })
            new._onchange_partner_id()
            if self.copy_products:
                copies = new.line_ids.sorted(lambda l: (l.sequence, l.id))
                for src, dst in zip(sources, copies):
                    vals = {'request_line_id': src.request_line_id.id}
                    if not dst._is_discount_line():
                        vals['price_unit'], vals['discount'] = self._vendor_price(dst, partner)
                    dst.write(vals)
            else:
                new.line_ids.unlink()
            new.message_post(
                body=_("Created as an alternative of %s.", order.name),
                subtype_xmlid='mail.mt_note')
            new_orders |= new
        if not new_orders:
            raise UserError(_("These vendors already have an RFQ in this group of alternatives."))
        order._link_alternatives(new_orders)
        order.message_post(
            body=_("Alternatives created: %s", ", ".join(new_orders.mapped('name'))),
            subtype_xmlid='mail.mt_note')
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}


class EmployeePurchaseOrderAlternativeWarning(models.TransientModel):
    _name = 'employee.purchase.order.alternative.warning'
    _description = 'Purchase Order Alternatives Warning'

    order_id = fields.Many2one(
        'employee.purchase.order', required=True, ondelete='cascade',
        default=lambda self: self.env.context.get('default_order_id'))
    message = fields.Text(compute='_compute_message')

    @api.depends('order_id')
    def _compute_message(self):
        for wiz in self:
            names = ", ".join(wiz.order_id._get_open_alternatives().mapped('name'))
            wiz.message = _(
                "This order has alternatives that are still in RFQ: %s.\n"
                "Do you want to cancel them before sending this order for approval?", names)

    def _confirm(self):
        return self.order_id.with_context(skip_alternative_check=True).action_confirm()

    def action_cancel_alternatives(self):
        self.ensure_one()
        self.order_id._get_open_alternatives().action_cancel()
        self._confirm()
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}

    def action_keep_alternatives(self):
        self.ensure_one()
        self._confirm()
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}
