# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionRfq(models.Model):
    _name = 'construction.rfq'
    _description = 'Request for Quotation (Construction)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='RFQ No.', required=True, copy=False, readonly=True, default='New')
    project_id = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='project_id.company_id', store=True)
    material_request_id = fields.Many2one('construction.material.request', string='Material Request')

    date = fields.Date(string='Date', default=fields.Date.today, required=True)
    date_required = fields.Date(string='Quotes Required By')
    vendor_ids = fields.Many2many('res.partner', string='Vendors Invited')

    line_ids = fields.One2many('construction.rfq.line', 'rfq_id', string='Items')
    quote_ids = fields.One2many('construction.rfq.quote', 'rfq_id', string='Quotes')

    state = fields.Selection([
        ('draft',    'Draft'),
        ('sent',     'Sent'),
        ('quoted',   'Quotes Received'),
        ('awarded',  'Awarded'),
        ('cancelled','Cancelled'),
    ], default='draft', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.rfq') or 'New'
        return super().create(vals_list)

    def action_send(self):
        self.write({'state': 'sent'})

    def action_mark_quoted(self):
        self.write({'state': 'quoted'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_generate_quote_matrix(self):
        """Create one quote row per (vendor x line) combination, ready to be filled in."""
        self.ensure_one()
        existing = {(q.vendor_id.id, q.rfq_line_id.id) for q in self.quote_ids}
        new_quotes = []
        for vendor in self.vendor_ids:
            for line in self.line_ids:
                if (vendor.id, line.id) not in existing:
                    new_quotes.append({
                        'rfq_id': self.id, 'vendor_id': vendor.id, 'rfq_line_id': line.id,
                    })
        if new_quotes:
            self.env['construction.rfq.quote'].create(new_quotes)

    def action_award_and_create_pos(self):
        """Group all quotes marked as awarded (per line) by vendor and create one draft
        Purchase Order per vendor, with lines linked back to the originating BOQ item when set."""
        self.ensure_one()
        awarded = self.quote_ids.filtered(lambda q: q.is_awarded and q.unit_price)
        if not awarded:
            raise UserError(_('Please mark at least one quote as "Awarded" first.'))

        POLine = self.env['purchase.order.line']
        uom_field = 'product_uom_id' if 'product_uom_id' in POLine._fields else 'product_uom'
        created_pos = self.env['purchase.order']

        for vendor in awarded.mapped('vendor_id'):
            vendor_quotes = awarded.filtered(lambda q: q.vendor_id == vendor)
            order_lines = []
            for q in vendor_quotes:
                line = q.rfq_line_id
                analytic_distribution = {}
                if line.boq_line_id and line.boq_line_id.project_id.analytic_account_id and 'analytic_distribution' in POLine._fields:
                    analytic_distribution = {str(line.boq_line_id.project_id.analytic_account_id.id): 100.0}
                vals = {
                    'product_id': line.product_id.id,
                    'name': line.description or line.product_id.display_name,
                    'product_qty': line.qty,
                    uom_field: (line.uom_id.id or line.product_id.uom_id.id),
                    'price_unit': q.unit_price,
                    'construction_boq_line_id': line.boq_line_id.id if line.boq_line_id else False,
                }
                if analytic_distribution:
                    vals['analytic_distribution'] = analytic_distribution
                order_lines.append((0, 0, vals))
            po = self.env['purchase.order'].create({
                'partner_id': vendor.id,
                'origin': _('RFQ: %s') % self.name,
                'order_line': order_lines,
            })
            created_pos |= po

        self.state = 'awarded'
        return {
            'type': 'ir.actions.act_window',
            'name': _('Purchase Orders'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created_pos.ids)],
        }


class ConstructionRfqLine(models.Model):
    _name = 'construction.rfq.line'
    _description = 'RFQ Line'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    rfq_id = fields.Many2one('construction.rfq', ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    boq_line_id = fields.Many2one('construction.boq.line', string='BOQ Item',
                                   domain="[('project_id','=',parent.project_id)]")
    description = fields.Char(string='Description')
    qty = fields.Float(string='Quantity', digits=(12, 3), required=True)
    uom_id = fields.Many2one('uom.uom', string='UoM')

    best_price = fields.Float(string='Best Price', compute='_compute_best_price')
    best_vendor_name = fields.Char(string='Best Vendor', compute='_compute_best_price')

    def _compute_best_price(self):
        for rec in self:
            quotes = rec.env['construction.rfq.quote'].search([
                ('rfq_line_id', '=', rec.id), ('unit_price', '>', 0)])
            if quotes:
                best = min(quotes, key=lambda q: q.unit_price)
                rec.best_price = best.unit_price
                rec.best_vendor_name = best.vendor_id.name
            else:
                rec.best_price = 0.0
                rec.best_vendor_name = ''


class ConstructionRfqQuote(models.Model):
    _name = 'construction.rfq.quote'
    _description = 'RFQ Vendor Quote'
    _order = 'rfq_line_id, unit_price'

    rfq_id = fields.Many2one('construction.rfq', ondelete='cascade', required=True)
    rfq_line_id = fields.Many2one('construction.rfq.line', ondelete='cascade', required=True)
    vendor_id = fields.Many2one('res.partner', string='Vendor', required=True)
    unit_price = fields.Float(string='Unit Price', digits=(12, 2))
    lead_time_days = fields.Integer(string='Lead Time (Days)')
    is_awarded = fields.Boolean(string='Awarded')
    notes = fields.Char(string='Notes')
