# -*- coding: utf-8 -*-
import logging
import re

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class EducationWebsiteController(http.Controller):
    """Public-facing 'Prime Educational Hub' booking website: fully inside this module (no
    external site/CMS), built with normal Website pages so it can still be edited the usual
    way from the Website app's editor (drag & drop blocks, inline text editing, etc.)."""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _published_groups_domain(self):
        return [('is_published', '=', True), ('active', '=', True)]

    def _get_group_or_404(self, group_id):
        group = request.env['education.group'].sudo().search(
            [('id', '=', group_id)] + self._published_groups_domain(), limit=1)
        return group

    def _get_lead_with_token(self, lead_id, token):
        if not token:
            return request.env['education.lead']
        lead = request.env['education.lead'].sudo().search([
            ('id', '=', lead_id), ('access_token', '=', token),
        ], limit=1)
        return lead

    # ------------------------------------------------------------------
    # Course listing
    # ------------------------------------------------------------------
    @http.route(['/courses', '/courses/page/<int:page>'], type='http', auth='public', sitemap=True)
    def courses_list(self, page=1, subject_id=None, **kwargs):
        domain = self._published_groups_domain()
        if subject_id:
            try:
                domain.append(('subject_id', '=', int(subject_id)))
            except ValueError:
                pass

        Group = request.env['education.group'].sudo()
        groups = Group.search(domain, order='name')
        subjects = request.env['education.subject'].sudo().search([
            ('id', 'in', groups.mapped('subject_id').ids),
        ], order='name')

        return request.render('prime_educational_hub.website_courses_list', {
            'groups': groups,
            'subjects': subjects,
            'selected_subject_id': int(subject_id) if subject_id else False,
        })

    # ------------------------------------------------------------------
    # Course detail
    # ------------------------------------------------------------------
    @http.route(['/courses/<int:group_id>'], type='http', auth='public', sitemap=True)
    def course_detail(self, group_id, **kwargs):
        group = self._get_group_or_404(group_id)
        if not group:
            return request.not_found()
        weekday_labels = dict(group.schedule_ids._fields['weekday'].selection)
        schedules = [{
            'weekday': weekday_labels.get(sched.weekday, ''),
            'time_range': sched.time_range_label,
        } for sched in group.schedule_ids.filtered('active')]
        return request.render('prime_educational_hub.website_course_detail', {
            'group': group,
            'schedules': schedules,
        })

    # ------------------------------------------------------------------
    # Booking form
    # ------------------------------------------------------------------
    @http.route(['/courses/<int:group_id>/book'], type='http', auth='public', sitemap=False)
    def course_book_form(self, group_id, **kwargs):
        group = self._get_group_or_404(group_id)
        if not group:
            return request.not_found()
        return request.render('prime_educational_hub.website_course_book_form', {
            'group': group,
            'error': kwargs.get('error'),
            'form_data': {},
        })

    @http.route(['/courses/<int:group_id>/book/submit'], type='http', auth='public',
                sitemap=False, methods=['POST'], csrf=True)
    def course_book_submit(self, group_id, **post):
        group = self._get_group_or_404(group_id)
        if not group:
            return request.not_found()

        name = (post.get('name') or '').strip()
        phone = (post.get('phone') or '').strip()
        email = (post.get('email') or '').strip()
        notes = (post.get('notes') or '').strip()

        errors = []
        if not name:
            errors.append('Please enter your name.')
        if not phone and not email:
            errors.append('Please enter a phone number or an email so we can reach you.')
        if email and not EMAIL_RE.match(email):
            errors.append('That email address doesn\'t look valid.')

        if errors:
            return request.render('prime_educational_hub.website_course_book_form', {
                'group': group,
                'error': ' '.join(errors),
                'form_data': post,
            })

        Lead = request.env['education.lead'].sudo()
        lead_vals = {
            'name': name,
            'phone': phone or False,
            'email': email or False,
            'subject_id': group.subject_id.id,
            'level_id': group.level_id.id if group.level_id else False,
            'source': 'website',
            'website_group_id': group.id,
            'notes': notes or False,
            'company_id': group.company_id.id,
            'currency_id': group.currency_id.id,
        }
        # A reservation deposit is the group's fee plan amount, if one is configured -
        # staff can always adjust this per-lead afterwards from the backend before the
        # visitor pays (the amount actually charged is re-read from the lead right before
        # the payment link is generated, never trusted from the browser).
        if group.fee_plan_id:
            lead_vals['reservation_amount'] = group.fee_plan_id.amount

        lead = Lead.create(lead_vals)

        # A dedicated, single-purpose contact for this one booking - see
        # payment.transaction.create() for why this must never be reused across leads.
        partner = request.env['res.partner'].sudo().create({
            'name': name,
            'email': email or False,
            'phone': phone or False,
            'company_id': group.company_id.id,
        })
        lead.website_partner_id = partner.id

        return request.redirect(f'/courses/booking/{lead.id}?token={lead.access_token}')

    # ------------------------------------------------------------------
    # Booking confirmation / optional online reservation payment
    # ------------------------------------------------------------------
    @http.route(['/courses/booking/<int:lead_id>'], type='http', auth='public', sitemap=False)
    def booking_confirmation(self, lead_id, token=None, **kwargs):
        lead = self._get_lead_with_token(lead_id, token)
        if not lead:
            return request.not_found()

        payment_link = False
        payment_error = False
        if lead.reservation_amount > 0 and not lead.reservation_paid:
            payment_link = self._generate_payment_link(lead)
            if not payment_link:
                payment_error = True

        return request.render('prime_educational_hub.website_booking_confirmation', {
            'lead': lead,
            'payment_link': payment_link,
            'payment_error': payment_error,
        })

    def _generate_payment_link(self, lead):
        """Builds a real Odoo online-payment link (via the standard payment.link.wizard, the
        same mechanism behind every 'Pay Now' / 'Generate Payment Link' button elsewhere in
        Odoo) for this lead's reservation deposit. Whichever payment provider(s) the admin has
        enabled (Stripe, Paymob, PayTabs, the free zero-config Demo provider for testing...)
        show up automatically on the resulting checkout page - nothing about a specific
        gateway is hardcoded here."""
        if not lead.website_partner_id:
            return False
        try:
            wizard = request.env['payment.link.wizard'].sudo().create({
                'amount': lead.reservation_amount,
                'currency_id': lead.currency_id.id,
                'partner_id': lead.website_partner_id.id,
                'description': f'Reservation deposit - {lead.website_group_id.name or lead.subject_id.name}',
            })
            return wizard.link
        except Exception:
            _logger.exception(
                'Prime Educational Hub: could not generate an online payment link for '
                'lead %s. Is a Payment Provider enabled (Website/Accounting > Payment '
                'Providers)? The free "Demo" provider needs no setup and is good for '
                'testing this flow end to end.', lead.id
            )
            return False
