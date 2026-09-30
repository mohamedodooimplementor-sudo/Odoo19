# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import models, fields, _

_logger = logging.getLogger(__name__)


class EducationInstallmentCron(models.Model):
    _inherit = 'education.installment'

    def _cron_mark_overdue_installments(self):
        """Daily job: force-recompute the 'state' of every not-fully-paid
        installment so any that have crossed their due date flip to
        'overdue'. Calling the compute method directly (rather than write())
        is what lets a stored computed field react to the passage of time,
        which no @api.depends() can express."""
        installments = self.search([('state', 'in', ('unpaid', 'partial'))])
        if installments:
            installments._compute_state()
            _logger.info('Education: recomputed overdue status for %d installment(s).', len(installments))


class EducationGroupCron(models.Model):
    _inherit = 'education.group'

    def _cron_generate_upcoming_sessions(self, days_ahead=None):
        """Runs daily: for every active group with a weekly schedule, makes
        sure sessions exist for the next N days (N configurable in Settings,
        default 14). Skips dates that already have a session, so re-running
        the cron never creates duplicates -- this is what lets a group's
        weekly schedule turn into actual sessions automatically, with no
        manual 'Generate Sessions' click needed."""
        if days_ahead is None:
            ICP = self.env['ir.config_parameter'].sudo()
            days_ahead = int(ICP.get_param('prime_educational_hub.auto_session_horizon_days', 14) or 14)
        today = fields.Date.context_today(self)
        date_to = today + timedelta(days=days_ahead)
        groups = self.search([('state', '=', 'active')]).filtered('schedule_ids')
        total_created = 0
        for group in groups:
            sessions = group._generate_sessions_from_schedule(today, date_to, skip_existing=True)
            total_created += len(sessions)
        _logger.info(
            'Education: session auto-generation cron created %d session(s) across %d active group(s) '
            '(horizon: %d day(s)).', total_created, len(groups), days_ahead)


class EducationNotifyCron(models.Model):
    _inherit = 'education.exam'

    def _cron_notify_upcoming_events(self):
        """Optional automation: remind the responsible teacher about exams
        happening tomorrow and sessions happening today, via an Odoo
        activity. Guards against duplicate notifications on repeated runs
        by checking for an existing open activity on the same record first."""
        today = fields.Date.context_today(self)
        tomorrow = today + timedelta(days=1)
        Activity = self.env['mail.activity']
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)

        # Exams tomorrow
        exams = self.search([
            ('exam_date', '=', tomorrow), ('state', 'in', ('draft', 'published')),
        ])
        for exam in exams:
            teacher_user = exam.group_id.teacher_id.user_id
            if not teacher_user:
                continue
            already = Activity.search_count([
                ('res_model', '=', 'education.exam'), ('res_id', '=', exam.id),
                ('user_id', '=', teacher_user.id),
            ])
            if already:
                continue
            exam.activity_schedule(
                activity_type_id=activity_type.id if activity_type else False,
                user_id=teacher_user.id,
                summary=_('Exam Tomorrow'),
                note=_('Exam "%s" for group "%s" is scheduled for tomorrow (%s).') % (
                    exam.name, exam.group_id.name, tomorrow),
            )

        # Sessions today
        Session = self.env['education.session']
        sessions = Session.search([('date', '=', today), ('state', 'in', ('planned', 'open'))])
        for session in sessions:
            teacher_user = session.teacher_id.user_id
            if not teacher_user:
                continue
            already = Activity.search_count([
                ('res_model', '=', 'education.session'), ('res_id', '=', session.id),
                ('user_id', '=', teacher_user.id),
            ])
            if already:
                continue
            session.activity_schedule(
                activity_type_id=activity_type.id if activity_type else False,
                user_id=teacher_user.id,
                summary=_('Session Today'),
                note=_('Session for group "%s" is scheduled today (%s).') % (
                    session.group_id.name, today),
            )

        _logger.info('Education: notification cron processed %d exam(s) and %d session(s).',
                      len(exams), len(sessions))
