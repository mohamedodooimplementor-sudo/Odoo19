# -*- coding: utf-8 -*-
from odoo import fields, models


class StockLandedCost(models.Model):
    _inherit = 'stock.landed.cost'

    intercompany_operation_id = fields.Many2one(
        'intercompany.operation',
        string='Intercompany Operation',
        copy=False,
        index=True,
    )

    intercompany_vendor_bill_id = fields.Many2one(
        'account.move',
        string='Source Intercompany Bill',
        copy=False,
        index=True,
        domain=[('move_type', '=', 'in_invoice')],
    )


class StockLandedCostLines(models.Model):
    """Add tax support to Landed Cost cost lines."""
    _inherit = 'stock.landed.cost.lines'

    tax_ids = fields.Many2many(
        'account.tax',
        'stock_landed_cost_line_tax_rel',
        'landed_cost_line_id',
        'tax_id',
        string='Taxes',
        domain="[('type_tax_use', 'in', ('purchase', 'none')), ('company_id', '=', company_id)]",
        help='Taxes to apply when posting this landed cost line.',
    )

    company_id = fields.Many2one(
        related='cost_id.company_id',
        store=True,
        readonly=True,
    )

    price_with_tax = fields.Float(
        string='Total incl. Tax',
        compute='_compute_price_with_tax',
        digits='Account',
        help='Price unit including computed taxes.',
    )

    def _compute_price_with_tax(self):
        for line in self:
            if line.tax_ids:
                taxes = line.tax_ids.compute_all(
                    line.price_unit, currency=line.cost_id.company_id.currency_id,
                    quantity=1.0,
                )
                line.price_with_tax = taxes['total_included']
            else:
                line.price_with_tax = line.price_unit
