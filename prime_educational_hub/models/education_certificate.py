# -*- coding: utf-8 -*-
import uuid

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, UserError


class EducationCertificate(models.Model):
    _name = 'education.certificate'
    _description = 'Certificate'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'issue_date desc'

    certificate_number = fields.Char(string='Certificate Number', copy=False, readonly=True, default='New')
    student_id = fields.Many2one('education.student', string='Student', required=True, tracking=True)
    group_id = fields.Many2one('education.group', string='Group')
    subject_id = fields.Many2one('education.subject', string='Subject')
    academic_year_id = fields.Many2one('education.academic.year', string='Academic Year')
    issue_date = fields.Date(string='Issue Date', default=fields.Date.context_today, required=True)
    certificate_type = fields.Selection([
        ('completion', 'Completion'),
        ('achievement', 'Achievement'),
        ('participation', 'Participation'),
        ('other', 'Other'),
    ], string='Certificate Type', default='completion', required=True)
    template_id = fields.Many2one('education.certificate.template', string='Template')
    final_percentage = fields.Float(string='Final Percentage')
    final_grade = fields.Char(string='Final Grade')
    result = fields.Selection([
        ('pass', 'Pass'),
        ('fail', 'Fail'),
        ('merit', 'Merit'),
        ('distinction', 'Distinction'),
    ], string='Result')
    qr_token = fields.Char(string='Verification Token', copy=False, readonly=True, index=True)
    verification_url = fields.Char(string='Verification URL', compute='_compute_verification_url')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('issued', 'Issued'),
        ('revoked', 'Revoked'),
    ], string='Status', default='draft', tracking=True, required=True)
    revoke_reason = fields.Text(string='Revoke Reason')
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    _sql_constraints = [
        ('certificate_number_uniq', 'unique(certificate_number, company_id)',
         'Certificate number must be unique.'),
        ('qr_token_uniq', 'unique(qr_token)', 'Verification token must be unique.'),
    ]

    # Once issued, the substance of a certificate must not silently change —
    # only revoke (with a mandatory reason) or a privileged reset-to-draft.
    _LOCKED_AFTER_ISSUE = {'student_id', 'group_id', 'subject_id', 'academic_year_id',
                           'certificate_type', 'final_percentage', 'final_grade', 'result', 'issue_date'}

    def write(self, vals):
        if self._LOCKED_AFTER_ISSUE.intersection(vals.keys()) and not self.env.context.get('allow_system_write'):
            for rec in self:
                if rec.state == 'issued':
                    raise ValidationError(_(
                        'Certificate "%s" is issued and its content is locked. Revoke it (with a reason) '
                        'and issue a new corrected certificate instead.'
                    ) % rec.certificate_number)
        return super().write(vals)

    @api.depends('qr_token')
    def _compute_verification_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for rec in self:
            rec.verification_url = '%s/education/certificate/verify/%s' % (base_url, rec.qr_token) \
                if rec.qr_token else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('certificate_number', 'New') == 'New':
                vals['certificate_number'] = self.env['ir.sequence'].next_by_code('education.certificate') or 'New'
        return super().create(vals_list)

    @api.constrains('final_percentage')
    def _check_final_percentage(self):
        for rec in self:
            if rec.final_percentage and not (0 <= rec.final_percentage <= 100):
                raise ValidationError(_('Final percentage must be between 0 and 100.'))

    @api.constrains('company_id', 'student_id')
    def _check_company_consistency(self):
        for rec in self:
            if rec.student_id and rec.student_id.company_id and rec.student_id.company_id != rec.company_id:
                raise ValidationError(_(
                    'Certificate company must match the student\'s company (%s).') % rec.student_id.company_id.name)

    def action_compute_from_exam_results(self):
        """Convenience: average the student's exam results for the matching
        group/subject to pre-fill the final percentage and grade."""
        for rec in self:
            domain = [('student_id', '=', rec.student_id.id)]
            if rec.group_id:
                domain.append(('group_id', '=', rec.group_id.id))
            results = self.env['education.exam.result'].search(domain)
            if not results:
                continue
            percentage = sum(results.mapped('percentage')) / len(results)
            scale = self.env['education.grade.scale'].get_grade_for_percentage(percentage, rec.company_id.id)
            rec.final_percentage = percentage
            rec.final_grade = scale.grade if scale else rec.final_grade
            rec.result = 'pass' if all(results.mapped('passed')) else 'fail'

    def action_issue(self):
        for rec in self:
            if not rec.qr_token:
                rec.qr_token = uuid.uuid4().hex
        self.write({'state': 'issued'})

    def action_rotate_token(self):
        """Invalidates the current QR/verification link and issues a fresh
        one — old printed copies with the previous QR code will stop
        verifying. Use if a certificate's link may have been shared publicly
        by mistake."""
        is_privileged = self.env.user.has_group('prime_educational_hub.group_education_admin') or \
            self.env.user.has_group('prime_educational_hub.group_education_supervisor')
        if not is_privileged:
            raise UserError(_('Only an Academic Supervisor or Administrator can rotate a verification token.'))
        for rec in self:
            rec.qr_token = uuid.uuid4().hex

    def action_revoke(self, reason=None):
        for rec in self:
            final_reason = reason or rec.revoke_reason
            if not final_reason:
                raise UserError(_('A revoke reason is required.'))
            rec.with_context(allow_system_write=True).write({
                'state': 'revoked',
                'revoke_reason': final_reason,
            })

    def action_open_revoke_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Revoke Certificate'),
            'res_model': 'education.certificate.revoke.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_certificate_id': self.id},
        }

    def action_reset_to_draft(self):
        is_privileged = self.env.user.has_group('prime_educational_hub.group_education_admin') or \
            self.env.user.has_group('prime_educational_hub.group_education_supervisor')
        if not is_privileged:
            raise UserError(_(
                'Only an Academic Supervisor or Administrator can reset an issued/revoked '
                'certificate back to draft.'
            ))
        for rec in self:
            if not rec.revoke_reason:
                raise UserError(_(
                    'Please record a reason (in the Revoke Reason field) documenting why this '
                    'certificate is being reset to draft before proceeding.'
                ))
        self.with_context(allow_system_write=True).write({'state': 'draft'})

    @api.model
    def get_public_verification_data(self, token):
        """Returns only non-sensitive validity information for the public
        verification page/controller."""
        certificate = self.sudo().search([('qr_token', '=', token)], limit=1)
        if not certificate:
            return {'found': False}
        return {
            'found': True,
            'valid': certificate.state == 'issued',
            'state': certificate.state,
            'certificate_number': certificate.certificate_number,
            'student_name': certificate.student_id.name,
            'subject': certificate.subject_id.name or '',
            'group': certificate.group_id.name or '',
            'academic_year': certificate.academic_year_id.name or '',
            'certificate_type': dict(certificate._fields['certificate_type'].selection).get(
                certificate.certificate_type, ''),
            'issue_date': certificate.issue_date,
            'result': dict(certificate._fields['result'].selection).get(certificate.result, '') \
                if certificate.result else '',
        }
