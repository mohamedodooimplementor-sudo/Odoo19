# -*- coding: utf-8 -*-
from odoo import fields, models


class EmployeeRequestRejectWizard(models.TransientModel):
    _name = 'employee.request.reject.wizard'
    _description = 'Reject Employee Request / Purchase Order'

    res_model = fields.Char(required=True)
    res_id = fields.Integer(required=True)
    reason = fields.Text(string='Reason', required=True)

    def action_confirm(self):
        self.ensure_one()
        self.env[self.res_model].browse(self.res_id)._do_reject(self.reason)
        return {'type': 'ir.actions.act_close_window'} if False else {'type': 'ir.actions.act_window_close'}
