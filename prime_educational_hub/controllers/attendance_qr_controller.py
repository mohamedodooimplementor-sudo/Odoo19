# -*- coding: utf-8 -*-
"""Public, no-Odoo-user self check-in flow.

Flow: Teacher generates a time-limited QR on the Session form -> student
scans it with a phone browser -> lands here with ?token=... -> student
proves identity with Student Code + personal PIN -> server validates
token/window/enrollment/duplicate -> attendance record created.

The student is NEVER an Odoo user (auth='public' throughout); all writes
happen through education.attendance.register_self_checkin() using sudo().
"""
import logging

from odoo import http, fields
from odoo.http import request

from ..models.education_config_helpers import is_pin_required_for_checkin

_logger = logging.getLogger(__name__)

ERROR_MESSAGES = {
    'invalid_qr': ('QR Code Not Found', 'رمز الحضور غير صالح. اطلب من المعلّم عرض QR جديد.'),
    'qr_expired': ('QR Code Expired', 'انتهت صلاحية رمز الحضور لهذه الحصة. اطلب من المعلّم توليد رمز جديد.'),
    'qr_disabled': ('QR Check-in Disabled', 'تسجيل الحضور عبر QR غير مفعل لهذه الحصة. برجاء إبلاغ المعلّم لتسجيل حضورك يدويًا.'),
    'student_not_found': ('Student Not Found', 'كود الطالب غير موجود. تأكد من الكود وحاول مرة أخرى.'),
    'invalid_pin': ('Invalid Student Code or PIN', 'كود الطالب أو الرقم السري غير صحيح.'),
    'pin_locked': ('Too Many Failed Attempts', 'تم قفل الدخول مؤقتًا بسبب محاولات خاطئة متكررة. حاول مرة أخرى بعد قليل أو راجع المعلّم.'),
    'not_enrolled': ('Not Enrolled In This Session', 'أنت غير مسجّل في هذه الحصة.'),
    'window_closed': ('Attendance Window Closed', 'انتهى الوقت المسموح به لتسجيل الحضور لهذه الحصة.'),
    'already_registered': ('Attendance Already Registered', 'تم تسجيل حضورك بالفعل لهذه الحصة.'),
    'registration_failed': ('Registration Failed', 'حدث خطأ أثناء تسجيل الحضور. برجاء إبلاغ المعلّم لتسجيل حضورك يدويًا.'),
    'rate_limited': ('Too Many Attempts', 'محاولات كثيرة جدًا. حاول مرة أخرى بعد قليل.'),
}

STATUS_LABELS = {
    'present': ('Present', 'حاضر'),
    'late': ('Late', 'متأخر'),
}


class EducationAttendanceQRController(http.Controller):

    def _client_ip(self):
        return request.httprequest.headers.get('X-Forwarded-For', request.httprequest.remote_addr)

    def _device_info(self):
        return request.httprequest.headers.get('User-Agent', '')

    @http.route(['/education/attendance'], type='http', auth='public', website=False, methods=['GET'], csrf=False)
    def attendance_scan(self, token=None, **kwargs):
        if not token:
            return request.render('prime_educational_hub.attendance_error_page',
                                   {'error_en': 'Missing QR Code', 'error_ar': 'رابط غير صالح — لا يوجد رمز QR.'})

        session = request.env['education.session'].sudo().search([('qr_token', '=', token)], limit=1)
        if not session:
            _logger.warning(
                'Attendance QR scan: no session found for token=%r (checked as of %s). '
                'This means either the token was regenerated/revoked after this QR was '
                'created, the session was deleted, or the URL/token was copied incorrectly.',
                token, fields.Datetime.now())
            en, ar = ERROR_MESSAGES['invalid_qr']
            return request.render('prime_educational_hub.attendance_error_page',
                                   {'error_en': en, 'error_ar': ar})
        if session.qr_token_expiry and fields.Datetime.now() > session.qr_token_expiry:
            _logger.info(
                'Attendance QR scan: token=%r matched session id=%s (%s) but expired at %s '
                '(now=%s).', token, session.id, session.name, session.qr_token_expiry, fields.Datetime.now())
            en, ar = ERROR_MESSAGES['qr_expired']
            return request.render('prime_educational_hub.attendance_error_page',
                                   {'error_en': en, 'error_ar': ar})

        return request.render('prime_educational_hub.attendance_identify_page', {
            'token': token,
            'session': session,
            'csrf_token': request.csrf_token(),
            'pin_required': is_pin_required_for_checkin(request.env),
        })

    @http.route(['/education/attendance/submit'], type='http', auth='public', website=False,
                methods=['POST'], csrf=True)
    def attendance_submit(self, token=None, student_code=None, pin=None, **kwargs):
        ip = self._client_ip()
        AccessLog = request.env['education.public.access.log'].sudo()
        if not AccessLog.check_rate_limit(ip, 'attendance', max_requests=20, window_minutes=15):
            en, ar = ERROR_MESSAGES['rate_limited']
            return request.render('prime_educational_hub.attendance_result_page',
                                   {'ok': False, 'error_en': en, 'error_ar': ar})

        result = request.env['education.attendance'].sudo().register_self_checkin(
            token=token, student_code=student_code, pin=pin,
            ip_address=ip, device_info=self._device_info(),
        )
        AccessLog.log_access(ip, 'attendance', token, result.get('ok', False))

        if not result.get('ok'):
            en, ar = ERROR_MESSAGES.get(result.get('error'), ('Error', 'حدث خطأ غير متوقع.'))
            return request.render('prime_educational_hub.attendance_result_page',
                                   {'ok': False, 'error_en': en, 'error_ar': ar, 'token': token})

        status_en, status_ar = STATUS_LABELS.get(result['status'], (result['status'], result['status']))
        return request.render('prime_educational_hub.attendance_result_page', {
            'ok': True,
            'student_name': result['student_name'],
            'session_name': result['session_name'],
            'group_name': result['group_name'],
            'subject_name': result['subject_name'],
            'status_en': status_en,
            'status_ar': status_ar,
            'check_in': result['check_in'],
        })
