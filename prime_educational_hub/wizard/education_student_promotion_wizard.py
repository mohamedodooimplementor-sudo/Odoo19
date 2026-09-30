# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EducationStudentPromotionWizard(models.TransientModel):
    _name = 'education.student.promotion.wizard'
    _description = 'Student Promotion / Transfer Wizard'

    student_ids = fields.Many2many('education.student', string='Students', required=True)
    target_academic_year_id = fields.Many2one('education.academic.year', string='Target Academic Year')
    target_group_id = fields.Many2one('education.group', string='Target Group')
    target_grade_level_id = fields.Many2one('education.level', string='Target Grade Level')
    close_current_enrollments = fields.Boolean(
        string='Complete Current Active Enrollments', default=True,
        help='Marks each student\'s current active enrollment(s) as Completed before moving them.')
    reason = fields.Text(string='Reason', required=True,
                          help='e.g. "Promoted to next grade", "Transferred to evening group"')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_ids = self.env.context.get('active_ids')
        if active_ids and self.env.context.get('active_model') == 'education.student':
            res['student_ids'] = [(6, 0, active_ids)]
        return res

    def action_confirm(self):
        self.ensure_one()
        if not self.target_group_id and not self.target_grade_level_id:
            raise UserError(_('Choose at least a target group or a target grade level.'))

        Enrollment = self.env['education.enrollment']
        new_enrollments = self.env['education.enrollment']

        for student in self.student_ids:
            if self.close_current_enrollments:
                active_enrollments = student.enrollment_ids.filtered(lambda e: e.state == 'active')
                for enr in active_enrollments:
                    enr.write({'end_reason': self.reason})
                    enr.action_set_completed()

            if self.target_grade_level_id:
                student.write({'grade_level_id': self.target_grade_level_id.id})

            if self.target_group_id:
                new_enrollment = Enrollment.create({
                    'student_id': student.id,
                    'group_id': self.target_group_id.id,
                    'notes': _('Promoted/transferred: %s') % self.reason,
                })
                new_enrollments |= new_enrollment

        message = _('%d student(s) processed.') % len(self.student_ids)
        if new_enrollments:
            message += _(' %d new draft enrollment(s) created — review and activate them.') % len(new_enrollments)
            return {
                'type': 'ir.actions.act_window',
                'name': _('New Enrollments'),
                'res_model': 'education.enrollment',
                'view_mode': 'list,form',
                'domain': [('id', 'in', new_enrollments.ids)],
            }
        return {'type': 'ir.actions.act_window_close'}
