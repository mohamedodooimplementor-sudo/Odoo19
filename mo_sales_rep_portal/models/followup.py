from odoo import api, fields, models, _


class SalesFollowup(models.Model):
    _name = 'mo.sales.followup'
    _description = 'Sales Follow-up'
    _inherit = ['mail.thread']
    _order = 'due_date, priority desc, id'

    name = fields.Char('Task', required=True)
    rep_id = fields.Many2one('mo.sales.rep', 'Sales Representative', required=True, tracking=True)
    partner_id = fields.Many2one('res.partner', 'Customer', required=True)
    due_date = fields.Date(required=True, default=fields.Date.context_today)
    priority = fields.Selection([('0', 'Normal'), ('1', 'High'), ('2', 'Urgent')], default='0')
    notes = fields.Text()
    visit_id = fields.Many2one('mo.sales.visit', 'Related Visit')
    order_id = fields.Many2one('sale.order', 'Related Order')
    state = fields.Selection([('open', 'Open'), ('done', 'Done'), ('cancelled', 'Cancelled')], default='open',
                             required=True, tracking=True)
    done_date = fields.Datetime(readonly=True, copy=False)
    company_id = fields.Many2one('res.company', related='rep_id.company_id', store=True)
    client_uid = fields.Char(copy=False, index=True)

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        for rec in recs:
            if self.env.uid != rec.rep_id.user_id.id:
                rec.rep_id._notify(_('New follow-up'), '%s - %s' % (rec.partner_id.display_name, rec.name), '/rep/followups')
        return recs

    def action_done(self):
        self.filtered(lambda r: r.state == 'open').write({'state': 'done', 'done_date': fields.Datetime.now()})

    def action_cancel(self):
        self.filtered(lambda r: r.state == 'open').write({'state': 'cancelled'})

    def action_reopen(self):
        self.filtered(lambda r: r.state != 'open').write({'state': 'open', 'done_date': False})
