from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    pp_order_id = fields.Many2one('pp.order', 'Pre-Production Order', index=True, copy=False)
    pp_issue_type = fields.Selection([('material', 'Material'), ('packaging', 'Packaging')], copy=False)
    pp_finished = fields.Boolean('Finished Product Transfer', copy=False)

    def _action_done(self):
        res = super()._action_done()
        for p in self.filtered(lambda x: x.pp_order_id and x.pp_issue_type and x.state == 'done'):
            order = p.pp_order_id.sudo()
            if not order.lock_ids.filtered(lambda l: l.picking_id == p):
                order._create_locks(p)
            order._finalize_issue()
        return res


class StockMove(models.Model):
    _inherit = 'stock.move'

    pp_order_id = fields.Many2one('pp.order', 'Pre-Production Order', index=True, copy=False)
    pp_line_id = fields.Many2one('pp.order.line', copy=False)
    pp_packaging = fields.Boolean('Packaging (not consumed)', copy=False)


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    pp_order_id = fields.Many2one('pp.order', 'Pre-Production Order', index=True, copy=False)
    pp_extra_ids = fields.One2many('pp.mo.extra', 'mo_id', 'Extra Compound', readonly=True, copy=False)

    def button_mark_done(self):
        res = super().button_mark_done()
        # whether the MO is closed automatically or by hand, send the finished product to its category warehouse
        for mo in self.filtered(lambda m: m.pp_order_id and m.state == 'done'):
            mo.pp_order_id.sudo()._create_finished_transfer()
        return res

    def action_confirm(self):
        res = super().action_confirm()
        for mo in self.filtered(lambda m: m.pp_order_id and m.state == 'confirmed' and not m.pp_order_id.mo_confirmed):
            mo.pp_order_id.sudo()._bind_locks()
        return res

    def unlink(self):
        for move in self:
            line = move.pp_line_id
            if line and (line.issued or move.picking_id.state == 'done'):
                raise ValidationError(_(
                    "You cannot delete the stock move for %(product)s because it belongs to an issued Pre-Production line.",
                    product=move.product_id.display_name))
        return super().unlink()


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    @api.constrains('quantity', 'lot_id', 'location_id', 'move_id')
    def _check_pp_lock(self):
        """Quantities issued by a Pre-Production Order are locked: no other order/MO may consume them."""
        Lock = self.env['pp.lock'].sudo()
        for ml in self:
            if not ml.lot_id or ml.state == 'cancel' or not ml.quantity or not ml.location_id:
                continue
            locks = Lock.search([('lot_id', '=', ml.lot_id.id), ('product_id', '=', ml.product_id.id),
                                 ('state', 'in', ('active', 'bound'))])
            # a lock bound to an MO that is already done/cancelled no longer holds any stock
            locks = locks.filtered(lambda l: l.state == 'active' or (l.mo_id and l.mo_id.state not in ('done', 'cancel')))
            locks = locks.filtered(lambda l: ml.location_id.parent_path.startswith(l.location_id.parent_path))
            if not locks:
                continue
            order = (ml.move_id.pp_order_id or ml.move_id.raw_material_production_id.pp_order_id
                     or ml.picking_id.pp_order_id or ml.production_id.pp_order_id)
            other = locks.filtered(lambda l: l.order_id != order)
            if not other:
                continue
            quants = self.env['stock.quant'].sudo().search([
                ('product_id', '=', ml.product_id.id), ('lot_id', '=', ml.lot_id.id),
                ('location_id', 'child_of', other[0].location_id.id)])
            on_hand = sum(quants.mapped('quantity'))
            if float_compare(on_hand - sum(other.mapped('qty')), ml.quantity, precision_rounding=ml.product_uom_id.rounding) < 0:
                raise ValidationError(_(
                    "%(product)s (lot %(lot)s): %(qty)s requested but only %(free)s is free, the rest is locked by Pre-Production "
                    "Order(s) %(orders)s.", product=ml.product_id.display_name, lot=ml.lot_id.name, qty=ml.quantity,
                    free=on_hand - sum(other.mapped('qty')), orders=', '.join(other.mapped('order_id.name'))))


class PPMoExtra(models.Model):
    _name = 'pp.mo.extra'
    _description = 'Manufacturing Order Extra Compound (packaging, not consumed)'
    _order = 'id'

    mo_id = fields.Many2one('mrp.production', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', 'Product', required=True)
    product_qty = fields.Float('Quantity')
    product_uom_id = fields.Many2one('uom.uom', 'UoM')
    lot_summary = fields.Char('Lots')
