from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from .stock_mixin import _pick_field


ISSUE_PROTECTED = {'state', 'picking_id', 'issued_by', 'issue_date', 'received_by', 'receive_date'}
ISSUE_LINE_PROTECTED = {'qty_received', 'qty_returned', 'move_id'}


class RcIssue(models.Model):
    _name = 'rc.issue'
    _inherit = ['rc.stock.mixin', 'mail.thread']
    _description = 'Issue to Room'
    _order = 'id desc'

    name = fields.Char(default=lambda s: _('New'), readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'), ('in_transit', 'In Transit'),
        ('received', 'Received'), ('cancel', 'Cancelled'),
    ], default='draft', tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    source_location_id = fields.Many2one(
        'stock.location', string='From (Main Store)', required=True,
        domain="[('usage', '=', 'internal'), ('is_room', '=', False), ('is_lab', '=', False)]")
    room_id = fields.Many2one(
        'stock.location', string='To Room / Lab', required=True, tracking=True,
        domain="[('usage', '=', 'internal'), '|', ('is_room', '=', True), ('is_lab', '=', True)]")
    issued_by = fields.Many2one('res.users', readonly=True)
    issue_date = fields.Datetime(readonly=True)
    received_by = fields.Many2one('res.users', readonly=True)
    receive_date = fields.Datetime(readonly=True)
    difference_reason = fields.Text()
    has_difference = fields.Boolean(compute='_compute_has_difference', store=True)
    line_ids = fields.One2many('rc.issue.line', 'issue_id', string='Items')
    picking_id = fields.Many2one('stock.picking', string='Internal Transfer', readonly=True, copy=False, tracking=True)

    @api.depends('line_ids.qty_issued', 'line_ids.qty_received', 'line_ids.qty_returned', 'state')
    def _compute_has_difference(self):
        for rec in self:
            rec.has_difference = rec.state == 'received' and any(
                l.qty_issued - l.qty_received - l.qty_returned > 0 for l in rec.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                bad = {k for k in ISSUE_PROTECTED
                       if vals.get(k) and not (k == 'state' and vals[k] == 'draft')}
                if bad:
                    raise AccessError(_('These fields are managed by the workflow: %s', ', '.join(sorted(bad))))
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('rc.issue') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        # Workflow fields change only through the action buttons (they write as superuser).
        # Room staff may only add the reason for a quantity difference.
        if not self.env.su:
            if ISSUE_PROTECTED & set(vals):
                raise AccessError(_('These fields are managed by the workflow and cannot be edited directly.'))
            if not self._rc_is_storekeeper():
                allowed = {k for k in vals if k == 'difference_reason' or k.startswith(('message_', 'activity_'))}
                if set(vals) - allowed:
                    raise AccessError(_('Room staff can only write the difference reason.'))
        return super().write(vals)

    def _lock(self):
        if not self.ids:
            return
        self.env.cr.execute('SELECT id FROM rc_issue WHERE id IN %s FOR UPDATE', (tuple(self.ids),))

    def action_issue(self):
        """Create a standard Odoo internal transfer from the main store to the room.
        The transfer is deliberately NOT validated here; the storekeeper validates it
        from Inventory, then the room receipt can be confirmed on this document.
        """
        self._rc_require_storekeeper()
        self._lock()
        for rec in self:
            if rec.state != 'draft':
                continue
            lines = rec.line_ids.filtered(lambda l: l.qty_issued > 0)
            if not lines:
                raise UserError(_('Add at least one item with a quantity.'))
            if rec.source_location_id == rec.room_id:
                raise UserError(_('The source location and room must be different.'))

            PickingType = self.env['stock.picking.type'].sudo().with_company(rec.company_id)
            picking_type = PickingType.search([
                ('code', '=', 'internal'),
                ('company_id', '=', rec.company_id.id),
            ], order='sequence, id', limit=1)
            if not picking_type:
                raise UserError(_('No Internal Transfer operation type was found for this company.'))

            # Let Odoo create a normal stock picking so it appears in Inventory /
            # Operations / Transfers and can be reserved and validated there.
            picking_vals = {
                'picking_type_id': picking_type.id,
                'location_id': rec.source_location_id.id,
                'location_dest_id': rec.room_id.id,
                'origin': rec.name,
                'company_id': rec.company_id.id,
            }
            if 'partner_id' in self.env['stock.picking']._fields:
                picking_vals['partner_id'] = False
            picking = self.env['stock.picking'].sudo().with_company(rec.company_id).create(picking_vals)

            Move = self.env['stock.move'].sudo().with_company(rec.company_id)
            for line in lines:
                if line.lot_id:
                    available = self.env['stock.quant'].sudo()._get_available_quantity(
                        line.product_id, rec.source_location_id, lot_id=line.lot_id, strict=False)
                    if available < line.qty_issued:
                        raise UserError(_(
                            'Not enough stock of %(product)s in %(location)s for lot %(lot)s. '
                            'Available: %(available)s; requested: %(requested)s.',
                            product=line.product_id.display_name,
                            location=rec.source_location_id.display_name,
                            lot=line.lot_id.display_name,
                            available=available,
                            requested=line.qty_issued,
                        ))
                move_vals = {
                    'product_id': line.product_id.id,
                    _pick_field(Move, 'product_uom', 'uom_id'): line.product_id.uom_id.id,
                    _pick_field(Move, 'product_uom_qty', 'product_qty'): line.qty_issued,
                    'location_id': rec.source_location_id.id,
                    'location_dest_id': rec.room_id.id,
                    'picking_id': picking.id,
                    'company_id': rec.company_id.id,
                }
                # 'name' was removed from stock.move in newer Odoo versions
                if 'name' in Move._fields:
                    move_vals['name'] = rec.name
                if 'description_picking' in Move._fields:
                    move_vals['description_picking'] = rec.name
                line.sudo().move_id = Move.create(move_vals)

            picking.action_confirm()
            picking.action_assign()
            rec.sudo().write({
                'picking_id': picking.id,
                'state': 'in_transit',
                'issued_by': self.env.uid,
                'issue_date': fields.Datetime.now(),
            })

    def action_open_picking(self):
        self.ensure_one()
        if not self.picking_id:
            raise UserError(_('There is no internal transfer linked to this issue yet.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Internal Transfer'),
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_receive(self):
        self._lock()
        user = self.env.user
        for rec in self:
            if rec.state != 'in_transit':
                continue
            if not rec.picking_id:
                raise UserError(_('Create the internal transfer first by clicking Issue to Room.'))
            if rec.picking_id.state != 'done':
                raise UserError(_(
                    'You cannot confirm this issue until the linked internal transfer is validated. '
                    'Open the transfer and click Validate in Inventory first.'
                ))
            if user not in rec.room_id.rc_responsible_ids and \
                    not user.has_group('radiology_consumables.group_rc_manager'):
                raise UserError(_('Only the staff of %s can confirm receipt.', rec.room_id.display_name))

            diff = False
            for line in rec.line_ids:
                if line.move_id:
                    # exact move of this line: two lines of one product no longer share a total
                    done_qty = line.move_id.sudo().quantity
                else:
                    moves = rec.picking_id.move_ids.filtered(lambda m: m.product_id == line.product_id)
                    done_qty = sum(moves.mapped('quantity'))
                line.sudo().qty_received = done_qty
                if done_qty < 0 or done_qty > line.qty_issued:
                    raise UserError(_('The transferred quantity is invalid for %s.', line.product_id.display_name))
                if done_qty < line.qty_issued:
                    diff = True
            if diff and not (rec.difference_reason or '').strip():
                raise UserError(_('Please write the reason for the quantity difference.'))
            rec.sudo().write({
                'state': 'received',
                'received_by': user.id,
                'receive_date': fields.Datetime.now(),
            })

    def action_return_difference(self):
        self._rc_require_storekeeper()
        self._lock()
        for rec in self:
            if rec.state != 'received':
                continue
            # The standard internal transfer moves only the quantity actually
            # validated. Any short quantity never left the source location.
            for line in rec.line_ids:
                rest = line.qty_issued - line.qty_received - line.qty_returned
                if rest > 0:
                    sline = line.sudo()
                    sline.qty_returned = sline.qty_returned + rest

    def action_cancel(self):
        self._rc_require_storekeeper()
        self.filtered(lambda r: r.state == 'draft').sudo().write({'state': 'cancel'})


class RcIssueLine(models.Model):
    _name = 'rc.issue.line'
    _description = 'Issue to Room Line'

    issue_id = fields.Many2one('rc.issue', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', required=True, domain="[('type', '=', 'consu')]")
    uom_id = fields.Many2one(related='product_id.uom_id')
    tracking = fields.Selection(related='product_id.tracking')
    lot_id = fields.Many2one('stock.lot', domain="[('product_id', '=', product_id)]")
    qty_issued = fields.Float(string='Issued', default=1.0)
    qty_received = fields.Float(string='Received')
    qty_returned = fields.Float(string='Returned to Store', readonly=True)
    move_id = fields.Many2one('stock.move', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                if any(vals.get(k) for k in ISSUE_LINE_PROTECTED):
                    raise AccessError(_('Received and returned quantities are set by the workflow.'))
            issues = self.env['rc.issue'].browse([v['issue_id'] for v in vals_list if v.get('issue_id')])
            if any(i.state != 'draft' for i in issues):
                raise AccessError(_('Items can only be added while the issue is a draft.'))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if ISSUE_LINE_PROTECTED & set(vals):
                raise AccessError(_('Received and returned quantities are set by the workflow.'))
            if not self._rc_is_storekeeper():
                raise AccessError(_('Only a storekeeper or a manager can edit issue items.'))
            if {'product_id', 'qty_issued', 'lot_id', 'issue_id'} & set(vals) and \
                    any(l.issue_id.state != 'draft' for l in self):
                raise AccessError(_('Items cannot be changed after the issue left draft.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and any(l.issue_id.state != 'draft' for l in self):
            raise AccessError(_('Items cannot be deleted after the issue left draft.'))
        return super().unlink()

    def _rc_is_storekeeper(self):
        return (self.env.su or self.env.user.has_group('radiology_consumables.group_rc_storekeeper')
                or self.env.user.has_group('base.group_system'))
