# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EducationAcademicYear(models.Model):
    _name = 'education.academic.year'
    _description = 'Academic Year'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc'

    name = fields.Char(string='Name', required=True, tracking=True)
    code = fields.Char(string='Code')
    date_start = fields.Date(string='Start Date', required=True, tracking=True)
    date_end = fields.Date(string='End Date', required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', tracking=True, required=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    notes = fields.Text(string='Notes')

    term_ids = fields.One2many('education.term', 'academic_year_id', string='Terms')
    term_count = fields.Integer(string='Terms Count', compute='_compute_term_count')
    group_ids = fields.One2many('education.group', 'academic_year_id', string='Groups')
    group_count = fields.Integer(string='Groups Count', compute='_compute_group_count')

    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_uniq', 'unique(code, company_id)', 'Academic Year code must be unique per company.'),
    ]

    @api.depends('term_ids')
    def _compute_term_count(self):
        for rec in self:
            rec.term_count = len(rec.term_ids)

    @api.depends('group_ids')
    def _compute_group_count(self):
        for rec in self:
            rec.group_count = len(rec.group_ids)

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_start >= rec.date_end:
                raise ValidationError(_('Academic Year "%s": start date must be before end date.') % rec.name)

    def action_set_active(self):
        self.write({'state': 'active'})

    def action_set_closed(self):
        self.write({'state': 'closed'})

    def action_set_draft(self):
        self.write({'state': 'draft'})

    def action_view_terms(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Terms'),
            'res_model': 'education.term',
            'view_mode': 'list,form',
            'domain': [('academic_year_id', '=', self.id)],
            'context': {'default_academic_year_id': self.id},
        }

    def action_view_groups(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Groups'),
            'res_model': 'education.group',
            'view_mode': 'list,form',
            'domain': [('academic_year_id', '=', self.id)],
            'context': {'default_academic_year_id': self.id},
        }


