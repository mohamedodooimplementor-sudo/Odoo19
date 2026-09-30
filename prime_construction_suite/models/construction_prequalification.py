# -*- coding: utf-8 -*-
from odoo import models, fields, api, _


class ConstructionSubcontractorPrequalification(models.Model):
    _name = 'construction.subcontractor.prequalification'
    _description = 'Subcontractor Prequalification'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'partner_id'
    _order = 'create_date desc'

    partner_id = fields.Many2one('res.partner', string='Company', required=True, domain=[('is_company', '=', True)])
    trades = fields.Char(string='Trades / Specialization', help="e.g. 'Structural Steel, MEP'")

    insurance_valid       = fields.Boolean(string='Valid Insurance on File')
    insurance_expiry_date = fields.Date(string='Insurance Expiry Date')
    safety_record_notes   = fields.Text(string='Safety Record / HSE History')
    financial_reference    = fields.Text(string='Financial Capacity / Bank Reference')
    years_experience       = fields.Integer(string='Years of Experience')
    reference_projects     = fields.Text(string='Reference Projects')

    score = fields.Integer(string='Prequalification Score (0-100)', default=0)
    status = fields.Selection([
        ('pending',  'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('expired',  'Expired'),
    ], string='Status', default='pending', tracking=True, required=True)

    valid_until  = fields.Date(string='Approval Valid Until')
    reviewed_by  = fields.Many2one('res.users', string='Reviewed By')
    review_date  = fields.Date(string='Review Date')
    notes        = fields.Text(string='Notes')

    def action_approve(self):
        self.write({'status': 'approved', 'reviewed_by': self.env.user.id, 'review_date': fields.Date.today()})

    def action_reject(self):
        self.write({'status': 'rejected', 'reviewed_by': self.env.user.id, 'review_date': fields.Date.today()})

    def action_reset_pending(self):
        self.write({'status': 'pending'})

    def _cron_expire_prequalifications(self):
        from datetime import date
        expired = self.search([('status', '=', 'approved'), ('valid_until', '<', date.today())])
        expired.write({'status': 'expired'})
