from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .template import PHASES

LOSS_TYPES = ('extravasation', 'human_error', 'defective')
PHASE_ORDER = [code for code, _label in PHASES]
# how many phases are already confirmed in each state
EXAM_PROTECTED = {'state', 'sale_order_id', 'sale_line_id'}
EXAM_LOCKED_AFTER_DRAFT = {'room_id', 'company_id', 'service_product_id', 'template_id'}
PHASES_DONE = {'draft': 0, 'prep': 1, 'scan': 2, 'done': 3, 'cancel': 0}


class RcExamConsumption(models.Model):
    _name = 'rc.exam.consumption'
    _inherit = ['rc.stock.mixin', 'mail.thread']
    _description = 'Exam Consumption'
    _order = 'date desc, id desc'

    name = fields.Char(default=lambda s: _('New'), readonly=True, copy=False)
    state = fields.Selection([
        ('draft', 'Draft'), ('prep', 'Preparation Done'), ('scan', 'Scan Done'),
        ('done', 'Done'), ('cancel', 'Cancelled'),
    ], default='draft', tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    room_id = fields.Many2one(
        'stock.location', string='Room', tracking=True,
        domain="[('usage', '=', 'internal'), '|', ('is_room', '=', True), ('is_lab', '=', True)]",
        default=lambda s: s.env['stock.location'].search(
            [('rc_responsible_ids', 'in', s.env.uid)], limit=1))
    service_product_id = fields.Many2one(
        'product.product', string='Exam', domain="[('type', '=', 'service')]")
    template_id = fields.Many2one('rc.consumption.template', string='Template')
    patient_id = fields.Many2one('res.partner', string='Patient', index=True, tracking=True,
                                 help='The patient as a customer (contact).')
    sale_order_id = fields.Many2one('sale.order', string='Sales Order', readonly=True, copy=False, index=True)
    sale_line_id = fields.Many2one('sale.order.line', readonly=True, copy=False, index=True, ondelete='set null')
    ris_ref = fields.Char(string='RIS Reference', index=True, copy=False)
    source = fields.Selection([('manual', 'Manual'), ('ris', 'RIS')], default='manual', required=True)
    date = fields.Datetime(default=fields.Datetime.now)
    nurse_id = fields.Many2one('res.users', string='Nurse', default=lambda s: s.env.user)
    with_contrast = fields.Boolean()
    allergy_case = fields.Boolean()
    needs_gown = fields.Boolean()
    line_ids = fields.One2many('rc.exam.consumption.line', 'consumption_id', string='Consumables')

    @api.constrains('ris_ref', 'company_id')
    def _check_ris_ref(self):
        for rec in self.filtered('ris_ref'):
            if self.search_count([('id', '!=', rec.id), ('ris_ref', '=', rec.ris_ref),
                                  ('company_id', '=', rec.company_id.id),
                                  ('state', '!=', 'cancel')]):
                raise ValidationError(_('This RIS reference already has a consumption record.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                bad = {k for k in EXAM_PROTECTED
                       if vals.get(k) and not (k == 'state' and vals[k] == 'draft')}
                if bad:
                    raise AccessError(_('These fields are managed by the workflow: %s', ', '.join(sorted(bad))))
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('rc.exam.consumption') or _('New')
        return super().create(vals_list)

    def write(self, vals):
        # The stage only moves through the confirm buttons, which write as superuser.
        if not self.env.su:
            if EXAM_PROTECTED & set(vals):
                raise AccessError(_('These fields are managed by the workflow and cannot be edited directly.'))
            if EXAM_LOCKED_AFTER_DRAFT & set(vals) and any(r.state != 'draft' for r in self):
                raise AccessError(_('The room, exam and company cannot change after the first stage is confirmed.'))
        return super().write(vals)

    def _rc_fill_lines(self):
        for rec in self:
            cmds = [Command.clear()]
            for l in rec.template_id.line_ids:
                if l.condition == 'contrast' and not rec.with_contrast:
                    continue
                if l.condition == 'allergy' and not rec.allergy_case:
                    continue
                if l.condition == 'gown' and not rec.needs_gown:
                    continue
                cmds.append(Command.create({
                    'phase': l.phase, 'product_id': l.product_id.id,
                    'qty_planned': l.qty, 'qty_done': l.qty,
                }))
            rec.line_ids = cmds

    @api.onchange('service_product_id')
    def _onchange_service_product_id(self):
        if self.service_product_id:
            tmpl = self.env['rc.consumption.template'].search([
                ('service_tmpl_ids', 'in', self.service_product_id.product_tmpl_id.id),
                ('company_id', 'in', [False, self.company_id.id]),
            ], limit=1)
            self.template_id = tmpl
            self._rc_fill_lines()

    @api.onchange('template_id')
    def _onchange_template_id(self):
        self._rc_fill_lines()

    picking_ids = fields.Many2many('stock.picking', compute='_compute_picking_ids', string='Stock Transfers')
    picking_count = fields.Integer(compute='_compute_picking_ids')
    consumable_count = fields.Integer(compute='_compute_smart_button_counts')
    sales_order_count = fields.Integer(compute='_compute_smart_button_counts')
    room_stock_count = fields.Integer(compute='_compute_smart_button_counts')

    @api.depends('line_ids', 'sale_order_id', 'room_id')
    def _compute_smart_button_counts(self):
        RoomPar = self.env['rc.room.par']
        for rec in self:
            rec.consumable_count = len(rec.line_ids)
            rec.sales_order_count = 1 if rec.sale_order_id else 0
            rec.room_stock_count = RoomPar.search_count([('room_id', '=', rec.room_id.id)]) if rec.room_id else 0

    def action_view_consumables(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Consumables'),
            'res_model': 'rc.exam.consumption.line',
            'view_mode': 'list,form',
            'views': [(self.env.ref('radiology_consumables.rc_consumption_line_dashboard_list').id, 'list')],
            'domain': [('consumption_id', '=', self.id)],
            'target': 'current',
        }

    def action_view_sales_order(self):
        self.ensure_one()
        if not self.sale_order_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sales Order'),
            'res_model': 'sale.order',
            'res_id': self.sale_order_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_room_stock(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Room Stock'),
            'res_model': 'rc.room.par',
            'view_mode': 'list,form',
            'domain': [('room_id', '=', self.room_id.id)],
            'target': 'current',
        }

    @api.depends('line_ids.move_id.picking_id')
    def _compute_picking_ids(self):
        for rec in self:
            pickings = rec.line_ids.move_id.picking_id
            rec.picking_ids = pickings
            rec.picking_count = len(pickings)

    def action_view_pickings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Stock Transfers'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.picking_ids.ids)],
            'target': 'current',
        }

    def action_reload_lines(self):
        self.filtered(lambda r: r.state == 'draft')._rc_fill_lines()

    def _rc_confirm_phase(self, phase, from_state, to_state):
        """Pass one stage: move the consumables of that phase from the room
        to the Consumption location (or Loss for wasted items)."""
        if not self.ids:
            return
        self.env.cr.execute(
            'SELECT id FROM rc_exam_consumption WHERE id IN %s FOR UPDATE', (tuple(self.ids),))
        label = dict(PHASES)[phase]
        for rec in self:
            if rec.state != from_state:
                raise UserError(_('%(name)s is not ready for this stage.', name=rec.name))
            if not rec.room_id:
                raise UserError(_('Choose the room before confirming.'))

            # Block the next phase until all earlier phase transfers are validated.
            phase_index = PHASE_ORDER.index(phase)
            earlier_phases = PHASE_ORDER[:phase_index]
            earlier_lines = rec.line_ids.filtered(
                lambda line: line.phase in earlier_phases and line.move_id
            )
            pending_pickings = earlier_lines.mapped('picking_id').filtered(
                lambda picking: picking.state != 'done'
            )
            if pending_pickings:
                raise UserError(_(
                    'You cannot confirm %(phase)s until the previous phase stock transfer(s) are validated: %(pickings)s',
                    phase=label,
                    pickings=', '.join(pending_pickings.mapped('display_name')),
                ))

            rec.company_id._rc_ensure_locations()
            comp = rec.company_id.sudo()
            lines = rec.line_ids.filtered(lambda l: l.phase == phase and l.qty_done > 0)
            # One standard Odoo Internal Transfer per exam phase. All items,
            # including loss-type items, go to the configured Consum location.
            dest = comp.rc_consumption_location_id
            if not dest:
                raise UserError(_('Please configure the Consumption Location in Radiology Consumables settings.'))
            entries = [(line.product_id, line.qty_done, line.lot_id) for line in lines]
            picking, moves = rec._rc_picking(
                entries, rec.room_id, dest, origin='%s - %s' % (rec.name, label))
            for line, move in zip(lines, moves):
                if move:
                    line.sudo().move_id = move

            # Optional company-level automatic validation.
            if picking and rec.company_id.rc_auto_validate_exam_transfers:
                result = picking.with_context(
                    skip_immediate=True,
                    skip_backorder=True,
                    picking_ids_not_to_backorder=picking.ids,
                ).button_validate()
                if isinstance(result, dict) or picking.state != 'done':
                    raise UserError(_(
                        'Transfer %s could not be validated automatically. Please open it in Inventory and validate it manually.',
                        picking.display_name,
                    ))
            rec.sudo().state = to_state

    def action_confirm_prep(self):
        self._rc_confirm_phase('prep', 'draft', 'prep')

    def action_confirm_scan(self):
        self._rc_confirm_phase('scan', 'prep', 'scan')

    def action_confirm_post(self):
        self._rc_confirm_phase('post', 'scan', 'done')

    def action_confirm(self):
        """Confirm the next pending stage (kept for API / RIS callers)."""
        for rec in self:
            {'draft': rec.action_confirm_prep,
             'prep': rec.action_confirm_scan,
             'scan': rec.action_confirm_post}.get(rec.state, lambda: None)()

    def action_cancel(self):
        self.filtered(lambda r: r.state == 'draft').sudo().write({'state': 'cancel'})


    @api.model
    def get_dashboard_data(self, room_id=False, date_from=False, date_to=False):
        """Dashboard data restricted to rooms the current user may access."""
        user = self.env.user
        is_manager = user.has_group('radiology_consumables.group_rc_manager')
        is_storekeeper = user.has_group('radiology_consumables.group_rc_storekeeper')
        room_domain = [
            ('usage', '=', 'internal'),
            '|', ('is_room', '=', True), ('is_lab', '=', True),
        ]
        if not (is_manager or is_storekeeper):
            room_domain.append(('rc_responsible_ids', 'in', user.id))
        rooms = self.env['stock.location'].search(room_domain, order='complete_name')
        allowed_room_ids = rooms.ids
        if room_id:
            room_id = int(room_id)
            if room_id not in allowed_room_ids:
                raise UserError(_('You are not allowed to view this room.'))
            selected_room_ids = [room_id]
        else:
            selected_room_ids = allowed_room_ids

        domain = [('room_id', 'in', selected_room_ids), ('state', '!=', 'cancel')]
        if date_from:
            domain.append(('date', '>=', date_from + ' 00:00:00'))
        if date_to:
            domain.append(('date', '<=', date_to + ' 23:59:59'))

        Consumption = self.env['rc.exam.consumption']
        total = Consumption.search_count(domain)
        done = Consumption.search_count(domain + [('state', '=', 'done')])
        progress = Consumption.search_count(domain + [('state', 'in', ('prep', 'scan'))])
        draft = Consumption.search_count(domain + [('state', '=', 'draft')])

        Issue = self.env['rc.issue']
        issue_domain = [('room_id', 'in', selected_room_ids)]
        pending_domain = issue_domain + [('state', '=', 'in_transit')]
        received_domain = issue_domain + [('state', '=', 'received')]
        requests_domain = issue_domain + [('state', '=', 'draft')]
        if date_from:
            received_domain.append(('receive_date', '>=', date_from + ' 00:00:00'))
            requests_domain.append(('create_date', '>=', date_from + ' 00:00:00'))
        if date_to:
            received_domain.append(('receive_date', '<=', date_to + ' 23:59:59'))
            requests_domain.append(('create_date', '<=', date_to + ' 23:59:59'))
        pending_issues = Issue.search_count(pending_domain)
        received_count = Issue.search_count(received_domain)
        requests_count = Issue.search_count(requests_domain)
        diff_domain = received_domain + [('has_difference', '=', True)]
        diff_count = Issue.search_count(diff_domain)
        recent_issues_recs = Issue.search(
            issue_domain + [('state', '!=', 'cancel')], order='id desc', limit=8)
        issue_states = dict(Issue._fields['state'].selection)

        records = Consumption.search(domain, order='date desc, id desc', limit=8)
        used_qty = 0.0
        all_records = Consumption.search(domain)
        # Count only stock transfers that have actually been validated in Inventory.
        # A created/reserved picking is not yet considered consumed.
        lines = self.env['rc.exam.consumption.line'].search([
            ('consumption_id', 'in', all_records.ids),
            ('picking_id.state', '=', 'done'),
        ])
        used_qty = sum(lines.mapped('qty_transferred'))
        used_domain = [('id', 'in', lines.ids)]

        pars = self.env['rc.room.par'].search([('room_id', 'in', selected_room_ids)])
        low_stock = len(pars.filtered(lambda p: p.qty_to_request > 0))
        recent = [{
            'id': rec.id,
            'name': rec.name,
            'date': fields.Datetime.to_string(rec.date) if rec.date else '',
            'room': rec.room_id.display_name,
            'patient': rec.patient_id.name or '',
            'nurse': rec.nurse_id.name or '',
            'state': dict(rec._fields['state'].selection).get(rec.state, rec.state),
        } for rec in records]
        return {
            'rooms': [{'id': r.id, 'name': r.complete_name} for r in rooms],
            'selected_room_id': room_id or False,
            'kpis': {
                'total': total, 'done': done, 'progress': progress,
                'draft': draft, 'pending_issues': pending_issues,
                'received': received_count, 'requests': requests_count,
                'differences': diff_count,
                'low_stock': low_stock, 'used_qty': round(used_qty, 2),
            },
            'recent': recent,
            'recent_issues': [{
                'id': i.id,
                'name': i.name,
                'room': i.room_id.display_name,
                'state_key': i.state,
                'state': issue_states.get(i.state, i.state),
                'date': fields.Datetime.to_string(i.issue_date or i.create_date) or '',
            } for i in recent_issues_recs],
            'domains': {
                'total': domain,
                'done': domain + [('state', '=', 'done')],
                'progress': domain + [('state', 'in', ('prep', 'scan'))],
                'draft': domain + [('state', '=', 'draft')],
                'pending_receipts': pending_domain,
                'received': received_domain,
                'requests': requests_domain,
                'differences': diff_domain,
                'used': used_domain,
            },
        }


class RcExamConsumptionLine(models.Model):
    _name = 'rc.exam.consumption.line'
    _description = 'Exam Consumption Line'
    _order = 'phase, id'

    consumption_id = fields.Many2one('rc.exam.consumption', required=True, ondelete='cascade')
    phase = fields.Selection(PHASES, required=True, default='prep')
    line_type = fields.Selection([
        ('normal', 'Normal'),
        ('patient_extra', 'Extra (patient)'),
        ('extravasation', 'Extravasation'),
        ('human_error', 'Human Error'),
        ('defective', 'Defective / Faulty'),
    ], default='normal', required=True)
    product_id = fields.Many2one('product.product', required=True, domain="[('type', '=', 'consu')]")
    uom_id = fields.Many2one(related='product_id.uom_id')
    tracking = fields.Selection(related='product_id.tracking')
    lot_id = fields.Many2one('stock.lot', domain="[('product_id', '=', product_id)]")
    qty_planned = fields.Float(string='Planned')
    qty_done = fields.Float(string='Used', default=1.0)
    move_id = fields.Many2one('stock.move', readonly=True, copy=False)
    picking_id = fields.Many2one(
        'stock.picking', related='move_id.picking_id', store=True, readonly=True,
        string='Internal Transfer')
    qty_transferred = fields.Float(
        string='Transferred Quantity', compute='_compute_qty_transferred',
        digits='Product Unit of Measure')
    notes = fields.Char()
    charged_to = fields.Char(compute='_compute_charged_to')
    locked = fields.Boolean(
        compute='_compute_locked',
        help='The stage of this line is already confirmed, so it cannot be changed.')

    @api.depends('move_id', 'move_id.state', 'picking_id.state')
    def _compute_qty_transferred(self):
        for rec in self:
            qty = 0.0
            move = rec.move_id
            if move and move.state == 'done' and rec.picking_id.state == 'done':
                # In current Odoo versions stock.move.quantity is the done
                # quantity. Keep a fallback for versions exposing qty_done
                # only on stock.move.line.
                if 'quantity' in move._fields:
                    qty = move.quantity
                else:
                    for move_line in move.move_line_ids:
                        if 'quantity' in move_line._fields:
                            qty += move_line.quantity
                        elif 'qty_done' in move_line._fields:
                            qty += move_line.qty_done
            rec.qty_transferred = qty

    @api.depends('phase', 'consumption_id.state')
    def _compute_locked(self):
        for rec in self:
            done = PHASES_DONE.get(rec.consumption_id.state, 0)
            rec.locked = rec.phase in PHASE_ORDER and PHASE_ORDER.index(rec.phase) < done

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and any(vals.get('move_id') for vals in vals_list):
            raise AccessError(_('The stock move of a line is set by the workflow.'))
        lines = super().create(vals_list)
        if any(lines.mapped('locked')):
            raise UserError(_('This stage is already confirmed. Add the item to a stage that is still open.'))
        return lines

    def write(self, vals):
        if not self.env.su and 'move_id' in vals:
            raise AccessError(_('The stock move of a line is set by the workflow.'))
        if set(vals) - {'move_id'} and any(self.mapped('locked')):
            raise UserError(_('This stage is already confirmed and cannot be changed.'))
        res = super().write(vals)
        if 'phase' in vals and any(self.mapped('locked')):
            raise UserError(_('This stage is already confirmed. Choose a stage that is still open.'))
        return res

    def unlink(self):
        if any(self.mapped('locked')):
            raise UserError(_('This stage is already confirmed and its items cannot be deleted.'))
        return super().unlink()

    @api.depends('line_type', 'consumption_id.patient_id', 'consumption_id.nurse_id')
    def _compute_charged_to(self):
        for rec in self:
            if rec.line_type == 'human_error':
                rec.charged_to = rec.consumption_id.nurse_id.name or ''
            elif rec.line_type == 'patient_extra':
                rec.charged_to = rec.consumption_id.patient_id.name or ''
            else:
                rec.charged_to = ''
