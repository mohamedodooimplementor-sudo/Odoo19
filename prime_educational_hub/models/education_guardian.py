# -*- coding: utf-8 -*-
import secrets

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EducationGuardian(models.Model):
    _name = 'education.guardian'
    _description = 'Guardian'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Name', required=True, tracking=True)
    phone = fields.Char(string='Phone')
    mobile = fields.Char(string='Mobile')
    whatsapp = fields.Char(string='WhatsApp')
    email = fields.Char(string='Email')
    address = fields.Text(string='Address')
    occupation = fields.Char(string='Occupation')
    relationship = fields.Selection([
        ('father', 'Father'),
        ('mother', 'Mother'),
        ('brother', 'Brother'),
        ('sister', 'Sister'),
        ('uncle', 'Uncle'),
        ('aunt', 'Aunt'),
        ('grandparent', 'Grandparent'),
        ('other', 'Other'),
    ], string='Relationship', default='father')
    notes = fields.Text(string='Notes')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    student_ids = fields.Many2many('education.student', 'education_student_guardian_rel',
                                    'guardian_id', 'student_id', string='Students')
    student_count = fields.Integer(string='Students Count', compute='_compute_student_count')
    user_id = fields.Many2one('res.users', string='Portal Account', copy=False,
                               help='Authenticated login linked to this guardian, giving them access '
                                    "to their own children's records only.")

    @api.depends('student_ids')
    def _compute_student_count(self):
        for rec in self:
            rec.student_count = len(rec.student_ids)

    def action_view_students(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Students',
            'res_model': 'education.student',
            'view_mode': 'list,form',
            'domain': [('guardian_ids', 'in', self.id)],
        }

    def action_create_portal_account(self):
        """Creates an authenticated login (base.group_portal) linked to this
        guardian, replacing the need for shared/anonymous links. The account
        starts with a random password; use Odoo's standard 'Reset Password'
        action afterward to email the guardian a login link, or share the
        temporary password directly."""
        self.ensure_one()
        if self.user_id:
            raise UserError(_('This guardian already has a portal account (%s).') % self.user_id.login)
        if not self.email:
            raise UserError(_('An email address is required to create a portal account.'))
        existing = self.env['res.users'].sudo().search([('login', '=', self.email)], limit=1)
        if existing:
            raise UserError(_('A user with the login "%s" already exists.') % self.email)

        portal_group = self.env.ref('base.group_portal')
        user = self.env['res.users'].sudo().create({
            'name': self.name,
            'login': self.email,
            'email': self.email,
            'password': secrets.token_urlsafe(12),
            'group_ids': [(6, 0, [portal_group.id])],
        })
        self.user_id = user.id
        return {
            'type': 'ir.actions.act_window',
            'name': _('Portal User'),
            'res_model': 'res.users',
            'view_mode': 'form',
            'res_id': user.id,
        }

    def action_revoke_portal_account(self):
        self.ensure_one()
        if self.user_id:
            self.user_id.sudo().write({'active': False})
            self.user_id = False
