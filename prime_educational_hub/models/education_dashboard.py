# -*- coding: utf-8 -*-
from datetime import timedelta
from collections import OrderedDict

from odoo import api, fields, models


class EducationDashboard(models.AbstractModel):
    _name = 'education.dashboard'
    _description = 'Education Dashboard (data provider)'

    @api.model
    def _get_shell_data(self):
        """Header/sidebar data shared by every Prime Education Hub OWL dashboard page (the
        main Dashboard and the Session Calendar), so a lightweight page never has to pay for
        the full KPI/chart computation just to render its sidebar."""
        return {
            'company_name': self.env.company.name,
            'is_admin': self.env.user.has_group('base.group_system'),
            'sidebar_items': [{
                'id': item.id,
                'name': item.name,
                'icon': item.icon,
                'color': item.color,
                'is_dashboard_home': item.is_dashboard_home,
                'action_id': item.action_id.id,
            } for item in self.env['education.dashboard.menu.item'].get_visible_items()],
        }

    @api.model
    def get_session_calendar_data(self, date_from, date_to):
        """All sessions between date_from and date_to (inclusive, 'YYYY-MM-DD' strings) for
        the Session Calendar dashboard - a live, purple-themed calendar view, distinct from
        the plain Odoo calendar/list views on the Sessions menu itself."""
        Session = self.env['education.session']
        sessions = Session.search([
            ('date', '>=', date_from), ('date', '<=', date_to),
        ], order='date, start_datetime')
        data = []
        for s in sessions:
            start_str = end_str = False
            if s.start_datetime:
                start_str = fields.Datetime.context_timestamp(self, s.start_datetime).strftime('%H:%M')
            if s.end_datetime:
                end_str = fields.Datetime.context_timestamp(self, s.end_datetime).strftime('%H:%M')
            data.append({
                'id': s.id,
                'date': s.date.strftime('%Y-%m-%d'),
                'start': start_str,
                'end': end_str,
                'group': s.group_id.name,
                'teacher': s.teacher_id.name or '',
                'room': s.room_id.name or '',
                'state': s.state,
                'is_makeup': s.is_makeup,
            })
        return {
            **self._get_shell_data(),
            'sessions': data,
        }

    @api.model
    def get_dashboard_data(self):
        today = fields.Date.context_today(self)
        Student = self.env['education.student']
        Group = self.env['education.group']
        Session = self.env['education.session']
        Attendance = self.env['education.attendance']
        Exam = self.env['education.exam']
        Payment = self.env['education.payment']
        Enrollment = self.env['education.enrollment']
        Certificate = self.env['education.certificate']
        ExamResult = self.env['education.exam.result']

        # --- KPI cards --------------------------------------------------
        total_active_students = Student.search_count([('state', '=', 'active')])
        active_groups = Group.search_count([('state', '=', 'active')])
        todays_sessions = Session.search_count([('date', '=', today)])

        todays_attendance = Attendance.search([('session_date', '=', today)])
        if todays_attendance:
            present = len(todays_attendance.filtered(lambda a: a.status in ('present', 'late')))
            todays_attendance_percentage = round(present / len(todays_attendance) * 100.0, 1)
        else:
            todays_attendance_percentage = 0.0

        upcoming_exams = Exam.search_count([
            ('exam_date', '>=', today),
            ('exam_date', '<=', today + timedelta(days=30)),
            ('state', '!=', 'closed'),
        ])

        month_start = today.replace(day=1)
        monthly_collections = sum(Payment.search([
            ('state', '=', 'confirmed'),
            ('payment_date', '>=', month_start),
            ('payment_date', '<=', today),
        ]).mapped('amount'))

        active_enrollments = Enrollment.search([('state', '=', 'active')])
        outstanding_fees = sum(active_enrollments.mapped('outstanding_amount'))

        certificates_issued = Certificate.search_count([('state', '=', 'issued')])

        # --- Charts -------------------------------------------------------
        # Students by group
        students_by_group = [
            {'label': grp.name, 'value': cnt, 'res_id': grp.id}
            for grp, cnt in self._group_counts(active_enrollments, 'group_id')
        ]
        students_by_group.sort(key=lambda x: x['value'], reverse=True)
        students_by_group = students_by_group[:10]

        # Attendance trend - last 14 days
        attendance_trend = []
        for i in range(13, -1, -1):
            day = today - timedelta(days=i)
            lines = Attendance.search([('session_date', '=', day)])
            if lines:
                present = len(lines.filtered(lambda a: a.status in ('present', 'late')))
                pct = round(present / len(lines) * 100.0, 1)
            else:
                pct = None
            attendance_trend.append({'label': day.strftime('%d/%m'), 'value': pct, 'date': day.strftime('%Y-%m-%d')})

        # Exam performance by group (average %)
        exam_performance_by_group = []
        groups_with_results = ExamResult.read_group(
            [], ['group_id', 'percentage:avg'], ['group_id']
        )
        for row in groups_with_results:
            if row['group_id']:
                exam_performance_by_group.append({
                    'label': row['group_id'][1],
                    'value': round(row['percentage'], 1),
                    'res_id': row['group_id'][0],
                    'res_model': 'education.group',
                })
        exam_performance_by_group.sort(key=lambda x: x['value'], reverse=True)
        exam_performance_by_group = exam_performance_by_group[:10]

        # Collections by month - last 6 months
        collections_by_month = []
        for i in range(5, -1, -1):
            ref_date = (month_start - timedelta(days=1))
            # step back i months from current month_start
            year = month_start.year
            month = month_start.month - i
            while month <= 0:
                month += 12
                year -= 1
            from_date = fields.Date.to_date('%04d-%02d-01' % (year, month))
            if month == 12:
                to_date = fields.Date.to_date('%04d-01-01' % (year + 1)) - timedelta(days=1)
            else:
                to_date = fields.Date.to_date('%04d-%02d-01' % (year, month + 1)) - timedelta(days=1)
            total = sum(Payment.search([
                ('state', '=', 'confirmed'),
                ('payment_date', '>=', from_date),
                ('payment_date', '<=', to_date),
            ]).mapped('amount'))
            collections_by_month.append({
                'label': from_date.strftime('%b %Y'), 'value': total,
                'date_from': from_date.strftime('%Y-%m-%d'), 'date_to': to_date.strftime('%Y-%m-%d'),
            })

        # Outstanding fees by group
        outstanding_by_group = [
            {'label': g.name, 'value': g.total_outstanding, 'res_id': g.id}
            for g in Group.search([('state', '=', 'active')]) if g.total_outstanding
        ]
        outstanding_by_group.sort(key=lambda x: x['value'], reverse=True)
        outstanding_by_group = outstanding_by_group[:10]

        # Overall pass / fail rate (all exam results with a mark entered)
        all_results = ExamResult.search([])
        passed_count = len(all_results.filtered('passed'))
        failed_count = len(all_results) - passed_count

        # Certificate status distribution
        certificate_distribution = [
            {'label': label, 'value': Certificate.search_count([('state', '=', key)])}
            for key, label in Certificate._fields['state'].selection
        ]

        # 7-day planner: sessions + exams grouped by day (today included)
        planner_days = []
        for i in range(0, 7):
            day = today + timedelta(days=i)
            day_items = []
            for s in Session.search([('date', '=', day), ('state', 'in', ('planned', 'open'))], order='start_datetime'):
                time_str = False
                if s.start_datetime:
                    time_str = fields.Datetime.context_timestamp(self, s.start_datetime).strftime('%H:%M')
                day_items.append({
                    'type': 'Session', 'name': s.group_id.name, 'time': time_str,
                    'res_model': 'education.session', 'res_id': s.id,
                })
            for ex in Exam.search([('exam_date', '=', day)]):
                day_items.append({
                    'type': 'Exam', 'name': ex.name, 'time': False,
                    'res_model': 'education.exam', 'res_id': ex.id,
                })
            planner_days.append({
                'date': day.strftime('%Y-%m-%d'),
                'day_label': day.strftime('%a'),
                'day_number': day.strftime('%d'),
                'is_today': i == 0,
                'items': day_items,
            })

        # Upcoming sessions/exams (next 7 days)
        upcoming_items = []
        upcoming_sessions = Session.search([
            ('date', '>=', today), ('date', '<=', today + timedelta(days=7)),
            ('state', 'in', ('planned', 'open')),
        ], order='date', limit=10)
        for s in upcoming_sessions:
            upcoming_items.append({'type': 'Session', 'name': s.group_id.name, 'date': s.date})
        upcoming_exam_records = Exam.search([
            ('exam_date', '>=', today), ('exam_date', '<=', today + timedelta(days=7)),
        ], order='exam_date', limit=10)
        for ex in upcoming_exam_records:
            upcoming_items.append({'type': 'Exam', 'name': ex.name, 'date': ex.exam_date})
        upcoming_items.sort(key=lambda i: i['date'])

        # Top / low academic performance (students with at least one exam result)
        student_perf = ExamResult.read_group([], ['student_id', 'percentage:avg'], ['student_id'])
        student_perf = [
            {
                'name': row['student_id'][1], 'value': round(row['percentage'], 1),
                'res_id': row['student_id'][0], 'res_model': 'education.student',
            }
            for row in student_perf if row['student_id']
        ]
        student_perf.sort(key=lambda r: r['value'], reverse=True)
        top_performers = student_perf[:5]
        low_performers = sorted(student_perf, key=lambda r: r['value'])[:5]

        # Most active teachers this month (by sessions given)
        Teacher = self.env['education.teacher']
        teacher_activity = []
        for teacher in Teacher.search([]):
            cnt = Session.search_count([
                ('teacher_id', '=', teacher.id),
                ('date', '>=', month_start), ('date', '<=', today),
            ])
            if cnt:
                teacher_activity.append({
                    'label': teacher.name, 'value': cnt,
                    'res_id': teacher.id, 'res_model': 'education.teacher',
                })
        teacher_activity.sort(key=lambda r: r['value'], reverse=True)
        teacher_activity = teacher_activity[:5]

        # Lowest attendance rate this week, per active group
        week_start = today - timedelta(days=today.weekday())
        low_attendance_groups = []
        for group in Group.search([('state', '=', 'active')]):
            lines = Attendance.search([
                ('group_id', '=', group.id),
                ('session_date', '>=', week_start), ('session_date', '<=', today),
            ])
            if lines:
                present = len(lines.filtered(lambda a: a.status in ('present', 'late')))
                low_attendance_groups.append({
                    'label': group.name, 'value': round(present / len(lines) * 100.0, 1),
                    'res_id': group.id, 'res_model': 'education.group',
                })
        low_attendance_groups.sort(key=lambda r: r['value'])
        low_attendance_groups = low_attendance_groups[:5]

        total_teachers = self.env['education.teacher'].search_count([])
        pending_payouts = sum(self.env['education.teacher.payout'].search([
            ('state', '!=', 'paid'),
        ]).mapped('amount'))

        return {
            'kpis': {
                'total_active_students': total_active_students,
                'active_groups': active_groups,
                'todays_sessions': todays_sessions,
                'todays_attendance_percentage': todays_attendance_percentage,
                'upcoming_exams': upcoming_exams,
                'monthly_collections': monthly_collections,
                'outstanding_fees': outstanding_fees,
                'certificates_issued': certificates_issued,
                'total_teachers': total_teachers,
                'pending_payouts': round(pending_payouts, 2),
            },
            'currency_symbol': self.env.company.currency_id.symbol or '',
            **self._get_shell_data(),
            'stat_cards': self.env['education.dashboard.stat.card'].get_visible_cards_data(),
            'students_by_group': students_by_group,
            'attendance_trend': attendance_trend,
            'exam_performance_by_group': exam_performance_by_group,
            'collections_by_month': collections_by_month,
            'outstanding_by_group': outstanding_by_group,
            'upcoming_items': upcoming_items[:10],
            'top_performers': top_performers,
            'low_performers': low_performers,
            'teacher_activity': teacher_activity,
            'low_attendance_groups': low_attendance_groups,
            'pass_rate': {'passed': passed_count, 'failed': failed_count},
            'certificate_distribution': certificate_distribution,
            'planner_days': planner_days,
        }

    def _group_counts(self, enrollments, field_name):
        counts = OrderedDict()
        for rec in enrollments:
            key = rec[field_name]
            if key:
                counts[key] = counts.get(key, 0) + 1
        return list(counts.items())
