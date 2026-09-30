# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EducationTerm(models.Model):
    _name = 'education.term'
    _description = 'Academic Term'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'academic_year_id, sequence, date_start'

    name = fields.Char(string='Name', required=True, tracking=True)
    academic_year_id = fields.Many2one('education.academic.year', string='Academic Year',
                                        required=True, ondelete='restrict', tracking=True)
    date_start = fields.Date(string='Start Date', required=True)
    date_end = fields.Date(string='End Date', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('closed', 'Closed'),
    ], string='Status', default='draft', tracking=True, required=True)
    notes = fields.Text(string='Notes')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(related='academic_year_id.company_id', store=True, string='Company')
    group_count = fields.Integer(string='Groups Count', compute='_compute_group_count')

    _sql_constraints = [
        ('name_year_uniq', 'unique(name, academic_year_id)',
         'A term with this name already exists for the selected academic year.'),
    ]

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start and rec.date_end and rec.date_start >= rec.date_end:
                raise ValidationError(_('Term "%s": start date must be before end date.') % rec.name)

    @api.constrains('date_start', 'date_end', 'academic_year_id')
    def _check_within_academic_year(self):
        for rec in self:
            year = rec.academic_year_id
            if not year:
                continue
            if rec.date_start and year.date_start and rec.date_start < year.date_start:
                raise ValidationError(_('Term "%s" start date must fall within the academic year dates.') % rec.name)
            if rec.date_end and year.date_end and rec.date_end > year.date_end:
                raise ValidationError(_('Term "%s" end date must fall within the academic year dates.') % rec.name)

    def action_set_active(self):
        self.write({'state': 'active'})

    def action_set_closed(self):
        self.write({'state': 'closed'})

    def action_set_draft(self):
        self.write({'state': 'draft'})

    def _compute_group_count(self):
        Group = self.env['education.group']
        for rec in self:
            rec.group_count = Group.search_count([('term_id', '=', rec.id)])

    def action_view_groups(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'res_model': 'education.group', 'name': _('Groups'),
            'view_mode': 'list,form', 'domain': [('term_id', '=', self.id)],
            'context': {'default_term_id': self.id},
        }
