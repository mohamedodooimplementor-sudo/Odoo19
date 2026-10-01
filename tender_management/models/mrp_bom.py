# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

COST_TYPES = [
    ('labour', 'Labour'),
    ('overhead', 'Overhead'),
    ('other', 'Other'),
]


class MrpBomCostLine(models.Model):
    _name = 'mrp.bom.cost.line'
    _description = 'BOM Manufacturing Cost Line'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    bom_id = fields.Many2one('mrp.bom', string='Bill of Materials', required=True,
                             ondelete='cascade', index=True)
    company_id = fields.Many2one(related='bom_id.company_id', store=True)
    currency_id = fields.Many2one('res.currency', compute='_compute_currency_id')
    cost_type = fields.Selection(COST_TYPES, string='Cost Type', required=True, default='labour')
    name = fields.Char(string='Description')
    amount = fields.Monetary(string='Amount', currency_field='currency_id', required=True,
                             help='Cost for the full quantity produced by the BOM.')
    account_id = fields.Many2one(
        'account.account', string='Account', compute='_compute_account_id',
        store=True, readonly=False, precompute=True,
        domain="[('account_type', 'not in', ('asset_receivable', 'liability_payable'))]",
        help='Account credited when this cost is absorbed into the production cost.')

    @api.depends('bom_id.company_id')
    def _compute_currency_id(self):
        for line in self:
            company = line.bom_id.company_id or self.env.company
            line.currency_id = company.currency_id

    @api.depends('cost_type', 'bom_id.company_id')
    def _compute_account_id(self):
        for line in self:
            company = line.bom_id.company_id or self.env.company
            mapping = {
                'labour': company.tm_labour_account_id,
                'overhead': company.tm_overhead_account_id,
                'other': company.tm_other_account_id,
            }
            line.account_id = mapping.get(line.cost_type) or False

    @api.constrains('amount', 'account_id')
    def _check_line(self):
        for line in self:
            if line.amount < 0:
                raise ValidationError(_('Manufacturing cost amounts cannot be negative.'))
            if not line.account_id:
                raise ValidationError(_(
                    'Please choose an account for the %s cost line (or set default accounts '
                    'in Tenders > Configuration > Settings).') % dict(COST_TYPES)[line.cost_type])


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    mfg_cost_line_ids = fields.One2many(
        'mrp.bom.cost.line', 'bom_id', string='Manufacturing Costs', copy=True)
    tm_currency_id = fields.Many2one('res.currency', compute='_compute_tm_currency_id')
    tm_material_cost = fields.Monetary(
        'Material Cost', compute='_compute_tm_costs', currency_field='tm_currency_id')
    tm_mfg_cost = fields.Monetary(
        'Manufacturing Costs', compute='_compute_tm_costs', currency_field='tm_currency_id')
    tm_total_cost = fields.Monetary(
        'Total BOM Cost', compute='_compute_tm_costs', currency_field='tm_currency_id')
    tm_unit_cost = fields.Monetary(
        'Cost / Unit', compute='_compute_tm_costs', currency_field='tm_currency_id',
        help='Total BOM Cost divided by the BOM quantity (in the product unit of measure).')

    @api.depends('company_id')
    def _compute_tm_currency_id(self):
        for bom in self:
            bom.tm_currency_id = (bom.company_id or self.env.company).currency_id

    def _tm_unit_factor(self):
        """1 / (BOM quantity expressed in the product's own UoM)."""
        self.ensure_one()
        qty = self.product_uom_id._compute_quantity(
            self.product_qty, self.product_tmpl_id.uom_id, round=False)
        return 1.0 / qty if qty else 0.0

    @api.depends('bom_line_ids.product_id', 'bom_line_ids.product_qty',
                 'bom_line_ids.product_uom_id', 'mfg_cost_line_ids.amount',
                 'product_qty', 'product_uom_id', 'product_tmpl_id', 'company_id')
    def _compute_tm_costs(self):
        for bom in self:
            b = bom.sudo()
            company = b.company_id or self.env.company
            material = 0.0
            for line in b.bom_line_ids:
                product = line.product_id.with_company(company)
                qty = line.product_uom_id._compute_quantity(
                    line.product_qty, product.uom_id, round=False)
                material += product.standard_price * qty
            mfg = sum(b.mfg_cost_line_ids.mapped('amount'))
            bom.tm_material_cost = material
            bom.tm_mfg_cost = mfg
            bom.tm_total_cost = material + mfg
            bom.tm_unit_cost = (material + mfg) * b._tm_unit_factor()

    tm_tender_count = fields.Integer('Tenders', compute='_compute_tm_tender_count')

    def _compute_tm_tender_count(self):
        Tender = self.env['tm.tender'].sudo()
        for bom in self:
            bom.tm_tender_count = Tender.search_count([('line_ids.bom_id', '=', bom.id)])

    def action_view_tm_tenders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Tenders'),
            'res_model': 'tm.tender',
            'view_mode': 'list,form',
            'domain': [('line_ids.bom_id', '=', self.id)],
        }

    def _tm_unit_breakdown(self):
        """Materials / Labour / Overhead / Other per unit of the product (product UoM)."""
        self.ensure_one()
        bom = self.sudo()
        factor = bom._tm_unit_factor()
        per_type = {'labour': 0.0, 'overhead': 0.0, 'other': 0.0}
        for line in bom.mfg_cost_line_ids:
            per_type[line.cost_type] += line.amount
        return {
            'material': bom.tm_material_cost * factor,
            'labour': per_type['labour'] * factor,
            'overhead': per_type['overhead'] * factor,
            'other': per_type['other'] * factor,
        }

    def _tm_report_lines(self):
        """Component rows for the BOM cost sheet."""
        self.ensure_one()
        bom = self.sudo()
        company = bom.company_id or self.env.company
        rows = []
        for line in bom.bom_line_ids:
            product = line.product_id.with_company(company)
            std_qty = line.product_uom_id._compute_quantity(
                line.product_qty, product.uom_id, round=False)
            cost = product.standard_price * std_qty
            rows.append({
                'product': product.display_name,
                'qty': line.product_qty,
                'uom': line.product_uom_id.name,
                'unit_cost': cost / line.product_qty if line.product_qty else 0.0,
                'cost': cost,
            })
        return rows
