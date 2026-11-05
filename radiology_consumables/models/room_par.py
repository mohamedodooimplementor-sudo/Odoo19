from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class RcRoomPar(models.Model):
    _name = 'rc.room.par'
    _description = 'Room Stock Level (Max)'
    _order = 'room_id, product_id'

    room_id = fields.Many2one(
        'stock.location', string='Room / Lab', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='room_id.company_id', store=True)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True, domain="[('type', '=', 'consu')]")
    uom_id = fields.Many2one(related='product_id.uom_id')
    max_qty = fields.Float(string='Max', default=0.0)
    qty_on_hand = fields.Float(string='In Room', compute='_compute_qty', digits='Product Unit')
    qty_pending = fields.Float(
        string='On the Way', compute='_compute_qty', digits='Product Unit',
        help='Quantity already requested (draft) or issued and not yet received for this room.')
    qty_to_request = fields.Float(
        string='To Request', compute='_compute_qty', digits='Product Unit',
        help='Max - In Room - On the Way (never negative).')

    _room_product_uniq = models.Constraint(
        'unique(room_id, product_id)', 'This product is already in the room list.')

    @api.constrains('max_qty')
    def _check_max_qty(self):
        for rec in self:
            if rec.max_qty < 0:
                raise ValidationError(_('Max cannot be negative.'))

    @api.depends('room_id', 'product_id', 'max_qty')
    def _compute_qty(self):
        Quant = self.env['stock.quant'].sudo()
        Line = self.env['rc.issue.line'].sudo()
        room_ids = {(r._origin.id or r.id) for r in self.mapped('room_id')}
        room_ids = [i for i in room_ids if isinstance(i, int)]
        product_ids = [p._origin.id or p.id for p in self.mapped('product_id')]
        on_hand, pending = {}, {}
        for room_id in room_ids:
            groups = Quant._read_group(
                [('location_id', 'child_of', room_id), ('product_id', 'in', product_ids)],
                ['product_id'], ['quantity:sum'])
            for product, qty in groups:
                on_hand[(room_id, product.id)] = qty
        if room_ids:
            lines = Line.search([
                ('issue_id.room_id', 'in', room_ids),
                ('issue_id.state', 'in', ('draft', 'in_transit')),
                ('product_id', 'in', product_ids)])
            for line in lines:
                key = (line.issue_id.room_id.id, line.product_id.id)
                pending[key] = pending.get(key, 0.0) + line.qty_issued
        for rec in self:
            key = (rec.room_id._origin.id or rec.room_id.id, rec.product_id._origin.id or rec.product_id.id)
            rec.qty_on_hand = on_hand.get(key, 0.0)
            rec.qty_pending = pending.get(key, 0.0)
            rec.qty_to_request = max(rec.max_qty - rec.qty_on_hand - rec.qty_pending, 0.0)
