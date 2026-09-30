# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionMaterialReturn(models.Model):
    _name = 'construction.material.return'
    _description = 'Material Return'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='Return No.', required=True, copy=False, readonly=True, default='New')
    project_id = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='project_id.company_id', store=True)
    site_issue_id = fields.Many2one('construction.site.issue', string='Original Site Issue',
                                     domain="[('project_id','=',project_id)]")

    date = fields.Date(string='Date', default=fields.Date.today, required=True)
    return_type = fields.Selection([
        ('to_store',  'Return to Store'),
        ('to_vendor', 'Return to Vendor'),
    ], default='to_store', required=True)
    partner_id = fields.Many2one('res.partner', string='Vendor', help='Required when returning to a vendor.')
    reason = fields.Char(string='Reason')

    line_ids = fields.One2many('construction.material.return.line', 'return_id', string='Items')
    line_count = fields.Integer(compute='_compute_line_count')

    picking_id = fields.Many2one('stock.picking', string='Stock Transfer', readonly=True, copy=False)
    state = fields.Selection([
        ('draft',    'Draft'),
        ('returned', 'Returned'),
    ], default='draft', required=True, tracking=True)

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.material.return') or 'New'
        return super().create(vals_list)

    def action_return(self):
        for rec in self:
            if rec.state != 'draft':
                continue
            if not rec.line_ids:
                raise UserError(_('Please add at least one item before processing the return.'))
            if rec.return_type == 'to_vendor' and not rec.partner_id:
                raise UserError(_('Please select a vendor for a return-to-vendor.'))

            site_location = rec.project_id._get_or_create_site_location()
            warehouse = rec.env['stock.warehouse'].search([('company_id', '=', rec.company_id.id)], limit=1)
            store_location = warehouse.lot_stock_id if warehouse else rec.env.ref('stock.stock_location_stock')

            if rec.return_type == 'to_store':
                dest_location = store_location
                picking_type = warehouse.int_type_id if warehouse else None
            else:
                dest_location = rec.env.ref('stock.stock_location_suppliers', raise_if_not_found=False)
                picking_type = warehouse.out_type_id if warehouse else None

            picking = rec.env['stock.picking'].create({
                'picking_type_id': picking_type.id if picking_type else False,
                'location_id': site_location.id,
                'location_dest_id': dest_location.id if dest_location else False,
                'partner_id': rec.partner_id.id if rec.return_type == 'to_vendor' else False,
                'origin': rec.name,
                'move_ids': [(0, 0, {
                    'name': line.product_id.display_name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.qty_returned,
                    'product_uom': line.uom_id.id or line.product_id.uom_id.id,
                    'location_id': site_location.id,
                    'location_dest_id': dest_location.id if dest_location else False,
                }) for line in rec.line_ids],
            })
            picking.action_confirm()
            picking.action_assign()
            for move in picking.move_ids:
                if hasattr(move, 'quantity'):
                    move.quantity = move.product_uom_qty
                elif hasattr(move, 'quantity_done'):
                    move.quantity_done = move.product_uom_qty
            picking.button_validate()
            rec.write({'state': 'returned', 'picking_id': picking.id})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_view_picking(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
        }


class ConstructionMaterialReturnLine(models.Model):
    _name = 'construction.material.return.line'
    _description = 'Material Return Line'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    return_id = fields.Many2one('construction.material.return', ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    qty_returned = fields.Float(string='Qty Returned', digits=(12, 3), required=True)
    uom_id = fields.Many2one('uom.uom', string='UoM')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id
