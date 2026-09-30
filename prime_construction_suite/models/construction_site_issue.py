# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionSiteIssue(models.Model):
    _name = 'construction.site.issue'
    _description = 'Site Material Issue'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(string='Issue No.', required=True, copy=False, readonly=True, default='New')
    project_id  = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    company_id  = fields.Many2one(related='project_id.company_id', store=True)
    boq_line_id = fields.Many2one('construction.boq.line', string='For BOQ Item',
                                   domain="[('project_id','=',project_id)]")

    date        = fields.Date(string='Date', default=fields.Date.today, required=True)
    issued_by   = fields.Many2one('res.users', string='Issued By', default=lambda s: s.env.user)
    issued_to   = fields.Char(string='Issued To (Foreman/Crew)')
    location    = fields.Char(string='Work Area / Location')

    line_ids = fields.One2many('construction.site.issue.line', 'issue_id', string='Items')
    line_count = fields.Integer(compute='_compute_line_count')
    notes = fields.Text(string='Notes')

    picking_id = fields.Many2one('stock.picking', string='Stock Transfer', readonly=True, copy=False)
    state = fields.Selection([
        ('draft',  'Draft'),
        ('issued', 'Issued'),
    ], default='draft', required=True, tracking=True)

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.site.issue') or 'New'
        return super().create(vals_list)

    def action_issue(self):
        for rec in self:
            if rec.state != 'draft':
                continue
            if not rec.line_ids:
                raise UserError(_('Please add at least one item before issuing.'))
            site_location = rec.project_id._get_or_create_site_location()
            warehouse = rec.env['stock.warehouse'].search([('company_id', '=', rec.company_id.id)], limit=1)
            source_location = warehouse.lot_stock_id if warehouse else rec.env.ref('stock.stock_location_stock')
            picking_type = warehouse.int_type_id if warehouse else rec.env.ref('stock.picking_type_internal', raise_if_not_found=False)

            picking = rec.env['stock.picking'].create({
                'picking_type_id': picking_type.id if picking_type else False,
                'location_id': source_location.id,
                'location_dest_id': site_location.id,
                'origin': rec.name,
                'move_ids': [(0, 0, {
                    'name': line.product_id.display_name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.qty_issued,
                    'product_uom': line.uom_id.id or line.product_id.uom_id.id,
                    'location_id': source_location.id,
                    'location_dest_id': site_location.id,
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
            rec.write({'state': 'issued', 'picking_id': picking.id})

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


class ConstructionSiteIssueLine(models.Model):
    _name = 'construction.site.issue.line'
    _description = 'Site Issue Line'
    _order = 'sequence, id'

    sequence  = fields.Integer(default=10)
    issue_id  = fields.Many2one('construction.site.issue', ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    qty_issued = fields.Float(string='Qty Issued', digits=(12, 3), required=True)
    uom_id = fields.Many2one('uom.uom', string='UoM')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id
