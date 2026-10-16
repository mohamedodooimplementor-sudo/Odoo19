# -*- coding: utf-8 -*-
from odoo import api, fields, models

from .utils import convert_uom, pick_field


class EmployeeRequestLineExec(models.Model):
    _inherit = 'employee.request.line'

    employee_id = fields.Many2one(related='request_id.employee_id', store=True)
    department_id = fields.Many2one(related='request_id.department_id', store=True)
    request_state = fields.Selection(related='request_id.state', store=True,
                                     string='Request Status')
    move_ids = fields.One2many('stock.move', 'er_request_line_id', string='Stock Moves')
    po_line_ids = fields.One2many('employee.purchase.order.line', 'request_line_id',
                                  string='Purchase Order Lines')
    qty_stock_planned = fields.Float(string='Stock Planned', digits='Product Unit',
                                     compute='_compute_progress', store=True)
    qty_purchase_planned = fields.Float(string='Purchased', digits='Product Unit',
                                        compute='_compute_progress', store=True)
    qty_issued = fields.Float(string='Issued', digits='Product Unit',
                              compute='_compute_progress', store=True)
    qty_received = fields.Float(string='Received', digits='Product Unit',
                                compute='_compute_progress', store=True)
    qty_remaining = fields.Float(string='Remaining', digits='Product Unit',
                                 compute='_compute_progress', store=True)
    qty_unprocessed = fields.Float(string='Not Yet Processed', digits='Product Unit',
                                   compute='_compute_progress', store=True)

    @api.depends('product_uom_qty', 'product_uom_id',
                 'move_ids.state', 'move_ids.quantity', 'move_ids.product_uom_qty',
                 'po_line_ids.planned_qty', 'po_line_ids.received_qty')
    def _compute_progress(self):
        for line in self:
            stock_planned = issued = 0.0
            for move in line.move_ids:
                if move.state == 'cancel':
                    continue
                move_uom = move[pick_field(move, 'product_uom', 'product_uom_id')]
                if move.state == 'done':
                    qty = convert_uom(move.quantity, move_uom, line.product_uom_id)
                    issued += qty
                    stock_planned += qty
                else:
                    stock_planned += convert_uom(move.product_uom_qty, move_uom,
                                                 line.product_uom_id)
            purchase_planned = sum(line.po_line_ids.mapped('planned_qty'))
            received = sum(line.po_line_ids.mapped('received_qty'))
            line.qty_stock_planned = stock_planned
            line.qty_purchase_planned = purchase_planned
            line.qty_issued = issued
            line.qty_received = received
            line.qty_remaining = max(line.product_uom_qty - issued - received, 0.0)
            line.qty_unprocessed = max(
                line.product_uom_qty - stock_planned - purchase_planned, 0.0)

    def _er_locked_for_others(self):
        """Quantity (line UoM) of the line's product held for projects other than its own."""
        self.ensure_one()
        company = self.company_id.sudo()
        if not (company.er_project_lock_enabled and self.product_id and self.location_id):
            return 0.0
        held = self.env['stock.move']._er_project_locked_qty(
            self.product_id, self.location_id, exclude_project=self.project_id)
        return self._to_line_uom(sum(held.values()))

    @api.model
    def get_forecast_data(self, product_id, location_id, qty=0.0):
        """Data for the forecast popup (OWL widget)."""
        product = self.env['product.product'].sudo().browse(product_id).exists()
        location = self.env['stock.location'].sudo().browse(location_id).exists()
        if not product or not location:
            return {}
        prod = product.with_context(location=location.id)
        onhand, free = prod.qty_available, prod.free_qty
        quants = self.env['stock.quant'].sudo()._read_group(
            [('product_id', '=', product.id),
             ('location_id', 'child_of', location.id),
             ('location_id.usage', '=', 'internal')],
            ['location_id'], ['quantity:sum', 'reserved_quantity:sum'])
        locations = [{'name': loc.display_name, 'quantity': qty_sum,
                      'reserved': res_sum} for loc, qty_sum, res_sum in quants]

        Move = self.env['stock.move'].sudo()
        open_states = ('waiting', 'confirmed', 'assigned', 'partially_available')
        base = [('product_id', '=', product.id), ('state', 'in', open_states)]
        wh_locations = self.env['stock.location'].sudo().search(
            [('id', 'child_of', location.id)]).ids
        incoming = Move.search(base + [
            ('location_dest_id', 'in', wh_locations),
            ('location_id', 'not in', wh_locations)], limit=20)
        outgoing = Move.search(base + [
            ('location_id', 'in', wh_locations),
            ('location_dest_id', 'not in', wh_locations)], limit=20)

        def fmt(moves):
            return [{'reference': m.picking_id.name or m.reference or m.name,
                     'quantity': m.product_uom_qty,
                     'date': fields.Date.to_string(m.date) if m.date else ''}
                    for m in moves]

        # every location that has the product, and which project holds how much of it.
        # The locations of the projects are listed first; each project location is shown once.
        all_locations, projects = [], []
        Project = self.env['project.project'].sudo()
        Location = self.env['stock.location'].sudo()
        company_ids = self.env.companies.ids
        loc_ids = {loc.id for loc, _q in self.env['stock.quant'].sudo()._read_group(
            [('product_id', '=', product.id), ('location_id.usage', '=', 'internal'),
             ('location_id.company_id', 'in', company_ids), ('quantity', '>', 0)],
            ['location_id'], ['quantity:sum'])}
        project_locs = Project.search([('er_location_id', '!=', False)]).er_location_id
        loc_ids |= set(project_locs.ids)
        for loc in Location.browse(sorted(loc_ids)):
            loc_prod = product.with_context(location=loc.id)
            held = self.env['stock.move']._er_project_locked_qty(product, loc)
            if loc_prod.qty_available or held:
                all_locations.append({
                    'name': loc.display_name, 'on_hand': loc_prod.qty_available,
                    'available': loc_prod.free_qty, 'held': sum(held.values())})
            for project_id, held_qty in held.items():
                projects.append({'project': Project.browse(project_id).display_name,
                                 'location': loc.display_name, 'quantity': held_qty})
        projects.sort(key=lambda r: (r['project'], r['location']))

        status = 'unavailable'
        if free >= qty > 0:
            status = 'available'
        elif free > 0:
            status = 'partial'
        return {
            'product': product.display_name,
            'location': location.display_name,
            'uom': product.uom_id.name,
            'requested': qty,
            'on_hand': onhand, 'reserved': onhand - free, 'available': free,
            'incoming': prod.incoming_qty, 'outgoing': prod.outgoing_qty,
            'forecast': prod.virtual_available,
            'status': status,
            'locations': locations,
            'all_locations': all_locations,
            'projects': projects,
            'incoming_moves': fmt(incoming),
            'outgoing_moves': fmt(outgoing),
        }

    # ------------------------------------------------------------------
    # Standard Odoo product catalog support
    # ------------------------------------------------------------------
    def action_add_from_catalog(self):
        """Called by the "Catalog" button of the lines list (same as sale/purchase lines)."""
        request = self.env['employee.request'].browse(self.env.context.get('order_id'))
        return request.with_context(child_field='line_ids').action_add_from_catalog()

    def _get_product_catalog_lines_data(self, **kwargs):
        """Data shown in the catalog kanban for the product of these lines."""
        if len(self) == 1:
            return {
                'quantity': self.product_uom_qty,
                'price': 0.0,
                'readOnly': self.request_id._is_readonly(),
                'uomDisplayName': self.product_uom_id.display_name or '',
            }
        if self:
            self.product_id.ensure_one()
            return {
                'quantity': sum(self.mapped('product_uom_qty')),
                'price': 0.0,
                'readOnly': True,
                'uomDisplayName': self[0].product_uom_id.display_name or '',
            }
        return {'quantity': 0, 'price': 0.0}
