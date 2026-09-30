# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionActualCost(models.Model):
    _name = 'construction.actual.cost'
    _description = 'Actual Project Cost'
    _inherit = ['mail.thread']
    _rec_name = 'description'
    _order = 'date desc'

    project_id    = fields.Many2one('construction.project',  string='Project',  required=True, ondelete='restrict', index=True)
    contract_id   = fields.Many2one('construction.contract', string='Contract', domain="[('project_id','=',project_id)]")
    currency_id   = fields.Many2one(related='project_id.currency_id', store=True)
    company_id    = fields.Many2one(related='project_id.company_id',  store=True)
    date          = fields.Date(string='Date', required=True, default=fields.Date.today, index=True)
    cost_type     = fields.Selection([
        ('material',    'Materials'),
        ('labor',       'Labor'),
        ('equipment',   'Equipment'),
        ('subcontract', 'Subcontractors'),
        ('overhead',    'Overhead'),
        ('other',       'Other'),
    ], string='Cost Type', required=True, default='material')
    description      = fields.Char(string='Description', required=True)
    quantity         = fields.Float(string='Quantity', digits=(12,3), default=1.0)
    unit_price       = fields.Monetary(string='Unit Price', currency_field='currency_id')
    amount           = fields.Monetary(string='Amount', currency_field='currency_id', compute='_compute_amount', store=True)
    boq_line_id      = fields.Many2one('construction.boq.line', string='Related BOQ Item', domain="[('contract_id','=',contract_id)]")
    cost_code_id     = fields.Many2one('construction.cost.code', string='Cost Code (WBS)')
    analytic_line_id = fields.Many2one('account.analytic.line', string='Analytic Line')
    purchase_order_id= fields.Many2one('purchase.order', string='Purchase Order')
    stock_move_id    = fields.Many2one('stock.move', string='Stock Move', copy=False, readonly=True,
                                        help='Set automatically when this cost was generated from a '
                                             'goods receipt linked to a BOQ item.')
    move_id          = fields.Many2one('account.move', string='Journal Entry', copy=False, readonly=True,
                                        help='Accounting entry posted to the general ledger when this '
                                             'cost was approved (requires Construction Suite accounting '
                                             'accounts/journal to be configured in Settings).')
    notes            = fields.Text(string='Notes')

    state = fields.Selection([
        ('draft',    'Draft'),
        ('approved', 'Approved'),
    ], string='Status', default='draft', tracking=True, required=True, copy=False, index=True)
    approved_by   = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    date_approved = fields.Date(string='Approval Date', readonly=True, copy=False)

    @api.depends('quantity', 'unit_price')
    def _compute_amount(self):
        for rec in self:
            rec.amount = rec.quantity * rec.unit_price

    def action_approve(self):
        for rec in self:
            company = rec.company_id or self.env.company
            ApprovalRule = self.env['construction.approval.rule']
            if ApprovalRule.get_required_role('actual_cost', rec.amount, company):
                ApprovalRule.check_approval('actual_cost', rec.amount, company)
            else:
                # No Approval Matrix configured for Actual Costs — fall back to the simple
                # two-threshold settings for backward compatibility.
                t1 = company.construction_approval_threshold_1
                t2 = company.construction_approval_threshold_2
                user = self.env.user

                if rec.amount > t2 and not user.has_group('prime_construction_suite.group_construction_financial'):
                    raise UserError(_(
                        'This cost (%s) exceeds the Project Manager limit (%s) and requires approval '
                        'by a Financial Manager.') % (rec.amount, t2))
                elif rec.amount > t1 and not (
                        user.has_group('prime_construction_suite.group_construction_manager')
                        or user.has_group('prime_construction_suite.group_construction_financial')):
                    raise UserError(_(
                        'This cost (%s) exceeds the auto-approval limit (%s) and requires approval '
                        'by a Project Manager or Financial Manager.') % (rec.amount, t1))

            rec.write({
                'state': 'approved',
                'approved_by': self.env.user.id,
                'date_approved': fields.Date.today(),
            })
            rec._create_journal_entry()

    def action_reset_draft(self):
        for rec in self:
            if rec.move_id and rec.move_id.state == 'posted':
                rec.move_id.sudo()._reverse_moves(cancel=False)
                rec.move_id = False
        self.write({'state': 'draft', 'approved_by': False, 'date_approved': False})

    def action_view_journal_entry(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
        }

    def _get_cost_account(self, company):
        """Return the debit (expense/WIP) account configured for this cost's type."""
        self.ensure_one()
        field_map = {
            'material':    'construction_material_account_id',
            'labor':       'construction_labor_account_id',
            'equipment':   'construction_equipment_account_id',
            'subcontract': 'construction_subcontract_account_id',
            'overhead':    'construction_overhead_account_id',
            'other':       'construction_other_account_id',
        }
        field_name = field_map.get(self.cost_type)
        return company[field_name] if field_name else self.env['account.account']

    def _create_journal_entry(self):
        """Post a journal entry to Accounting for this approved cost: debit the project's cost
        account (by cost type) and credit the Accrued Project Costs clearing account, tagged with
        the project's analytic account. Silently skipped if the accounting integration hasn't been
        configured in Settings > Construction Suite — costs remain fully usable within the Suite
        either way."""
        self.ensure_one()
        if self.move_id:
            return
        company = self.company_id or self.env.company
        journal = company.construction_cost_journal_id
        debit_account = self._get_cost_account(company)
        credit_account = company.construction_accrual_account_id
        if not journal or not debit_account or not credit_account:
            return

        analytic_distribution = {}
        if self.project_id.analytic_account_id and 'analytic_distribution' in self.env['account.move.line']._fields:
            analytic_distribution = {str(self.project_id.analytic_account_id.id): 100.0}
        partner_id = self.purchase_order_id.partner_id.id if self.purchase_order_id else False

        move = self.env['account.move'].sudo().create({
            'journal_id': journal.id,
            'date': self.date,
            'ref': self.description,
            'move_type': 'entry',
            'line_ids': [
                (0, 0, {
                    'name': self.description,
                    'account_id': debit_account.id,
                    'debit': self.amount, 'credit': 0.0,
                    'partner_id': partner_id,
                    'analytic_distribution': analytic_distribution,
                }),
                (0, 0, {
                    'name': self.description,
                    'account_id': credit_account.id,
                    'debit': 0.0, 'credit': self.amount,
                    'partner_id': partner_id,
                    'analytic_distribution': analytic_distribution,
                }),
            ],
        })
        move.action_post()
        self.move_id = move.id


class ConstructionProjectDashboard(models.Model):
    _name = 'construction.project.dashboard'
    _description = 'Project Dashboard KPIs'
    _auto = False

    project_id      = fields.Many2one('construction.project', string='Project')
    contract_value  = fields.Float(string='Contract Value')
    invoiced_amount = fields.Float(string='Invoiced Amount')
    actual_cost     = fields.Float(string='Actual Cost')
    subcontract_cost= fields.Float(string='Subcontract Cost')
    remaining       = fields.Float(string='Remaining')
    progress        = fields.Float(string='Progress %')

    def init(self):
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW construction_project_dashboard AS
            SELECT p.id AS id, p.id AS project_id,
                COALESCE(c.revised_contract_value, p.contract_value, 0) AS contract_value,
                COALESCE(inv_sum.total, 0)  AS invoiced_amount,
                COALESCE(cost_sum.total, 0) AS actual_cost,
                COALESCE(sub_sum.total, 0)  AS subcontract_cost,
                COALESCE(c.revised_contract_value, p.contract_value, 0) - COALESCE(inv_sum.total, 0) AS remaining,
                p.progress_percent AS progress
            FROM construction_project p
            LEFT JOIN construction_contract c ON c.project_id = p.id AND c.state != 'terminated'
            LEFT JOIN (SELECT contract_id, SUM(gross_amount) AS total FROM construction_progress_invoice
                       WHERE state IN ('approved','invoiced','paid') GROUP BY contract_id) inv_sum ON inv_sum.contract_id = c.id
            LEFT JOIN (SELECT project_id, SUM(amount) AS total FROM construction_actual_cost WHERE state = 'approved' GROUP BY project_id) cost_sum ON cost_sum.project_id = p.id
            LEFT JOIN (SELECT project_id, SUM(paid_amount) AS total FROM construction_subcontractor GROUP BY project_id) sub_sum ON sub_sum.project_id = p.id
        """)
