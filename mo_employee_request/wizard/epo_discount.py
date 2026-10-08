# -*- coding: utf-8 -*-
"""Discount wizard for Employee Purchase Orders - same mechanism as the Sales "Discount" button.

  * On All Order Lines : writes the percentage on every line's Discount % column
  * Global Discount    : adds negative "Discount" line(s) = percentage of the order,
                         one per tax group so the taxes stay correct
  * Fixed Amount       : adds one negative "Discount" line with the given amount
"""
from collections import defaultdict

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class EmployeePurchaseOrderDiscount(models.TransientModel):
    _name = 'employee.purchase.order.discount'
    _description = 'Employee Purchase Order Discount Wizard'

    order_id = fields.Many2one(
        'employee.purchase.order', required=True, ondelete='cascade',
        default=lambda self: self.env.context.get('active_id'))
    company_id = fields.Many2one(related='order_id.company_id')
    currency_id = fields.Many2one(related='order_id.currency_id')
    discount_amount = fields.Monetary(string="Amount")
    discount_percentage = fields.Float(string="Percentage")
    discount_type = fields.Selection(
        [('sol_discount', "On All Order Lines"),
         ('so_discount', "Global Discount"),
         ('amount', "Fixed Amount")],
        string="Discount Type", default='sol_discount', required=True)

    @api.constrains('discount_type', 'discount_percentage', 'discount_amount')
    def _check_discount_amount(self):
        for wizard in self:
            if wizard.discount_type in ('sol_discount', 'so_discount') and \
                    not 0.0 <= wizard.discount_percentage <= 1.0:
                raise ValidationError(_("Invalid discount percentage."))
            if wizard.discount_type == 'amount' and wizard.discount_amount < 0:
                raise ValidationError(_("The discount amount cannot be negative."))

    # ------------------------------------------------------------------
    def _get_discount_product(self):
        self.ensure_one()
        company = self.company_id.sudo()
        if not company.er_discount_product_id:
            company.er_discount_product_id = self.env['product.product'].sudo().create({
                'name': _("Discount"),
                'type': 'service',
                'purchase_method': 'purchase',   # billed on ordered quantity
                'list_price': 0.0,
                'standard_price': 0.0,
                'sale_ok': False,
                'purchase_ok': True,
                'company_id': company.id,
            })
        return company.er_discount_product_id

    def _prepare_discount_line_values(self, product, amount, taxes, description=None):
        self.ensure_one()
        return {
            'order_id': self.order_id.id,
            'product_id': product.id,
            'name': description or product.display_name,
            'product_uom_qty': 1.0,
            'product_uom_id': product.uom_id.id,
            'price_unit': -amount,
            'sequence': 999,
            'tax_ids': [Command.set(taxes.ids)],
        }

    def _create_discount_lines(self):
        self.ensure_one()
        order = self.order_id
        product = self._get_discount_product()
        if self.discount_type == 'amount':
            vals_list = [self._prepare_discount_line_values(
                product, self.discount_amount, self.env['account.tax'])]
        else:
            subtotal_per_taxes = defaultdict(float)
            for line in order.line_ids:
                if not line.product_uom_qty or not line.price_unit:
                    continue
                subtotal_per_taxes[line.tax_ids] += line.price_subtotal
            if not subtotal_per_taxes:
                raise UserError(_("There are no order lines to apply a discount on."))
            percent = self.discount_percentage * 100
            vals_list = []
            for taxes, subtotal in subtotal_per_taxes.items():
                if len(subtotal_per_taxes) == 1:
                    desc = _("Discount: %(percent)s%%", percent=percent)
                else:
                    desc = _("Discount: %(percent)s%% - On products with the following taxes %(taxes)s",
                             percent=percent, taxes=", ".join(taxes.mapped('name')) or _("no taxes"))
                vals_list.append(self._prepare_discount_line_values(
                    product, subtotal * self.discount_percentage, taxes, desc))
        return self.env['employee.purchase.order.line'].create(vals_list)

    def action_apply_discount(self):
        self.ensure_one()
        order = self.order_id
        if order.state != 'draft' and not (order.state == 'budget_control' and order.can_edit_budget):
            raise UserError(_("A discount can only be added while the order is in RFQ "
                              "(or in Budget Control)."))
        if self.discount_type == 'sol_discount':
            order.line_ids.filtered(lambda l: not l._is_discount_line()).write(
                {'discount': self.discount_percentage * 100})
        else:
            self._create_discount_lines()
        return {'type': 'ir.actions.act_window_close'}
