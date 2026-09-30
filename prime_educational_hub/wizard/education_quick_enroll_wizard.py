# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EducationQuickEnrollWizard(models.TransientModel):
    """One screen instead of three: register the student (or pick an
    existing one), enroll them into a group, and let the enrollment's own
    _ensure_fee_record() generate the Fee/Installments automatically --
    exactly what a receptionist registering a walk-in needs, without
    bouncing between the Students, Enrollments, and Fees menus."""
    _name = 'education.quick.enroll.wizard'
    _description = 'Quick Enroll'

    mode = fields.Selection([
        ('new', 'New Student'),
        ('existing', 'Existing Student'),
    ], string='Student', default='new', required=True)
    existing_student_id = fields.Many2one('education.student', string='Student')

    # New-student fields
    name = fields.Char(string='Full Name')
    phone = fields.Char(string='Phone')
    mobile = fields.Char(string='Mobile')
    whatsapp = fields.Char(string='WhatsApp')
    email = fields.Char(string='Email')
    guardian_id = fields.Many2one('education.guardian', string='Guardian (optional)')

    # Enrollment fields
    group_id = fields.Many2one('education.group', string='Group', required=True,
                                domain="[('state', '=', 'active')]")
    enrollment_date = fields.Date(string='Enrollment Date', default=fields.Date.context_today, required=True)
    fee_plan_id = fields.Many2one('education.fee.plan', string='Fee Plan')
    gross_fee = fields.Monetary(string='Gross Fee (override)', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency',
                                   default=lambda self: self.env.company.currency_id)

    @api.onchange('group_id')
    def _onchange_group_id(self):
        for rec in self:
            if rec.group_id.fee_plan_id and not rec.fee_plan_id:
                rec.fee_plan_id = rec.group_id.fee_plan_id

    def action_confirm(self):
        self.ensure_one()
        if self.mode == 'new' and not self.name:
            raise UserError(_('Please enter the student\'s full name.'))
        if self.mode == 'existing' and not self.existing_student_id:
            raise UserError(_('Please select an existing student.'))

        if self.mode == 'new':
            student = self.env['education.student'].create({
                'name': self.name,
                'phone': self.phone,
                'mobile': self.mobile,
                'whatsapp': self.whatsapp,
                'email': self.email,
                'guardian_ids': [(4, self.guardian_id.id)] if self.guardian_id else False,
            })
        else:
            student = self.existing_student_id

        enrollment_vals = {
            'student_id': student.id,
            'group_id': self.group_id.id,
            'enrollment_date': self.enrollment_date,
        }
        if self.fee_plan_id:
            enrollment_vals['fee_plan_id'] = self.fee_plan_id.id
        if self.gross_fee:
            enrollment_vals['gross_fee'] = self.gross_fee
        enrollment = self.env['education.enrollment'].create(enrollment_vals)
        enrollment.action_set_active()

        return {
            'type': 'ir.actions.act_window',
            'name': _('Student Enrolled'),
            'res_model': 'education.student',
            'view_mode': 'form',
            'res_id': student.id,
        }
