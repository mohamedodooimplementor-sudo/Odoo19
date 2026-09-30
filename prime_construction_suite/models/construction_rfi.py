# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionRfi(models.Model):
    _name = 'construction.rfi'
    _description = 'Request for Information (RFI)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'date_submitted desc, id desc'

    name = fields.Char(string='RFI No.', required=True, copy=False, readonly=True, default='New')
    project_id  = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    company_id  = fields.Many2one(related='project_id.company_id', store=True)
    contract_id = fields.Many2one('construction.contract', string='Contract', domain="[('project_id','=',project_id)]")
    drawing_id  = fields.Many2one('construction.drawing', string='Related Drawing',
                                   domain="[('project_id','=',project_id)]")

    subject  = fields.Char(string='Subject', required=True)
    question = fields.Text(string='Question', required=True)

    discipline = fields.Selection([
        ('architectural', 'Architectural'),
        ('structural',    'Structural'),
        ('mep',           'MEP'),
        ('civil',         'Civil'),
        ('landscape',     'Landscape'),
        ('other',         'Other'),
    ], string='Discipline', default='architectural', required=True)

    priority = fields.Selection([
        ('low',      'Low'),
        ('medium',   'Medium'),
        ('high',     'High'),
        ('critical', 'Critical'),
    ], string='Priority', default='medium', required=True, tracking=True)

    submitted_by   = fields.Many2one('res.users', string='Submitted By', default=lambda s: s.env.user)
    date_submitted = fields.Date(string='Date Submitted', default=fields.Date.today, required=True)
    assigned_to    = fields.Many2one('res.partner', string='Assigned To (Consultant/Client)')
    date_required  = fields.Date(string='Response Required By')

    answer        = fields.Text(string='Answer')
    answered_by   = fields.Many2one('res.users', string='Answered By', readonly=True, copy=False)
    date_answered = fields.Date(string='Date Answered', readonly=True, copy=False)

    cost_impact          = fields.Boolean(string='Cost Impact')
    schedule_impact       = fields.Boolean(string='Schedule Impact')
    schedule_impact_days = fields.Integer(string='Schedule Impact (Days)')

    state = fields.Selection([
        ('draft',     'Draft'),
        ('submitted', 'Submitted'),
        ('answered',  'Answered'),
        ('closed',    'Closed'),
    ], default='draft', required=True, tracking=True)

    days_open = fields.Integer(string='Days Open', compute='_compute_days_open')
    is_overdue = fields.Boolean(string='Overdue', compute='_compute_days_open', store=True)

    @api.depends('date_submitted', 'date_answered', 'date_required', 'state')
    def _compute_days_open(self):
        today = fields.Date.today()
        for rec in self:
            end = rec.date_answered or today
            rec.days_open = (end - rec.date_submitted).days if rec.date_submitted else 0
            rec.is_overdue = bool(
                rec.date_required and rec.state in ('draft', 'submitted') and rec.date_required < today)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.rfi') or 'New'
        return super().create(vals_list)

    def action_submit(self):
        self.write({'state': 'submitted'})

    def action_answer(self):
        for rec in self:
            if not rec.answer:
                raise UserError(_('Please enter the answer before marking this RFI as answered.'))
            rec.write({
                'state': 'answered',
                'answered_by': self.env.user.id,
                'date_answered': fields.Date.today(),
            })

    def action_close(self):
        self.write({'state': 'closed'})

    def action_reset_draft(self):
        self.write({'state': 'draft', 'answered_by': False, 'date_answered': False})

    def _cron_remind_overdue_rfis(self):
        overdue = self.search([
            ('state', 'in', ('draft', 'submitted')),
            ('date_required', '!=', False),
            ('date_required', '<', fields.Date.today()),
        ])
        for rec in overdue:
            already = rec.activity_ids.filtered(lambda a: a.summary == _('RFI Overdue'))
            if already:
                continue
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('RFI Overdue'),
                note=_('RFI %s (%s) is overdue for a response — due %s.') % (
                    rec.name, rec.subject, rec.date_required),
            )
