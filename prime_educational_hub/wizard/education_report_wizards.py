# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EducationGroupAttendanceSheetWizard(models.TransientModel):
    _name = 'education.group.attendance.sheet.wizard'
    _description = 'Group Attendance Sheet Wizard'

    group_id = fields.Many2one('education.group', string='Group', required=True)
    date_from = fields.Date(string='From', required=True,
                             default=lambda self: fields.Date.context_today(self) - timedelta(days=30))
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)

    def action_print(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('"From" date must be before "To" date.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/pdf/group_attendance_sheet/%s' % self.id,
            'target': 'new',
        }

    def get_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = Utils.get_report_language()
        group = self.group_id
        sessions = self.env['education.session'].search([
            ('group_id', '=', group.id),
            ('date', '>=', self.date_from), ('date', '<=', self.date_to),
        ], order='date asc')
        students = group.enrollment_ids.filtered(lambda e: e.state == 'active').mapped('student_id')

        status_abbrev = {'present': 'P', 'absent': 'A', 'late': 'L', 'excused': 'E'}
        header = [_('Student')] + [s.date.strftime('%d/%m') for s in sessions]
        rows = []
        for student in students:
            row = [student.name]
            for session in sessions:
                att = session.attendance_ids.filtered(lambda a: a.student_id.id == student.id)
                row.append(status_abbrev.get(att.status, '-') if att else '-')
            rows.append(row)

        meta = [
            (_('Group'), group.name),
            (_('Period'), '%s - %s' % (self.date_from, self.date_to)),
            (_('Sessions'), str(len(sessions))),
        ]
        return Utils.build_simple_report(
            title=_('Group Attendance Sheet'), subtitle=group.name,
            meta_pairs=meta, table_header=header, table_rows=rows, lang=lang,
        )


class EducationCollectionReportWizard(models.TransientModel):
    _name = 'education.collection.report.wizard'
    _description = 'Collection Report Wizard'

    date_from = fields.Date(string='From', required=True,
                             default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)
    group_id = fields.Many2one('education.group', string='Group (optional filter)')

    def action_print(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('"From" date must be before "To" date.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/pdf/collection_report/%s' % self.id,
            'target': 'new',
        }

    def action_export_excel(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('"From" date must be before "To" date.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/xlsx/collection_report/%s' % self.id,
            'target': 'new',
        }

    def _get_report_data(self):
        self.ensure_one()
        domain = [
            ('state', '=', 'confirmed'),
            ('payment_date', '>=', self.date_from), ('payment_date', '<=', self.date_to),
        ]
        if self.group_id:
            domain.append(('group_id', '=', self.group_id.id))
        payments = self.env['education.payment'].search(domain, order='payment_date asc')

        header = [_('Receipt #'), _('Date'), _('Student'), _('Group'), _('Method'), _('Amount')]
        rows = [[
            p.receipt_number, str(p.payment_date or ''), p.student_id.name,
            p.group_id.name or '-', p.payment_method_id.name, '%.2f' % p.amount,
        ] for p in payments]
        totals = [(_('Total Collected'), '%.2f' % sum(payments.mapped('amount')))]
        meta = [
            (_('Period'), '%s - %s' % (self.date_from, self.date_to)),
            (_('Group Filter'), self.group_id.name or _('All Groups')),
        ]
        return meta, header, rows, totals

    def get_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = Utils.get_report_language()
        meta, header, rows, totals = self._get_report_data()
        return Utils.build_simple_report(
            title=_('Collection Report'), subtitle='%s - %s' % (self.date_from, self.date_to),
            meta_pairs=meta, table_header=header, table_rows=rows, totals=totals, lang=lang,
        )

    def get_excel(self):
        self.ensure_one()
        ExcelUtils = self.env['education.excel.utils']
        meta, header, rows, totals = self._get_report_data()
        return ExcelUtils.build_simple_excel(
            title=_('Collection Report'), meta_pairs=meta,
            table_header=header, table_rows=rows, totals=totals, sheet_name='Collections',
        )


class EducationReportCardWizard(models.TransientModel):
    _name = 'education.report.card.wizard'
    _description = 'Student Report Card / Transcript Wizard'

    student_id = fields.Many2one('education.student', string='Student', required=True)
    academic_year_id = fields.Many2one('education.academic.year', string='Academic Year')

    def action_print(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/pdf/report_card/%s' % self.id,
            'target': 'new',
        }

    def get_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = Utils.get_report_language()
        student = self.student_id

        results = student.exam_result_ids
        if self.academic_year_id:
            results = results.filtered(lambda r: r.exam_id.academic_year_id == self.academic_year_id)

        # Group by subject for a transcript-style breakdown
        by_subject = {}
        for r in results:
            subject = r.exam_id.subject_id
            by_subject.setdefault(subject, []).append(r)

        header = [_('Subject'), _('Exams'), _('Average %'), _('Best Grade')]
        rows = []
        for subject, recs in by_subject.items():
            avg = sum(x.percentage for x in recs) / len(recs) if recs else 0.0
            best_grade = min((x.grade for x in recs if x.grade), default='-')
            rows.append([subject.name if subject else _('(No Subject)'), str(len(recs)),
                         '%.1f%%' % avg, best_grade])

        overall_avg = (sum(r.percentage for r in results) / len(results)) if results else 0.0
        meta = [
            (_('Student'), '%s (%s)' % (student.name, student.student_code)),
            (_('Academic Year'), self.academic_year_id.name or _('All Years')),
            (_('Grade Level'), student.grade_level_id.name or ''),
        ]
        totals = [
            (_('Overall Average %'), '%.1f%%' % overall_avg),
            (_('Attendance %'), '%.1f%%' % student.attendance_percentage),
            (_('Assignment Completion %'), '%.1f%%' % student.submission_completion_percentage),
        ]
        return Utils.build_simple_report(
            title=_('Student Report Card / Transcript'), subtitle=student.name,
            meta_pairs=meta, table_header=header, table_rows=rows, totals=totals, lang=lang,
        )


class EducationAgingReportWizard(models.TransientModel):
    _name = 'education.aging.report.wizard'
    _description = 'Outstanding Receivables Aging Report Wizard'

    group_id = fields.Many2one('education.group', string='Group (optional filter)')
    as_of_date = fields.Date(string='As Of', required=True, default=fields.Date.context_today)

    def action_print(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/pdf/aging_report/%s' % self.id,
            'target': 'new',
        }

    def action_export_excel(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/xlsx/aging_report/%s' % self.id,
            'target': 'new',
        }

    def _get_report_data(self):
        self.ensure_one()
        as_of = self.as_of_date
        domain = [('remaining_amount', '>', 0)]
        if self.group_id:
            domain.append(('fee_id.group_id', '=', self.group_id.id))
        installments = self.env['education.installment'].search(domain)

        buckets = {}  # student -> {bucket_label: amount}
        bucket_labels = [_('Current'), _('1-7 Days'), _('8-30 Days'), _('31-60 Days'), _('60+ Days')]
        for inst in installments:
            days_overdue = (as_of - inst.due_date).days if inst.due_date else 0
            if days_overdue <= 0:
                bucket = bucket_labels[0]
            elif days_overdue <= 7:
                bucket = bucket_labels[1]
            elif days_overdue <= 30:
                bucket = bucket_labels[2]
            elif days_overdue <= 60:
                bucket = bucket_labels[3]
            else:
                bucket = bucket_labels[4]
            key = (inst.student_id, inst.fee_id.group_id)
            row = buckets.setdefault(key, {label: 0.0 for label in bucket_labels})
            row[bucket] += inst.remaining_amount

        header = [_('Student'), _('Group')] + bucket_labels + [_('Total')]
        rows = []
        column_totals = {label: 0.0 for label in bucket_labels}
        grand_total = 0.0
        for (student, group), row in sorted(buckets.items(), key=lambda kv: kv[0][0].name):
            total = sum(row.values())
            rows.append([student.name, group.name if group else '-'] +
                        ['%.2f' % row[label] if row[label] else '' for label in bucket_labels] +
                        ['%.2f' % total])
            for label in bucket_labels:
                column_totals[label] += row[label]
            grand_total += total

        totals = [(label, '%.2f' % column_totals[label]) for label in bucket_labels]
        totals.append((_('Grand Total'), '%.2f' % grand_total))
        meta = [
            (_('As Of'), str(as_of)),
            (_('Group Filter'), self.group_id.name or _('All Groups')),
        ]
        return meta, header, rows, totals

    def get_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = Utils.get_report_language()
        meta, header, rows, totals = self._get_report_data()
        return Utils.build_simple_report(
            title=_('Outstanding Receivables Aging Report'), subtitle=str(self.as_of_date),
            meta_pairs=meta, table_header=header, table_rows=rows, totals=totals, lang=lang,
        )

    def get_excel(self):
        self.ensure_one()
        ExcelUtils = self.env['education.excel.utils']
        meta, header, rows, totals = self._get_report_data()
        return ExcelUtils.build_simple_excel(
            title=_('Outstanding Receivables Aging Report'), meta_pairs=meta,
            table_header=header, table_rows=rows, totals=totals, sheet_name='Aging Report',
        )


class EducationCashierClosingWizard(models.TransientModel):
    _name = 'education.cashier.closing.wizard'
    _description = 'Cashier Daily Closing Wizard'

    closing_date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    cashier_id = fields.Many2one('res.users', string='Cashier (optional filter)')

    def action_print(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/pdf/cashier_closing/%s' % self.id,
            'target': 'new',
        }

    def get_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = Utils.get_report_language()
        domain = [('state', '=', 'confirmed'), ('payment_date', '=', self.closing_date)]
        if self.cashier_id:
            domain.append(('received_by', '=', self.cashier_id.id))
        payments = self.env['education.payment'].search(domain, order='payment_method_id, payment_date')

        by_method = {}
        for p in payments:
            by_method.setdefault(p.payment_method_id, []).append(p)

        header = [_('Payment Method'), _('Count'), _('Total')]
        rows = [[
            method.name if method else _('(No Method)'), str(len(plist)), '%.2f' % sum(x.amount for x in plist),
        ] for method, plist in by_method.items()]
        totals = [
            (_('Total Payments'), str(len(payments))),
            (_('Grand Total'), '%.2f' % sum(payments.mapped('amount'))),
        ]
        meta = [
            (_('Date'), str(self.closing_date)),
            (_('Cashier'), self.cashier_id.name or _('All Cashiers')),
        ]
        detail_table = (
            _('Payment Detail'),
            [_('Receipt #'), _('Student'), _('Method'), _('Amount')],
            [[p.receipt_number, p.student_id.name, p.payment_method_id.name, '%.2f' % p.amount] for p in payments],
        )
        return Utils.build_simple_report(
            title=_('Cashier Daily Closing'), subtitle=str(self.closing_date),
            meta_pairs=meta, table_header=header, table_rows=rows, totals=totals, lang=lang,
            extra_tables=[detail_table],
        )


class EducationOutstandingFeesReportWizard(models.TransientModel):
    _name = 'education.outstanding.fees.report.wizard'
    _description = 'Outstanding Fees Report Wizard'

    group_id = fields.Many2one('education.group', string='Group (optional filter)')

    def action_print(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/pdf/outstanding_fees/%s' % self.id,
            'target': 'new',
        }

    def action_export_excel(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/xlsx/outstanding_fees/%s' % self.id,
            'target': 'new',
        }

    def _get_report_data(self):
        self.ensure_one()
        domain = [('state', '=', 'active'), ('outstanding_amount', '>', 0)]
        if self.group_id:
            domain.append(('group_id', '=', self.group_id.id))
        enrollments = self.env['education.enrollment'].search(domain, order='outstanding_amount desc')

        header = [_('Student'), _('Group'), _('Net Fee'), _('Paid'), _('Outstanding')]
        rows = [[
            e.student_id.name, e.group_id.name, '%.2f' % e.net_fee,
            '%.2f' % e.paid_amount, '%.2f' % e.outstanding_amount,
        ] for e in enrollments]
        totals = [(_('Total Outstanding'), '%.2f' % sum(enrollments.mapped('outstanding_amount')))]
        meta = [(_('Group Filter'), self.group_id.name or _('All Groups'))]
        return meta, header, rows, totals

    def get_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = Utils.get_report_language()
        meta, header, rows, totals = self._get_report_data()
        return Utils.build_simple_report(
            title=_('Outstanding Fees Report'), subtitle=fields.Date.context_today(self).strftime('%Y-%m-%d'),
            meta_pairs=meta, table_header=header, table_rows=rows, totals=totals, lang=lang,
        )

    def get_excel(self):
        self.ensure_one()
        ExcelUtils = self.env['education.excel.utils']
        meta, header, rows, totals = self._get_report_data()
        return ExcelUtils.build_simple_excel(
            title=_('Outstanding Fees Report'), meta_pairs=meta,
            table_header=header, table_rows=rows, totals=totals, sheet_name='Outstanding Fees',
        )
