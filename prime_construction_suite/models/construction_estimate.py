# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionEstimate(models.Model):
    _name = 'construction.estimate'
    _description = 'Pre-Construction Estimate / Takeoff'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'create_date desc'

    name        = fields.Char(string='Reference', required=True, copy=False, default='New')
    client_id   = fields.Many2one('res.partner', string='Prospective Client')
    project_name = fields.Char(string='Project Name', required=True)
    date        = fields.Date(string='Estimate Date', default=fields.Date.today)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    company_id  = fields.Many2one('res.company', default=lambda self: self.env.company)

    line_ids    = fields.One2many('construction.estimate.line', 'estimate_id', string='Estimate Lines')
    total_amount = fields.Monetary(string='Estimated Total', currency_field='currency_id',
                                    compute='_compute_total', store=True)
    margin_percent = fields.Float(string='Target Margin %', default=15.0)
    total_with_margin = fields.Monetary(string='Total incl. Margin', currency_field='currency_id',
                                         compute='_compute_total', store=True)

    state = fields.Selection([
        ('draft',     'Draft'),
        ('submitted', 'Submitted to Client'),
        ('won',       'Won'),
        ('lost',      'Lost'),
    ], string='Status', default='draft', tracking=True, required=True)

    converted_project_id = fields.Many2one('construction.project', string='Converted Project', readonly=True, copy=False)

    @api.depends('line_ids.total_price', 'margin_percent')
    def _compute_total(self):
        for rec in self:
            rec.total_amount = sum(rec.line_ids.mapped('total_price'))
            rec.total_with_margin = rec.total_amount * (1 + rec.margin_percent / 100)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.estimate') or 'New'
        return super().create(vals_list)

    def action_submit(self): self.write({'state': 'submitted'})
    def action_mark_lost(self): self.write({'state': 'lost'})
    def action_reset_draft(self): self.write({'state': 'draft'})

    def action_convert_to_project(self):
        """Win the estimate: create the Project, Contract and initial BOQ from the estimate lines."""
        self.ensure_one()
        if self.converted_project_id:
            raise UserError(_('This estimate has already been converted to a project.'))

        project = self.env['construction.project'].create({
            'name': self.project_name,
            'client_id': self.client_id.id if self.client_id else False,
            'contract_value': self.total_with_margin,
        })
        contract = self.env['construction.contract'].create({
            'project_id': project.id,
            'contract_value': self.total_with_margin,
        })
        project.contract_id = contract.id

        for line in self.line_ids:
            self.env['construction.boq.line'].create({
                'contract_id': contract.id,
                'description': line.description,
                'cost_code_id': line.cost_code_id.id if line.cost_code_id else False,
                'uom_id': line.uom_id.id if line.uom_id else False,
                'qty_contract': line.quantity,
                'unit_price': line.unit_price * (1 + self.margin_percent / 100),
            })

        self.write({'state': 'won', 'converted_project_id': project.id})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Project'),
            'res_model': 'construction.project',
            'view_mode': 'form',
            'res_id': project.id,
        }


class ConstructionEstimateLine(models.Model):
    _name = 'construction.estimate.line'
    _description = 'Estimate Line (Takeoff Item)'
    _order = 'sequence'

    estimate_id  = fields.Many2one('construction.estimate', required=True, ondelete='cascade')
    sequence     = fields.Integer(default=10)
    description  = fields.Char(string='Description', required=True)
    cost_code_id = fields.Many2one('construction.cost.code', string='Cost Code (WBS)')
    uom_id       = fields.Many2one('uom.uom', string='UoM')
    quantity     = fields.Float(string='Quantity (Takeoff)', default=1.0)
    unit_price   = fields.Float(string='Unit Price')
    currency_id  = fields.Many2one(related='estimate_id.currency_id', store=True)
    total_price  = fields.Monetary(string='Total', currency_field='currency_id', compute='_compute_total', store=True)

    @api.depends('quantity', 'unit_price')
    def _compute_total(self):
        for rec in self:
            rec.total_price = rec.quantity * rec.unit_price
