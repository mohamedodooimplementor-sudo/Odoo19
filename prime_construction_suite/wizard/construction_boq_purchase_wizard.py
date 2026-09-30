# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionBoqPurchaseWizard(models.TransientModel):
    _name = 'construction.boq.purchase.wizard'
    _description = 'Create Purchase Order from BOQ Item'

    boq_line_id = fields.Many2one('construction.boq.line', required=True, ondelete='cascade')
    project_id  = fields.Many2one(related='boq_line_id.project_id', readonly=True)
    description = fields.Text(related='boq_line_id.description', readonly=True)
    product_id  = fields.Many2one(
        'product.product', string='Product', required=True,
        domain="[('purchase_ok', '=', True)]",
        help='Defaults to the product linked on the BOQ item, if any.')
    vendor_id    = fields.Many2one('res.partner', string='Vendor', required=True)
    quantity     = fields.Float(string='Quantity to Purchase', required=True, digits=(12, 3))
    price_unit   = fields.Float(string='Unit Price', required=True)
    date_planned = fields.Datetime(string='Expected Date', default=fields.Datetime.now)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        boq_line_id = self.env.context.get('default_boq_line_id') or res.get('boq_line_id')
        if boq_line_id:
            line = self.env['construction.boq.line'].browse(boq_line_id)
            if 'product_id' in fields_list and line.product_id:
                res.setdefault('product_id', line.product_id.id)
            if 'quantity' in fields_list:
                remaining = max(line.qty_contract - line.qty_purchased, 0.0)
                res.setdefault('quantity', remaining or line.qty_contract)
            if 'price_unit' in fields_list:
                res.setdefault('price_unit', line.unit_price)
        return res

    def action_create_purchase_order(self):
        self.ensure_one()
        if not self.product_id:
            raise UserError(_('Please select a product before creating a Purchase Order.'))
        if self.quantity <= 0:
            raise UserError(_('Quantity to purchase must be greater than zero.'))

        boq_line = self.boq_line_id
        if not boq_line.product_id:
            # keep the BOQ item and product linked for future reference / receipt tracking
            boq_line.product_id = self.product_id.id

        PurchaseOrder = self.env['purchase.order']
        POLine = self.env['purchase.order.line']

        # Reuse an existing draft PO for the same vendor & project when possible,
        # instead of creating a new one for every single BOQ item.
        existing = PurchaseOrder.search([
            ('partner_id', '=', self.vendor_id.id),
            ('state', '=', 'draft'),
            ('construction_project_id', '=', boq_line.project_id.id),
        ], limit=1)

        analytic_distribution = {}
        if boq_line.project_id.analytic_account_id and 'analytic_distribution' in POLine._fields:
            analytic_distribution = {str(boq_line.project_id.analytic_account_id.id): 100.0}

        uom_field = 'product_uom_id' if 'product_uom_id' in POLine._fields else 'product_uom'
        line_vals = {
            'product_id': self.product_id.id,
            'name': boq_line.description,
            'product_qty': self.quantity,
            uom_field: (self.product_id.uom_po_id.id or self.product_id.uom_id.id),
            'price_unit': self.price_unit,
            'date_planned': self.date_planned,
            'construction_boq_line_id': boq_line.id,
        }
        if analytic_distribution:
            line_vals['analytic_distribution'] = analytic_distribution

        if existing:
            po = existing
            po.write({'order_line': [(0, 0, line_vals)]})
        else:
            po = PurchaseOrder.create({
                'partner_id': self.vendor_id.id,
                'company_id': boq_line.project_id.company_id.id,
                'origin': _('BOQ: %s') % (boq_line.description or ''),
                'order_line': [(0, 0, line_vals)],
            })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': po.id,
            'view_mode': 'form',
            'target': 'current',
        }
