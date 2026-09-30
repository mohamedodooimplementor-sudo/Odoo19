# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    construction_boq_line_id = fields.Many2one(
        'construction.boq.line', string='Construction BOQ Item',
        help='When set, goods receipts posted against this line automatically create an '
             'Actual Cost entry against this BOQ item in the Construction Suite.')
    construction_project_id = fields.Many2one(
        'construction.project', string='Construction Project',
        related='construction_boq_line_id.project_id', store=True)


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    construction_project_id = fields.Many2one(
        'construction.project', string='Construction Project',
        compute='_compute_construction_project', store=True)

    @api.depends('order_line.construction_boq_line_id.project_id')
    def _compute_construction_project(self):
        for order in self:
            projects = order.order_line.construction_boq_line_id.project_id
            order.construction_project_id = projects[:1].id if projects else False


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_done(self, cancel_backorder=False):
        moves = super()._action_done(cancel_backorder=cancel_backorder)
        for move in moves:
            move._construction_create_actual_cost()
        return moves

    def _construction_create_actual_cost(self):
        """When a goods receipt is validated against a Purchase Order line that is linked to a
        BOQ item, automatically post the corresponding Actual Cost so budget-vs-actual figures
        stay up to date without any manual data entry."""
        self.ensure_one()
        po_line = self.purchase_line_id
        if not po_line or not po_line.construction_boq_line_id:
            return
        if self.state != 'done':
            return
        ActualCost = self.env['construction.actual.cost'].sudo()
        if ActualCost.search_count([('stock_move_id', '=', self.id)]):
            return  # already posted for this specific move (avoid duplicates on re-processing)

        qty = getattr(self, 'quantity', None)
        if not qty:
            qty = getattr(self, 'quantity_done', None) or self.product_uom_qty
        if not qty:
            return

        boq_line = po_line.construction_boq_line_id
        ActualCost.create({
            'project_id': boq_line.project_id.id,
            'contract_id': boq_line.contract_id.id,
            'date': fields.Date.context_today(self),
            'cost_type': 'material',
            'description': _('Goods Receipt: %s (%s)') % (
                po_line.product_id.display_name, self.picking_id.name or po_line.order_id.name),
            'quantity': qty,
            'unit_price': po_line.price_unit,
            'boq_line_id': boq_line.id,
            'purchase_order_id': po_line.order_id.id,
            'cost_code_id': boq_line.cost_code_id.id,
            'stock_move_id': self.id,
        })
