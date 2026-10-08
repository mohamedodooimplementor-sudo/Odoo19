# -*- coding: utf-8 -*-
from odoo import fields, models


class EmployeeRequestApproval(models.Model):
    _name = 'employee.request.approval'
    _description = 'Employee Request Approval History'
    _order = 'id desc'

    request_id = fields.Many2one(
        'employee.request', required=True, ondelete='cascade', index=True)
    round = fields.Integer(string='Round', default=1)
    stage = fields.Selection([
        ('draft', 'Draft'),
        ('department', 'Department Approval'),
        ('warehouse', 'Warehouse Approval'),
        ('budget', 'Budget Approval'),
        ('approved', 'Approved'),
        ('processing', 'Processing'),
        ('partial', 'Partially Done'),
        ('closed', 'Closed'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ], string='Stage')
    user_id = fields.Many2one('res.users', string='User', required=True,
                              default=lambda self: self.env.user)
    date = fields.Datetime(string='Date', default=fields.Datetime.now)
    action = fields.Selection([
        ('submit', 'Submitted'),
        ('approve', 'Approved'),
        ('reject', 'Rejected'),
        ('reset', 'Reset to Draft'),
        ('cancel', 'Cancelled'),
    ], string='Action', required=True)
    comment = fields.Text(string='Comments')
