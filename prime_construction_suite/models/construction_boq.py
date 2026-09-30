# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ConstructionBoqSection(models.Model):
    _name = 'construction.boq.section'
    _description = 'BOQ Section'
    _order = 'sequence, id'

    sequence    = fields.Integer(default=10)
    name        = fields.Char(string='Section Name', required=True)
    code        = fields.Char(string='Code')
    contract_id = fields.Many2one('construction.contract', string='Contract', ondelete='cascade')
    project_id  = fields.Many2one(related='contract_id.project_id', store=True)
    currency_id = fields.Many2one(related='contract_id.currency_id', store=True)
    line_ids    = fields.One2many('construction.boq.line', 'section_id', string='Lines')
    total_section = fields.Monetary(string='Section Total', currency_field='currency_id',
                                    compute='_compute_total', store=True)
    line_count  = fields.Integer(compute='_compute_total', store=True)

    @api.depends('line_ids.total_price')
    def _compute_total(self):
        for rec in self:
            rec.line_count    = len(rec.line_ids)
            rec.total_section = sum(rec.line_ids.mapped('total_price'))


class ConstructionBoqLine(models.Model):
    _name = 'construction.boq.line'
    _description = 'BOQ Line'
    _order = 'sequence, id'

    sequence    = fields.Integer(default=10)
    contract_id = fields.Many2one('construction.contract', string='Contract', ondelete='cascade', required=True, index=True)
    project_id  = fields.Many2one(related='contract_id.project_id', store=True)
    company_id  = fields.Many2one(related='contract_id.company_id', store=True)
    currency_id = fields.Many2one(related='contract_id.currency_id', store=True)
    section_id  = fields.Many2one('construction.boq.section', string='Section',
                                   domain="[('contract_id','=',contract_id)]", ondelete='restrict')
    section_name = fields.Char(related='section_id.name', store=True, string='Section')

    item_code   = fields.Char(string='Item Code')
    cost_code_id = fields.Many2one('construction.cost.code', string='Cost Code (WBS)')
    description = fields.Text(string='Description', required=True)
    notes       = fields.Text(string='Technical Notes')
    line_type   = fields.Selection([
        ('work',      'Work Item'),
        ('supply',    'Supply'),
        ('lump_sum',  'Lump Sum'),
        ('allowance', 'Allowance'),
    ], string='Type', default='work', required=True)

    uom_id         = fields.Many2one('uom.uom', string='UoM', required=True)
    qty_contract   = fields.Float(string='Contract Qty',  digits=(12, 3))
    qty_executed   = fields.Float(string='Executed Qty',  digits=(12, 3), compute='_compute_executed', store=True)
    qty_remaining  = fields.Float(string='Remaining Qty', digits=(12, 3), compute='_compute_executed', store=True)
    qty_variation  = fields.Float(string='Variation Qty', digits=(12, 3), compute='_compute_executed', store=True)
    unit_price     = fields.Monetary(string='Unit Price',  currency_field='currency_id')
    total_price    = fields.Monetary(string='Total Price', currency_field='currency_id', compute='_compute_totals', store=True)
    executed_value = fields.Monetary(string='Executed Value', currency_field='currency_id', compute='_compute_totals', store=True)
    completion_percent = fields.Float(string='Completion %', compute='_compute_totals', store=True)

    state = fields.Selection([
        ('pending',     'Pending'),
        ('in_progress', 'In Progress'),
        ('completed',   'Completed'),
        ('on_hold',     'On Hold'),
    ], string='Status', default='pending')

    progress_line_ids     = fields.One2many('construction.progress.invoice.line', 'boq_line_id')
    change_order_line_ids = fields.One2many('construction.change.order.line',     'boq_line_id')
    actual_cost_ids       = fields.One2many('construction.actual.cost', 'boq_line_id', string='Actual Costs')

    # ── Site Measurement (physical quantities executed, independent of billing) ──
    measurement_line_ids = fields.One2many(
        'construction.measurement.sheet.line', 'boq_line_id', string='Measurement Sheet Entries')
    qty_measured = fields.Float(
        string='Measured Qty (Site)', digits=(12, 3), compute='_compute_measured', store=True,
        help='Cumulative quantity physically executed on site, from approved Measurement Sheets. '
             'This is the source used to auto-fill quantities on new Progress Invoices.')
    qty_measured_remaining = fields.Float(
        string='Remaining to Measure', digits=(12, 3), compute='_compute_measured', store=True)
    physical_completion_percent = fields.Float(
        string='Physical Completion %', compute='_compute_measured', store=True,
        help='Based on quantities measured on site, as opposed to Completion % which is based on billed quantities.')
    qty_measured_uninvoiced = fields.Float(
        string='Measured, Not Yet Invoiced', digits=(12, 3), compute='_compute_measured', store=True,
        help='Approved measured quantity still available to be picked up on a new Progress Invoice.')
    measurement_count = fields.Integer(compute='_compute_measured', string='Measurement Sheets')

    @api.depends('measurement_line_ids.qty_today', 'measurement_line_ids.sheet_id.state',
                 'qty_contract', 'qty_executed')
    def _compute_measured(self):
        for rec in self:
            approved = rec.measurement_line_ids.filtered(lambda l: l.sheet_id.state == 'approved')
            rec.qty_measured = sum(approved.mapped('qty_today'))
            rec.qty_measured_remaining = rec.qty_contract - rec.qty_measured
            rec.physical_completion_percent = (
                min(rec.qty_measured / rec.qty_contract * 100, 100.0) if rec.qty_contract else 0.0)
            rec.qty_measured_uninvoiced = max(rec.qty_measured - rec.qty_executed, 0.0)
            rec.measurement_count = len(rec.measurement_line_ids.mapped('sheet_id'))

    def action_view_measurements(self):
        self.ensure_one()
        sheets = self.measurement_line_ids.mapped('sheet_id')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Measurement Sheets'),
            'res_model': 'construction.measurement.sheet',
            'view_mode': 'list,form',
            'domain': [('id', 'in', sheets.ids)],
        }

    # ── Purchasing & Inventory integration ──
    product_id = fields.Many2one(
        'product.product', string='Product', domain="[('purchase_ok', '=', True)]",
        help='Optional: link this BOQ item to a purchasable/stockable product. Once set, you can '
             'generate Purchase Orders directly from this line, and goods receipts against those '
             'orders will automatically post an Actual Cost entry here.')
    purchase_line_ids = fields.One2many(
        'purchase.order.line', 'construction_boq_line_id', string='Purchase Order Lines')
    purchase_count = fields.Integer(compute='_compute_purchase_stats', string='Purchases')
    qty_purchased  = fields.Float(string='Qty Ordered', compute='_compute_purchase_stats',
                                   store=True, digits=(12, 3))
    qty_received   = fields.Float(string='Qty Received', compute='_compute_purchase_stats',
                                   store=True, digits=(12, 3))

    @api.depends('purchase_line_ids.product_qty', 'purchase_line_ids.qty_received',
                 'purchase_line_ids.order_id.state')
    def _compute_purchase_stats(self):
        for rec in self:
            lines = rec.purchase_line_ids.filtered(lambda l: l.order_id.state in ('purchase', 'done'))
            rec.qty_purchased  = sum(lines.mapped('product_qty'))
            rec.qty_received   = sum(lines.mapped('qty_received'))
            rec.purchase_count = len(lines.mapped('order_id'))

    def action_create_purchase_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Purchase Order'),
            'res_model': 'construction.boq.purchase.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_boq_line_id': self.id},
        }

    def action_view_purchases(self):
        self.ensure_one()
        orders = self.purchase_line_ids.mapped('order_id')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Purchase Orders'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', orders.ids)],
        }

    actual_cost_amount  = fields.Monetary(string='Actual Cost', currency_field='currency_id',
                                           compute='_compute_actual_cost', store=True)
    cost_variance       = fields.Monetary(string='Budget Variance', currency_field='currency_id',
                                           compute='_compute_actual_cost', store=True,
                                           help='Budget (BOQ Total Price) minus Actual Cost incurred against this item. Positive = under budget.')
    cost_variance_percent = fields.Float(string='Variance %', compute='_compute_actual_cost', store=True)

    @api.depends('actual_cost_ids.amount', 'actual_cost_ids.state', 'total_price')
    def _compute_actual_cost(self):
        for rec in self:
            approved = rec.actual_cost_ids.filtered(lambda c: c.state == 'approved')
            rec.actual_cost_amount = sum(approved.mapped('amount'))
            rec.cost_variance = rec.total_price - rec.actual_cost_amount
            rec.cost_variance_percent = (rec.cost_variance / rec.total_price * 100) if rec.total_price else 0.0

    @api.depends('progress_line_ids.qty_this_invoice', 'progress_line_ids.invoice_id.state')
    def _compute_executed(self):
        for rec in self:
            confirmed = rec.progress_line_ids.filtered(lambda l: l.invoice_id.state in ('approved','invoiced','paid'))
            rec.qty_executed  = sum(confirmed.mapped('qty_this_invoice'))
            rec.qty_remaining = rec.qty_contract - rec.qty_executed
            rec.qty_variation = rec.qty_executed - rec.qty_contract

    @api.depends('qty_contract', 'unit_price', 'qty_executed')
    def _compute_totals(self):
        for rec in self:
            rec.total_price        = rec.qty_contract * rec.unit_price
            rec.executed_value     = rec.qty_executed * rec.unit_price
            rec.completion_percent = min(rec.qty_executed / rec.qty_contract * 100, 100.0) if rec.qty_contract else 0.0

    @api.constrains('qty_contract')
    def _check_qty(self):
        for rec in self:
            if rec.line_type != 'allowance' and rec.qty_contract < 0:
                raise ValidationError(_('Contract quantity cannot be negative!'))
