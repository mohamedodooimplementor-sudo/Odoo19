# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionFinalAccount(models.Model):
    _name = 'construction.final.account'
    _description = 'Final Account (Project Close-Out Statement)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, default='New')
    project_id  = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    contract_id = fields.Many2one('construction.contract', string='Contract', domain="[('project_id','=',project_id)]")
    company_id  = fields.Many2one(related='project_id.company_id', store=True)
    currency_id = fields.Many2one(related='project_id.currency_id', store=True)

    date = fields.Date(string='Date', default=fields.Date.today, required=True)
    prepared_by = fields.Many2one('res.users', string='Prepared By', default=lambda s: s.env.user)

    original_contract_value = fields.Monetary(string='Original Contract Value', currency_field='currency_id')
    total_variations = fields.Monetary(string='Total Approved Variations', currency_field='currency_id')
    final_contract_value = fields.Monetary(string='Final Contract Value', currency_field='currency_id',
                                            compute='_compute_totals', store=True)

    total_invoiced = fields.Monetary(string='Total Invoiced (Gross)', currency_field='currency_id')
    total_actual_cost = fields.Monetary(string='Total Actual Cost', currency_field='currency_id')
    final_profit = fields.Monetary(string='Final Profit / Loss', currency_field='currency_id',
                                    compute='_compute_totals', store=True)

    total_retention_held = fields.Monetary(string='Total Retention Held', currency_field='currency_id')
    retention_release_1 = fields.Monetary(string='Retention Release 1 (at Completion)', currency_field='currency_id')
    retention_release_2 = fields.Monetary(string='Retention Release 2 (after DLP)', currency_field='currency_id')
    retention_remaining = fields.Monetary(string='Retention Remaining', currency_field='currency_id',
                                           compute='_compute_totals', store=True)

    balance_due = fields.Monetary(string='Final Balance Due', currency_field='currency_id',
                                   compute='_compute_totals', store=True)

    defects_liability_end_date = fields.Date(string='Defects Liability Period Ends')
    notes = fields.Text(string='Notes')

    state = fields.Selection([
        ('draft',     'Draft'),
        ('submitted', 'Submitted'),
        ('agreed',    'Agreed by Client'),
        ('closed',    'Closed'),
    ], default='draft', required=True, tracking=True)

    @api.depends('original_contract_value', 'total_variations', 'total_invoiced', 'total_actual_cost',
                 'total_retention_held', 'retention_release_1', 'retention_release_2')
    def _compute_totals(self):
        for rec in self:
            rec.final_contract_value = rec.original_contract_value + rec.total_variations
            rec.final_profit = rec.total_invoiced - rec.total_actual_cost
            rec.retention_remaining = rec.total_retention_held - rec.retention_release_1 - rec.retention_release_2
            rec.balance_due = rec.final_contract_value - rec.total_invoiced

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.final.account') or 'New'
        return super().create(vals_list)

    def action_pull_figures(self):
        """Pull the latest figures from the contract/project so the statement reflects reality
        before it's submitted — still fully editable afterwards."""
        for rec in self:
            contract = rec.contract_id or rec.project_id.contract_id
            if not contract:
                continue
            approved_costs = rec.project_id.cost_ids.filtered(lambda c: c.state == 'approved')
            rec.write({
                'original_contract_value': contract.contract_value,
                'total_variations': contract.change_orders_total,
                'total_invoiced': contract.invoiced_amount,
                'total_actual_cost': sum(approved_costs.mapped('amount')),
                'total_retention_held': contract.retention_outstanding,
            })

    def action_submit(self):
        for rec in self:
            if not rec.final_contract_value:
                raise UserError(_('Please pull or enter the figures before submitting.'))
            rec.state = 'submitted'

    def action_agree(self):
        self.write({'state': 'agreed'})

    def action_close(self):
        self.write({'state': 'closed'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})
