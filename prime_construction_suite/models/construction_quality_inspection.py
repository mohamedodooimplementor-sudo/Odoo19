# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionQualityInspection(models.Model):
    _name = 'construction.quality.inspection'
    _description = 'Quality Inspection (IR / MIR / WIR)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_requested desc, id desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default='New')
    inspection_type = fields.Selection([
        ('ir',  'Inspection Request (IR)'),
        ('mir', 'Material Inspection Request (MIR)'),
        ('wir', 'Work Inspection Request (WIR)'),
    ], string='Type', default='wir', required=True, tracking=True)

    project_id  = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    contract_id = fields.Many2one('construction.contract', string='Contract', domain="[('project_id','=',project_id)]")
    company_id  = fields.Many2one(related='project_id.company_id', store=True)
    boq_line_id = fields.Many2one('construction.boq.line', string='Related BOQ Item',
                                   domain="[('project_id','=',project_id)]")

    description = fields.Text(string='Description', required=True)
    location    = fields.Char(string='Location / Area')

    requested_by  = fields.Many2one('res.users', string='Requested By', default=lambda s: s.env.user)
    date_requested = fields.Date(string='Date Requested', default=fields.Date.today, required=True)
    date_required  = fields.Date(string='Inspection Required By')

    inspector_id = fields.Many2one('res.partner', string='Inspector / Consultant')
    date_inspected = fields.Date(string='Date Inspected', readonly=True)

    result = fields.Selection([
        ('pending',               'Pending'),
        ('passed',                'Passed'),
        ('passed_with_comments',  'Passed with Comments'),
        ('failed',                'Failed'),
    ], default='pending', required=True, tracking=True)
    result_notes = fields.Text(string='Inspector Comments')

    ncr_ids = fields.One2many('construction.quality.ncr', 'inspection_id', string='NCRs Raised')
    ncr_count = fields.Integer(compute='_compute_ncr_count')

    state = fields.Selection([
        ('draft',     'Draft'),
        ('submitted', 'Submitted'),
        ('inspected', 'Inspected'),
        ('closed',    'Closed'),
    ], default='draft', required=True, tracking=True)

    @api.depends('ncr_ids')
    def _compute_ncr_count(self):
        for rec in self:
            rec.ncr_count = len(rec.ncr_ids)

    @api.model_create_multi
    def create(self, vals_list):
        code_map = {
            'ir':  'construction.quality.inspection.ir',
            'mir': 'construction.quality.inspection.mir',
            'wir': 'construction.quality.inspection.wir',
        }
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                code = code_map.get(vals.get('inspection_type', 'wir'), code_map['wir'])
                vals['name'] = self.env['ir.sequence'].next_by_code(code) or 'New'
        return super().create(vals_list)

    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_record_result(self):
        for rec in self:
            if rec.result == 'pending':
                raise UserError(_('Please set a result (Passed / Passed with Comments / Failed) first.'))
            rec.write({'state': 'inspected', 'date_inspected': fields.Date.today()})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_reset_draft(self):
        self.write({'state': 'draft', 'date_inspected': False})

    def action_raise_ncr(self):
        self.ensure_one()
        ncr = self.env['construction.quality.ncr'].create({
            'project_id': self.project_id.id,
            'contract_id': self.contract_id.id,
            'inspection_id': self.id,
            'description': _('Raised from %s: %s') % (self.name, self.description or ''),
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'construction.quality.ncr',
            'res_id': ncr.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_ncrs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('NCRs'),
            'res_model': 'construction.quality.ncr',
            'view_mode': 'list,form',
            'domain': [('inspection_id', '=', self.id)],
        }
