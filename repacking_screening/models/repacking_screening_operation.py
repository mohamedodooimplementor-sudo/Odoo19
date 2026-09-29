# -*- coding: utf-8 -*-
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class RepackingScreeningOperation(models.Model):
    _name = 'repacking.screening.operation'
    _description = 'Repacking & Screening Operation'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'scheduled_date desc, id desc'

    # ── Identity ──────────────────────────────────────────────────────────────
    name = fields.Char(
        string='Reference', required=True, copy=False, readonly=True,
        default=lambda self: _('New'))

    operation_type = fields.Selection([
        ('repacking', 'Repacking'),
        ('screening', 'Screening'),
    ], string='Operation Type', required=True, default='repacking', tracking=True)

    company_id = fields.Many2one(
        'res.company', string='Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True)

    # 4-step flow (same for both types):
    #   Draft → Transferred → Confirmed → (Manufacturing) → Done
    state = fields.Selection([
        ('draft',         'Draft'),
        ('transferred',   'Transferred to Manufacturing'),  # Step 0 done: product + packaging staged in Manufacturing Location
        ('confirmed',     'Confirmed'),      # Step 1 MO done: intermediate product ready in Manufacturing Location
        ('manufacturing', 'Manufacturing'),  # Step 2 MO in progress (manual mode only)
        ('done',          'Done'),           # Step 2 MO done + Step 3: → Destination(s)
        ('cancelled',     'Cancelled'),
    ], string='Status', default='draft', tracking=True, copy=False,
       group_expand='_group_expand_states')

    @api.model
    def _group_expand_states(self, states, domain, order=None):
        """Keep every stage visible as a kanban column, in the fixed order
        defined on the field, even when a stage currently has zero records —
        instead of Odoo's default of only showing/sorting groups that exist."""
        return [key for key, _label in
                type(self).state.selection]

    # ── Common fields ─────────────────────────────────────────────────────────
    source_location_id = fields.Many2one(
        'stock.location', string='Source Location', required=True,
        domain="[('usage','=','internal')]",
        default=lambda self: self.env.ref(
            'stock.stock_location_stock', raise_if_not_found=False))

    # Input product = Final product (same)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain="[('type','in',('product','consu'))]")

    quantity = fields.Float(
        string='Input Quantity', required=True, digits='Product Unit of Measure')
    product_uom_id = fields.Many2one(
        'uom.uom', related='product_id.uom_id', readonly=True)

    output_quantity = fields.Float(
        string='Output Quantity', digits='Product Unit of Measure')

    scheduled_date = fields.Datetime(
        string='Scheduled Date', required=True, default=fields.Datetime.now)
    user_id = fields.Many2one(
        'res.users', string='Responsible', default=lambda self: self.env.user)
    notes = fields.Text(string='Notes')

    # ── Intermediate product & location ───────────────────────────────────────
    intermediate_product_id = fields.Many2one(
        'product.product', string='Intermediate Product',
        domain="[('type','in',('product','consu'))]",
        default=lambda self: self.env.ref(
            'repacking_screening.product_intermediate_wip',
            raise_if_not_found=False),
        help='WIP product — auto-created at module install, reused across batches.')

    # Manufacturing location: internal, auto-created. Serves as the single
    # "factory" location for the whole flow — Step 0 stages the input
    # product (and packaging materials, for Repacking) here first, then
    # Step 1's MO consumes them from here to produce the intermediate
    # product, and Step 2's MO produces the final product + byproducts here
    # too — all within the same location.
    manufacturing_location_id = fields.Many2one(
        'stock.location', string='Manufacturing Location',
        domain="[('usage','=','internal')]",
        default=lambda self: self.env.ref(
            'repacking_screening.stock_location_manufacturing',
            raise_if_not_found=False),
        help='Dedicated manufacturing location. Step 0 moves the input '
             'product (and packaging materials, for Repacking) here from '
             'the Source Location; the intermediate product, final product '
             'and any byproducts are all produced here too.')

    lot_id = fields.Many2one(
        'stock.lot', string='Batch / Lot', copy=False, readonly=True)

    # ── Packaging materials (Repacking only) ──────────────────────────────────
    packaging_line_ids = fields.One2many(
        'repacking.packaging.line', 'operation_id', string='Packaging Materials')

    # ── Secondary / byproducts (both types) ───────────────────────────────────
    secondary_product_ids = fields.One2many(
        'repacking.secondary.product', 'operation_id', string='Secondary Products')

    # ── Screening result lines (optional detailed breakdown) ──────────────────
    line_ids = fields.One2many(
        'repacking.screening.line', 'operation_id', string='Screening Result Lines')

    total_quantity = fields.Float(
        string='Total Result Qty', compute='_compute_total_quantity', store=True,
        digits='Product Unit of Measure')

    # ── Generated Manufacturing Orders / stock pickings ─────────────────────────
    # Step 0 – تحويل داخلي: Internal Transfer — Product (+ Packaging
    # Materials, for Repacking) → Manufacturing Location.
    transfer_picking_id = fields.Many2one(
        'stock.picking',
        string='Step 0 – Internal Transfer: Product + Packaging → Manufacturing Location',
        copy=False, readonly=True)
    # Step 1 – Confirm: Manufacturing Order — Product (+ Packaging Materials)
    # → Intermediate Product, produced into the Manufacturing Location.
    intermediate_mo_id = fields.Many2one(
        'mrp.production', string='Step 1 – Intermediate Manufacturing Order',
        copy=False, readonly=True)
    # Step 2 – تصديق: Manufacturing Order — Intermediate → final product
    # (+ byproducts), consumed from and produced back into the Manufacturing
    # Location.
    mfg_production_id = fields.Many2one(
        'mrp.production', string='Step 2 – Final Manufacturing Order',
        copy=False, readonly=True)
    # Step 3 (auto) – Manufacturing Location → each product's own destination
    # (main product → Source Location, each secondary product → its own
    # "Store In" location if set, otherwise Source Location too).
    output_transfer_picking_ids = fields.Many2many(
        'stock.picking', 'repacking_step4_picking_rel', 'operation_id',
        'picking_id', string='Step 3 – Manufacturing → Destination(s)',
        copy=False, readonly=True)

    picking_count = fields.Integer(compute='_compute_picking_count')
    mfg_count = fields.Integer(compute='_compute_picking_count')

    # ── Cost Analysis ──────────────────────────────────────────────────────────
    total_input_cost = fields.Monetary(
        compute='_compute_cost', store=True, currency_field='currency_id')
    main_product_cost = fields.Monetary(
        compute='_compute_cost', store=True, currency_field='currency_id')
    secondary_cost_pct_total = fields.Float(
        compute='_compute_cost', store=True, digits=(6, 2))
    good_quantity = fields.Float(
        compute='_compute_cost', store=True, digits='Product Unit of Measure')
    waste_quantity = fields.Float(
        compute='_compute_cost', store=True, digits='Product Unit of Measure')
    loss_percentage = fields.Float(
        compute='_compute_cost', store=True, digits=(6, 2), group_operator='avg')
    yield_percentage = fields.Float(
        compute='_compute_cost', store=True, digits=(6, 2), group_operator='avg')

    # ── Recurrence ────────────────────────────────────────────────────────────
    is_recurring = fields.Boolean(string='Recurring', tracking=True)
    recurrence_interval = fields.Integer(string='Repeat Every', default=1)
    recurrence_unit = fields.Selection([
        ('day', 'Day(s)'), ('week', 'Week(s)'), ('month', 'Month(s)'),
    ], default='week')
    recurrence_end_date = fields.Date(string='End Date')
    next_recurrence_date = fields.Datetime(copy=False, readonly=True)
    recurring_parent_id = fields.Many2one(
        'repacking.screening.operation', copy=False, readonly=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Computes
    # ─────────────────────────────────────────────────────────────────────────

    @api.depends('output_transfer_picking_ids', 'transfer_picking_id',
                 'intermediate_mo_id', 'mfg_production_id')
    def _compute_picking_count(self):
        for rec in self:
            rec.picking_count = (len(rec.output_transfer_picking_ids.ids)
                                  + (1 if rec.transfer_picking_id else 0))
            rec.mfg_count = len(rec.intermediate_mo_id.ids) + len(rec.mfg_production_id.ids)

    @api.depends('line_ids.quantity', 'output_quantity')
    def _compute_total_quantity(self):
        for rec in self:
            rec.total_quantity = (sum(rec.line_ids.mapped('quantity'))
                                  if rec.line_ids else rec.output_quantity)

    @api.depends('product_id', 'quantity', 'output_quantity',
                 'packaging_line_ids.product_id', 'packaging_line_ids.quantity',
                 'secondary_product_ids.cost_percentage',
                 'line_ids.quantity', 'line_ids.line_type')
    def _compute_cost(self):
        for rec in self:
            # yield / loss
            if rec.line_ids:
                waste = sum(rec.line_ids.filtered(
                    lambda l: l.line_type == 'waste').mapped('quantity'))
                good = sum(rec.line_ids.filtered(
                    lambda l: l.line_type != 'waste').mapped('quantity'))
            else:
                good = rec.output_quantity
                waste = max(rec.quantity - rec.output_quantity, 0.0)

            rec.good_quantity = good
            rec.waste_quantity = waste
            rec.loss_percentage = (waste / rec.quantity * 100.0) if rec.quantity else 0.0
            rec.yield_percentage = (good / rec.quantity * 100.0) if rec.quantity else 0.0

            # cost
            input_cost = (rec.product_id.standard_price or 0.0) * rec.quantity
            pkg_cost = sum(
                (l.product_id.standard_price or 0.0) * l.quantity
                for l in rec.packaging_line_ids)
            total = input_cost + pkg_cost
            sec_pct = sum(rec.secondary_product_ids.mapped('cost_percentage'))
            rec.total_input_cost = total
            rec.secondary_cost_pct_total = sec_pct
            rec.main_product_cost = total * max(100.0 - sec_pct, 0.0) / 100.0

    # ─────────────────────────────────────────────────────────────────────────
    # ORM
    # ─────────────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                seq = ('repacking.screening.repacking'
                       if vals.get('operation_type', 'repacking') == 'repacking'
                       else 'repacking.screening.screening')
                vals['name'] = self.env['ir.sequence'].next_by_code(seq) or _('New')
        return super().create(vals_list)

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _step_auto(self, key):
        """Whether the given step ('step0'..'step3') should auto-validate its
        generated stock document, per Configuration > Settings. Defaults to
        True (always-automatic behavior) if never configured."""
        settings = self.env['repacking.screening.settings'].sudo().get_settings()
        return bool(getattr(settings, '%s_auto_validate' % key, True))

    def _int_pt(self):
        """Internal picking type for the operation's warehouse, derived from
        the Source Location (destination_warehouse_id was removed — unused)."""
        warehouse = self.source_location_id.warehouse_id
        pt = self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id', '=', warehouse.id),
        ], limit=1)
        return pt or self.env['stock.picking.type'].search(
            [('code', '=', 'internal')], limit=1)

    def _make_and_validate(self, picking_type, src, dst, move_specs, auto_validate=True):
        """
        Create and confirm a picking, reserve it, and pre-fill quantities.
        If auto_validate is True, also mark it Done immediately (previous
        behavior). If False, the picking is left "Ready"/"Reserved" with
        quantities already filled in, for the user to validate manually
        from Inventory whenever they choose to.
        move_specs: list of dict(product_id, qty, uom=None, lot_id=None, price_unit=None)
        """
        # 'planned_picking=True' prevents _autoconfirm_picking() from being triggered
        # during create(), avoiding the mrp/mrp_workorder force_qty conflict.
        picking = self.env['stock.picking'].with_context(
            planned_picking=True,
            mail_notrack=True,
        ).create({
            'picking_type_id': picking_type.id,
            'location_id': src.id,
            'location_dest_id': dst.id,
            'scheduled_date': self.scheduled_date,
            'origin': self.name,
            'move_type': 'direct',
            'company_id': self.company_id.id,
        })
        for spec in move_specs:
            self.env['stock.move'].create({
                'name': spec['product_id'].display_name,
                'product_id': spec['product_id'].id,
                'product_uom_qty': spec['qty'],
                'product_uom': (spec.get('uom') or spec['product_id'].uom_id).id,
                'picking_id': picking.id,
                # Allow a move to override the picking's default src/dst,
                # e.g. a packaging material pulled from a different warehouse.
                'location_id': spec.get('location_id', src.id),
                'location_dest_id': spec.get('location_dest_id', dst.id),
                'company_id': self.company_id.id,
                'price_unit': spec.get('price_unit', 0.0),
            })
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
            lot = next(
                (s.get('lot_id') for s in move_specs
                 if s['product_id'].id == move.product_id.id), None)
            if lot:
                for ml in move.move_line_ids:
                    ml.lot_id = lot
            move.picked = True
        if auto_validate:
            picking.with_context(skip_backorder=True).button_validate()
        return picking

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 0 — تحويل داخلي:  Internal Transfer — Product (+ Packaging
    #                         Materials, for Repacking) → Manufacturing Location.
    # ─────────────────────────────────────────────────────────────────────────

    def action_transfer_to_factory(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_(
                    'Operation must be in Draft to perform the internal '
                    'transfer to the Manufacturing Location.'))
            if not rec.manufacturing_location_id:
                raise UserError(_('Please set the Manufacturing Location.'))
            if rec.operation_type == 'repacking' and not rec.packaging_line_ids:
                raise UserError(_('Please add at least one Packaging Material.'))

            src = rec.source_location_id
            dst = rec.manufacturing_location_id

            move_specs = [{
                'product_id': rec.product_id,
                'qty': rec.quantity,
                'uom': rec.product_uom_id,
            }]
            if rec.operation_type == 'repacking':
                for l in rec.packaging_line_ids:
                    move_specs.append({
                        'product_id': l.product_id,
                        'qty': l.quantity,
                        'uom': l.uom_id,
                        'location_id': (l.location_id or src).id,
                    })

            step0_auto = rec._step_auto('step0')
            picking = rec._make_and_validate(
                rec._int_pt(), src, dst, move_specs, auto_validate=step0_auto)

            rec.transfer_picking_id = picking
            rec.state = 'transferred'

            rec.message_post(body=_(
                'Step 0 — Internal Transfer <b>%(p)s</b> created%(auto)s. '
                'Product%(pkg)s moved to <b>%(loc)s</b>.',
                p=picking.name,
                loc=dst.display_name,
                pkg=_(' and packaging materials') if rec.operation_type == 'repacking' else '',
                auto=_(' and validated') if step0_auto else _(
                    ' — please validate it yourself from the Inventory app '
                    'before proceeding to Step 1')))
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1 — Confirm:  Manufacturing Order — Product (+ Packaging Materials)
    #                     → Intermediate Product, produced in the
    #                     Manufacturing Location.
    # ─────────────────────────────────────────────────────────────────────────

    def action_confirm(self):
        for rec in self:
            if rec.state != 'transferred':
                raise UserError(_(
                    'Operation must go through Step 0 — Internal Transfer to '
                    'the Manufacturing Location — before it can be confirmed.'))
            if (not rec._step_auto('step0') and rec.transfer_picking_id
                    and rec.transfer_picking_id.state != 'done'):
                raise UserError(_(
                    'Step 0 Internal Transfer is set to manual validation '
                    'and is not Done yet. Please validate it from the '
                    'Inventory app first (or enable auto-validation for '
                    'Step 0 in Configuration > Settings).'))
            if not rec.intermediate_product_id:
                raise UserError(_('Please set the Intermediate Product.'))
            if not rec.manufacturing_location_id:
                raise UserError(_('Please set the Manufacturing Location.'))
            if not rec.output_quantity:
                raise UserError(_('Please set the Output Quantity.'))
            if rec.operation_type == 'repacking' and not rec.packaging_line_ids:
                raise UserError(_('Please add at least one Packaging Material.'))

            # Step 0 already staged the product + packaging materials into
            # the Manufacturing Location, so Step 1's MO consumes them from
            # (and produces the intermediate product back into) that same
            # single location.
            src = rec.manufacturing_location_id
            mfg_loc = rec.manufacturing_location_id
            production_loc = self.env.ref(
                'mrp.location_production', raise_if_not_found=False)

            # Auto-create batch/lot for the intermediate product
            lot = rec.env['stock.lot'].create({
                'name': rec.name,
                'product_id': rec.intermediate_product_id.id,
                'company_id': rec.company_id.id,
            })
            rec.lot_id = lot

            # Unit cost of the intermediate = (input product cost + packaging
            # materials cost) / output qty — same formula as before, just
            # applied directly on the MO's component moves now.
            input_cost = (rec.product_id.standard_price or 0.0) * rec.quantity
            pkg_cost = sum(
                (l.product_id.standard_price or 0.0) * l.quantity
                for l in rec.packaging_line_ids)
            total_cost = input_cost + pkg_cost
            unit_cost = total_cost / rec.output_quantity if rec.output_quantity else 0.0

            move_raw_vals = [(0, 0, {
                'name': rec.product_id.display_name,
                'product_id': rec.product_id.id,
                'product_uom_qty': rec.quantity,
                'product_uom': rec.product_uom_id.id,
                'location_id': src.id,
                'location_dest_id': production_loc.id if production_loc else src.id,
            })]
            if rec.operation_type == 'repacking':
                for l in rec.packaging_line_ids:
                    # Sourced uniformly from the Manufacturing Location now —
                    # Step 0 already staged it there (from l.location_id, if set).
                    move_raw_vals.append((0, 0, {
                        'name': l.product_id.display_name,
                        'product_id': l.product_id.id,
                        'product_uom_qty': l.quantity,
                        'product_uom': l.uom_id.id,
                        'location_id': src.id,
                        'location_dest_id': (
                            production_loc.id if production_loc else src.id),
                    }))

            mo_vals = {
                'product_id': rec.intermediate_product_id.id,
                'product_qty': rec.output_quantity,
                'product_uom_id': rec.intermediate_product_id.uom_id.id,
                'location_src_id': src.id,       # consume from source
                'location_dest_id': mfg_loc.id,  # produce to manufacturing location
                'origin': rec.name,
                'company_id': rec.company_id.id,
                'move_raw_ids': move_raw_vals,
            }
            mo1 = self.env['mrp.production'].create(mo_vals)
            mo1.action_confirm()

            for move in mo1.move_raw_ids:
                move.quantity = move.product_uom_qty
                move.picked = True

            if rec.intermediate_product_id.tracking != 'none':
                mo1.lot_producing_id = lot
            mo1.qty_producing = mo1.product_qty
            mo1._set_qty_producing()

            rec.intermediate_mo_id = mo1
            step1_auto = rec._step_auto('step1')

            if step1_auto:
                try:
                    mo1.button_mark_done()
                except Exception:
                    mo1.with_context(skip_backorder=True).button_mark_done()

            rec.state = 'confirmed'
            if rec.is_recurring and not rec.next_recurrence_date:
                rec.next_recurrence_date = rec._get_next_recurrence_date(
                    rec.scheduled_date or fields.Datetime.now())

            rec.message_post(body=_(
                'Step 1 — Manufacturing Order <b>%(mo)s</b> created%(auto)s. '
                'Intermediate product <b>%(p)s</b> (batch <b>%(l)s</b>) '
                'produced in %(loc)s. Unit cost set to <b>%(c).4f</b>.',
                mo=mo1.name, p=rec.intermediate_product_id.display_name,
                l=lot.name, loc=mfg_loc.display_name, c=unit_cost,
                auto=_(' and validated') if step1_auto else _(
                    ' — please mark it Done yourself in the Manufacturing '
                    'app before proceeding to Step 2')))
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 2 — تصديق:  Manufacturing Order — Intermediate → Final Product
    #                   (+ byproducts), all within the Manufacturing Location.
    # ─────────────────────────────────────────────────────────────────────────

    def action_validate(self):
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('Operation must be Confirmed before this step.'))
            if (not rec._step_auto('step1') and rec.intermediate_mo_id
                    and rec.intermediate_mo_id.state != 'done'):
                raise UserError(_(
                    'Step 1 Manufacturing Order is set to manual validation '
                    'and is not Done yet. Please validate it from the '
                    'Manufacturing app first (or enable auto-validation for '
                    'Step 1 in Configuration > Settings).'))

            mfg_loc = rec.manufacturing_location_id
            src = rec.source_location_id

            # ── Recompute cost for allocation ─────────────────────────────────
            input_cost = (rec.product_id.standard_price or 0.0) * rec.quantity
            pkg_cost = sum(
                (l.product_id.standard_price or 0.0) * l.quantity
                for l in rec.packaging_line_ids)
            total_cost = input_cost + pkg_cost
            sec_pct = sum(rec.secondary_product_ids.mapped('cost_percentage'))
            main_pct = max(100.0 - sec_pct, 0.0)
            main_unit_cost = (
                total_cost * main_pct / 100.0 / rec.output_quantity
                if rec.output_quantity else 0.0)

            # ── Create Manufacturing Order ────────────────────────────────────
            # Component (raw material): intermediate product (with lot + cost),
            # consumed from the Manufacturing Location where Step 1 produced it.
            # Output: final product (= input product) → manufacturing location
            # Byproducts: secondary products
            mo_vals = {
                'product_id': rec.product_id.id,
                'product_qty': rec.output_quantity,
                'product_uom_id': rec.product_uom_id.id,
                'location_src_id': mfg_loc.id,    # consume from manufacturing location
                'location_dest_id': mfg_loc.id,   # produce back to manufacturing location
                'origin': rec.name,
                'company_id': rec.company_id.id,
                'move_raw_ids': [(0, 0, {
                    'name': rec.intermediate_product_id.display_name,
                    'product_id': rec.intermediate_product_id.id,
                    'product_uom_qty': rec.output_quantity,
                    'product_uom': rec.intermediate_product_id.uom_id.id,
                    'location_id': mfg_loc.id,
                    'location_dest_id': self.env.ref(
                        'mrp.location_production', raise_if_not_found=False
                    ).id if self.env.ref(
                        'mrp.location_production', raise_if_not_found=False) else mfg_loc.id,
                    'price_unit': main_unit_cost,
                })],
            }

            # Add byproducts if any
            if rec.secondary_product_ids:
                byproduct_moves = []
                for sec in rec.secondary_product_ids:
                    sec_unit_cost = (
                        total_cost * sec.cost_percentage / 100.0 / sec.quantity
                        if sec.quantity else 0.0)
                    byproduct_moves.append((0, 0, {
                        'name': sec.product_id.display_name,
                        'product_id': sec.product_id.id,
                        'product_uom_qty': sec.quantity,
                        'product_uom': sec.uom_id.id,
                        'location_id': self.env.ref(
                            'mrp.location_production', raise_if_not_found=False
                        ).id if self.env.ref(
                            'mrp.location_production', raise_if_not_found=False) else mfg_loc.id,
                        # Byproducts land in the manufacturing location first,
                        # just like the main product — Step 3 below then
                        # transfers each one out to its own destination.
                        'location_dest_id': mfg_loc.id,
                        'price_unit': sec_unit_cost,
                        # This is the field that actually drives cost
                        # allocation on the MO — see the cost_share loop below.
                        'cost_share': sec.cost_percentage,
                        'byproduct_id': False,
                    }))
                mo_vals['move_byproduct_ids'] = byproduct_moves

            mo = self.env['mrp.production'].create(mo_vals)
            mo.action_confirm()

            # ── Cost split between main product and byproducts ────────────────
            # Odoo allocates the components' cost across move_finished_ids using
            # each move's `cost_share` (%). Setting only price_unit (as before)
            # has NO effect on that split — without cost_share, the byproducts
            # are valued at 0 and the main product silently absorbs 100% of the
            # cost. This is what was causing byproducts to "not take cost".
            for m in mo.move_finished_ids:
                if m.product_id == rec.product_id:
                    m.cost_share = main_pct
                else:
                    sec = rec.secondary_product_ids.filtered(
                        lambda s: s.product_id == m.product_id)
                    if sec:
                        m.cost_share = sec[0].cost_percentage

            # Set quantities and assign lot to raw material
            for move in mo.move_raw_ids:
                move.quantity = move.product_uom_qty
                if move.product_id == rec.intermediate_product_id and rec.lot_id:
                    for ml in move.move_line_ids:
                        ml.lot_id = rec.lot_id
                move.picked = True

            mo.qty_producing = mo.product_qty
            mo._set_qty_producing()

            rec.mfg_production_id = mo
            step2_auto = rec._step_auto('step2')

            if step2_auto:
                try:
                    mo.button_mark_done()
                except Exception:
                    mo.with_context(skip_backorder=True).button_mark_done()

                rec.message_post(body=_(
                    'Step 2 done — Manufacturing Order <b>%(mo)s</b> created and validated. '
                    'Final product <b>%(p)s</b> (qty: %(q)s, unit cost: %(c).4f) '
                    'produced in %(loc)s.',
                    mo=mo.name,
                    p=rec.product_id.display_name,
                    q=rec.output_quantity,
                    c=main_unit_cost,
                    loc=mfg_loc.display_name))

                rec._do_output_transfer(mo)
            else:
                rec.state = 'manufacturing'
                rec.message_post(body=_(
                    'Step 2 — Manufacturing Order <b>%(mo)s</b> created and '
                    'confirmed, quantities pre-filled. Manual validation is '
                    'enabled for Step 2: please mark it Done yourself in the '
                    'Manufacturing app, then click <b>Complete Manufacturing</b> '
                    'here to transfer the output.',
                    mo=mo.name))
        return True

    def _do_output_transfer(self, mo):
        """Step 3 — Manufacturing Location → each product's own destination.
        Called automatically right after the Step 2 MO is marked Done (Step 2
        auto mode), or manually via action_complete_manufacturing (Step 2
        manual mode, once the user has finished the MO themselves)."""
        self.ensure_one()
        mfg_loc = self.manufacturing_location_id
        src = self.source_location_id
        step3_auto = self._step_auto('step3')

        finished_lot = (mo.lot_producing_id
                        if self.product_id.tracking != 'none' else False)
        dest_groups = {}  # stock.location -> list of move specs
        dest_groups.setdefault(src, []).append({
            'product_id': self.product_id,
            'qty': self.output_quantity,
            'uom': self.product_uom_id,
            'lot_id': finished_lot,
        })
        for sec in self.secondary_product_ids:
            dest = sec.location_id or src
            dest_groups.setdefault(dest, []).append({
                'product_id': sec.product_id,
                'qty': sec.quantity,
                'uom': sec.uom_id,
            })

        out_pickings = self.env['stock.picking']
        for dest, specs in dest_groups.items():
            out_pickings |= self._make_and_validate(
                self._int_pt(), mfg_loc, dest, specs, auto_validate=step3_auto)
        self.output_transfer_picking_ids = [(6, 0, out_pickings.ids)]

        self.state = 'done'
        self.message_post(body=_(
            'Step 3 done — finished product and secondary products '
            'transferred out of %(loc)s via %(n)s transfer(s)%(auto)s.',
            loc=mfg_loc.display_name, n=len(out_pickings),
            auto=_('') if step3_auto else _(' (pending manual validation)')))

    def action_complete_manufacturing(self):
        """Manual counterpart to Step 2 auto-completion: called once the user
        has marked the Step 2 Manufacturing Order Done themselves."""
        for rec in self:
            if rec.state != 'manufacturing':
                raise UserError(_(
                    'This operation is not waiting on a manual Manufacturing '
                    'completion.'))
            mo = rec.mfg_production_id
            if not mo or mo.state != 'done':
                raise UserError(_(
                    'Please validate the Manufacturing Order first — mark it '
                    'as Done in the Manufacturing app — then come back here.'))
            rec._do_output_transfer(mo)
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Cancel / Reset
    # ─────────────────────────────────────────────────────────────────────────

    def action_cancel(self):
        for rec in self:
            if rec.transfer_picking_id and rec.transfer_picking_id.state not in ('done', 'cancel'):
                rec.transfer_picking_id.action_cancel()
            if rec.intermediate_mo_id and rec.intermediate_mo_id.state not in ('done', 'cancel'):
                rec.intermediate_mo_id.action_cancel()
            if rec.mfg_production_id and rec.mfg_production_id.state not in ('done', 'cancel'):
                rec.mfg_production_id.action_cancel()
            for pick in rec.output_transfer_picking_ids:
                if pick.state not in ('done', 'cancel'):
                    pick.action_cancel()
            rec.state = 'cancelled'
        return True

    def action_draft(self):
        self.write({'state': 'draft'})

    # ─────────────────────────────────────────────────────────────────────────
    # Smart button
    # ─────────────────────────────────────────────────────────────────────────

    def action_view_pickings(self):
        self.ensure_one()
        picks = self.output_transfer_picking_ids | self.transfer_picking_id
        action = self.env['ir.actions.act_window']._for_xml_id(
            'stock.action_picking_tree_all')
        if len(picks) > 1:
            action['domain'] = [('id', 'in', picks.ids)]
        elif picks:
            action['views'] = [(False, 'form')]
            action['res_id'] = picks.id
        return action

    def action_view_mo(self):
        self.ensure_one()
        mos = self.intermediate_mo_id | self.mfg_production_id
        action = self.env['ir.actions.act_window']._for_xml_id(
            'mrp.mrp_production_action')
        if len(mos) > 1:
            action['domain'] = [('id', 'in', mos.ids)]
        elif mos:
            action['views'] = [(False, 'form')]
            action['res_id'] = mos.id
        return action

    # ─────────────────────────────────────────────────────────────────────────
    # Recurrence
    # ─────────────────────────────────────────────────────────────────────────

    def _get_next_recurrence_date(self, from_date):
        self.ensure_one()
        n = self.recurrence_interval or 1
        if self.recurrence_unit == 'day':
            return from_date + relativedelta(days=n)
        if self.recurrence_unit == 'month':
            return from_date + relativedelta(months=n)
        return from_date + relativedelta(weeks=n)

    @api.model
    def _cron_generate_recurring_operations(self):
        now = fields.Datetime.now()
        for rec in self.search([
            ('is_recurring', '=', True),
            ('next_recurrence_date', '<=', now),
            ('state', 'in', ('transferred', 'confirmed', 'packaging', 'done')),
        ]):
            if rec.recurrence_end_date and now.date() > rec.recurrence_end_date:
                rec.is_recurring = False
                continue
            self.create({
                'operation_type': rec.operation_type,
                'source_location_id': rec.source_location_id.id,
                'product_id': rec.product_id.id,
                'quantity': rec.quantity,
                'output_quantity': rec.output_quantity,
                'intermediate_product_id': rec.intermediate_product_id.id,
                'scheduled_date': rec.next_recurrence_date,
                'user_id': rec.user_id.id,
                'notes': rec.notes,
                'company_id': rec.company_id.id,
                'is_recurring': False,
                'recurring_parent_id': rec.id,
                'packaging_line_ids': [(0, 0, {
                    'product_id': l.product_id.id,
                    'uom_id': l.uom_id.id,
                    'quantity': l.quantity,
                }) for l in rec.packaging_line_ids],
                'secondary_product_ids': [(0, 0, {
                    'product_id': s.product_id.id,
                    'uom_id': s.uom_id.id,
                    'quantity': s.quantity,
                    'cost_percentage': s.cost_percentage,
                }) for s in rec.secondary_product_ids],
                'line_ids': [(0, 0, {
                    'product_id': l.product_id.id,
                    'line_type': l.line_type,
                    'uom_id': l.uom_id.id,
                    'quantity': l.quantity,
                }) for l in rec.line_ids],
            })
            rec.next_recurrence_date = rec._get_next_recurrence_date(
                rec.next_recurrence_date)
