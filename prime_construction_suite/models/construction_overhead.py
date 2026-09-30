# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionOverheadAllocation(models.Model):
    _name = 'construction.overhead.allocation'
    _description = 'Overhead Cost Allocation'
    _inherit = ['mail.thread']
    _rec_name = 'name'
    _order = 'period_to desc'

    name          = fields.Char(string='Reference', required=True, copy=False, default='New')
    company_id    = fields.Many2one('res.company', default=lambda self: self.env.company)
    currency_id   = fields.Many2one(related='company_id.currency_id', store=True)
    period_from   = fields.Date(string='Period From', required=True)
    period_to     = fields.Date(string='Period To', required=True)
    total_amount  = fields.Monetary(string='Total Overhead Amount', currency_field='currency_id', required=True)
    basis = fields.Selection([
        ('contract_value', 'Contract Value'),
        ('equal',          'Equal Split'),
    ], string='Allocation Basis', default='contract_value', required=True)

    state = fields.Selection([
        ('draft',     'Draft'),
        ('allocated', 'Allocated'),
    ], string='Status', default='draft', tracking=True, required=True, copy=False)

    line_ids = fields.One2many('construction.overhead.allocation.line', 'allocation_id', string='Allocation Lines')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.overhead.allocation') or 'New'
        return super().create(vals_list)

    def action_compute_lines(self):
        for rec in self:
            rec.line_ids.unlink()
            projects = self.env['construction.project'].search([('state', '=', 'running')])
            if not projects:
                raise UserError(_('There are no running projects to allocate overhead to.'))

            if rec.basis == 'equal':
                share = 1.0 / len(projects)
                weights = {p.id: share for p in projects}
            else:
                total_value = sum(projects.mapped('contract_value')) or 1.0
                weights = {p.id: (p.contract_value / total_value) for p in projects}

            lines = []
            for p in projects:
                pct = weights.get(p.id, 0.0)
                lines.append((0, 0, {
                    'project_id': p.id,
                    'share_percent': pct * 100,
                    'allocated_amount': rec.total_amount * pct,
                }))
            rec.line_ids = lines

    def action_confirm(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Please compute allocation lines first.'))
            for line in rec.line_ids:
                self.env['construction.actual.cost'].create({
                    'project_id': line.project_id.id,
                    'cost_type': 'overhead',
                    'description': _('Overhead Allocation %s (%s to %s)') % (rec.name, rec.period_from, rec.period_to),
                    'quantity': 1.0,
                    'unit_price': line.allocated_amount,
                    'date': rec.period_to,
                })
            rec.state = 'allocated'

    def action_reset_draft(self):
        self.write({'state': 'draft'})


class ConstructionOverheadAllocationLine(models.Model):
    _name = 'construction.overhead.allocation.line'
    _description = 'Overhead Allocation Line'

    allocation_id    = fields.Many2one('construction.overhead.allocation', required=True, ondelete='cascade')
    currency_id      = fields.Many2one(related='allocation_id.currency_id', store=True)
    project_id       = fields.Many2one('construction.project', string='Project', required=True)
    share_percent    = fields.Float(string='Share %')
    allocated_amount = fields.Monetary(string='Allocated Amount', currency_field='currency_id')
