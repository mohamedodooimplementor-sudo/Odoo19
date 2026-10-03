# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class InterBranchTransfer(models.Model):
    _name = 'inter.branch.transfer'
    _description = 'Inter-Branch Transfer'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Transfer No.', default='New', copy=False, readonly=True)

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company)

    date = fields.Date(string='Date', default=fields.Date.context_today, tracking=True)
    expected_date = fields.Date(string='Expected Date', tracking=True)

    source_branch_id = fields.Many2one(
        'res.branch', string='Source Branch', required=True, tracking=True,
        domain="[('id', 'in', allowed_branch_ids)]",
        default=lambda self: self.env.user.branch_id)
    destination_branch_id = fields.Many2one(
        'res.branch', string='Destination Branch', required=True, tracking=True)

    allowed_branch_ids = fields.Many2many(
        'res.branch', compute='_compute_allowed_branch_ids', string='Allowed Branches')

    source_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Source Warehouse',
        related='source_branch_id.warehouse_id', store=True, readonly=True)
    destination_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Destination Warehouse',
        related='destination_branch_id.warehouse_id', store=True, readonly=True)

    transit_location_id = fields.Many2one(
        'stock.location', string='Transit Location', required=True,
        domain="[('usage', '=', 'transit')]",
        default=lambda self: self._get_default_transit_location())

    line_ids = fields.One2many(
        'inter.branch.transfer.line', 'transfer_id', string='Products', copy=True)

    picking_id_1 = fields.Many2one(
        'stock.picking', string='Source \u2192 Transit Picking', copy=False, readonly=True)
    picking_id_2 = fields.Many2one(
        'stock.picking', string='Transit \u2192 Destination Picking', copy=False, readonly=True)
    picking_count = fields.Integer(
        string='Picking Count', compute='_compute_picking_count')

    notes = fields.Text(string='Notes')
    cancel_reason = fields.Text(string='Cancellation Reason', copy=False)

    in_transit_date = fields.Datetime(
        string='In Transit Since', copy=False, readonly=True,
        help='When the transfer became In Transit. Used to detect transfers '
             'stuck waiting for Destination confirmation for too long.')
    escalated = fields.Boolean(
        string='Escalated', copy=False, default=False,
        help='Set once a reminder has been sent for a transfer stuck In '
             'Transit for too long, so we do not spam the same reminder '
             'every time the cron runs.')

    state = fields.Selection([
        ('draft', 'Draft'),
        ('waiting_source_approval', 'Waiting Source Approval'),
        ('in_transit', 'In Transit / Waiting Destination Approval'),
        ('done', 'Done'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, copy=False)

    @api.depends_context('uid')
    def _compute_allowed_branch_ids(self):
        allowed = self.env.user.get_allowed_branches()
        for rec in self:
            rec.allowed_branch_ids = allowed

    def _compute_picking_count(self):
        for rec in self:
            rec.picking_count = len(rec.picking_id_1 | rec.picking_id_2)

    def action_view_pickings(self):
        self.ensure_one()
        pickings = self.picking_id_1 | self.picking_id_2
        action = {
            'name': 'Pickings',
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
        }
        if len(pickings) == 1:
            action.update({
                'view_mode': 'form',
                'res_id': pickings.id,
            })
        else:
            action.update({
                'view_mode': 'list,form',
                'domain': [('id', 'in', pickings.ids)],
            })
        return action

    def _get_default_transit_location(self):
        Location = self.env['stock.location']
        # Reuse the module's transit location if it was already created.
        location = Location.search(
            [('name', '=', 'Branch Management Transit'), ('usage', '=', 'transit')], limit=1)
        if location:
            return location
        # Fall back to any transit location already configured on the system.
        location = Location.search(
            [('usage', '=', 'transit'),
             ('company_id', 'in', (self.env.company.id, False))], limit=1)
        if location:
            return location
        # None exists yet: create one on the fly as a top-level location
        # (no parent), exactly like Odoo's own "Physical Locations" root.
        # We deliberately do NOT nest it under a warehouse's view location:
        # those belong to a specific company, and a company-agnostic
        # (company_id=False) transit location cannot sit under a
        # company-owned parent without triggering a company-consistency
        # error.
        return Location.create({
            'name': 'Branch Management Transit',
            'usage': 'transit',
            'location_id': False,
            'company_id': False,
        })

    @api.constrains('source_branch_id', 'destination_branch_id')
    def _check_branches_different(self):
        for rec in self:
            if rec.source_branch_id and rec.source_branch_id == rec.destination_branch_id:
                raise UserError("Source Branch and Destination Branch must be different.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'inter.branch.transfer') or 'New'
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # Workflow actions
    # ------------------------------------------------------------------
    def action_confirm(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError("Add at least one product line before confirming.")
            if not rec.source_warehouse_id or not rec.destination_warehouse_id:
                raise UserError("Both branches must have a Warehouse configured.")
            rec.state = 'waiting_source_approval'

    def _check_source_availability(self):
        """Soft pre-flight check: warn clearly, before creating any picking,
        which lines don't have enough free stock at the Source Warehouse,
        instead of only discovering shortages later inside Inventory."""
        self.ensure_one()
        shortages = []
        for line in self.line_ids:
            free_qty = line.product_id.with_context(
                location=self.source_warehouse_id.lot_stock_id.id,
            ).free_qty
            if free_qty < line.product_uom_qty:
                shortages.append(
                    "- %s: requested %.2f, only %.2f available at %s" % (
                        line.product_id.display_name, line.product_uom_qty,
                        free_qty, self.source_warehouse_id.name))
        if shortages:
            raise UserError(_(
                "Not enough available stock at %(warehouse)s for:\n%(lines)s",
                warehouse=self.source_warehouse_id.name,
                lines='\n'.join(shortages),
            ))

    def action_approve_source(self):
        """Create both stock pickings (Source -> Transit and Transit ->
        Destination) as Draft. Nothing is confirmed/reserved/validated here
        on purpose: the warehouse team processes each picking normally from
        the Inventory app, at the time the stock is actually ready to move.
        """
        for rec in self:
            if rec.state != 'waiting_source_approval':
                raise UserError("Only transfers waiting for Source Approval can be approved.")

            rec._check_source_availability()

            source_picking_type = rec.source_warehouse_id.int_type_id or self.env['stock.picking.type'].search(
                [('code', '=', 'internal'),
                 ('warehouse_id', '=', rec.source_warehouse_id.id)], limit=1)
            # sudo(): this picking is created automatically as a system
            # consequence of the approval, and its branch_id (source or
            # destination) may not both be within the approving user's own
            # allowed branches. Creating as sudo avoids the "Restricted to
            # Allowed Branches" create-rule blocking this internal action.
            picking_1 = self.env['stock.picking'].sudo().create({
                'picking_type_id': source_picking_type.id,
                'location_id': rec.source_warehouse_id.lot_stock_id.id,
                'location_dest_id': rec.transit_location_id.id,
                'origin': rec.name,
                'company_id': rec.company_id.id,
                'branch_id': rec.source_branch_id.id,
                'transfer_source_branch_id': rec.source_branch_id.id,
                'move_ids': [(0, 0, {
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.product_uom_qty,
                    'product_uom': line.product_uom_id.id,
                    'location_id': rec.source_warehouse_id.lot_stock_id.id,
                    'location_dest_id': rec.transit_location_id.id,
                    'company_id': rec.company_id.id,
                }) for line in rec.line_ids],
            })

            destination_picking_type = rec.destination_warehouse_id.int_type_id or self.env['stock.picking.type'].search(
                [('code', '=', 'internal'),
                 ('warehouse_id', '=', rec.destination_warehouse_id.id)], limit=1)
            picking_2 = self.env['stock.picking'].sudo().create({
                'picking_type_id': destination_picking_type.id,
                'location_id': rec.transit_location_id.id,
                'location_dest_id': rec.destination_warehouse_id.lot_stock_id.id,
                'origin': rec.name,
                'company_id': rec.company_id.id,
                'branch_id': rec.destination_branch_id.id,
                'transfer_source_branch_id': rec.source_branch_id.id,
                'move_ids': [(0, 0, {
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.product_uom_qty,
                    'product_uom': line.product_uom_id.id,
                    'location_id': rec.transit_location_id.id,
                    'location_dest_id': rec.destination_warehouse_id.lot_stock_id.id,
                    'company_id': rec.company_id.id,
                }) for line in rec.line_ids],
            })

            rec.picking_id_1 = picking_1
            rec.picking_id_2 = picking_2
            rec.state = 'in_transit'
            rec.in_transit_date = fields.Datetime.now()
            rec.escalated = False
            rec._notify_destination_branch()

    def _notify_destination_branch(self):
        """Let the destination branch's users know a transfer is on its way
        and needs them to validate the Transit -> Destination picking."""
        for rec in self:
            users = rec.destination_branch_id.user_ids
            if rec.destination_branch_id.manager_id:
                users |= rec.destination_branch_id.manager_id
            if not users:
                continue
            partners = users.mapped('partner_id')
            rec.message_subscribe(partner_ids=partners.ids)
            rec.message_post(
                body=_(
                    "Transfer %(name)s is now In Transit from %(source)s to "
                    "%(destination)s. Please validate the Transit \u2192 "
                    "Destination picking to receive the goods.",
                    name=rec.name, source=rec.source_branch_id.name,
                    destination=rec.destination_branch_id.name,
                ),
                partner_ids=partners.ids,
            )
            # A ToDo activity on the branch manager so it also shows up on
            # their Activities view/dashboard, not just as a chat notification.
            if rec.destination_branch_id.manager_id:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Confirm receipt of Inter-Branch Transfer %s') % rec.name,
                    note=_(
                        'Please validate the Transit \u2192 Destination picking '
                        'once the goods have arrived.'),
                    user_id=rec.destination_branch_id.manager_id.id,
                )

    def action_receive_now(self):
        """Shortcut so the destination team doesn't have to go hunt for the
        picking in Inventory: jump straight to its form to validate it."""
        self.ensure_one()
        if not self.picking_id_2:
            raise UserError("No Transit \u2192 Destination picking to receive yet.")
        return {
            'name': self.picking_id_2.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': self.picking_id_2.id,
        }

    def action_approve_destination(self):
        """Close the transfer once the warehouse team has validated the
        Transit -> Destination picking themselves in Inventory."""
        for rec in self:
            if rec.state != 'in_transit':
                raise UserError("Only transfers currently In Transit can be received at destination.")
            if not rec.picking_id_2 or rec.picking_id_2.state != 'done':
                raise UserError(
                    "The Transit \u2192 Destination picking must be validated "
                    "(from Inventory) before the transfer can be closed.")
            rec.state = 'done'

    def action_cancel(self):
        self.ensure_one()
        return {
            'name': "Cancel Transfer",
            'type': 'ir.actions.act_window',
            'res_model': 'inter.branch.transfer.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_transfer_id': self.id},
        }

    def _do_cancel(self, reason):
        for picking in (self.picking_id_1, self.picking_id_2):
            if picking and picking.state not in ('done', 'cancel'):
                picking.action_cancel()
        self.cancel_reason = reason
        self.state = 'cancel'
        self.message_post(body=_("Transfer cancelled. Reason: %s") % reason)

    def action_draft(self):
        for rec in self:
            rec.state = 'draft'

    @api.model
    def _cron_escalate_stale_transfers(self):
        """Send a reminder for transfers stuck In Transit for longer than
        the configured threshold (default 3 days). Called by a scheduled
        action; safe to run as often as needed since 'escalated' prevents
        sending the same reminder twice."""
        threshold_days = int(self.env['ir.config_parameter'].sudo().get_param(
            'branch_management.transfer_escalation_days', default=3))
        deadline = fields.Datetime.now() - timedelta(days=threshold_days)
        stale = self.search([
            ('state', '=', 'in_transit'),
            ('escalated', '=', False),
            ('in_transit_date', '<=', deadline),
        ])
        for rec in stale:
            users = rec.destination_branch_id.user_ids
            if rec.destination_branch_id.manager_id:
                users |= rec.destination_branch_id.manager_id
            if rec.source_branch_id.manager_id:
                users |= rec.source_branch_id.manager_id
            partners = users.mapped('partner_id')
            if partners:
                rec.message_post(
                    body=_(
                        "\u23f0 Reminder: Transfer %(name)s has been In "
                        "Transit for more than %(days)s day(s) and is still "
                        "waiting to be received at %(destination)s.",
                        name=rec.name, days=threshold_days,
                        destination=rec.destination_branch_id.name,
                    ),
                    partner_ids=partners.ids,
                )
            if rec.destination_branch_id.manager_id:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Overdue: confirm receipt of %s') % rec.name,
                    note=_(
                        'This transfer has been In Transit for more than '
                        '%s day(s). Please validate the Transit \u2192 '
                        'Destination picking.') % threshold_days,
                    user_id=rec.destination_branch_id.manager_id.id,
                )
            rec.escalated = True


class InterBranchTransferLine(models.Model):
    _name = 'inter.branch.transfer.line'
    _description = 'Inter-Branch Transfer Line'

    transfer_id = fields.Many2one(
        'inter.branch.transfer', string='Transfer', required=True, ondelete='cascade')
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain="[('is_storable', '=', True)]")
    product_uom_qty = fields.Float(string='Quantity', required=True, default=1.0)
    product_uom_id = fields.Many2one('uom.uom', string='UoM')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.product_uom_id = self.product_id.uom_id

    @api.constrains('product_uom_qty')
    def _check_qty_positive(self):
        for line in self:
            if line.product_uom_qty <= 0:
                raise UserError("Quantity must be strictly positive.")
