# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionQualityCapa(models.Model):
    _name = 'construction.quality.capa'
    _description = 'Corrective / Preventive Action (CAPA)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'due_date, id desc'

    name = fields.Char(string='CAPA No.', required=True, copy=False, readonly=True, default='New')
    ncr_id = fields.Many2one('construction.quality.ncr', string='Related NCR', ondelete='cascade')
    project_id = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='project_id.company_id', store=True)

    action_type = fields.Selection([
        ('corrective', 'Corrective'),
        ('preventive', 'Preventive'),
    ], default='corrective', required=True)

    description = fields.Text(string='Action Description', required=True)
    assigned_to = fields.Many2one('res.users', string='Assigned To')
    due_date = fields.Date(string='Due Date')
    is_overdue = fields.Boolean(compute='_compute_overdue', store=True)

    date_completed = fields.Date(string='Date Completed', readonly=True)
    verified_by = fields.Many2one('res.users', string='Verified By', readonly=True)
    date_verified = fields.Date(string='Date Verified', readonly=True)
    verification_notes = fields.Text(string='Verification Notes')

    state = fields.Selection([
        ('draft',       'Draft'),
        ('in_progress', 'In Progress'),
        ('completed',   'Completed'),
        ('verified',    'Verified'),
    ], default='draft', required=True, tracking=True)

    @api.depends('due_date', 'state')
    def _compute_overdue(self):
        today = fields.Date.today()
        for rec in self:
            rec.is_overdue = bool(rec.due_date and rec.due_date < today and rec.state not in ('completed', 'verified'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.quality.capa') or 'New'
        return super().create(vals_list)

    def action_start(self):
        self.write({'state': 'in_progress'})

    def action_complete(self):
        self.write({'state': 'completed', 'date_completed': fields.Date.today()})

    def action_verify(self):
        for rec in self:
            if rec.state != 'completed':
                raise UserError(_('Only completed actions can be verified.'))
            rec.write({
                'state': 'verified',
                'verified_by': self.env.user.id,
                'date_verified': fields.Date.today(),
            })

    def action_reset_draft(self):
        self.write({'state': 'draft', 'date_completed': False, 'verified_by': False, 'date_verified': False})

    def _cron_remind_overdue_capas(self):
        overdue = self.search([('is_overdue', '=', True)])
        for rec in overdue:
            already = rec.activity_ids.filtered(lambda a: a.summary == _('CAPA Overdue'))
            if already:
                continue
            rec.activity_schedule(
                'mail.mail_activity_data_todo', summary=_('CAPA Overdue'),
                note=_('CAPA %s is overdue (due %s).') % (rec.name, rec.due_date),
                user_id=rec.assigned_to.id or self.env.user.id,
            )
