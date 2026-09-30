# -*- coding: utf-8 -*-
from odoo import fields, models


class EducationExpenseCategory(models.Model):
    """A lightweight 'chart of expense accounts' for the center — e.g. Rent,
    Salaries, Utilities, Marketing, Maintenance. Deliberately not a real
    account.account (this module has no dependency on Accounting): it exists
    only to classify education.expense records for the Income Statement and
    Expense reports."""
    _name = 'education.expense.category'
    _description = 'Expense Category'
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code')
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    expense_count = fields.Integer(string='Expenses', compute='_compute_expense_count')

    _sql_constraints = [
        ('code_uniq', 'unique(code, company_id)', 'Expense category code must be unique per company.'),
    ]

    def _compute_expense_count(self):
        Expense = self.env['education.expense']
        for rec in self:
            rec.expense_count = Expense.search_count([('category_id', '=', rec.id)])

    def action_view_expenses(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': 'education.expense',
            'view_mode': 'list,form',
            'domain': [('category_id', '=', self.id)],
            'context': {'default_category_id': self.id},
        }
