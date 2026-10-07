from odoo import api, fields, models


class SalesRepEmployee(models.Model):
    _inherit = 'mo.sales.rep'

    employee_id = fields.Many2one('hr.employee', 'Employee', tracking=True, copy=False)
    department_id = fields.Many2one(related='employee_id.department_id', string='Department', store=True)

    @api.onchange('user_id')
    def _onchange_user_employee(self):
        """Suggest the employee linked to the same user, when there is one."""
        for rep in self:
            if rep.user_id and not rep.employee_id:
                rep.employee_id = self.env['hr.employee'].search([('user_id', '=', rep.user_id.id)], limit=1)

    @api.onchange('employee_id')
    def _onchange_employee_name(self):
        for rep in self:
            if rep.employee_id and not rep.name:
                rep.name = rep.employee_id.name
