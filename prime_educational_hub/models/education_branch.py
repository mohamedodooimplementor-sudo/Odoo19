# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .education_config_helpers import has_multi_branch


class EducationBranch(models.Model):
    _name = 'education.branch'
    _description = 'Branch / Campus'
    _order = 'name'

    name = fields.Char(string='Branch Name', required=True)
    code = fields.Char(string='Code')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company,
                                  required=True)
    address = fields.Text(string='Address')
    phone = fields.Char(string='Phone')
    manager_id = fields.Many2one('res.users', string='Branch Manager')
    active = fields.Boolean(default=True)

    group_count = fields.Integer(string='Groups', compute='_compute_counts')
    student_count = fields.Integer(string='Students', compute='_compute_counts')
    teacher_count = fields.Integer(string='Teachers', compute='_compute_counts')
    room_count = fields.Integer(string='Rooms', compute='_compute_counts')

    _sql_constraints = [
        ('code_company_uniq', 'unique(code, company_id)', 'Branch code must be unique per company.'),
    ]

    def _compute_counts(self):
        Group = self.env['education.group']
        Student = self.env['education.student']
        Teacher = self.env['education.teacher']
        Room = self.env['education.room']
        for rec in self:
            rec.group_count = Group.search_count([('branch_id', '=', rec.id)])
            rec.student_count = Student.search_count([('branch_id', '=', rec.id)])
            rec.teacher_count = Teacher.search_count([('branch_id', '=', rec.id)])
            rec.room_count = Room.search_count([('branch_id', '=', rec.id)])

    def action_view_groups(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'res_model': 'education.group', 'name': 'Groups',
            'view_mode': 'list,form', 'domain': [('branch_id', '=', self.id)],
        }

    def action_view_students(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'res_model': 'education.student', 'name': 'Students',
            'view_mode': 'list,form', 'domain': [('branch_id', '=', self.id)],
        }

    def action_view_teachers(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'res_model': 'education.teacher', 'name': 'Teachers',
            'view_mode': 'list,form', 'domain': [('branch_id', '=', self.id)],
        }

    def action_view_rooms(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'res_model': 'education.room', 'name': 'Rooms',
            'view_mode': 'kanban,list,form', 'domain': [('branch_id', '=', self.id)],
        }


class EducationGroupBranchMixin(models.Model):
    _inherit = 'education.group'
    branch_id = fields.Many2one('education.branch', string='Branch',
                                 domain="[('company_id', '=', company_id)]")
    show_branch_field = fields.Boolean(compute='_compute_show_branch_field')

    def _compute_show_branch_field(self):
        show = has_multi_branch(self.env)
        for rec in self:
            rec.show_branch_field = show

    @api.constrains('branch_id')
    def _check_branch_required(self):
        if has_multi_branch(self.env):
            for rec in self:
                if not rec.branch_id:
                    raise ValidationError(_('Branch is required once more than one branch is configured.'))


class EducationStudentBranchMixin(models.Model):
    _inherit = 'education.student'
    branch_id = fields.Many2one('education.branch', string='Branch',
                                 domain="[('company_id', '=', company_id)]")
    show_branch_field = fields.Boolean(compute='_compute_show_branch_field')

    def _compute_show_branch_field(self):
        show = has_multi_branch(self.env)
        for rec in self:
            rec.show_branch_field = show

    @api.constrains('branch_id')
    def _check_branch_required(self):
        if has_multi_branch(self.env):
            for rec in self:
                if not rec.branch_id:
                    raise ValidationError(_('Branch is required once more than one branch is configured.'))


class EducationTeacherBranchMixin(models.Model):
    _inherit = 'education.teacher'
    branch_id = fields.Many2one('education.branch', string='Branch',
                                 domain="[('company_id', '=', company_id)]")
    show_branch_field = fields.Boolean(compute='_compute_show_branch_field')

    def _compute_show_branch_field(self):
        show = has_multi_branch(self.env)
        for rec in self:
            rec.show_branch_field = show

    @api.constrains('branch_id')
    def _check_branch_required(self):
        if has_multi_branch(self.env):
            for rec in self:
                if not rec.branch_id:
                    raise ValidationError(_('Branch is required once more than one branch is configured.'))


class EducationSessionBranchMixin(models.Model):
    _inherit = 'education.session'
    branch_id = fields.Many2one(related='group_id.branch_id', string='Branch', store=True)
