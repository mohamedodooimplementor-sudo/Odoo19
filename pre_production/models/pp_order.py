from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

from .pp_stage import QUALITY_STAGES, STAGE_GROUPS


class PPOrder(models.Model):
    _name = 'pp.order'
    _description = 'Pre-Production Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(default=lambda s: _('New'), readonly=True, copy=False)
    active = fields.Boolean(default=True)
    order_date = fields.Datetime('Order Date', default=fields.Datetime.now, copy=False, tracking=True,
                                 help="Date of the Pre-Production Order. Set automatically at creation; you can change it.")
    production_date = fields.Datetime('Production Date', compute='_compute_production_date', store=True, copy=False,
                                      help="Date the Manufacturing Order was done. Empty until then.")
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company, required=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    material_cost_total = fields.Monetary('Materials Cost', compute='_compute_cost_totals', currency_field='currency_id', groups='pre_production.group_pp_cost')
    packaging_cost_total = fields.Monetary('Packaging Cost', compute='_compute_cost_totals', currency_field='currency_id', groups='pre_production.group_pp_cost')
    total_cost = fields.Monetary('Total Cost', compute='_compute_cost_totals', currency_field='currency_id', groups='pre_production.group_pp_cost')

    @api.depends('line_ids.cost', 'line_ids.line_type')
    def _compute_cost_totals(self):
        for o in self:
            lines = o.line_ids.sudo()
            mat = sum(lines.filtered(lambda l: l.line_type == 'material').mapped('cost'))
            pack = sum(lines.filtered(lambda l: l.line_type == 'packaging').mapped('cost'))
            o.material_cost_total = mat
            o.packaging_cost_total = pack
            o.total_cost = mat + pack
    partner_id = fields.Many2one('res.partner', 'Customer', required=True, tracking=True)
    sale_order_id = fields.Many2one('sale.order', 'Sales Order', index=True, tracking=True)
    sale_line_id = fields.Many2one('sale.order.line', 'Sales Order Line')
    product_id = fields.Many2one('product.product', 'Product', required=True, tracking=True)
    product_qty = fields.Float('Quantity', required=True, default=1.0)
    actual_product_qty = fields.Float('Actual Produced Quantity', copy=False, tracking=True)
    waste_qty = fields.Float('Waste / Loss Quantity', compute='_compute_actual_quantities', store=True)
    product_uom_id = fields.Many2one('uom.uom', 'UoM')
    bom_id = fields.Many2one('mrp.bom', 'BOM', required=True, domain="[('product_tmpl_id', '=', product_tmpl_id)]")
    product_tmpl_id = fields.Many2one(related='product_id.product_tmpl_id')
    manufacturing_warehouse_id = fields.Many2one(
        'stock.warehouse', 'Manufacturing Warehouse',
        default=lambda s: s.env.company.pp_manufacturing_warehouse_id)
    product_tracking = fields.Selection(related='product_id.tracking')
    lot_producing_id = fields.Many2one(
        'stock.lot', 'Finished Product Lot', copy=False, tracking=True,
        domain="[('product_id', '=', product_id), ('company_id', '=', company_id)]",
        help="Lot/Serial of the product to be manufactured, passed to the Manufacturing Order. Required before the last "
             "approval. The product must be tracked by Lot or Serial Number (Inventory tab of the product).")
    attachment_ids = fields.Many2many('ir.attachment', string='Attachments')
    state = fields.Selection([('draft', 'Draft'), ('in_progress', 'In Progress'), ('rejected', 'Rejected'),
                              ('done', 'Done'), ('cancel', 'Cancelled')], default='draft', tracking=True, copy=False)
    current_stage_id = fields.Many2one('pp.stage', 'Current Stage', copy=False, tracking=True,
                                       group_expand='_read_group_stage_ids')
    stage_code = fields.Selection(related='current_stage_id.code', store=True)
    components_availability = fields.Selection([
        ('issued', 'Issued'), ('available', 'Available'), ('not_available', 'Not Available'),
    ], 'Component Status', compute='_compute_components_availability',
        search='_search_components_availability')

    def _search_components_availability(self, operator, value):
        if operator not in ('=', '!=', 'in', 'not in'):
            raise UserError(_("Unsupported search on Component Status."))
        values = value if isinstance(value, (list, tuple)) else [value]
        open_orders = self.search([('state', 'not in', ('done', 'cancel'))])
        if operator in ('=', 'in'):
            ids = open_orders.filtered(lambda o: o.components_availability in values).ids
        else:
            ids = open_orders.filtered(lambda o: o.components_availability not in values).ids
        return [('id', 'in', ids)]

    @api.depends('state', 'line_ids.issued', 'line_ids.required_qty', 'line_ids.available_qty',
                 'line_ids.source_warehouse_id')
    def _compute_components_availability(self):
        for o in self:
            lines = o.line_ids
            if o.state in ('done', 'cancel') or not lines:
                o.components_availability = False
            elif all(lines.mapped('issued')):
                o.components_availability = 'issued'
            else:
                pending = lines.filtered(lambda l: not l.issued)
                ok = all(l.available_qty >= l.required_qty for l in pending)
                o.components_availability = 'available' if ok else 'not_available'
    line_ids = fields.One2many('pp.order.line', 'order_id', 'Lines')
    material_line_ids = fields.One2many('pp.order.line', 'order_id', domain=[('line_type', '=', 'material')])
    packaging_line_ids = fields.One2many('pp.order.line', 'order_id', domain=[('line_type', '=', 'packaging')])
    picking_ids = fields.One2many('stock.picking', 'pp_order_id', 'Transfers')
    check_ids = fields.One2many('pp.quality.check', 'order_id', 'Quality Checks')
    audit_ids = fields.One2many('pp.audit', 'order_id', 'Approval History')
    stage_log_ids = fields.One2many('pp.stage.log', 'order_id', 'Time per Stage')
    lock_ids = fields.One2many('pp.lock', 'order_id', 'Locked Stock')
    mo_id = fields.Many2one('mrp.production', 'Manufacturing Order', copy=False, readonly=True)
    mo_confirmed = fields.Boolean(copy=False)
    material_issue_done = fields.Boolean(copy=False)
    packaging_issue_done = fields.Boolean(copy=False)
    rejected_check_id = fields.Many2one('pp.quality.check', compute='_compute_rejected_check')
    picking_count = fields.Integer(compute='_compute_counts')
    check_count = fields.Integer(compute='_compute_counts')
    lock_count = fields.Integer(compute='_compute_counts')

    weight_all = fields.Boolean('Confirm All Weights', compute='_compute_weight_all', inverse='_inverse_weight_all')

    @api.depends('material_line_ids.weight_confirmed', 'packaging_line_ids.weight_confirmed')
    def _compute_weight_all(self):
        for o in self:
            lines = o.material_line_ids | o.packaging_line_ids
            o.weight_all = bool(lines) and all(lines.mapped('weight_confirmed'))

    def _inverse_weight_all(self):
        for o in self:
            (o.material_line_ids | o.packaging_line_ids).write({'weight_confirmed': o.weight_all})

    @api.onchange('weight_all')
    def _onchange_weight_all(self):
        value = self.weight_all  # read once: ticking the first line recomputes weight_all
        for l in self.material_line_ids | self.packaging_line_ids:
            l.weight_confirmed = value

    # ------------------------------------------------------------------ computes
    @api.depends('product_qty', 'actual_product_qty')
    def _compute_actual_quantities(self):
        for o in self:
            o.waste_qty = max(o.product_qty - o.actual_product_qty, 0.0)

    @api.depends('mo_id.state', 'mo_id.date_finished')
    def _compute_production_date(self):
        for o in self:
            o.production_date = o.mo_id.date_finished if o.mo_id.state == 'done' else False

    @api.depends('picking_ids', 'check_ids', 'lock_ids')
    def _compute_counts(self):
        for o in self:
            o.picking_count = len(o.picking_ids)
            o.check_count = len(o.check_ids)
            o.lock_count = len(o.lock_ids)

    @api.depends('check_ids.state')
    def _compute_rejected_check(self):
        for o in self:
            rej = o.check_ids.filtered(lambda c: c.state == 'rejected').sorted('id')
            o.rejected_check_id = rej[-1:] if o.state == 'rejected' else False

    # ------------------------------------------------------------------ helpers
    def _check_perm(self, group, msg):
        if not self.env.user.has_group(group):
            raise ValidationError(msg)

    def _log(self, stage, result, notes=''):
        self.env['pp.audit'].sudo().create({
            'order_id': self.id, 'stage_id': stage.id if stage else False,
            'user_id': self.env.user.id, 'result': result, 'notes': notes})

    @api.model
    def _read_group_stage_ids(self, stages, domain):
        return stages.search([], order='sequence, id')

    def _stage_sequence(self):
        """Ordered stages applicable according to the module settings."""
        c = self.company_id
        stages = self.env['pp.stage'].search([], order='sequence, id')
        res = self.env['pp.stage']
        for s in stages:
            if s.code == 'material_issue' and not (c.pp_material_issue_required or c.pp_packaging_issue_required):
                continue
            if s.code == 'weight' and not c.pp_weight_required:
                continue
            res |= s
        return res

    def _enter_stage(self, stage):
        self.ensure_one()
        if stage.code == 'done' and self.product_id.tracking != 'none' and not self.lot_producing_id:
            raise ValidationError(_("Please set the Finished Product Lot on the Pre-Production Order before the last approval."))
        self._close_stage_log()
        self.current_stage_id = stage
        self.env['pp.stage.log'].sudo().create({'order_id': self.id, 'stage_id': stage.id})
        self._schedule_stage_activity(stage)
        if stage.code in QUALITY_STAGES:
            self.env['pp.quality.check']._create_for_order(self, stage)
        elif stage.code == 'done':
            # last stage reached: wait for the "Create MO & Final Transfer" button (action_create_mo)
            self._log(stage, _('Ready for Manufacturing Order'))

    ACTIVITY_TYPE = 'pre_production.mail_act_pp_stage'

    def _close_stage_log(self):
        logs = self.env['pp.stage.log'].sudo().search([('order_id', 'in', self.ids), ('date_end', '=', False)])
        logs.write({'date_end': fields.Datetime.now()})

    def _clear_stage_activities(self):
        self.sudo().activity_unlink([self.ACTIVITY_TYPE])

    def _schedule_stage_activity(self, stage):
        """Tell the users who can act on the stage that the order is waiting for them."""
        self.ensure_one()
        self._clear_stage_activities()
        group = STAGE_GROUPS.get(stage.code)
        if not group:
            return
        users = self.env.ref(group).sudo().users.filtered(
            lambda u: u.active and not u.share and u.id not in (1, self.env.user.id))
        if stage.code == 'done':
            summary = _('Ready for Manufacturing Order')
        else:
            summary = _('Waiting for: %s', stage.name)
        for user in users:
            self.sudo().activity_schedule(
                self.ACTIVITY_TYPE, date_deadline=fields.Date.context_today(self),
                summary=summary, user_id=user.id)

    def action_print_final(self):
        self.ensure_one()
        return self.env.ref('pre_production.report_pp_final').report_action(self)

    def _stage_latest_checks(self, stage):
        """Latest Quality Check of every template of the stage (several templates = several checks)."""
        self.ensure_one()
        latest = {}
        for c in self.check_ids.filtered(lambda k: k.stage_id == stage).sorted('id'):
            latest[c.template_id.id or False] = c
        return latest

    def _stage_checks_approved(self, stage):
        """The stage is complete when the latest check of each of its templates is approved."""
        self.ensure_one()
        checks = self._stage_latest_checks(stage).values()
        return bool(checks) and all(c.state == 'approved' for c in checks)

    def _advance(self):
        self.ensure_one()
        seq = self._stage_sequence().filtered(lambda s: s.sequence > self.current_stage_id.sequence)
        if seq:
            self._enter_stage(seq[0])

    # ------------------------------------------------------------------ CRUD
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('New'):
                vals['name'] = self._get_pp_name(vals.get('sale_order_id'))
        for vals in vals_list:
            if vals.get('actual_product_qty') is None:
                vals['actual_product_qty'] = vals.get('product_qty', 1.0)
        orders = super().create(vals_list)
        for o in orders:
            if not o.product_uom_id:
                o.product_uom_id = o.product_id.uom_id
            if not o.actual_product_qty:
                o.actual_product_qty = o.product_qty
            o._load_lines()
        return orders

    def write(self, vals):
        if 'actual_product_qty' in vals:
            for o in self:
                if o.state == 'draft':
                    continue
                if o.state != 'in_progress' or o.stage_code not in ('product_check2', 'done'):
                    raise ValidationError(_('Actual Produced Quantity can only be changed during Product Check 2 or before creating the Manufacturing Order.'))
                group = 'pre_production.group_pp_final' if o.stage_code == 'done' else 'pre_production.group_pp_check2'
                if not self.env.user.has_group(group):
                    raise ValidationError(_('You do not have permission to set the Actual Produced Quantity at this stage.'))
        return super().write(vals)

    def unlink(self):
        for o in self:
            if o.picking_ids or o.check_ids or o.mo_id:
                raise ValidationError(_("You cannot delete a Pre-Production Order linked to transfers, quality checks or a "
                                        "Manufacturing Order. Archive it instead."))
        return super().unlink()

    def _load_lines(self):
        self.ensure_one()
        self.line_ids.unlink()
        bom = self.bom_id
        if not bom:
            return
        bom_qty = bom.product_uom_id._compute_quantity(bom.product_qty, self.product_uom_id or self.product_id.uom_id)
        factor = self.product_qty / (bom_qty or 1.0)
        vals = []
        for bl in bom.bom_line_ids:
            if not bl.product_id.is_storable:
                continue
            vals.append({
                'order_id': self.id, 'product_id': bl.product_id.id, 'bom_product_id': bl.product_id.id, 'bom_line_id': bl.id,
                'required_qty': bl.product_qty * factor, 'uom_id': bl.product_uom_id.id,
                'line_type': 'packaging' if bl.product_id.categ_id._pp_categ().pp_is_packaging else 'material',
            })
        self.env['pp.order.line'].create(vals)

    @api.onchange('product_qty')
    def _onchange_product_qty_actual(self):
        if self.state == 'draft':
            self.actual_product_qty = self.product_qty

    @api.onchange('bom_id', 'product_qty')
    def _onchange_reload_lines(self):
        if self._origin and self.state == 'draft':
            self._origin._load_lines()

    # ------------------------------------------------------------------ workflow
    def action_confirm(self):
        for o in self:
            o._check_perm('pre_production.group_pp_confirm', _("You do not have permission to confirm Pre-Production Orders."))
            if o.state != 'draft':
                continue
            missing = [label for label, val in (
                (_('Customer'), o.partner_id), (_('Product'), o.product_id), (_('BOM'), o.bom_id),
                (_('Manufacturing Warehouse'), o.manufacturing_warehouse_id)) if not val]
            if missing or o.product_qty <= 0:
                raise ValidationError(_("Cannot confirm. Missing or invalid: %s", ', '.join(missing + ([_('Quantity')] if o.product_qty <= 0 else []))))
            for l in o.line_ids:
                l._pick_warehouse()
                if not l.source_warehouse_id:
                    raise ValidationError(_("No Pre-Production warehouse is configured on the category of %s.", l.product_id.display_name))
            first = o._stage_sequence().filtered(lambda s: s.code != 'done')[:1]
            o.state = 'in_progress'
            o._log(False, _('Confirmed'))
            o._enter_stage(first)

    def action_cancel(self):
        self._check_perm('pre_production.group_pp_manager', _("Only Pre-Production managers can cancel orders."))
        for o in self:
            if o.mo_id and o.mo_id.state not in ('cancel', 'draft'):
                raise ValidationError(_("Cancel the Manufacturing Order first."))
            o.lock_ids.filtered(lambda l: l.state == 'active')._release()
            o.state = 'cancel'
            o._close_stage_log()
            o._clear_stage_activities()
            o._log(o.current_stage_id, _('Cancelled'))

    def _check_actual_qty(self):
        self.ensure_one()
        qty = self.actual_product_qty or 0.0
        if qty <= 0:
            raise ValidationError(_('Actual Produced Quantity must be greater than zero.'))
        if qty > self.product_qty:
            raise ValidationError(_('Actual Produced Quantity cannot be greater than the planned quantity.'))

    def action_set_actual_qty(self):
        self.ensure_one()
        self._check_perm('pre_production.group_pp_check2', _('You do not have permission to set the actual produced quantity.'))
        self._assert_stage('product_check2')
        self._check_actual_qty()
        self._log(self.current_stage_id, _('Actual Produced Quantity Set'), _('Planned: %s | Actual: %s | Waste/Loss: %s') % (self.product_qty, self.actual_product_qty, self.waste_qty))

    def _assert_stage(self, code):
        self.ensure_one()
        if self.state != 'in_progress' or self.current_stage_id.code != code:
            raise ValidationError(_("This action is not allowed at the current stage."))

    # --- issue (one button: materials + packaging)
    def action_issue(self):
        self.ensure_one()
        self._check_perm('pre_production.group_pp_issue', _("You do not have permission to issue materials."))
        self._assert_stage('material_issue')
        lines = self.line_ids.filtered(lambda l: not l.issued)
        if not lines:
            raise ValidationError(_("Nothing to issue."))
        lines._check_ready_for_issue()
        names = []
        for line_type in ('material', 'packaging'):
            type_lines = lines.filtered(lambda l: l.line_type == line_type)
            for wh in type_lines.mapped('source_warehouse_id'):
                picking = self._create_issue_picking(wh, type_lines.filtered(lambda l: l.source_warehouse_id == wh), line_type)
                names.append(picking.name)
        lines.write({'issued': True})
        if self.company_id.pp_auto_validate_issue:
            self._finalize_issue(names)
        else:
            self._log(self.current_stage_id, _('Issue transfers created'), ', '.join(names))

    def _finalize_issue(self, names=None):
        """Move on once every issue transfer of the order is done (called after issue or after manual validation)."""
        self.ensure_one()
        if self.state != 'in_progress' or self.current_stage_id.code != 'material_issue':
            return
        if any(not l.issued for l in self.line_ids):
            return
        pickings = self.picking_ids.filtered('pp_issue_type')
        if any(p.state not in ('done', 'cancel') for p in pickings):
            return
        self.write({'material_issue_done': True, 'packaging_issue_done': True})
        self._log(self.current_stage_id, _('Issued'), ', '.join(names or pickings.filtered(lambda p: p.state == 'done').mapped('name')))
        self._advance()

    def _create_issue_picking(self, wh, lines, line_type):
        self.ensure_one()
        dest = self.manufacturing_warehouse_id.lot_stock_id
        Move, MoveLine = self.env['stock.move'], self.env['stock.move.line']
        picking = self.env['stock.picking'].create({
            'picking_type_id': wh.int_type_id.id, 'location_id': wh.lot_stock_id.id,
            'location_dest_id': dest.id, 'origin': self.name, 'pp_order_id': self.id, 'pp_issue_type': line_type})
        for l in lines:
            Move.create({
                'name': l.product_id.display_name, 'product_id': l.product_id.id, 'product_uom_qty': l.required_qty,
                'product_uom': l.uom_id.id, 'picking_id': picking.id, 'location_id': wh.lot_stock_id.id,
                'location_dest_id': dest.id, 'company_id': self.company_id.id,
                'pp_order_id': self.id, 'pp_line_id': l.id})
        picking.action_confirm()
        # Odoo may already have reserved the stock on confirm (reservation method "at confirmation").
        # Drop that automatic reservation for lines with chosen lots, otherwise the lot lines created
        # below would be added on top of it and the transfer would take double the quantity.
        picking.move_ids.filtered(lambda m: m.pp_line_id.lot_line_ids)._do_unreserve()
        for l in lines.filtered('lot_line_ids'):
            move = picking.move_ids.filtered(lambda m: m.pp_line_id == l)
            for ll in l.lot_line_ids:
                for quant, qty in ll._allocate():
                    MoveLine.create({
                        'move_id': move.id, 'picking_id': picking.id, 'product_id': l.product_id.id,
                        'lot_id': ll.lot_id.id, 'quantity': qty, 'product_uom_id': l.uom_id.id,
                        'location_id': quant.location_id.id, 'location_dest_id': dest.id})
        picking.action_assign()
        if picking.state != 'assigned':
            raise ValidationError(_("Insufficient quantity available in the selected Lot."))
        if not self.company_id.pp_auto_validate_issue:
            return picking
        picking.move_ids.write({'picked': True})
        picking.with_context(skip_backorder=True, skip_sms=True, skip_immediate=True).button_validate()
        if picking.state != 'done':
            raise ValidationError(_("The stock transfer %s could not be validated.", picking.name))
        return picking

    def _create_locks(self, picking):
        Quant = self.env['stock.quant'].sudo()
        for ml in picking.move_line_ids:
            if not ml.product_id.is_storable or not ml.quantity:
                continue  # no stock tracking (e.g. packaging bought as consumable): nothing to lock
            qty = ml.product_uom_id._compute_quantity(ml.quantity, ml.product_id.uom_id)
            rounding = ml.product_id.uom_id.rounding
            # Odoo itself refuses to reserve more than the free quantity; just make its message explicit.
            try:
                Quant._update_reserved_quantity(
                    ml.product_id, ml.location_dest_id, qty, lot_id=ml.lot_id, strict=True)
            except UserError as e:
                free = Quant._get_available_quantity(ml.product_id, ml.location_dest_id, lot_id=ml.lot_id, strict=True)
                raise ValidationError(_(
                    "Cannot lock %(qty)s of %(product)s%(lot)s in %(loc)s (free quantity: %(free)s). %(err)s",
                    qty=qty, product=ml.product_id.display_name,
                    lot=_(" (lot %s)", ml.lot_id.name) if ml.lot_id else '',
                    loc=ml.location_dest_id.display_name, free=free, err=e.args[0] if e.args else ''))
            self.env['pp.lock'].sudo().create({
                'order_id': self.id, 'product_id': ml.product_id.id, 'lot_id': ml.lot_id.id, 'qty': qty,
                'location_id': ml.location_dest_id.id, 'picking_id': picking.id,
                'line_id': ml.move_id.pp_line_id.id})

    # --- weights
    def action_confirm_weights(self):
        self.ensure_one()
        self._check_perm('pre_production.group_pp_weight', _("You do not have permission to confirm weights."))
        self._assert_stage('weight')
        if any(not l.weight_confirmed for l in self.line_ids):
            raise ValidationError(_("Weight Confirmation is required."))
        self._log(self.current_stage_id, _('Done'))
        self._advance()

    # --- rejection / final
    def action_reinspect(self):
        self.ensure_one()
        stage = self.current_stage_id
        self._check_perm(STAGE_GROUPS[stage.code], _("You do not have permission to approve this stage."))
        if self.state != 'rejected':
            raise ValidationError(_("Only rejected orders can be re-inspected."))
        self.state = 'in_progress'
        # only the checks that failed are redone; the approved ones of the same stage stay valid
        rejected = self._stage_latest_checks(stage)
        templates = self.env['pp.quality.template'].browse(
            [t for t, c in rejected.items() if t and c.state == 'rejected'])
        if templates or any(c.state == 'rejected' and not t for t, c in rejected.items()):
            self.env['pp.quality.check']._create_for_order(self, stage, templates=templates or None)
        self._log(stage, _('Re-inspection started'))

    def action_create_mo(self):
        """Button after the last stage: close the order, create/confirm/finish the MO and make the final transfer."""
        self.ensure_one()
        self._check_perm('pre_production.group_pp_final', _("You do not have permission to create the Manufacturing Order."))
        self._assert_stage('done')
        if self.mo_id:
            raise ValidationError(_("The Manufacturing Order has already been created."))
        self._finish()

    def _finish(self):
        """Last stage reached: close the order, create the Manufacturing Order, confirm it and mark it as done."""
        self.ensure_one()
        self._check_actual_qty()
        self.state = 'done'
        self._close_stage_log()
        self._clear_stage_activities()
        self._log(self.current_stage_id, _('Done'))
        order = self.sudo()
        order._create_mo()
        order.mo_id.action_confirm()  # locks are bound to the component moves by MrpProduction.action_confirm
        order._auto_done_mo()

    def _auto_done_mo(self):
        """Produce the full quantity, consume the components (materials + packaging) and mark the MO as done."""
        self.ensure_one()
        mo = self.mo_id
        try:
            with self.env.cr.savepoint():
                mo.qty_producing = mo.product_qty
                mo.move_raw_ids.filtered(lambda m: m.state not in ('done', 'cancel')).write({'picked': True})
                mo.with_context(skip_immediate=True, skip_backorder=True, skip_consumption=True,
                                skip_expired=True).button_mark_done()
                if mo.state != 'done':
                    raise UserError(_("The Manufacturing Order needs manual validation."))
        except UserError as e:
            # keep the approval, leave the confirmed MO for the user to finish by hand
            self._log(self.current_stage_id, _('Manufacturing Order left for manual Mark as Done'), str(e.args[0])[:200])
            return
        self._log(self.current_stage_id, _('Manufacturing Order done'), mo.name)

    @api.model
    def _get_pp_name(self, sale_order_id=False):
        """Name of the Pre-Production Order: PRE-<sales order number> when it comes from a sales order
        (PRE-S00001, PRE-S00001-2 ... if several), else PRE-00001, PRE-00002..."""
        if sale_order_id:
            base = 'PRE-%s' % self.env['sale.order'].browse(sale_order_id).name
            PP = self.sudo().with_context(active_test=False)
            taken = PP.search([('name', '=like', base + '%')]).mapped('name')
            name, n = base, 1
            while name in taken:  # several Pre-Production orders on the same sales order
                n += 1
                name = '%s-%s' % (base, n)
            return name
        seq = self.env['ir.sequence'].sudo()
        name = seq.next_by_code('pp.order')
        if not name:  # the sequence record is missing (e.g. data not loaded): create it on the fly
            seq.create({'name': 'Pre-Production Order', 'code': 'pp.order', 'prefix': 'PRE-', 'padding': 5})
            name = seq.next_by_code('pp.order')
        return name

    def _create_finished_transfer(self):
        """Once the MO is done: internal transfer of the manufactured product from the manufacturing warehouse
        to the warehouse configured on the product category (Pre-Production Warehouses)."""
        self.ensure_one()
        mo = self.mo_id
        if not mo or mo.state != 'done' or self.picking_ids.filtered('pp_finished'):
            return
        mfg = self.manufacturing_warehouse_id
        dest_wh = (self.product_id.categ_id._pp_categ().pp_warehouse_ids - mfg)[:1]
        if not dest_wh:
            self._log(self.current_stage_id, _('Finished product transfer not created'),
                      _("No Pre-Production warehouse is configured on the category of %s.", self.product_id.display_name))
            return
        try:
            with self.env.cr.savepoint():
                finished = mo.move_finished_ids.filtered(lambda m: m.product_id == mo.product_id and m.state == 'done')
                src, dest = mfg.lot_stock_id, dest_wh.lot_stock_id
                picking = self.env['stock.picking'].create({
                    'picking_type_id': mfg.int_type_id.id, 'location_id': src.id, 'location_dest_id': dest.id,
                    'origin': '%s / %s' % (self.name, mo.name), 'pp_order_id': self.id, 'pp_finished': True})
                for m in finished:
                    qty = m.quantity
                    move = self.env['stock.move'].create({
                        'name': m.product_id.display_name, 'product_id': m.product_id.id, 'product_uom_qty': qty,
                        'product_uom': m.product_uom.id, 'picking_id': picking.id, 'location_id': src.id,
                        'location_dest_id': dest.id, 'company_id': self.company_id.id, 'pp_order_id': self.id})
                picking.action_confirm()
                # reserve exactly the lots produced by the MO (not any other lot of the same product in the warehouse)
                picking.move_ids._do_unreserve()
                for move, fm in zip(picking.move_ids, finished):
                    for ml in fm.move_line_ids:
                        self.env['stock.move.line'].create({
                            'move_id': move.id, 'picking_id': picking.id, 'product_id': move.product_id.id,
                            'lot_id': ml.lot_id.id, 'quantity': ml.quantity, 'product_uom_id': ml.product_uom_id.id,
                            'location_id': src.id, 'location_dest_id': dest.id})
                picking.action_assign()
                if self.company_id.pp_auto_validate_issue:
                    picking.move_ids.write({'picked': True})
                    picking.with_context(skip_backorder=True, skip_sms=True, skip_immediate=True).button_validate()
                    if picking.state != 'done':
                        raise UserError(_("The stock transfer %s could not be validated.", picking.name))
        except (UserError, ValidationError) as e:
            self._log(self.current_stage_id, _('Finished product transfer not created'), str(e.args[0])[:200])
            return
        self._log(self.current_stage_id, _('Finished product transfer'),
                  '%s (%s -> %s)' % (picking.name, mfg.name, dest_wh.name))

    def _create_mo(self):
        self.ensure_one()
        wh = self.manufacturing_warehouse_id
        mo = self.env['mrp.production'].create({
            'product_id': self.product_id.id, 'product_qty': self.actual_product_qty, 'product_uom_id': self.product_uom_id.id,
            'bom_id': self.bom_id.id, 'origin': self.sale_order_id.name or self.name,
            'picking_type_id': wh.manu_type_id.id, 'location_src_id': wh.lot_stock_id.id,
            'location_dest_id': wh.lot_stock_id.id, 'company_id': self.company_id.id, 'pp_order_id': self.id,
            'lot_producing_id': self.lot_producing_id.id or False})
        # Components come from the Pre-Production Order (products and quantities), not from the BOM.
        # Packaging lines are not consumed by the Manufacturing Order.
        mo.move_raw_ids.unlink()
        grouped = {}
        for l in self.line_ids.filtered(lambda x: x.line_type == 'material'):
            key = (l.product_id, l.uom_id)
            grouped.setdefault(key, self.env['pp.order.line'])
            grouped[key] |= l
        move_vals = []
        for (product, uom), lines in grouped.items():
            vals = mo._get_move_raw_values(product, sum(lines.mapped('required_qty')), uom,
                                           bom_line=lines.mapped('bom_line_id')[:1])
            vals['pp_order_id'] = self.id
            move_vals.append(vals)
        # Packaging is a normal component of the MO: issued and consumed together with the materials.
        packaging = {}
        for l in self.line_ids.filtered(lambda x: x.line_type == 'packaging'):
            packaging.setdefault((l.product_id, l.uom_id), self.env['pp.order.line'])
            packaging[(l.product_id, l.uom_id)] |= l
        for (product, uom), lines in packaging.items():
            vals = mo._get_move_raw_values(product, sum(lines.mapped('required_qty')), uom)
            vals.update({'pp_order_id': self.id, 'pp_packaging': True})
            move_vals.append(vals)
        if move_vals:
            self.env['stock.move'].create(move_vals)
        # Packaging is listed on the MO (EXTRA COMPOUND tab) for information; it is not consumed by the MO.
        extra = {}
        for l in self.line_ids.filtered(lambda x: x.line_type == 'packaging'):
            extra.setdefault((l.product_id, l.uom_id), self.env['pp.order.line'])
            extra[(l.product_id, l.uom_id)] |= l
        self.env['pp.mo.extra'].create([{
            'mo_id': mo.id, 'product_id': product.id, 'product_qty': sum(lines.mapped('required_qty')),
            'product_uom_id': uom.id, 'lot_summary': ', '.join(s for s in lines.mapped('lot_summary') if s),
        } for (product, uom), lines in extra.items()])
        self.mo_id = mo
        self._log(self.current_stage_id, _('Manufacturing Order created'), mo.name)

    def _bind_locks(self):
        """Called when the user confirms the MO: bind the locked lots/quantities to its component moves."""
        self.ensure_one()
        mo = self.mo_id
        mo.move_raw_ids._do_unreserve()
        locks = self.lock_ids.filtered(lambda l: l.state == 'active')
        locks._unreserve()
        for lock in locks:
            is_pack = lock.line_id.line_type == 'packaging'
            move = mo.move_raw_ids.filtered(lambda m: m.product_id == lock.product_id and m.pp_packaging == is_pack)[:1]
            if not move:
                continue
            self.env['stock.move.line'].create({
                'move_id': move.id, 'product_id': lock.product_id.id, 'lot_id': lock.lot_id.id,
                'quantity': lock.qty, 'product_uom_id': lock.product_id.uom_id.id,
                'location_id': lock.location_id.id, 'location_dest_id': move.location_dest_id.id})
        locks.write({'state': 'bound', 'mo_id': mo.id})
        self.mo_confirmed = True
        self._log(self.current_stage_id, _('Manufacturing Order confirmed'), mo.name)

    # ------------------------------------------------------------------ smart buttons
    def _act(self, name, model, domain):
        return {'type': 'ir.actions.act_window', 'name': name, 'res_model': model,
                'view_mode': 'list,form', 'domain': domain}

    def action_open_sale(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'sale.order', 'res_id': self.sale_order_id.id, 'view_mode': 'form'}

    def action_open_pickings(self):
        return self._act(_('Transfers'), 'stock.picking', [('pp_order_id', '=', self.id)])

    def action_open_checks(self):
        return self._act(_('Quality Checks'), 'pp.quality.check', [('order_id', '=', self.id)])

    def action_open_locks(self):
        return self._act(_('Lots / Traceability'), 'pp.lock', [('order_id', '=', self.id)])

    def action_open_mo(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'mrp.production', 'res_id': self.mo_id.id, 'view_mode': 'form'}


class PPAudit(models.Model):
    _name = 'pp.audit'
    _description = 'Pre-Production Audit Trail'
    _order = 'id'

    order_id = fields.Many2one('pp.order', required=True, ondelete='cascade', index=True)
    stage_id = fields.Many2one('pp.stage', 'Stage')
    user_id = fields.Many2one('res.users', 'User', default=lambda s: s.env.user)
    date = fields.Datetime(default=fields.Datetime.now)
    result = fields.Char()
    notes = fields.Char()

    def write(self, vals):
        raise ValidationError(_("Approval history cannot be modified."))

    def unlink(self):
        if not self.env.context.get('pp_cascade') and not self.env.su:
            raise ValidationError(_("Approval history cannot be deleted."))
        return super().unlink()


class PPLock(models.Model):
    _name = 'pp.lock'
    _description = 'Pre-Production Locked Stock / Lot Traceability'
    _order = 'id desc'

    order_id = fields.Many2one('pp.order', required=True, ondelete='restrict', index=True)
    line_id = fields.Many2one('pp.order.line')
    product_id = fields.Many2one('product.product', required=True)
    lot_id = fields.Many2one('stock.lot', 'Lot')
    qty = fields.Float('Locked Quantity')
    location_id = fields.Many2one('stock.location', 'Location')
    source_warehouse_id = fields.Many2one(related='line_id.source_warehouse_id', store=True)
    picking_id = fields.Many2one('stock.picking', 'Stock Transfer')
    mo_id = fields.Many2one('mrp.production', 'Manufacturing Order')
    state = fields.Selection([('active', 'Locked'), ('bound', 'Bound to MO'), ('released', 'Released')], default='active')

    def _unreserve(self):
        Quant = self.env['stock.quant'].sudo()
        for l in self:
            Quant._update_reserved_quantity(l.product_id, l.location_id, -l.qty, lot_id=l.lot_id, strict=True)

    def _release(self):
        self._unreserve()
        self.write({'state': 'released'})
