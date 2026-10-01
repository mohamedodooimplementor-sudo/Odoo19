from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class PPOrderLine(models.Model):
    _name = 'pp.order.line'
    _description = 'Pre-Production Line'
    _order = 'line_type, id'

    order_id = fields.Many2one('pp.order', required=True, ondelete='cascade', index=True)
    line_type = fields.Selection([('material', 'Material'), ('packaging', 'Packaging')], default='material', required=True)
    # product_id is the actual material/packaging used. bom_product_id keeps the original BOM component for traceability.
    product_id = fields.Many2one('product.product', required=True, domain=[('is_storable', '=', True)])
    bom_product_id = fields.Many2one('product.product', 'BOM Material', readonly=True, copy=False, index=True)
    bom_line_id = fields.Many2one('mrp.bom.line')
    is_substituted = fields.Boolean('Substituted', compute='_compute_is_substituted', store=True)
    substitution_note = fields.Char('Substitution Note', copy=False)

    tracking = fields.Selection(related='product_id.tracking')
    required_qty = fields.Float('Required Quantity', required=True)
    uom_id = fields.Many2one('uom.uom', 'UoM', required=True)
    unit_cost = fields.Float('Unit Cost', related='product_id.standard_price', groups='pre_production.group_pp_cost')
    cost = fields.Float('Cost', compute='_compute_cost', digits='Product Price', groups='pre_production.group_pp_cost',
                        help="Cost of the required quantity = unit cost x quantity (converted to the product unit of measure).")
    available_qty = fields.Float('Available Quantity', compute='_compute_available')
    allowed_warehouse_ids = fields.Many2many('stock.warehouse', compute='_compute_allowed_warehouses')
    source_warehouse_id = fields.Many2one('stock.warehouse', 'Source Warehouse',
                                          domain="[('id', 'in', allowed_warehouse_ids)]")
    lot_line_ids = fields.One2many('pp.order.line.lot', 'line_id', 'Lots')
    available_lot_ids = fields.Many2many('stock.lot', compute='_compute_available_lot_ids')
    lot_ids = fields.Many2many('stock.lot', string='Lots/Serials', compute='_compute_lot_ids', inverse='_inverse_lot_ids',
                               domain="[('id', 'in', available_lot_ids)]")
    selected_qty = fields.Float('Selected Quantity', compute='_compute_selected')
    lot_summary = fields.Char(compute='_compute_selected')
    weight_confirmed = fields.Boolean('Weight Confirmed', copy=False)
    issued = fields.Boolean(copy=False, readonly=True)

    @api.depends('product_id.standard_price', 'required_qty', 'uom_id')
    def _compute_cost(self):
        for l in self:
            qty = l.required_qty
            if l.uom_id and l.product_id and l.uom_id != l.product_id.uom_id:
                qty = l.uom_id._compute_quantity(qty, l.product_id.uom_id)
            l.cost = qty * l.product_id.sudo().standard_price

    @api.depends('product_id', 'bom_product_id')
    def _compute_is_substituted(self):
        for l in self:
            l.is_substituted = bool(l.bom_product_id and l.product_id != l.bom_product_id)

    @api.depends('product_id')
    def _compute_allowed_warehouses(self):
        for l in self:
            l.allowed_warehouse_ids = l.product_id.categ_id._pp_categ().pp_warehouse_ids

    def _pick_warehouse(self):
        """Look at the warehouses of the product category and pick the one that holds the stock."""
        Quant = self.env['stock.quant']
        for l in self:
            if l.issued or l.lot_line_ids:
                continue
            mfg = l.order_id.manufacturing_warehouse_id
            best, best_qty = False, -1.0
            for wh in l.product_id.categ_id._pp_categ().pp_warehouse_ids - mfg:
                qty = Quant._get_available_quantity(l.product_id, wh.lot_stock_id)
                if qty >= l.required_qty:
                    best = wh
                    break
                if qty > best_qty:
                    best, best_qty = wh, qty
            l.source_warehouse_id = best

    @api.model_create_multi
    def create(self, vals_list):
        lots = [vals.pop('lot_ids', False) for vals in vals_list]
        lines = super().create(vals_list)
        for l in lines.filtered(lambda x: not x.source_warehouse_id):
            l._pick_warehouse()
        for l, lot in zip(lines, lots):
            if lot:
                l.write({'lot_ids': lot})
        return lines

    @api.depends('product_id', 'source_warehouse_id', 'uom_id')
    def _compute_available(self):
        for l in self:
            wh = l.source_warehouse_id
            qty = 0.0
            if l.product_id and wh:
                qty = self.env['stock.quant']._get_available_quantity(l.product_id, wh.lot_stock_id)
                qty = l.product_id.uom_id._compute_quantity(qty, l.uom_id or l.product_id.uom_id)
            l.available_qty = qty

    @api.depends('product_id', 'source_warehouse_id')
    def _compute_available_lot_ids(self):
        Quant = self.env['stock.quant'].sudo()
        for l in self:
            lots = self.env['stock.lot']
            if l.product_id and l.tracking != 'none':
                dom = [('product_id', '=', l.product_id.id), ('lot_id', '!=', False)]
                if l.source_warehouse_id:
                    dom.append(('location_id', 'child_of', l.source_warehouse_id.lot_stock_id.id))
                lots = Quant.search(dom).filtered(lambda q: q.quantity - q.reserved_quantity > 0).mapped('lot_id')
            l.available_lot_ids = lots

    @api.depends('lot_line_ids.lot_id')
    def _compute_lot_ids(self):
        for l in self:
            l.lot_ids = l.lot_line_ids.lot_id

    def _lot_free_qty(self, lot):
        self.ensure_one()
        dom = [('product_id', '=', self.product_id.id), ('lot_id', '=', lot.id)]
        if self.source_warehouse_id:
            dom.append(('location_id', 'child_of', self.source_warehouse_id.lot_stock_id.id))
        return sum(q.quantity - q.reserved_quantity for q in self.env['stock.quant'].sudo().search(dom))

    def _allocate_lots(self, lots):
        """Spread the required quantity over the chosen lots, in the order they were picked."""
        for l in self:
            l.lot_line_ids.unlink()
            if not lots:
                continue
            left, vals = l.required_qty, []
            for lot in lots:
                if left <= 0:
                    break
                take = min(l._lot_free_qty(lot), left)
                if take > 0:
                    vals.append({'line_id': l.id, 'lot_id': lot.id, 'qty': take})
                    left -= take
            if float_compare(left, 0.0, precision_rounding=l.uom_id.rounding or 0.01) > 0:
                raise ValidationError(_("The selected lots do not cover the required quantity of %s (missing %s).",
                                        l.product_id.display_name, left))
            self.env['pp.order.line.lot'].create(vals)

    def _inverse_lot_ids(self):
        for l in self:
            l._allocate_lots(l.lot_ids)

    @api.depends('lot_line_ids.qty', 'lot_line_ids.lot_id', 'required_qty', 'tracking')
    def _compute_selected(self):
        for l in self:
            if l.lot_line_ids:
                l.selected_qty = sum(l.lot_line_ids.mapped('qty'))
                l.lot_summary = ', '.join('%s (%s)' % (x.lot_id.name, x.qty) for x in l.lot_line_ids)
            else:
                l.selected_qty = l.required_qty if l.tracking == 'none' else 0.0
                l.lot_summary = False

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            old_uom = self.uom_id or (self._origin.product_id.uom_id if self._origin and self._origin.product_id else self.product_id.uom_id)
            new_uom = self.product_id.uom_id
            if old_uom and new_uom and old_uom.category_id != new_uom.category_id and self.bom_product_id and self.product_id != self.bom_product_id:
                return {'warning': {'title': _('Invalid Substitute'), 'message': _('The substitute material must use the same UoM category as the original BOM material.')}}
            if old_uom and new_uom and old_uom.category_id == new_uom.category_id and old_uom != new_uom and self.bom_product_id and self.product_id != self.bom_product_id:
                self.required_qty = old_uom._compute_quantity(self.required_qty, new_uom)
            self.uom_id = new_uom
            self.source_warehouse_id = self.product_id.categ_id._pp_categ().pp_warehouse_ids[:1]
        self.lot_ids = False

    @api.constrains('product_id', 'bom_product_id')
    def _check_substitution(self):
        for l in self:
            if l.bom_product_id and not l.product_id:
                raise ValidationError(_('An actual material is required.'))
            if l.bom_product_id and l.product_id != l.bom_product_id and l.issued:
                raise ValidationError(_('A material cannot be substituted after it has been issued.'))

    @api.onchange('source_warehouse_id')
    def _onchange_source_warehouse_id(self):
        self.lot_ids = False

    def action_select_lots(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Select Lots'), 'res_model': 'pp.order.line',
            'res_id': self.id, 'target': 'new',
            'views': [(self.env.ref('pre_production.view_pp_order_line_form').id, 'form')],
        }

    def _check_ready_for_issue(self):
        for l in self:
            prec = l.uom_id.rounding
            l._pick_warehouse()
            if not l.source_warehouse_id:
                raise ValidationError(_("No Pre-Production warehouse is configured on the category of %s.", l.product_id.display_name))
            if l.tracking != 'none' and l.order_id.company_id.pp_lot_required and not l.lot_line_ids:
                raise ValidationError(_("Lot Number is required for this material: %s", l.product_id.display_name))
            if l.lot_line_ids and float_compare(l.selected_qty, l.required_qty, precision_rounding=prec) != 0:
                raise ValidationError(_("Selected quantity must equal the required quantity for %s.", l.product_id.display_name))
            if not l.lot_line_ids and float_compare(l.available_qty, l.required_qty, precision_rounding=prec) < 0:
                raise ValidationError(_("Insufficient quantity available for %s.", l.product_id.display_name))
            l.lot_line_ids._check_lot()

    def write(self, vals):
        if 'weight_confirmed' in vals and not self.env.user.has_group('pre_production.group_pp_weight'):
            raise ValidationError(_("You do not have permission to confirm weights."))
        if 'weight_confirmed' in vals:
            for l in self:
                if l.order_id.state != 'in_progress' or l.order_id.stage_code != 'weight':
                    raise ValidationError(_("Weights can only be confirmed at the Weight Confirmation stage."))
        if 'product_id' in vals:
            new_product = self.env['product.product'].browse(vals['product_id']).exists()
            if not new_product:
                raise ValidationError(_("The substitute material is invalid."))
            for l in self:
                if l.issued:
                    raise ValidationError(_("You cannot substitute a material after it has been issued."))
                if l.bom_product_id and new_product != l.bom_product_id:
                    if l.bom_line_id and new_product.uom_id.category_id != l.bom_line_id.product_uom_id.category_id:
                        raise ValidationError(_("The substitute material must use the same UoM category as the original BOM material."))
                    old_uom = l.uom_id or l.product_id.uom_id
                    new_uom = new_product.uom_id
                    if old_uom and new_uom and old_uom.category_id == new_uom.category_id and old_uom != new_uom:
                        converted_qty = old_uom._compute_quantity(l.required_qty, new_uom)
                        vals = dict(vals)
                        vals['required_qty'] = converted_qty
                        vals['uom_id'] = new_uom.id
                    elif 'uom_id' not in vals:
                        vals = dict(vals)
                        vals['uom_id'] = new_uom.id
        res = super().write(vals)
        if 'required_qty' in vals and 'lot_ids' not in vals:
            for l in self.filtered(lambda x: not x.issued and x.lot_line_ids):
                l._allocate_lots(l.lot_line_ids.lot_id)
        return res

    def action_remove_line(self):
        """Row button replacing the trash icon (hidden on issued lines); unlink() still refuses issued lines."""
        self.unlink()
        return True

    def unlink(self):
        # Once an issue has been created/confirmed, the line is part of the
        # stock traceability chain and must not be removable.
        for l in self:
            if l.issued or l.order_id.picking_ids.filtered(lambda p: p.pp_issue_type and p.move_ids.filtered(lambda m: m.pp_line_id == l)):
                raise ValidationError(_(
                    "You cannot delete %(product)s after the material/packaging has been issued. "
                    "The stock transfer and traceability must remain intact.",
                    product=l.product_id.display_name))
            if l.order_id.mo_id and l.order_id.mo_id.move_raw_ids.filtered(lambda m: m.pp_line_id == l):
                raise ValidationError(_(
                    "You cannot delete %(product)s because it is linked to the Manufacturing Order.",
                    product=l.product_id.display_name))
        return super().unlink()


class PPOrderLineLot(models.Model):
    _name = 'pp.order.line.lot'
    _description = 'Pre-Production Line Lot'

    line_id = fields.Many2one('pp.order.line', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one(related='line_id.product_id')
    available_lot_ids = fields.Many2many('stock.lot', compute='_compute_available_lots')
    lot_id = fields.Many2one('stock.lot', 'Lot/Serial', required=True, domain="[('id', 'in', available_lot_ids)]")
    available_qty = fields.Float('Lot Available', compute='_compute_lot_available')
    qty = fields.Float('Quantity', required=True)

    _sql_constraints = [('lot_uniq', 'unique(line_id, lot_id)', 'A lot can only be selected once per line.')]

    def _quants(self, lot=None):
        self.ensure_one()
        wh = self.line_id.source_warehouse_id
        dom = [('product_id', '=', self.line_id.product_id.id), ('lot_id', '!=', False)]
        if wh:
            dom.append(('location_id', 'child_of', wh.lot_stock_id.id))
        if lot:
            dom.append(('lot_id', '=', lot.id))
        return self.env['stock.quant'].sudo().search(dom)

    @api.depends('line_id.product_id', 'line_id.source_warehouse_id')
    def _compute_available_lots(self):
        for r in self:
            quants = r._quants().filtered(lambda q: q.quantity - q.reserved_quantity > 0)
            r.available_lot_ids = quants.mapped('lot_id')

    @api.depends('lot_id', 'line_id.source_warehouse_id')
    def _compute_lot_available(self):
        for r in self:
            r.available_qty = sum(q.quantity - q.reserved_quantity for q in r._quants(r.lot_id)) if r.lot_id else 0.0

    def _allocate(self):
        """Split the selected qty over the quants of the lot (multi-location safe)."""
        self.ensure_one()
        left, res = self.qty, []
        for q in self._quants(self.lot_id).sorted('quantity', reverse=True):
            free = q.quantity - q.reserved_quantity
            if free <= 0:
                continue
            take = min(free, left)
            res.append((q, take))
            left -= take
            if left <= 0:
                break
        return res

    @api.constrains('lot_id', 'qty')
    def _check_lot(self):
        for r in self:
            if r.line_id.issued:
                continue
            if r.qty <= 0:
                raise ValidationError(_("Quantity must be greater than zero."))
            if r.lot_id.product_id != r.line_id.product_id:
                raise ValidationError(_("Selected Lot does not belong to the selected product."))
            if not r._quants(r.lot_id):
                raise ValidationError(_("Selected Lot does not belong to the selected warehouse."))
            if float_compare(r.qty, r.available_qty, precision_rounding=r.line_id.uom_id.rounding) > 0:
                raise ValidationError(_("Insufficient quantity available in the selected Lot."))

    def _check_editable(self):
        for r in self:
            o = r.line_id.order_id
            if r.line_id.issued or o.state not in ('draft', 'in_progress') or (o.state == 'in_progress' and o.stage_code != 'material_issue'):
                raise ValidationError(_("Lots cannot be changed after the material has been issued."))

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs._check_editable()
        return recs

    def write(self, vals):
        self._check_editable()
        return super().write(vals)

    def unlink(self):
        self._check_editable()
        return super().unlink()
