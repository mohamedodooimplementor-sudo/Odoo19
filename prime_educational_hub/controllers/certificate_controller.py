# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class EducationCertificateController(http.Controller):

    def _client_ip(self):
        return request.httprequest.headers.get('X-Forwarded-For', request.httprequest.remote_addr)

    @http.route(['/education/certificate/verify/<string:token>'], type='http', auth='public', website=False)
    def verify_certificate(self, token, **kwargs):
        ip = self._client_ip()
        AccessLog = request.env['education.public.access.log'].sudo()
        if not AccessLog.check_rate_limit(ip, 'certificate'):
            return request.render('prime_educational_hub.certificate_verification_page',
                                   {'data': {'found': False}})
        enabled = request.env['ir.config_parameter'].sudo().get_param(
            'prime_educational_hub.certificate_verification_enabled', 'True')
        if enabled in ('False', '0', 'false', False):
            AccessLog.log_access(ip, 'certificate', token, False)
            return request.render('prime_educational_hub.certificate_verification_page',
                                   {'data': {'found': False}})
        data = request.env['education.certificate'].sudo().get_public_verification_data(token)
        AccessLog.log_access(ip, 'certificate', token, bool(data.get('found')))
        return request.render('prime_educational_hub.certificate_verification_page', {'data': data})

    @http.route(['/education/portal/student/<string:token>'], type='http', auth='public', website=False)
    def student_portal(self, token, **kwargs):
        ip = self._client_ip()
        AccessLog = request.env['education.public.access.log'].sudo()
        if not AccessLog.check_rate_limit(ip, 'portal'):
            return request.render('prime_educational_hub.student_portal_page', {'data': {'found': False}})
        enabled = request.env['ir.config_parameter'].sudo().get_param(
            'prime_educational_hub.student_portal_enabled', 'True')
        if enabled in ('False', '0', 'false', False):
            AccessLog.log_access(ip, 'portal', token, False)
            return request.render('prime_educational_hub.student_portal_page', {'data': {'found': False}})
        data = request.env['education.student'].sudo().get_public_portal_data(token)
        AccessLog.log_access(ip, 'portal', token, bool(data.get('found')))
        return request.render('prime_educational_hub.student_portal_page', {'data': data})

    @http.route(['/education/portal/student/<string:token>/feedback'], type='http', auth='public',
                website=False, methods=['POST'], csrf=True)
    def student_portal_feedback(self, token, **kwargs):
        ip = self._client_ip()
        AccessLog = request.env['education.public.access.log'].sudo()
        student = request.env['education.student'].sudo().search([('portal_token', '=', token)], limit=1)
        if AccessLog.check_rate_limit(ip, 'portal'):
            rating = kwargs.get('rating')
            if student and rating in ('1', '2', '3', '4', '5'):
                request.env['education.feedback'].sudo().create({
                    'student_id': student.id,
                    'rating': rating,
                    'comment': kwargs.get('comment'),
                    'context_label': kwargs.get('context_label') or '',
                    'source': 'portal',
                })
        AccessLog.log_access(ip, 'portal', token, bool(student))
        return request.redirect('/education/portal/student/%s?feedback=1' % token)

