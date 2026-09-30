# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionMaterialRequest(models.Model):
    _name = 'construction.material.request'
    _description = 'Material Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_required desc, id desc'

    name = fields.Char(string='Request No.', required=True, copy=False, readonly=True, default='New')
    project_id  = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    contract_id = fields.Many2one('construction.contract', string='Contract', domain="[('project_id','=',project_id)]")
    company_id  = fields.Many2one(related='project_id.company_id', store=True)

    requested_by  = fields.Many2one('res.users', string='Requested By', default=lambda s: s.env.user)
    date          = fields.Date(string='Request Date', default=fields.Date.today, required=True)
    date_required = fields.Date(string='Required By')
    priority = fields.Selection([
        ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('urgent', 'Urgent'),
    ], default='medium', required=True)

    line_ids = fields.One2many('construction.material.request.line', 'request_id', string='Items')
    line_count = fields.Integer(compute='_compute_line_count')
    notes = fields.Text(string='Notes')

    rfq_ids = fields.One2many('construction.rfq', 'material_request_id', string='RFQs')
    rfq_count = fields.Integer(compute='_compute_line_count')

    state = fields.Selection([
        ('draft',     'Draft'),
        ('submitted', 'Submitted'),
        ('approved',  'Approved'),
        ('rejected',  'Rejected'),
        ('fulfilled', 'Fulfilled'),
    ], default='draft', required=True, tracking=True)

    @api.depends('line_ids', 'rfq_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
            rec.rfq_count = len(rec.rfq_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.material.request') or 'New'
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Please add at least one item before submitting.'))
            rec.state = 'submitted'

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def action_create_rfq(self):
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_('Only approved Material Requests can be sent to RFQ.'))
        rfq = self.env['construction.rfq'].create({
            'project_id': self.project_id.id,
            'material_request_id': self.id,
            'line_ids': [(0, 0, {
                'product_id': line.product_id.id,
                'description': line.description or line.product_id.display_name,
                'qty': line.qty_requested,
                'uom_id': line.uom_id.id,
                'boq_line_id': line.boq_line_id.id,
            }) for line in self.line_ids],
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'construction.rfq',
            'res_id': rfq.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_rfqs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('RFQs'),
            'res_model': 'construction.rfq',
            'view_mode': 'list,form',
            'domain': [('material_request_id', '=', self.id)],
        }


class ConstructionMaterialRequestLine(models.Model):
    _name = 'construction.material.request.line'
    _description = 'Material Request Line'
    _order = 'sequence, id'

    sequence   = fields.Integer(default=10)
    request_id = fields.Many2one('construction.material.request', ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    boq_line_id = fields.Many2one('construction.boq.line', string='BOQ Item',
                                   domain="[('project_id','=',parent.project_id)]")
    description = fields.Char(string='Description')
    qty_requested = fields.Float(string='Qty Requested', digits=(12, 3), required=True)
    uom_id = fields.Many2one('uom.uom', string='UoM')
    notes = fields.Char(string='Notes')

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.description = self.product_id.display_name
            self.uom_id = self.product_id.uom_id
