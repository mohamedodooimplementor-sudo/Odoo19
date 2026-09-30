# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ConstructionTransmittal(models.Model):
    _name = 'construction.transmittal'
    _description = 'Document Transmittal'
    _inherit = ['mail.thread']
    _rec_name = 'name'
    _order = 'date desc, id desc'

    name = fields.Char(string='Transmittal No.', required=True, copy=False, readonly=True, default='New')
    project_id = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='project_id.company_id', store=True)
    date        = fields.Date(string='Date', default=fields.Date.today, required=True)
    sent_by     = fields.Many2one('res.users', string='Sent By', default=lambda s: s.env.user)
    partner_id  = fields.Many2one('res.partner', string='To (Recipient)', required=True)

    purpose = fields.Selection([
        ('for_approval',     'For Approval'),
        ('for_review',       'For Review'),
        ('for_information',  'For Information'),
        ('for_construction', 'For Construction'),
        ('as_built',         'As-Built'),
    ], string='Purpose', default='for_review', required=True)

    method = fields.Selection([
        ('email',   'Email'),
        ('hand',    'Hand Delivery'),
        ('courier', 'Courier'),
        ('portal',  'Portal Upload'),
    ], string='Method', default='email', required=True)

    line_ids   = fields.One2many('construction.transmittal.line', 'transmittal_id', string='Documents')
    line_count = fields.Integer(compute='_compute_line_count')
    notes      = fields.Text(string='Notes')

    state = fields.Selection([
        ('draft',        'Draft'),
        ('sent',         'Sent'),
        ('acknowledged', 'Acknowledged'),
    ], default='draft', required=True, tracking=True)

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.transmittal') or 'New'
        return super().create(vals_list)

    def action_send(self):
        self.write({'state': 'sent'})

    def action_acknowledge(self):
        self.write({'state': 'acknowledged'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})


class ConstructionTransmittalLine(models.Model):
    _name = 'construction.transmittal.line'
    _description = 'Transmittal Line'
    _order = 'sequence, id'

    sequence       = fields.Integer(default=10)
    transmittal_id = fields.Many2one('construction.transmittal', ondelete='cascade')
    drawing_id     = fields.Many2one('construction.drawing', string='Drawing')
    revision_id    = fields.Many2one('construction.drawing.revision', string='Revision',
                                      domain="[('drawing_id','=',drawing_id)]")
    document_id    = fields.Many2one('construction.document', string='Document')
    description    = fields.Char(string='Description')
    copies         = fields.Integer(string='Copies', default=1)
    remarks        = fields.Char(string='Remarks')

    @api.onchange('drawing_id')
    def _onchange_drawing_id(self):
        if self.drawing_id:
            self.revision_id = self.drawing_id.current_revision_id
            if not self.description:
                self.description = self.drawing_id.display_name

    @api.onchange('document_id')
    def _onchange_document_id(self):
        if self.document_id and not self.description:
            self.description = self.document_id.name
