from datetime import timedelta

from odoo import api, fields, models, _


class SalesRepAlerts(models.Model):
    """Daily alerts for the back office (managers + accountants), sent once per record to the Odoo inbox."""
    _inherit = 'mo.sales.cheque'

    @api.model
    def _alert_recipients(self):
        groups = (self.env.ref('mo_sales_rep_portal.group_mo_rep_manager', raise_if_not_found=False)
                  | self.env.ref('mo_sales_rep_portal.group_mo_rep_accountant', raise_if_not_found=False))
        field = 'group_ids' if 'group_ids' in self.env['res.users']._fields else 'groups_id'
        users = self.env['res.users'].sudo().search([(field, 'in', groups.ids), ('share', '=', False)])
        return users.mapped('partner_id')

    @api.model
    def _alert_once(self, record, subject, body, partners):
        """Post an inbox notification on the record, only if this exact alert was not sent before."""
        record = record.sudo()
        if not partners or self.env['mail.message'].sudo().search_count([
                ('model', '=', record._name), ('res_id', '=', record.id), ('subject', '=', subject)]):
            return
        record.message_notify(partner_ids=partners.ids, subject=subject, body=body)

    @api.model
    def cron_backoffice_alerts(self):
        partners = self._alert_recipients()
        today = fields.Date.context_today(self)
        soon = today + timedelta(days=2)
        Cheque = self.sudo()
        open_states = ('received', 'deposited')
        for chq in Cheque.search([('state', 'in', open_states), ('due_date', '>=', today), ('due_date', '<=', soon)]):
            self._alert_once(chq, _('Cheque due soon: %s', chq.name),
                             _('Cheque %(n)s of %(c)s is due on %(d)s.', n=chq.cheque_number,
                               c=chq.partner_id.display_name, d=chq.due_date), partners)
        for chq in Cheque.search([('state', 'in', open_states), ('due_date', '<', today)]):
            self._alert_once(chq, _('Cheque overdue: %s', chq.name),
                             _('Cheque %(n)s of %(c)s was due on %(d)s and is still %(s)s.', n=chq.cheque_number,
                               c=chq.partner_id.display_name, d=chq.due_date, s=chq.state), partners)
        limit = fields.Datetime.now() - timedelta(days=2)
        for exp in self.env['mo.sales.expense'].sudo().search([('state', '=', 'submitted'), ('write_date', '<=', limit)]):
            self._alert_once(exp, _('Expense awaiting approval: %s', exp.name),
                             _('Expense %(n)s of %(r)s has been waiting for approval for more than 2 days.',
                               n=exp.name, r=exp.rep_id.name), partners)
