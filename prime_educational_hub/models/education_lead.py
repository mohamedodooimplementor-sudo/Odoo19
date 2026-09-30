# -*- coding: utf-8 -*-
import uuid

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EducationLead(models.Model):
    _name = 'education.lead'
    _description = 'Admissions Lead / Inquiry'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Contact Name', required=True, tracking=True)
    phone = fields.Char(string='Phone', tracking=True)
    email = fields.Char(string='Email')
    subject_id = fields.Many2one('education.subject', string='Interested In')
    level_id = fields.Many2one('education.level', string='Level')
    source = fields.Selection([
        ('referral', 'Referral'),
        ('social_media', 'Social Media'),
        ('walk_in', 'Walk-in'),
        ('phone', 'Phone Inquiry'),
        ('website', 'Website'),
        ('other', 'Other'),
    ], string='Source', default='other')
    stage_id = fields.Many2one(
        'education.lead.stage', string='Stage', tracking=True, required=True,
        default=lambda self: self._default_stage_id(), group_expand='_expand_stage_ids',
        ondelete='restrict', copy=False, index=True)
    trial_group_id = fields.Many2one('education.group', string='Trial Group')
    trial_date = fields.Date(string='Trial Session Date')
    lost_reason = fields.Text(string='Lost Reason')
    assigned_to = fields.Many2one('res.users', string='Assigned To', default=lambda self: self.env.user,
                                   tracking=True)
    student_id = fields.Many2one('education.student', string='Converted Student', readonly=True, copy=False)
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    color = fields.Integer(string='Color')

    # --- Website booking / online reservation payment ---------------------
    website_group_id = fields.Many2one(
        'education.group', string='Group Requested on Website',
        help='The specific group the visitor asked to reserve a seat in from the public '
             'Courses page (as opposed to trial_group_id, which staff set manually for a '
             'trial session once they follow up).')
    currency_id = fields.Many2one(
        'res.currency', string='Currency', default=lambda self: self.env.company.currency_id)
    reservation_amount = fields.Monetary(
        string='Reservation Amount', currency_field='currency_id',
        help='The deposit/reservation amount quoted to the visitor at booking time.')
    reservation_paid = fields.Boolean(
        string='Reservation Paid', compute='_compute_reservation_paid', store=True,
        help='True once an online payment for this booking has actually completed - computed '
             "live from the linked payment.transaction record(s), never set by hand, so it "
             "can't drift out of sync with what the payment provider actually confirmed.")
    reservation_paid_amount = fields.Monetary(
        string='Reservation Paid Amount', compute='_compute_reservation_paid',
        store=True, currency_field='currency_id')
    payment_transaction_ids = fields.One2many(
        'payment.transaction', 'education_lead_id', string='Payment Transactions')
    website_partner_id = fields.Many2one(
        'res.partner', string='Website Booking Contact', copy=False,
        help='A dedicated contact created for this specific website booking (never reused '
             "across leads, even for the same person), so any payment.transaction made "
             "against it can be traced back to this lead unambiguously.")
    access_token = fields.Char(
        string='Access Token', copy=False, default=lambda self: str(uuid.uuid4()),
        help='Random token included in the booking confirmation link sent to the website '
             "visitor, so only someone with that link (not just anyone who guesses the lead "
             "ID) can view this booking's status or pay its reservation online.")

    @api.depends('payment_transaction_ids.state', 'payment_transaction_ids.amount')
    def _compute_reservation_paid(self):
        for rec in self:
            done_txs = rec.payment_transaction_ids.filtered(lambda t: t.state == 'done')
            rec.reservation_paid = bool(done_txs)
            rec.reservation_paid_amount = sum(done_txs.mapped('amount'))

    @api.model
    def _default_stage_id(self):
        return self.env['education.lead.stage'].search([], order='sequence, id', limit=1)

    @api.model
    def _expand_stage_ids(self, stages, domain):
        # Always show every stage column in the kanban, even if empty, so
        # dragging a card into a not-yet-used stage for the first time works.
        return self.env['education.lead.stage'].search([], order='sequence, id')

    def action_mark_lost(self):
        lost_stage = self.env['education.lead.stage'].search([('is_lost', '=', True)], limit=1)
        if not lost_stage:
            raise UserError(_('No stage is configured as the "Lost" stage. '
                               'Set one up in Admissions ▸ Configuration ▸ Pipeline Stages.'))
        for rec in self:
            if rec.stage_id.is_won:
                raise UserError(_('This lead already converted to a student and cannot be marked lost.'))
            rec.stage_id = lost_stage.id

    def action_view_student(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'education.student',
            'res_id': self.student_id.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    def action_convert_to_student(self):
        """Creates the education.student (and guardian, if an email/phone
        was captured) from this lead's contact info, and links it back so
        the lead shows exactly which student it became. Does NOT create an
        enrollment automatically - staff still pick the actual group/fee
        plan on the Student form, since a trial interest doesn't always
        mean the parent settled on the same group."""
        self.ensure_one()
        if self.student_id:
            raise UserError(_('This lead was already converted to student "%s".') % self.student_id.name)
        if not self.stage_id.is_won:
            raise UserError(_('Move this lead to an "Enrolled" stage before converting it.'))
        student = self.env['education.student'].create({
            'name': self.name,
            'phone': self.phone,
            'company_id': self.company_id.id,
        })
        self.write({'student_id': student.id})
        self.message_post(body=_('Converted to student "%s".') % student.name)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'education.student',
            'res_id': student.id,
            'views': [[False, 'form']],
            'target': 'current',
        }
