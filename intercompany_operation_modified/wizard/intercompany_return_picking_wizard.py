# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IntercompanyReturnPickingWizard(models.TransientModel):
    _name = 'intercompany.return.picking.wizard'
    _description = 'Intercompany Return - Pickings Selection'

    return_id = fields.Many2one('intercompany.return', string='Return', required=True)
    line_ids = fields.One2many(
        'intercompany.return.picking.wizard.line', 'wizard_id', string='Pickings',
    )
    flat_move_line_ids = fields.One2many(
        'intercompany.return.picking.wizard.move.line', 'wizard_id',
        string='Products to Return',
    )
    total_pickings = fields.Integer(compute='_compute_totals', string='Total Pickings')
    total_products = fields.Integer(compute='_compute_totals', string='Total Products')

    @api.depends('flat_move_line_ids')
    def _compute_totals(self):
        for rec in self:
            rec.total_pickings = len(rec.flat_move_line_ids.mapped('picking_id'))
            rec.total_products = len(rec.flat_move_line_ids)

    def _link_picking_to_order(self, new_picking, original_picking):
        purchase = original_picking.purchase_id or original_picking.ic_purchase_order_id
        sale = (getattr(original_picking, 'sale_id', False)) or original_picking.ic_sale_order_id
        if purchase:
            new_picking.ic_purchase_order_id = purchase.id
        if sale:
            new_picking.ic_sale_order_id = sale.id

    def _process_picking(self, picking, qty_by_move_id=None, full=False, replace=False):
        if full:
            qty_by_move = {
                ml.move_id.id: ml.max_return_qty
                for ml in self.flat_move_line_ids
                if ml.picking_id == picking and ml.max_return_qty > 0
            }
        else:
            qty_by_move = {k: v for k, v in (qty_by_move_id or {}).items() if v > 0}

        if not qty_by_move:
            raise UserError(_('No quantity to return for picking %s.') % picking.name)

        return_type = picking.picking_type_id.return_picking_type_id or picking.picking_type_id

        # Return picking
        new_picking = self.env['stock.picking'].create({
            'picking_type_id': return_type.id,
            'location_id': picking.location_dest_id.id,
            'location_dest_id': picking.location_id.id,
            'origin': _('Return of %s') % picking.name,
            'company_id': picking.company_id.id,
            'partner_id': picking.partner_id.id if picking.partner_id else False,
            'intercompany_return_id': self.return_id.id,
            'is_return_replacement': False,
        })

        for move in picking.move_ids.filtered(lambda m: m.state == 'done'):
            qty = qty_by_move.get(move.id, 0.0)
            if qty <= 0:
                continue
            self.env['stock.move'].create({
                'name': _('Return of %s') % move.name,
                'product_id': move.product_id.id,
                'product_uom': move.product_uom.id,
                'product_uom_qty': qty,
                'picking_id': new_picking.id,
                'location_id': new_picking.location_id.id,
                'location_dest_id': new_picking.location_dest_id.id,
                'origin_returned_move_id': move.id,
                'company_id': picking.company_id.id,
                'procure_method': 'make_to_stock',
                'to_refund': True,
                'purchase_line_id': move.purchase_line_id.id if move.purchase_line_id else False,
                'sale_line_id': move.sale_line_id.id if hasattr(move, 'sale_line_id') and move.sale_line_id else False,
            })

        if not new_picking.move_ids:
            new_picking.unlink()
            raise UserError(_('No valid moves created for picking %s.') % picking.name)

        self._link_picking_to_order(new_picking, picking)
        new_picking.action_confirm()
        new_picking.action_assign()
        for move in new_picking.move_ids:
            move.quantity = move.product_uom_qty
        new_picking.button_validate()

        if replace:
            # Replacement picking — نفضل purchase_line_id/sale_line_id عشان
            # Odoo يحسب الـ received qty صح (received - returned + replacement = qty اتكلها)
            replacement = picking.copy({
                'origin': _('Replacement for %s') % picking.name,
                'intercompany_return_id': self.return_id.id,
                'is_return_replacement': True,
                'group_id': False,
            })
            for move in replacement.move_ids:
                move.group_id = False
                # to_refund = False عشان الـ replacement مش return
                move.to_refund = False

            self._link_picking_to_order(replacement, picking)
            replacement.action_confirm()
            replacement.action_assign()
            for move in replacement.move_ids:
                move.quantity = move.product_uom_qty
            replacement.button_validate()

    def action_return(self):
        self.ensure_one()
        lines_with_qty = self.flat_move_line_ids.filtered(lambda l: l.return_qty > 0)
        if not lines_with_qty:
            raise UserError(_('Please enter at least one quantity to return.'))
        for ml in lines_with_qty:
            if ml.return_qty > ml.max_return_qty:
                raise UserError(_(
                    'Return qty for %s (%.2f) exceeds max (%.2f).'
                ) % (ml.product_id.display_name, ml.return_qty, ml.max_return_qty))
        pickings = lines_with_qty.mapped('picking_id')
        for picking in pickings:
            qty_by_move = {
                ml.move_id.id: ml.return_qty
                for ml in lines_with_qty.filtered(lambda l: l.picking_id == picking)
            }
            self._process_picking(picking, qty_by_move_id=qty_by_move, full=False)
        self.return_id.state = 'returned'
        return {'type': 'ir.actions.act_window_close'}

    def action_return_all(self):
        self.ensure_one()
        pickings = self.flat_move_line_ids.mapped('picking_id')
        if not pickings:
            raise UserError(_('No pickings found to return.'))
        for picking in pickings:
            self._process_picking(picking, full=True, replace=False)
        self.return_id.state = 'returned'
        return {'type': 'ir.actions.act_window_close'}

    def action_return_replace(self):
        self.ensure_one()
        pickings = self.flat_move_line_ids.mapped('picking_id')
        if not pickings:
            raise UserError(_('No pickings found to return.'))
        for picking in pickings:
            self._process_picking(picking, full=True, replace=True)
        self.return_id.state = 'returned'
        return {'type': 'ir.actions.act_window_close'}


class IntercompanyReturnPickingWizardLine(models.TransientModel):
    _name = 'intercompany.return.picking.wizard.line'
    _description = 'Intercompany Return - Picking Line'

    wizard_id = fields.Many2one('intercompany.return.picking.wizard', ondelete='cascade')
    picking_id = fields.Many2one('stock.picking', string='Picking', required=True)
    order_ref = fields.Char(related='picking_id.origin', string='Order Ref.', readonly=True)
    move_line_ids = fields.One2many(
        'intercompany.return.picking.wizard.move.line', 'wizard_line_id', string='Products',
    )


class IntercompanyReturnPickingWizardMoveLine(models.TransientModel):
    _name = 'intercompany.return.picking.wizard.move.line'
    _description = 'Intercompany Return - Picking Move Line'

    wizard_id = fields.Many2one('intercompany.return.picking.wizard', ondelete='cascade')
    wizard_line_id = fields.Many2one('intercompany.return.picking.wizard.line', ondelete='cascade')
    picking_id = fields.Many2one('stock.picking', string='Picking', readonly=True)
    order_ref = fields.Char(related='picking_id.origin', string='Order Ref.', readonly=True)
    move_id = fields.Many2one('stock.move', string='Move')
    product_id = fields.Many2one('product.product', string='Product')
    product_uom_id = fields.Many2one(related='move_id.product_uom', string='Unit', readonly=True)
    original_qty = fields.Float(string='Delivered Qty', readonly=True)
    already_returned_qty = fields.Float(
        string='Already Returned', readonly=True,
        compute='_compute_already_returned',
    )
    max_return_qty = fields.Float(
        string='Max. Returnable', readonly=True,
        compute='_compute_already_returned',
    )
    return_qty = fields.Float(string='Qty to Return')

    @api.depends('move_id', 'original_qty')
    def _compute_already_returned(self):
        for rec in self:
            if rec.move_id:
                returned = sum(
                    rec.move_id.returned_move_ids.filtered(
                        lambda m: m.state == 'done'
                        and not m.picking_id.is_return_replacement
                    ).mapped('quantity')
                )
                rec.already_returned_qty = returned
                rec.max_return_qty = max(0.0, rec.original_qty - returned)
            else:
                rec.already_returned_qty = 0.0
                rec.max_return_qty = rec.original_qty
