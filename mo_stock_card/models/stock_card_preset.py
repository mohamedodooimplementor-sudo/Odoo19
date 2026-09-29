# -*- coding: utf-8 -*-
from odoo import models, fields, api


class StockCardPreset(models.Model):
    _name = 'stock.card.preset'
    _description = 'Stock Card Report - Saved Filter'
    _order = 'name'

    name = fields.Char(string='Filter Name', required=True)
    user_id = fields.Many2one(
        'res.users', string='Saved By', default=lambda self: self.env.user, readonly=True
    )
    is_default = fields.Boolean(
        string='Default Filter',
        help='Automatically applied every time you open a fresh Stock Card Report wizard '
             '(only the Period is left for you to set).'
    )
    is_auto_last_used = fields.Boolean(
        string='Auto: Last Used Settings',
        help='Internal, hidden entry auto-updated after every report you generate — '
             "used by the wizard's \"Load Last Used\" button. Not shown in the normal picker."
    )

    # Location
    location_ids = fields.Many2many(
        'stock.location', 'stock_card_preset_location_rel', 'preset_id', 'location_id',
        string='Locations'
    )
    include_child_locations = fields.Boolean(string='Include Child Locations', default=True)
    company_id = fields.Many2one('res.company', string='Company')
    company_ids = fields.Many2many(
        'res.company', 'stock_card_preset_company_rel', 'preset_id', 'res_company_id',
        string='Consolidate Companies'
    )
    consolidation_currency_id = fields.Many2one('res.currency', string='Consolidation Currency')

    # Product filter
    filter_by = fields.Selection([
        ('product', 'Product'),
        ('category', 'Product Category'),
    ], string='Filter By', default='product')
    product_ids = fields.Many2many(
        'product.product', 'stock_card_preset_product_rel', 'preset_id', 'product_id',
        string='Products'
    )
    categ_ids = fields.Many2many(
        'product.category', 'stock_card_preset_categ_rel', 'preset_id', 'categ_id',
        string='Product Categories'
    )
    picking_type_ids = fields.Many2many(
        'stock.picking.type', 'stock_card_preset_picking_type_rel', 'preset_id', 'picking_type_id',
        string='Operation Types'
    )

    # Grouping / options
    group_by = fields.Selection([
        ('product', 'Product'),
        ('category', 'Category'),
        ('warehouse', 'Warehouse'),
    ], string='Group By', default='product')
    show_reconciliation = fields.Boolean(string='Compare With Live On-Hand Quantity')
    print_with_costs = fields.Boolean(string='Print With Costs & Valuation')
    include_zero_movements = fields.Boolean(string='Include Zero Movements')
    only_products_with_movement = fields.Boolean(string='Only Products With Movement')

    _sql_constraints = [
        ('name_user_uniq', 'unique(name, user_id)',
         'You already have a saved filter with this name. Use a different name, or delete the old one first.'),
    ]

    def write(self, vals):
        res = super().write(vals)
        if vals.get('is_default'):
            for rec in self:
                other_defaults = self.search([
                    ('user_id', '=', rec.user_id.id), ('id', '!=', rec.id), ('is_default', '=', True)
                ])
                if other_defaults:
                    other_defaults.write({'is_default': False})
        return res

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.is_default:
                other_defaults = self.search([
                    ('user_id', '=', rec.user_id.id), ('id', '!=', rec.id), ('is_default', '=', True)
                ])
                if other_defaults:
                    other_defaults.write({'is_default': False})
        return records
