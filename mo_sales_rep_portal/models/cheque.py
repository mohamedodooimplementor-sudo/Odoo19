from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SalesCheque(models.Model):
    _name = 'mo.sales.cheque'
    _description = 'Cheque Received by a Sales Representative'
    _inherit = ['mail.thread']
    _order = 'due_date, id desc'

    name = fields.Char(default='New', readonly=True, copy=False)
    payment_id = fields.Many2one('account.payment', 'Payment', ondelete='cascade', index=True)
    rep_id = fields.Many2one('mo.sales.rep', 'Sales Representative', required=True, tracking=True)
    partner_id = fields.Many2one('res.partner', 'Customer', required=True)
    cheque_number = fields.Char(required=True, tracking=True)
    bank_name = fields.Char('Bank', required=True)
    cheque_date = fields.Date('Cheque Date')
    due_date = fields.Date(required=True, tracking=True)
    amount = fields.Monetary(currency_field='currency_id', required=True)
    currency_id = fields.Many2one('res.currency', default=lambda s: s.env.company.currency_id)
    notes = fields.Text()
    state = fields.Selection([('received', 'Received'), ('deposited', 'Deposited'), ('cleared', 'Cleared'),
                              ('returned', 'Returned')], default='received', required=True, tracking=True)
    company_id = fields.Many2one('res.company', related='rep_id.company_id', store=True)
    attachment_count = fields.Integer(compute='_compute_attachment_count')

    def _compute_attachment_count(self):
        Att = self.env['ir.attachment'].sudo()
        for rec in self:
            rec.attachment_count = Att.search_count([('res_model', '=', self._name), ('res_id', '=', rec.id)])

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('mo.sales.cheque') or 'New'
        return super().create(vals_list)

    def _move_to(self, new_state, allowed_from, title):
        if not (self.env.user.has_group('mo_sales_rep_portal.group_mo_rep_manager') or self.env.user.has_group('mo_sales_rep_portal.group_mo_rep_accountant')):
            raise UserError(_('Only sales managers or accountants can change the cheque status.'))
        for rec in self:
            if rec.state not in allowed_from:
                raise UserError(_('Cheque %(n)s cannot go from %(a)s to %(b)s.', n=rec.name, a=rec.state, b=new_state))
            rec.state = new_state
            rec.rep_id._notify(title, '%s - %s' % (rec.cheque_number, rec.partner_id.display_name), '/rep/cheques',
                               key='chq:%s:%s' % (rec.id, new_state))

    def action_deposit(self):
        self._move_to('deposited', ('received',), _('Cheque deposited'))

    def action_clear(self):
        self._move_to('cleared', ('deposited',), _('Cheque cleared'))

    def action_return(self):
        self._move_to('returned', ('received', 'deposited'), _('Cheque returned'))
