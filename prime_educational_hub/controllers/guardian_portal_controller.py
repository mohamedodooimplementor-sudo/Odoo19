# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class EducationGuardianPortalController(http.Controller):

    def _linked_students(self):
        """Students where the currently logged-in user is a linked guardian."""
        return request.env['education.student'].sudo().search([
            ('guardian_ids.user_id', '=', request.env.user.id),
        ])

    @http.route(['/education/my/children'], type='http', auth='user', website=False)
    def my_children(self, **kwargs):
        students = self._linked_students()
        rows = ''.join(
            '<li><a href="/education/my/student/%d">%s</a></li>' % (s.id, s.name) for s in students
        )
        html = (
            '<html><head><meta charset="utf-8"/><title>My Children</title>'
            '<style>body{font-family:sans-serif;padding:30px;} a{color:#2980b9;text-decoration:none;} '
            'li{margin:8px 0;font-size:15px;} .brand{text-align:center;margin-bottom:18px;} '
            '.brand img{width:56px;height:56px;border-radius:14px;box-shadow:0 4px 14px rgba(0,0,0,0.12);} '
            '.brand h3{margin:8px 0 0;font-size:15px;color:#2c3e50;}</style></head><body>'
            '<div class="brand"><img src="/prime_educational_hub/static/description/icon.png" alt="Prime Educational Hub"/>'
            '<h3>Prime Educational Hub</h3></div>'
            '<h2>My Children</h2><ul>%s</ul>'
            '%s'
            '</body></html>'
        ) % (rows, '' if students else '<p>No students are linked to your account yet.</p>')
        return request.make_response(html, headers=[('Content-Type', 'text/html')])

    @http.route(['/education/my/student/<int:student_id>'], type='http', auth='user', website=False)
    def my_student(self, student_id, **kwargs):
        allowed = self._linked_students().filtered(lambda s: s.id == student_id)
        if not allowed:
            return request.not_found()
        token = allowed.portal_token
        if not token:
            allowed.sudo().action_generate_portal_link()
            token = allowed.portal_token
        data = request.env['education.student'].sudo().get_public_portal_data(token)
        return request.render('prime_educational_hub.student_portal_page', {'data': data})
