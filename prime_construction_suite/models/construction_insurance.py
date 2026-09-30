# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class ConstructionInsurance(models.Model):
    _name = 'construction.insurance'
    _description = 'Insurance Policy'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'expiry_date'

    name        = fields.Char(string='Policy No.', required=True, copy=False, readonly=True, default='New')
    project_id  = fields.Many2one('construction.project',  string='Project',  required=True, ondelete='restrict')
    currency_id = fields.Many2one(related='project_id.currency_id', store=True)
    company_id  = fields.Many2one(related='project_id.company_id',  store=True)

    insurance_type = fields.Selection([
        ('car',        'Contractor\'s All Risk (CAR)'),
        ('liability',  'Third Party Liability'),
        ('workmen',    'Workmen\'s Compensation'),
        ('equipment',  'Equipment Insurance'),
        ('other',      'Other'),
    ], string='Type', required=True, default='car')

    insurer          = fields.Char(string='Insurance Company', required=True)
    policy_number    = fields.Char(string='Policy Reference No.')
    coverage_amount  = fields.Monetary(string='Coverage Amount', currency_field='currency_id')
    premium_amount   = fields.Monetary(string='Premium Paid', currency_field='currency_id')
    start_date       = fields.Date(string='Start Date', required=True, default=fields.Date.today)
    expiry_date      = fields.Date(string='Expiry Date', required=True, tracking=True)
    days_to_expiry   = fields.Integer(string='Days to Expiry', compute='_compute_days_to_expiry', store=True)

    state = fields.Selection([
        ('active',  'Active'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='active', tracking=True, required=True, copy=False)

    notes = fields.Text(string='Notes')

    @api.depends('expiry_date')
    def _compute_days_to_expiry(self):
        from datetime import date
        today = date.today()
        for rec in self:
            rec.days_to_expiry = (rec.expiry_date - today).days if rec.expiry_date else 0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.insurance') or 'New'
        return super().create(vals_list)

    def action_cancel(self): self.write({'state': 'cancelled'})
    def action_reactivate(self): self.write({'state': 'active'})

    def _cron_check_expiry(self):
        from datetime import date, timedelta
        today = date.today()
        soon = today + timedelta(days=30)

        active_recs = self.search([('state', '=', 'active')])
        active_recs._compute_days_to_expiry()
        active_recs.flush_recordset(['days_to_expiry'])

        expiring = active_recs.filtered(lambda r: r.expiry_date and today <= r.expiry_date <= soon)
        for rec in expiring:
            already = rec.activity_ids.filtered(lambda a: a.summary == _('Insurance Policy Expiring Soon'))
            if already:
                continue
            responsible = rec.project_id.project_manager_id.id or self.env.user.id
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('Insurance Policy Expiring Soon'),
                note=_('Insurance policy %s (%s) for project %s expires on %s.')
                     % (rec.name, dict(rec._fields['insurance_type'].selection).get(rec.insurance_type),
                        rec.project_id.name, rec.expiry_date),
                user_id=responsible,
            )

        expired = self.search([('state', '=', 'active'), ('expiry_date', '<', today)])
        expired.write({'state': 'expired'})
