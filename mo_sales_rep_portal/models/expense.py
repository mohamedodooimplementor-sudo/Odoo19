from odoo import api, fields, models, _
from odoo.exceptions import UserError

EXPENSE_TYPES = [('transport', 'Transportation'), ('fuel', 'Fuel'), ('parking', 'Parking'),
                 ('visit', 'Customer Visit Expenses'), ('meals', 'Meals'), ('other', 'Other')]


class SalesExpense(models.Model):
    _name = 'mo.sales.expense'
    _description = 'Sales Representative Expense'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    name = fields.Char(default='New', readonly=True, copy=False)
    rep_id = fields.Many2one('mo.sales.rep', 'Sales Representative', required=True, tracking=True)
    date = fields.Date(default=fields.Date.context_today, required=True)
    expense_type = fields.Selection(EXPENSE_TYPES, 'Expense Type', required=True, default='transport')
    amount = fields.Monetary(required=True, currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', store=True)
    company_id = fields.Many2one('res.company', related='rep_id.company_id', store=True)
    partner_id = fields.Many2one('res.partner', 'Customer')
    visit_id = fields.Many2one('mo.sales.visit', 'Visit')
    notes = fields.Text()
    state = fields.Selection([('draft', 'Draft'), ('submitted', 'Submitted'), ('approved', 'Approved'),
                              ('refused', 'Refused')], default='draft', required=True, tracking=True)
    approved_by_id = fields.Many2one('res.users', 'Decided By', readonly=True, copy=False)
    approved_date = fields.Datetime('Decision Date', readonly=True, copy=False)
    refuse_reason = fields.Char('Refusal Reason', copy=False)
    client_uid = fields.Char(copy=False, index=True)
    attachment_count = fields.Integer(compute='_compute_attachment_count')

    def _compute_attachment_count(self):
        Att = self.env['ir.attachment'].sudo()
        for rec in self:
            rec.attachment_count = Att.search_count([('res_model', '=', self._name), ('res_id', '=', rec.id)])

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise UserError(_('The expense amount must be greater than zero.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('mo.sales.expense') or 'New'
        return super().create(vals_list)

    def action_submit(self):
        for rec in self.filtered(lambda r: r.state == 'draft'):
            rec.state = 'submitted'
            rec.rep_id._audit(rec, _('submitted the expense'))

    def action_reset_draft(self):
        self.filtered(lambda r: r.state in ('submitted', 'refused')).write({'state': 'draft'})

    def _check_manager(self):
        if not (self.env.user.has_group('mo_sales_rep_portal.group_mo_rep_manager') or self.env.user.has_group('mo_sales_rep_portal.group_mo_rep_accountant')):
            raise UserError(_('Only sales managers or accountants can approve or refuse expenses.'))

    def action_approve(self):
        self._check_manager()
        for rec in self.filtered(lambda r: r.state == 'submitted'):
            rec.write({'state': 'approved', 'approved_by_id': self.env.user.id, 'approved_date': fields.Datetime.now()})
            rec.rep_id._notify(_('Expense approved'), '%s - %s' % (rec.name, rec.amount), '/rep/expense/%s' % rec.id,
                               key='exp-ok:%s' % rec.id)

    def action_refuse(self):
        self._check_manager()
        for rec in self.filtered(lambda r: r.state == 'submitted'):
            rec.write({'state': 'refused', 'approved_by_id': self.env.user.id, 'approved_date': fields.Datetime.now()})
            rec.rep_id._notify(_('Expense refused'), '%s %s' % (rec.name, rec.refuse_reason or ''),
                               '/rep/expense/%s' % rec.id, key='exp-no:%s' % rec.id)
