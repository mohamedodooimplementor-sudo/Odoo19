# -*- coding: utf-8 -*-
from odoo import http, fields
from odoo.http import request


class EducationTeacherPortalController(http.Controller):

    def _current_teacher(self):
        """The education.teacher record linked to the logged-in user, or an
        empty recordset if this user isn't a teacher. Every route below
        scopes to this so a teacher can only ever see their own data - there
        is no id in the URL to tamper with."""
        return request.env['education.teacher'].sudo().search([
            ('user_id', '=', request.env.user.id),
        ], limit=1)

    def _no_access_page(self):
        return request.render('prime_educational_hub.teacher_portal_no_access')

    @http.route(['/education/teacher/portal'], type='http', auth='user', website=False)
    def teacher_portal_home(self, **kwargs):
        teacher = self._current_teacher()
        if not teacher:
            return self._no_access_page()
        today = fields.Date.context_today(request.env['education.teacher'])
        upcoming_sessions = request.env['education.session'].sudo().search([
            ('teacher_id', '=', teacher.id),
            ('date', '>=', today),
            ('state', 'in', ('planned', 'open')),
        ], order='date, start_datetime', limit=20)
        pending_payouts = request.env['education.teacher.payout'].sudo().search([
            ('teacher_id', '=', teacher.id),
            ('state', '!=', 'paid'),
        ], order='date desc')
        recent_payouts = request.env['education.teacher.payout'].sudo().search([
            ('teacher_id', '=', teacher.id), ('state', '=', 'paid'),
        ], order='date desc', limit=10)
        leave_requests = request.env['education.teacher.leave.request'].sudo().search([
            ('teacher_id', '=', teacher.id),
        ], order='date_from desc', limit=20)
        return request.render('prime_educational_hub.teacher_portal_home', {
            'teacher': teacher,
            'sessions': upcoming_sessions,
            'pending_payouts': pending_payouts,
            'recent_payouts': recent_payouts,
            'leave_requests': leave_requests,
        })

    @http.route(['/education/teacher/leave/new'], type='http', auth='user', website=False, methods=['POST'], csrf=True)
    def teacher_leave_new(self, **kwargs):
        teacher = self._current_teacher()
        if not teacher:
            return self._no_access_page()
        date_from = kwargs.get('date_from')
        date_to = kwargs.get('date_to')
        reason = kwargs.get('reason')
        if date_from and date_to:
            request.env['education.teacher.leave.request'].sudo().create({
                'teacher_id': teacher.id,
                'date_from': date_from,
                'date_to': date_to,
                'reason': reason,
            })
        return request.redirect('/education/teacher/portal')
