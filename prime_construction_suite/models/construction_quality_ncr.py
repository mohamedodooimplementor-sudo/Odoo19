# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class ConstructionQualityNcr(models.Model):
    _name = 'construction.quality.ncr'
    _description = 'Non-Conformance Report (NCR)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_raised desc, id desc'

    name = fields.Char(string='NCR No.', required=True, copy=False, readonly=True, default='New')
    project_id  = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    contract_id = fields.Many2one('construction.contract', string='Contract', domain="[('project_id','=',project_id)]")
    company_id  = fields.Many2one(related='project_id.company_id', store=True)
    inspection_id = fields.Many2one('construction.quality.inspection', string='Originating Inspection')
    boq_line_id = fields.Many2one('construction.boq.line', string='Related BOQ Item',
                                   domain="[('project_id','=',project_id)]")

    date_raised = fields.Date(string='Date Raised', default=fields.Date.today, required=True)
    raised_by   = fields.Many2one('res.users', string='Raised By', default=lambda s: s.env.user)
    description = fields.Text(string='Non-Conformance Description', required=True)

    severity = fields.Selection([
        ('minor',    'Minor'),
        ('major',    'Major'),
        ('critical', 'Critical'),
    ], default='minor', required=True, tracking=True)

    responsible_party_id = fields.Many2one('res.partner', string='Responsible Party (Subcontractor/Vendor)')

    capa_ids = fields.One2many('construction.quality.capa', 'ncr_id', string='Corrective / Preventive Actions')
    capa_count = fields.Integer(compute='_compute_capa_count')

    date_closed = fields.Date(string='Date Closed', readonly=True)
    state = fields.Selection([
        ('draft',         'Draft'),
        ('open',          'Open'),
        ('capa_assigned', 'CAPA Assigned'),
        ('closed',        'Closed'),
    ], default='draft', required=True, tracking=True)

    @api.depends('capa_ids')
    def _compute_capa_count(self):
        for rec in self:
            rec.capa_count = len(rec.capa_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.quality.ncr') or 'New'
        return super().create(vals_list)

    def action_open(self):
        self.write({'state': 'open'})

    def action_create_capa(self):
        self.ensure_one()
        capa = self.env['construction.quality.capa'].create({
            'ncr_id': self.id,
            'project_id': self.project_id.id,
            'description': _('Action for %s') % self.name,
        })
        self.state = 'capa_assigned'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'construction.quality.capa',
            'res_id': capa.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_capas(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('CAPAs'),
            'res_model': 'construction.quality.capa',
            'view_mode': 'list,form',
            'domain': [('ncr_id', '=', self.id)],
        }

    def action_close(self):
        for rec in self:
            open_capas = rec.capa_ids.filtered(lambda c: c.state not in ('completed', 'verified'))
            if open_capas:
                from odoo.exceptions import UserError
                raise UserError(_('All CAPAs must be completed and verified before closing this NCR.'))
            rec.write({'state': 'closed', 'date_closed': fields.Date.today()})

    def action_reset_draft(self):
        self.write({'state': 'draft', 'date_closed': False})
