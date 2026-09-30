# -*- coding: utf-8 -*-
import random
import re
import uuid
from datetime import timedelta
from urllib.parse import quote

from werkzeug.security import generate_password_hash, check_password_hash

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EducationStudent(models.Model):
    _name = 'education.student'
    _description = 'Student'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'
    _rec_name = 'name'

    student_code = fields.Char(string='Student Code', copy=False, readonly=True,
                                default='New', tracking=True)
    name = fields.Char(string='Full Name', required=True, tracking=True)
    photo = fields.Image(string='Photo', max_width=1024, max_height=1024)
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
    ], string='Gender')
    date_of_birth = fields.Date(string='Date of Birth')
    age = fields.Integer(string='Age', compute='_compute_age')
    phone = fields.Char(string='Phone')
    mobile = fields.Char(string='Mobile')
    whatsapp = fields.Char(string='WhatsApp')
    quick_lookup = fields.Char(string='Phone / Code (any)', compute='_compute_quick_lookup',
                                help='Search-only field: matches student code, phone, mobile, or WhatsApp '
                                     'in one box. Never actually stored or displayed.')
    email = fields.Char(string='Email')
    address = fields.Text(string='Address')

    guardian_ids = fields.Many2many('education.guardian', 'education_student_guardian_rel',
                                     'student_id', 'guardian_id', string='Guardians')
    guardian_count = fields.Integer(string='Guardians Count', compute='_compute_guardian_count')

    school = fields.Char(string='Previous / Current School')
    grade_level_id = fields.Many2one('education.level', string='Grade Level')
    registration_date = fields.Date(string='Registration Date', default=fields.Date.context_today)
    state = fields.Selection([
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('graduated', 'Graduated'),
        ('suspended', 'Suspended'),
    ], string='Status', default='active', tracking=True, required=True)
    notes = fields.Text(string='Notes')
    active = fields.Boolean(default=True)

    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    enrollment_ids = fields.One2many('education.enrollment', 'student_id', string='Enrollments')
    enrollment_count = fields.Integer(string='Enrollments Count', compute='_compute_enrollment_count')
    active_group_ids = fields.Many2many('education.group', string='Active Groups',
                                         compute='_compute_active_groups')
    active_group_count = fields.Integer(string='Active Groups Count', compute='_compute_active_groups')
    waitlist_ids = fields.One2many('education.group.waitlist', 'student_id', string='Waiting List Entries')

    attendance_ids = fields.One2many('education.attendance', 'student_id', string='Attendance Records')
    attendance_percentage = fields.Float(string='Overall Attendance %', compute='_compute_attendance_percentage')
    session_count = fields.Integer(string='Sessions Count', compute='_compute_attendance_percentage')

    exam_result_ids = fields.One2many('education.exam.result', 'student_id', string='Exam Results')
    exam_average_percentage = fields.Float(string='Exam Average %', compute='_compute_exam_stats')
    exam_count = fields.Integer(string='Exams Count', compute='_compute_exam_stats')

    submission_ids = fields.One2many('education.assignment.submission', 'student_id', string='Assignment Submissions')
    submission_completion_percentage = fields.Float(string='Assignment Completion %',
                                                     compute='_compute_submission_stats')

    payment_ids = fields.One2many('education.payment', 'student_id', string='Payments')
    fee_ids = fields.One2many('education.fee', 'student_id', string='Fees')
    refund_ids = fields.One2many('education.refund', 'student_id', string='Refunds')
    total_net_fee = fields.Monetary(string='Total Fees', compute='_compute_financial_summary',
                                     currency_field='currency_id')
    total_paid = fields.Monetary(string='Total Paid', compute='_compute_financial_summary',
                                  currency_field='currency_id')
    total_refunded = fields.Monetary(string='Total Refunded', compute='_compute_financial_summary',
                                      currency_field='currency_id')
    total_outstanding = fields.Monetary(string='Total Outstanding', compute='_compute_financial_summary',
                                         currency_field='currency_id')
    overdue_installment_count = fields.Integer(string='Overdue Installments', compute='_compute_overdue_installments')
    currency_id = fields.Many2one('res.currency', string='Currency',
                                   default=lambda self: self.env.company.currency_id)

    certificate_ids = fields.One2many('education.certificate', 'student_id', string='Certificates')
    certificate_count = fields.Integer(string='Certificates Count', compute='_compute_certificate_count')
    refund_count = fields.Integer(string='Refunds Count', compute='_compute_refund_count')

    portal_token = fields.Char(string='Portal Token', copy=False, readonly=True)
    portal_url = fields.Char(string='Portal Link', compute='_compute_portal_url')

    # --- QR Self-Attendance (no Odoo user needed) --------------------------
    # The student never gets an Odoo login. Identity for self check-in via
    # QR is proven with Student Code + a personal PIN (hashed, never stored
    # or shown in clear text after generation).
    attendance_pin_hash = fields.Char(string='Attendance PIN Hash', copy=False,
                                       groups='prime_educational_hub.group_education_admin,'
                                              'prime_educational_hub.group_education_supervisor')
    attendance_pin_set = fields.Boolean(string='PIN Set', compute='_compute_attendance_pin_set')
    attendance_pin_plain = fields.Char(
        string='Attendance PIN', store=False, copy=False,
        help='In-memory only, right after a PIN is generated (on creation, or via "Generate/Reset '
             'Attendance PIN") — feeds attendance_pin_display below, never stored anywhere in '
             'plain text, and gone again on the next reload.')
    attendance_pin_display = fields.Char(
        string='QR Attendance PIN Set', compute='_compute_attendance_pin_display',
        help='Shows the actual PIN the moment it\'s generated (copy it now — this is the only '
             'chance). Once you reload, it just confirms a PIN is set without revealing it, '
             'since only its hash is ever stored.')
    attendance_pin_failed_attempts = fields.Integer(
        string='PIN Failed Attempts', default=0, copy=False,
        groups='prime_educational_hub.group_education_admin,'
               'prime_educational_hub.group_education_supervisor')
    attendance_pin_locked_until = fields.Datetime(
        string='PIN Locked Until', copy=False,
        groups='prime_educational_hub.group_education_admin,'
               'prime_educational_hub.group_education_supervisor')

    # NOTE: Progress Timeline (custom addition) — the unified view will combine
    # attendance % (now available), exam results and payment history once
    # Exams and Fees models are introduced in later phases.

    # --- Consolidated summary placeholders ---------------------------------
    # These KPI fields are wired up once the related modules (Enrollment,
    # Attendance, Exam Result, Fee/Payment) are introduced in later phases.
    # They are declared here (Phase 1) so the Student form/summary layout is
    # stable, and implemented with real compute logic in their own phases.

    _sql_constraints = [
        ('student_code_uniq', 'unique(student_code, company_id)', 'Student code must be unique.'),
        ('portal_token_uniq', 'unique(portal_token)', 'Portal token must be unique.'),
    ]

    @api.depends('attendance_ids.status')
    def _compute_attendance_percentage(self):
        exclude_excused = self.env['ir.config_parameter'].sudo().get_param(
            'prime_educational_hub.attendance_excused_excluded')
        for rec in self:
            lines = rec.attendance_ids
            excused = len(lines.filtered(lambda a: a.status == 'excused'))
            total = len(lines) - (excused if exclude_excused else 0)
            counted_present = len(lines.filtered(lambda a: a.status in ('present', 'late')))
            rec.attendance_percentage = (counted_present / total * 100.0) if total else 0.0
            rec.session_count = len(lines)

    @api.depends('exam_result_ids.percentage')
    def _compute_exam_stats(self):
        for rec in self:
            results = rec.exam_result_ids
            rec.exam_count = len(results)
            rec.exam_average_percentage = (sum(results.mapped('percentage')) / len(results)) if results else 0.0

    @api.depends('submission_ids.status')
    def _compute_submission_stats(self):
        for rec in self:
            lines = rec.submission_ids
            submitted = lines.filtered(lambda s: s.status in ('submitted', 'late'))
            rec.submission_completion_percentage = (len(submitted) / len(lines) * 100.0) if lines else 0.0

    @api.depends('enrollment_ids.net_fee', 'enrollment_ids.paid_amount',
                 'enrollment_ids.refunded_amount', 'enrollment_ids.outstanding_amount')
    def _compute_financial_summary(self):
        for rec in self:
            enrollments = rec.enrollment_ids
            rec.total_net_fee = sum(enrollments.mapped('net_fee'))
            rec.total_paid = sum(enrollments.mapped('paid_amount'))
            rec.total_refunded = sum(enrollments.mapped('refunded_amount'))
            rec.total_outstanding = sum(enrollments.mapped('outstanding_amount'))

    def _compute_overdue_installments(self):
        Installment = self.env['education.installment'].sudo()
        for rec in self:
            rec.overdue_installment_count = Installment.search_count([
                ('student_id', '=', rec.id), ('state', '=', 'overdue'),
            ])

    @api.depends('certificate_ids')
    def _compute_certificate_count(self):
        for rec in self:
            rec.certificate_count = len(rec.certificate_ids)

    def _compute_quick_lookup(self):
        # Search-only proxy field (see filter_domain on the search view) -- never
        # meant to hold or display a real value.
        for rec in self:
            rec.quick_lookup = False

    @api.depends('refund_ids')
    def _compute_refund_count(self):
        for rec in self:
            rec.refund_count = len(rec.refund_ids)

    @api.depends('portal_token')
    def _compute_portal_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for rec in self:
            rec.portal_url = '%s/education/portal/student/%s' % (base_url, rec.portal_token) \
                if rec.portal_token else False

    def action_generate_portal_link(self):
        for rec in self:
            if not rec.portal_token:
                rec.portal_token = uuid.uuid4().hex
        if len(self) == 1:
            return {
                'type': 'ir.actions.act_url',
                'url': self.portal_url,
                'target': 'new',
            }

    @api.depends('attendance_pin_hash')
    def _compute_attendance_pin_set(self):
        for rec in self:
            rec.attendance_pin_set = bool(rec.attendance_pin_hash)

    def _compute_attendance_pin_display(self):
        for rec in self:
            if rec.attendance_pin_plain:
                rec.attendance_pin_display = rec.attendance_pin_plain
            elif rec.attendance_pin_hash:
                rec.attendance_pin_display = _('Set (hidden)')
            else:
                rec.attendance_pin_display = _('Not Set')

    def _generate_unique_attendance_pin(self):
        """Picks a 4-digit PIN that isn't already in use by another active
        student in the same company, so two students never share a PIN.
        Hashes are one-way, so we can't look up collisions directly -- we
        generate a candidate and check it against every other student's
        stored hash instead. The 4-digit space is only 10,000 values, so
        this is cheap even fully populated."""
        others = self.sudo().search([
            ('company_id', '=', self.company_id.id),
            ('id', '!=', self.id),
            ('attendance_pin_hash', '!=', False),
        ])
        for _attempt in range(200):
            candidate = '%04d' % random.randint(0, 9999)
            if not any(check_password_hash(o.attendance_pin_hash, candidate) for o in others):
                return candidate
        # Extremely unlikely fallback: the whole 4-digit space is exhausted.
        raise UserError(_('Could not generate a unique PIN. Please try again.'))

    def _set_new_attendance_pin(self):
        """Generates a fresh, unique 4-digit PIN and stores only its hash,
        setting attendance_pin_plain in-memory so it shows up, copyable, the
        moment the record is (re)displayed after this — the ONLY point the
        plaintext PIN ever exists outside a hash. Returns the plaintext PIN
        too, for the sticky-notification flow on manual regeneration."""
        self.ensure_one()
        pin = self._generate_unique_attendance_pin()
        self.attendance_pin_hash = generate_password_hash(pin)
        self.attendance_pin_plain = pin
        return pin

    def action_generate_attendance_pin(self):
        """Manually (re)generates the PIN. attendance_pin_plain now holds it
        (copyable straight from the form) — the sticky notification is a
        backup in case the field isn't in view. Used to re-issue a PIN
        (lost/compromised); new students get one automatically on creation
        (see create() / _set_new_attendance_pin)."""
        self.ensure_one()
        pin = self._set_new_attendance_pin()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('New Attendance PIN Generated'),
                'message': _('PIN for %s (%s): %s\n'
                             'Write this down now — it will not be shown again. '
                             'Use "Generate New PIN" again to reset it if lost.'
                             ) % (self.name, self.student_code, pin),
                'sticky': True,
                'type': 'success',
            },
        }

    def action_unlock_attendance_pin(self):
        """Manual override for Supervisor/Administrator to lift a temporary
        PIN lock early (e.g. after confirming the student's identity)."""
        self.write({'attendance_pin_failed_attempts': 0, 'attendance_pin_locked_until': False})

    def action_revoke_attendance_pin(self):
        self.write({'attendance_pin_hash': False})

    def verify_attendance_pin(self, pin):
        self.ensure_one()
        if not self.attendance_pin_hash or not pin:
            return False
        try:
            return check_password_hash(self.attendance_pin_hash, pin)
        except Exception:
            return False

    # --- PIN attempt / temporary lockout -----------------------------------
    ATTENDANCE_PIN_MAX_ATTEMPTS = 5
    ATTENDANCE_PIN_LOCK_MINUTES = 15

    def attendance_pin_lock_active(self):
        """True if this student's PIN is currently under a temporary lock
        following too many failed attempts."""
        self.ensure_one()
        return bool(self.sudo().attendance_pin_locked_until and
                    fields.Datetime.now() < self.sudo().attendance_pin_locked_until)

    def register_pin_attempt(self, success):
        """Tracks failed self check-in PIN attempts and applies a temporary
        lock once the threshold is reached, regardless of the (global,
        per-IP) rate limiting already applied at the controller level."""
        self.ensure_one()
        student = self.sudo()
        if success:
            if student.attendance_pin_failed_attempts or student.attendance_pin_locked_until:
                student.write({'attendance_pin_failed_attempts': 0, 'attendance_pin_locked_until': False})
            return
        attempts = student.attendance_pin_failed_attempts + 1
        vals = {'attendance_pin_failed_attempts': attempts}
        if attempts >= self.ATTENDANCE_PIN_MAX_ATTEMPTS:
            vals['attendance_pin_locked_until'] = fields.Datetime.now() + timedelta(
                minutes=self.ATTENDANCE_PIN_LOCK_MINUTES)
        student.write(vals)

    def action_revoke_portal_link(self):
        self.write({'portal_token': False})

    def action_rotate_portal_link(self):
        """Invalidates the current portal link and issues a fresh one —
        anyone with the old link loses access immediately."""
        for rec in self:
            rec.portal_token = uuid.uuid4().hex

    @api.model
    def get_public_portal_data(self, token):
        """Non-sensitive-ish but personal snapshot for a guardian/parent,
        gated behind an unshared per-student token (same security model as
        the certificate verification link)."""
        student = self.sudo().search([('portal_token', '=', token)], limit=1)
        if not student:
            return {'found': False}

        recent_results = student.exam_result_ids.sorted('id', reverse=True)[:5]
        next_installment = self.env['education.installment'].sudo().search([
            ('student_id', '=', student.id), ('state', 'in', ('unpaid', 'partial', 'overdue')),
        ], order='due_date asc', limit=1)

        attendance_lines = student.attendance_ids
        attendance_breakdown = {
            'present': len(attendance_lines.filtered(lambda a: a.status == 'present')),
            'late': len(attendance_lines.filtered(lambda a: a.status == 'late')),
            'absent': len(attendance_lines.filtered(lambda a: a.status == 'absent')),
            'excused': len(attendance_lines.filtered(lambda a: a.status == 'excused')),
        }

        return {
            'found': True,
            'portal_token': token,
            'student_name': student.name,
            'student_code': student.student_code,
            'grade_level': student.grade_level_id.name or '',
            'attendance_percentage': round(student.attendance_percentage, 1),
            'attendance_breakdown': attendance_breakdown,
            'exam_average_percentage': round(student.exam_average_percentage, 1),
            'assignment_completion_percentage': round(student.submission_completion_percentage, 1),
            'total_outstanding': round(student.total_outstanding, 2),
            'currency_symbol': student.currency_id.symbol or '',
            'next_installment_due': str(next_installment.due_date) if next_installment else '',
            'next_installment_amount': round(next_installment.remaining_amount, 2) if next_installment else 0.0,
            'active_groups': student.active_group_ids.mapped('name'),
            'recent_results': [{
                'exam': r.exam_id.name,
                'subject': r.exam_id.subject_id.name or '',
                'percentage': round(r.percentage, 1),
                'grade': r.grade or '',
            } for r in recent_results],
        }

    def action_view_payments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Payments',
            'res_model': 'education.payment',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }

    def action_quick_payment(self):
        """Opens a blank Payment form in a dialog on top of the student's
        own page (target='new') instead of navigating away to the Payments
        menu -- the fastest path from 'this student owes money' to a
        recorded receipt."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Record Payment -- %s') % self.name,
            'res_model': 'education.payment',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_student_id': self.id},
        }

    def action_view_installments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Installments',
            'res_model': 'education.installment',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
        }

    def action_view_certificates(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Certificates',
            'res_model': 'education.certificate',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }

    def action_view_refunds(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Refunds',
            'res_model': 'education.refund',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }

    def _get_whatsapp_number(self):
        """Prefers the first guardian's WhatsApp/mobile, falls back to the
        student's own WhatsApp/mobile/phone. Returns digits only (wa.me format)."""
        self.ensure_one()
        raw = False
        guardian = self.guardian_ids[:1]
        if guardian:
            raw = guardian.whatsapp or guardian.mobile
        raw = raw or self.whatsapp or self.mobile or self.phone
        if not raw:
            return False
        return re.sub(r'\D', '', raw)

    def action_send_whatsapp_fee_reminder(self):
        self.ensure_one()
        number = self._get_whatsapp_number()
        if not number:
            raise UserError(_(
                'No WhatsApp/mobile number found for this student or their guardians.'))
        message = _(
            'Dear guardian of %(student)s,\n\n'
            'This is a friendly reminder that the outstanding balance on the account is '
            '%(amount)s %(currency)s.\n\nThank you.'
        ) % {
            'student': self.name,
            'amount': '%.2f' % self.total_outstanding,
            'currency': self.currency_id.name or '',
        }
        url = 'https://wa.me/%s?text=%s' % (number, quote(message))
        return {'type': 'ir.actions.act_url', 'url': url, 'target': 'new'}

    def action_view_exam_results(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Exam Results',
            'res_model': 'education.exam.result',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
        }

    def action_view_submissions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Assignment Submissions',
            'res_model': 'education.assignment.submission',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
        }

    @api.depends('enrollment_ids')
    def _compute_enrollment_count(self):
        for rec in self:
            rec.enrollment_count = len(rec.enrollment_ids)

    @api.depends('enrollment_ids.state', 'enrollment_ids.group_id')
    def _compute_active_groups(self):
        for rec in self:
            active_enrollments = rec.enrollment_ids.filtered(lambda e: e.state == 'active')
            rec.active_group_ids = active_enrollments.group_id
            rec.active_group_count = len(active_enrollments)

    @api.depends('guardian_ids')
    def _compute_guardian_count(self):
        for rec in self:
            rec.guardian_count = len(rec.guardian_ids)

    @api.depends('date_of_birth')
    def _compute_age(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.date_of_birth:
                years = today.year - rec.date_of_birth.year - (
                    (today.month, today.day) < (rec.date_of_birth.month, rec.date_of_birth.day)
                )
                rec.age = years
            else:
                rec.age = 0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('student_code', 'New') == 'New':
                vals['student_code'] = self.env['ir.sequence'].next_by_code('education.student') or 'New'
        students = super().create(vals_list)
        for student in students:
            if not student.attendance_pin_hash:
                student._set_new_attendance_pin()
        return students

    def action_view_guardians(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Guardians',
            'res_model': 'education.guardian',
            'view_mode': 'list,form',
            'domain': [('student_ids', 'in', self.id)],
        }

    def action_view_enrollments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Enrollments',
            'res_model': 'education.enrollment',
            'view_mode': 'list,form',
            'domain': [('student_id', '=', self.id)],
            'context': {'default_student_id': self.id},
        }

    def action_view_groups(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Groups',
            'res_model': 'education.group',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.active_group_ids.ids)],
        }

    def action_view_attendance(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Attendance',
            'res_model': 'education.attendance',
            'view_mode': 'list',
            'domain': [('student_id', '=', self.id)],
        }
