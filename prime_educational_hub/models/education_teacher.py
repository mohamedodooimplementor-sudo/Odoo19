# -*- coding: utf-8 -*-
import re

from odoo import api, fields, models, _


class EducationTeacher(models.Model):
    _name = 'education.teacher'
    _description = 'Teacher'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _rec_name = 'name'

    teacher_code = fields.Char(string='Teacher Code', copy=False, readonly=True,
                                default='New', tracking=True)
    name = fields.Char(string='Full Name', required=True, tracking=True)
    photo = fields.Image(string='Photo', max_width=1024, max_height=1024)
    phone = fields.Char(string='Phone')
    mobile = fields.Char(string='Mobile')
    whatsapp = fields.Char(string='WhatsApp')
    email = fields.Char(string='Email')
    subject_ids = fields.Many2many('education.subject', string='Subjects Taught')
    notes = fields.Text(string='Notes')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='Currency', related='company_id.currency_id')

    compensation_type = fields.Selection([
        ('none', 'None'),
        ('per_session', 'Per Session'),
        ('percentage', '% of Fees Collected (Their Groups)'),
        ('fixed', 'Fixed Monthly Salary'),
    ], string='Compensation Type', default='none', tracking=True)
    rate_per_session = fields.Monetary(string='Rate per Session', tracking=True)
    commission_percentage = fields.Float(string='Commission %', tracking=True)
    fixed_salary = fields.Monetary(string='Fixed Monthly Salary', tracking=True)
    payout_ids = fields.One2many('education.teacher.payout', 'teacher_id', string='Payouts')
    payout_count = fields.Integer(string='Payouts Count', compute='_compute_payout_count')
    leave_request_ids = fields.One2many('education.teacher.leave.request', 'teacher_id', string='Leave Requests')
    leave_request_count = fields.Integer(string='Leave Requests Count', compute='_compute_leave_request_count')

    # A teacher does NOT need to be an Odoo user -- this record is pure
    # master data (name, contact info, subjects). Only link a System User
    # for the subset of teachers who actually need to log in themselves
    # (e.g. to take their own attendance via the app, or use the portal).
    user_id = fields.Many2one(
        'res.users', string='System User', copy=False,
        help='Optional. Link an Odoo user account only if this teacher needs to log in '
             'themselves. Leave empty for teachers who are just master data -- staff will '
             'record their sessions/attendance on their behalf.')
    has_system_access = fields.Boolean(string='Has System Access', compute='_compute_has_system_access', store=True)

    group_ids = fields.One2many('education.group', 'teacher_id', string='Groups (as Permanent Teacher)')
    group_count = fields.Integer(string='Groups Count', compute='_compute_group_and_session_stats')
    session_count = fields.Integer(
        string='Sessions Count', compute='_compute_group_and_session_stats',
        help='Total sessions across all of this teacher\'s groups, as permanent teacher or substitute.')
    session_completed_count = fields.Integer(string='Completed Sessions', compute='_compute_group_and_session_stats')

    _sql_constraints = [
        ('teacher_code_uniq', 'unique(teacher_code, company_id)', 'Teacher code must be unique.'),
        ('user_id_uniq', 'unique(user_id)', 'This system user is already linked to another teacher.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('teacher_code', 'New') == 'New':
                vals['teacher_code'] = self.env['ir.sequence'].next_by_code('education.teacher') or 'New'
        return super().create(vals_list)

    @api.depends('user_id')
    def _compute_has_system_access(self):
        for rec in self:
            rec.has_system_access = bool(rec.user_id)

    def _compute_group_and_session_stats(self):
        Session = self.env['education.session'].sudo()
        for rec in self:
            rec.group_count = len(rec.group_ids)
            sessions = Session.search([('teacher_id', '=', rec.id)])
            rec.session_count = len(sessions)
            rec.session_completed_count = len(sessions.filtered(lambda s: s.state == 'completed'))

    def _compute_payout_count(self):
        for rec in self:
            rec.payout_count = len(rec.payout_ids)

    @api.depends('leave_request_ids')
    def _compute_leave_request_count(self):
        for rec in self:
            rec.leave_request_count = len(rec.leave_request_ids)

    def action_view_leave_requests(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Leave Requests -- %s') % self.name,
            'res_model': 'education.teacher.leave.request',
            'view_mode': 'list,form',
            'domain': [('teacher_id', '=', self.id)],
            'context': {'default_teacher_id': self.id},
        }

    def action_view_payouts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Payouts -- %s') % self.name,
            'res_model': 'education.teacher.payout',
            'view_mode': 'list,form',
            'domain': [('teacher_id', '=', self.id)],
            'context': {'default_teacher_id': self.id},
        }

    def _get_whatsapp_number(self):
        """Digits-only WhatsApp/mobile number for this teacher, for wa.me links."""
        self.ensure_one()
        raw = self.whatsapp or self.mobile or self.phone
        if not raw:
            return False
        return re.sub(r'\D', '', raw)

    def action_view_groups(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Groups -- %s') % self.name,
            'res_model': 'education.group',
            'view_mode': 'list,form',
            'domain': [('teacher_id', '=', self.id)],
        }

    def action_view_sessions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sessions -- %s') % self.name,
            'res_model': 'education.session',
            'view_mode': 'list,calendar,form',
            'domain': [('teacher_id', '=', self.id)],
            'context': {'search_default_group_by_group': 1},
        }
