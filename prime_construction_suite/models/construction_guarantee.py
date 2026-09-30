# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionGuarantee(models.Model):
    _name = 'construction.guarantee'
    _description = 'Bank Guarantee'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'expiry_date'

    name        = fields.Char(string='Guarantee No.', required=True, copy=False, readonly=True, default='New')
    project_id  = fields.Many2one('construction.project',  string='Project',  required=True, ondelete='restrict')
    contract_id = fields.Many2one('construction.contract', string='Contract', domain="[('project_id','=',project_id)]")
    currency_id = fields.Many2one(related='project_id.currency_id', store=True)
    company_id  = fields.Many2one(related='project_id.company_id',  store=True)

    guarantee_type = fields.Selection([
        ('initial',      'Initial (Bid) Guarantee'),
        ('performance',  'Performance Guarantee'),
        ('advance',      'Advance Payment Guarantee'),
        ('retention',    'Retention Guarantee'),
    ], string='Type', required=True, default='performance')

    bank_name        = fields.Char(string='Issuing Bank', required=True)
    guarantee_number = fields.Char(string='Bank Reference No.')
    amount           = fields.Monetary(string='Amount', currency_field='currency_id', required=True)
    issue_date       = fields.Date(string='Issue Date', required=True, default=fields.Date.today)
    expiry_date      = fields.Date(string='Expiry Date', required=True, tracking=True)
    days_to_expiry   = fields.Integer(string='Days to Expiry', compute='_compute_days_to_expiry', store=True)

    state = fields.Selection([
        ('active',   'Active'),
        ('released', 'Released'),
        ('claimed',  'Claimed'),
        ('expired',  'Expired'),
    ], string='Status', default='active', tracking=True, required=True, copy=False)

    release_date = fields.Date(string='Release Date', copy=False, tracking=True)
    notes        = fields.Text(string='Notes')

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
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.guarantee') or 'New'
        return super().create(vals_list)

    def action_release(self):
        for rec in self:
            rec.write({'state': 'released', 'release_date': fields.Date.today()})

    def action_claim(self):
        self.write({'state': 'claimed'})

    def action_reactivate(self):
        self.write({'state': 'active', 'release_date': False})

    def _cron_check_expiry(self):
        """Flag guarantees expiring within 30 days and mark truly-expired ones."""
        from datetime import date, timedelta
        today = date.today()
        soon = today + timedelta(days=30)

        active_recs = self.search([('state', '=', 'active')])
        active_recs._compute_days_to_expiry()
        active_recs.flush_recordset(['days_to_expiry'])

        expiring = active_recs.filtered(lambda r: r.expiry_date and today <= r.expiry_date <= soon)
        for rec in expiring:
            already = rec.activity_ids.filtered(lambda a: a.summary == _('Guarantee Expiring Soon'))
            if already:
                continue
            responsible = rec.project_id.project_manager_id.id or self.env.user.id
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('Guarantee Expiring Soon'),
                note=_('Guarantee %s (%s) for project %s expires on %s.')
                     % (rec.name, dict(rec._fields['guarantee_type'].selection).get(rec.guarantee_type),
                        rec.project_id.name, rec.expiry_date),
                user_id=responsible,
            )

        expired = self.search([('state', '=', 'active'), ('expiry_date', '<', today)])
        expired.write({'state': 'expired'})
