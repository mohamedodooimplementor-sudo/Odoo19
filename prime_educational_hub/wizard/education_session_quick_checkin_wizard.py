# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EducationSessionQuickCheckinWizard(models.TransientModel):
    """A fast, PIN-free way for logged-in staff to mark a student present:
    scan/type the student code, hit Enter, done. The PIN exists to prove
    identity on the PUBLIC self-check-in page where nobody is logged in --
    it adds nothing here since the staff member's own Odoo login is already
    the identity check. Stays open after each check-in (clearing the code
    field) so a receptionist can scan an ID badge after badge after badge
    without reopening the wizard."""
    _name = 'education.session.quick_checkin.wizard'
    _description = 'Quick Check-in (Code Only)'

    session_id = fields.Many2one('education.session', string='Session', required=True)
    student_code = fields.Char(string='Student Code', help='Type or scan the student code, then press Enter.')
    last_checked_in_name = fields.Char(string='Last Checked In', readonly=True)

    def action_check_in(self):
        self.ensure_one()
        code = (self.student_code or '').strip()
        if not code:
            raise UserError(_('Scan or type a student code first.'))

        student = self.env['education.student'].search([('student_code', '=', code)], limit=1)
        if not student:
            raise UserError(_('No student found with code "%s".') % code)

        active_students = self.session_id.group_id.enrollment_ids.filtered(
            lambda e: e.state == 'active').student_id
        if student not in active_students:
            raise UserError(_(
                '"%s" is not actively enrolled in "%s", so they can\'t be checked into this session.'
            ) % (student.name, self.session_id.group_id.name))

        Attendance = self.env['education.attendance']
        existing = Attendance.search([
            ('session_id', '=', self.session_id.id), ('student_id', '=', student.id),
        ], limit=1)
        if existing:
            existing.status = 'present'
        else:
            Attendance.create({
                'session_id': self.session_id.id,
                'student_id': student.id,
                'status': 'present',
                'check_in': fields.Datetime.now(),
            })

        if self.session_id.state == 'planned':
            self.session_id.state = 'open'

        # Re-open the same wizard, cleared and ready for the next scan --
        # this is what makes rapid-fire check-ins practical.
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'education.session.quick_checkin.wizard',
            'view_mode': 'form',
            'target': 'new',
            'name': _('Quick Check-in -- %s') % self.session_id.group_id.name,
            'context': {
                'default_session_id': self.session_id.id,
                'default_last_checked_in_name': _('✓ %s') % student.name,
            },
        }
