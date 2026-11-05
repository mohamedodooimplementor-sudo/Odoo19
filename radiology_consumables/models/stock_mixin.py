from odoo import _, models
from odoo.exceptions import AccessError, UserError


def _pick_field(model, *names):
    """Return the first field name that exists on the model (Odoo versions rename stock fields)."""
    for name in names:
        if name in model._fields:
            return name
    raise UserError(_('Unsupported stock model: none of the fields %(names)s exist on %(model)s.',
                      names=', '.join(names), model=model._name))


class RcStockMixin(models.AbstractModel):
    _name = 'rc.stock.mixin'
    _description = 'Consumables stock helper'

    def _rc_is_storekeeper(self):
        return (self.env.su or self.env.user.has_group('radiology_consumables.group_rc_storekeeper')
                or self.env.user.has_group('base.group_system'))

    def _rc_require_storekeeper(self):
        """Server-side check: hiding a button in the view is not a permission."""
        if not self._rc_is_storekeeper():
            raise AccessError(_('Only a storekeeper or a manager can do this.'))

    def _rc_move(self, product, qty, src, dest, lot=False, origin=''):
        """Create and validate one stock move. Runs with sudo so room nurses
        do not need Inventory rights. Raises UserError when stock is short."""
        self.ensure_one()
        empty = self.env['stock.move']
        if qty <= 0:
            return empty
        product, src, dest = product.sudo(), src.sudo(), dest.sudo()
        if 'is_storable' in product._fields and not product.is_storable:
            return empty
        lot = lot.sudo() if lot else False
        avail = self.env['stock.quant'].sudo()._get_available_quantity(
            product, src, lot_id=lot or None, strict=False)
        if avail < qty:
            raise UserError(_(
                'Not enough stock of %(product)s in %(loc)s: available %(avail)s, requested %(qty)s.',
                product=product.display_name, loc=src.display_name, avail=avail, qty=qty))
        company = self.company_id
        Move = self.env['stock.move'].sudo().with_company(company)
        vals = {
            'product_id': product.id,
            _pick_field(Move, 'product_uom_qty', 'product_qty'): qty,
            _pick_field(Move, 'product_uom', 'uom_id'): product.uom_id.id,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'company_id': company.id,
            'origin': origin,
        }
        if 'name' in Move._fields:
            vals['name'] = origin or product.display_name
        move = Move.create(vals)
        move._action_confirm()
        if lot:
            Line = self.env['stock.move.line'].sudo()
            Line.create({
                'move_id': move.id,
                'product_id': product.id,
                _pick_field(Line, 'product_uom_id', 'uom_id'): product.uom_id.id,
                'location_id': src.id,
                'location_dest_id': dest.id,
                'lot_id': lot.id,
                'quantity': qty,
                'company_id': company.id,
            })
        else:
            move._action_assign()
        if 'picked' in Move._fields:
            move.picked = True
        move._action_done()
        return move

    def _rc_picking(self, entries, src, dest, origin='', picking_type=False):
        """Create one standard, unvalidated Odoo Internal Transfer.

        The picking remains available in Inventory > Operations > Transfers
        for the storekeeper to review and validate. Each exam phase calls this
        method once, so its products are grouped in one picking.

        entries: list of (product, qty, lot) tuples.
        Returns (picking, moves), with moves in the same order as entries.
        """
        self.ensure_one()
        company = self.company_id
        src, dest = src.sudo(), dest.sudo()
        Picking = self.env['stock.picking'].sudo().with_company(company)
        Move = self.env['stock.move'].sudo().with_company(company)

        stocked = []
        for product, qty, lot in entries:
            product = product.sudo()
            if qty <= 0 or ('is_storable' in product._fields and not product.is_storable):
                stocked.append(None)
                continue
            stocked.append((product, qty, lot.sudo() if lot else False))

        if not any(stocked):
            return self.env['stock.picking'], [None] * len(entries)

        # Never fall back to Delivery Orders: the operation must be an
        # Inventory Internal Transfer.
        PickingType = self.env['stock.picking.type'].sudo().with_company(company)
        if picking_type:
            picking_type = picking_type.sudo()
            if picking_type.code != 'internal' or picking_type.company_id != company:
                raise UserError(_('The selected operation type must be an Internal Transfer for this company.'))
        else:
            picking_type = PickingType.search([
                ('code', '=', 'internal'), ('company_id', '=', company.id)
            ], order='sequence, id', limit=1)
        if not picking_type:
            raise UserError(_('No Internal Transfer operation type was found for this company.'))
        if src == dest:
            raise UserError(_('The room location and Consumption location must be different.'))

        picking = Picking.create({
            'picking_type_id': picking_type.id,
            'location_id': src.id,
            'location_dest_id': dest.id,
            'origin': origin,
            'company_id': company.id,
        })
        moves = []
        for item in stocked:
            if not item:
                moves.append(None)
                continue
            product, qty, lot = item
            vals = {
                'product_id': product.id,
                _pick_field(Move, 'product_uom_qty', 'product_qty'): qty,
                _pick_field(Move, 'product_uom', 'uom_id'): product.uom_id.id,
                'location_id': src.id,
                'location_dest_id': dest.id,
                'picking_id': picking.id,
                'company_id': company.id,
                'origin': origin,
            }
            if 'name' in Move._fields:
                vals['name'] = origin or product.display_name
            if 'description_picking' in Move._fields:
                vals['description_picking'] = origin
            moves.append(Move.create(vals))

        # Confirm and reserve what is currently available, but do NOT validate.
        # Validation is intentionally left to Inventory users.
        picking.action_confirm()
        picking.action_assign()
        Line = self.env['stock.move.line'].sudo()
        for item, move in zip(stocked, moves):
            if not item or not move:
                continue
            product, qty, lot = item
            if lot:
                # Keep the lot selected on the exam line. The move remains
                # unvalidated and can be reviewed in the standard picking.
                move.move_line_ids.unlink()
                line_vals = {
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': product.id,
                    _pick_field(Line, 'product_uom_id', 'uom_id'): product.uom_id.id,
                    'location_id': src.id,
                    'location_dest_id': dest.id,
                    'lot_id': lot.id,
                    'company_id': company.id,
                }
                if 'quantity' in Line._fields:
                    line_vals['quantity'] = qty
                elif 'qty_done' in Line._fields:
                    line_vals['qty_done'] = qty
                Line.create(line_vals)
        return picking, moves
