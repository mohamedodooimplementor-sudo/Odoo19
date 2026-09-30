# -*- coding: utf-8 -*-
import base64
from odoo import models, fields, _


class EducationStudentReports(models.Model):
    _inherit = 'education.student'

    def _report_lang(self):
        return self.env['education.report.utils'].get_report_language()

    def action_print_profile_report(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/education/report/pdf/student_profile/%s' % self.id, 'target': 'new'}

    def action_print_academic_report(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/education/report/pdf/student_academic/%s' % self.id, 'target': 'new'}

    def action_print_exam_result_report(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/education/report/pdf/student_exam_result/%s' % self.id, 'target': 'new'}

    def action_print_attendance_report(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/education/report/pdf/student_attendance/%s' % self.id, 'target': 'new'}

    def action_print_financial_statement(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/education/report/pdf/student_financial/%s' % self.id, 'target': 'new'}

    def action_print_id_card(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/education/report/pdf/student_id_card/%s' % self.id, 'target': 'new'}

    def get_id_card_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        photo_bytes = base64.b64decode(self.photo) if self.photo else None
        return Utils.build_id_card_pdf(
            name=self.name, code=self.student_code, role_label=_('Student'),
            qr_value=self.portal_url or '', photo_bytes=photo_bytes,
            company_name=self.company_id.name,
        )


    def get_profile_report_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = self._report_lang()
        meta = [
            (_('Student Code'), self.student_code),
            (_('Full Name'), self.name),
            (_('Gender'), dict(self._fields['gender'].selection).get(self.gender, '')),
            (_('Date of Birth'), str(self.date_of_birth or '')),
            (_('Age'), str(self.age)),
            (_('Grade Level'), self.grade_level_id.name or ''),
            (_('Phone / Mobile'), self.phone or self.mobile or ''),
            (_('Registration Date'), str(self.registration_date or '')),
            (_('Status'), dict(self._fields['state'].selection).get(self.state, '')),
            (_('Guardians'), ', '.join(self.guardian_ids.mapped('name')) or '-'),
        ]
        header = [_('Group'), _('Status'), _('Enrollment Date'), _('Net Fee'), _('Outstanding')]
        rows = [[
            e.group_id.name, dict(e._fields['state'].selection).get(e.state, ''),
            str(e.enrollment_date or ''), '%.2f' % e.net_fee, '%.2f' % e.outstanding_amount,
        ] for e in self.enrollment_ids]
        totals = [
            (_('Overall Attendance %'), '%.1f%%' % self.attendance_percentage),
            (_('Exam Average %'), '%.1f%%' % self.exam_average_percentage),
        ]
        pdf = Utils.build_simple_report(
            title=_('Student Profile Report'), subtitle=self.name,
            meta_pairs=meta, table_header=header, table_rows=rows, totals=totals, lang=lang,
        )
        return pdf

    def get_academic_report_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = self._report_lang()
        meta = [
            (_('Student'), '%s (%s)' % (self.name, self.student_code)),
            (_('Grade Level'), self.grade_level_id.name or ''),
        ]
        header = [_('Subject'), _('Group'), _('Exam'), _('Mark / Max'), _('%'), _('Grade')]
        rows = [[
            r.exam_id.subject_id.name, r.exam_id.group_id.name, r.exam_id.name,
            '%.1f / %.1f' % (r.mark, r.max_mark), '%.1f%%' % r.percentage, r.grade or '',
        ] for r in self.exam_result_ids]
        totals = [
            (_('Exam Average %'), '%.1f%%' % self.exam_average_percentage),
            (_('Overall Attendance %'), '%.1f%%' % self.attendance_percentage),
            (_('Assignment Completion %'), '%.1f%%' % self.submission_completion_percentage),
        ]
        return Utils.build_simple_report(
            title=_('Student Academic Report'), subtitle=self.name,
            meta_pairs=meta, table_header=header, table_rows=rows, totals=totals, lang=lang,
        )

    def get_exam_result_report_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = self._report_lang()
        meta = [(_('Student'), '%s (%s)' % (self.name, self.student_code))]
        header = [_('Exam'), _('Subject'), _('Date'), _('Mark / Max'), _('%'), _('Grade'), _('Rank'), _('Result')]
        rows = [[
            r.exam_id.name, r.exam_id.subject_id.name, str(r.exam_id.exam_date or ''),
            '%.1f / %.1f' % (r.mark, r.max_mark), '%.1f%%' % r.percentage, r.grade or '',
            str(r.rank or ''), _('Pass') if r.passed else _('Fail'),
        ] for r in self.exam_result_ids]
        return Utils.build_simple_report(
            title=_('Student Exam / Result Report'), subtitle=self.name,
            meta_pairs=meta, table_header=header, table_rows=rows, lang=lang,
        )

    def get_attendance_report_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = self._report_lang()
        meta = [(_('Student'), '%s (%s)' % (self.name, self.student_code))]
        header = [_('Date'), _('Group'), _('Status')]
        status_labels = dict(self.env['education.attendance']._fields['status'].selection)
        rows = [[
            str(a.session_date or ''), a.group_id.name, status_labels.get(a.status, ''),
        ] for a in self.attendance_ids.sorted('session_date')]
        present = len(self.attendance_ids.filtered(lambda a: a.status == 'present'))
        absent = len(self.attendance_ids.filtered(lambda a: a.status == 'absent'))
        late = len(self.attendance_ids.filtered(lambda a: a.status == 'late'))
        excused = len(self.attendance_ids.filtered(lambda a: a.status == 'excused'))
        totals = [
            (_('Present'), str(present)), (_('Absent'), str(absent)),
            (_('Late'), str(late)), (_('Excused'), str(excused)),
            (_('Attendance %'), '%.1f%%' % self.attendance_percentage),
        ]
        return Utils.build_simple_report(
            title=_('Student Attendance Report'), subtitle=self.name,
            meta_pairs=meta, table_header=header, table_rows=rows, totals=totals, lang=lang,
        )

    def get_financial_statement_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = self._report_lang()
        meta = [(_('Student'), '%s (%s)' % (self.name, self.student_code))]

        installments = self.env['education.installment'].search([('student_id', '=', self.id)])
        header = [_('Fee'), _('#'), _('Due Date'), _('Amount'), _('Paid'), _('Remaining'), _('Status')]
        status_labels = dict(installments._fields['state'].selection) if installments else dict(
            self.env['education.installment']._fields['state'].selection)
        rows = [[
            i.fee_id.fee_plan_id.name or i.fee_id.group_id.name or '-', str(i.sequence),
            str(i.due_date or ''), '%.2f' % i.amount, '%.2f' % i.paid_amount,
            '%.2f' % i.remaining_amount, status_labels.get(i.state, ''),
        ] for i in installments]

        totals = [
            (_('Total Fees'), '%.2f' % self.total_net_fee),
            (_('Total Paid'), '%.2f' % self.total_paid),
            (_('Total Refunded'), '%.2f' % self.total_refunded),
            (_('Total Outstanding'), '%.2f' % self.total_outstanding),
        ]

        payments = self.payment_ids.filtered(lambda p: p.state == 'confirmed')
        payments_table = (
            _('Payments'),
            [_('Receipt #'), _('Date'), _('Amount'), _('Method')],
            [[p.receipt_number, str(p.payment_date or ''), '%.2f' % p.amount, p.payment_method_id.name]
             for p in payments],
        )
        refunds = self.refund_ids.filtered(lambda r: r.state != 'cancelled')
        refunds_table = (
            _('Refunds'),
            [_('Refund #'), _('Date'), _('Amount'), _('Status')],
            [[r.refund_number, str(r.refund_date or ''), '%.2f' % r.amount,
              dict(r._fields['state'].selection).get(r.state, '')] for r in refunds],
        )

        return Utils.build_simple_report(
            title=_('Student Financial Statement'), subtitle=self.name,
            meta_pairs=meta, table_header=header, table_rows=rows, totals=totals, lang=lang,
            extra_tables=[payments_table, refunds_table],
        )


class EducationPaymentReports(models.Model):
    _inherit = 'education.payment'

    def action_print_receipt(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/education/report/pdf/payment_receipt/%s' % self.id, 'target': 'new'}

    def get_receipt_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = self.env['education.report.utils'].get_report_language()
        meta = [
            (_('Receipt Number'), self.receipt_number),
            (_('Student'), self.student_id.name),
            (_('Date'), str(self.payment_date or '')),
            (_('Amount'), '%.2f %s' % (self.amount, self.currency_id.symbol or '')),
            (_('Payment Method'), self.payment_method_id.name),
            (_('Reference'), self.reference or '-'),
            (_('Received By'), self.received_by.name or ''),
            (_('Group'), self.group_id.name or '-'),
        ]
        header = [_('Installment'), _('Fee'), _('Allocated Amount')]
        rows = [[
            'Installment #%s' % a.installment_id.sequence,
            a.installment_id.fee_id.group_id.name or '-',
            '%.2f' % a.amount,
        ] for a in self.allocation_ids]
        return Utils.build_simple_report(
            title=_('Payment Receipt'), subtitle=self.receipt_number,
            meta_pairs=meta, table_header=header, table_rows=rows, lang=lang,
        )


class EducationGroupReports(models.Model):
    _inherit = 'education.group'

    def action_print_student_list(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/education/report/pdf/group_student_list/%s' % self.id, 'target': 'new'}

    def action_print_financial_summary(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/education/report/pdf/group_financial_summary/%s' % self.id, 'target': 'new'}

    def action_open_attendance_sheet_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Print Attendance Sheet'),
            'res_model': 'education.group.attendance.sheet.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_group_id': self.id},
        }

    def get_student_list_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = self.env['education.report.utils'].get_report_language()
        meta = [
            (_('Group'), self.name),
            (_('Subject'), self.subject_id.name or ''),
            (_('Teacher'), self.teacher_id.name or ''),
            (_('Capacity'), '%s / %s' % (self.current_student_count, self.capacity)),
        ]
        header = [_('Code'), _('Student'), _('Mobile'), _('Guardian'), _('Status')]
        active_enrollments = self.enrollment_ids.filtered(lambda e: e.state == 'active')
        rows = [[
            e.student_id.student_code, e.student_id.name, e.student_id.mobile or '',
            ', '.join(e.student_id.guardian_ids.mapped('name')) or '-',
            dict(e._fields['state'].selection).get(e.state, ''),
        ] for e in active_enrollments]
        return Utils.build_simple_report(
            title=_('Group Student List'), subtitle=self.name,
            meta_pairs=meta, table_header=header, table_rows=rows, lang=lang,
        )

    def get_financial_summary_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = self.env['education.report.utils'].get_report_language()
        active_enrollments = self.enrollment_ids.filtered(lambda e: e.state == 'active')
        meta = [
            (_('Group'), self.name),
            (_('Total Students'), str(len(active_enrollments))),
        ]
        header = [_('Student'), _('Net Fee'), _('Paid'), _('Outstanding')]
        rows = [[
            e.student_id.name, '%.2f' % e.net_fee, '%.2f' % e.paid_amount, '%.2f' % e.outstanding_amount,
        ] for e in active_enrollments]
        totals = [
            (_('Total Fees'), '%.2f' % sum(active_enrollments.mapped('net_fee'))),
            (_('Total Collected'), '%.2f' % self.total_collected),
            (_('Total Outstanding'), '%.2f' % self.total_outstanding),
        ]
        return Utils.build_simple_report(
            title=_('Group Financial Summary'), subtitle=self.name,
            meta_pairs=meta, table_header=header, table_rows=rows, totals=totals, lang=lang,
        )


class EducationCertificateReports(models.Model):
    _inherit = 'education.certificate'

    def action_print_certificate(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/education/report/pdf/certificate/%s' % self.id, 'target': 'new'}

    def get_certificate_pdf(self):
        """Decorative single-page certificate, drawn free-form on a ReportLab
        canvas (a plain table layout wouldn't suit this document), including
        a native ReportLab QR code (no external qrcode/Pillow dependency).
        Layout is driven by education.certificate.template when one is set,
        so different certificate types/looks don't require code changes."""
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = Utils.get_report_language()
        from reportlab.lib import colors as rl_colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm

        tmpl = self.template_id
        header_text = tmpl.header_text if tmpl else 'CERTIFICATE'
        intro_text = tmpl.intro_text if tmpl else 'This is to certify that'
        border_hex = tmpl.border_color if tmpl else '#2c3e50'
        accent_hex = tmpl.accent_color if tmpl else '#2c3e50'
        show_qr = tmpl.show_qr_code if tmpl else True
        show_signature = tmpl.show_signature_line if tmpl else True
        footer_text = tmpl.footer_text if tmpl else None

        buffer, c, width, height = Utils.new_canvas_document(pagesize=A4)

        c.setStrokeColor(rl_colors.HexColor(border_hex))
        c.setLineWidth(3)
        margin = 1.2 * cm
        c.rect(margin, margin, width - 2 * margin, height - 2 * margin)

        logo_reader = Utils.get_logo_reader()
        if logo_reader is not None:
            logo_size = 1.4 * cm
            try:
                c.drawImage(logo_reader, width / 2 - logo_size / 2, height - 0.9 * cm - logo_size,
                            width=logo_size, height=logo_size, mask='auto', preserveAspectRatio=True)
            except Exception:  # noqa: BLE001 - a broken logo must never block certificate generation
                pass

        def centered(text, y, font='Helvetica', size=12, color='#1a1a1a'):
            c.setFont(font, size)
            c.setFillColor(rl_colors.HexColor(color))
            c.drawCentredString(width / 2, y, Utils.shape_text(text, lang))

        centered(header_text, height - 175, 'Helvetica-Bold', 26, accent_hex)
        centered((dict(self._fields['certificate_type'].selection).get(self.certificate_type, '') or '').upper(),
                  height - 200, 'Helvetica', 11, '#7f8c8d')
        centered(intro_text, height - 245, 'Helvetica', 13, '#555555')
        centered(self.student_id.name, height - 280, 'Helvetica-Bold', 22, '#111111')

        line_y = height - 315
        if self.subject_id:
            text = 'has successfully completed %s' % self.subject_id.name
            if self.group_id:
                text += ' — %s' % self.group_id.name
            centered(text, line_y, 'Helvetica', 12, '#555555')
            line_y -= 20
        if self.academic_year_id:
            centered('Academic Year: %s' % self.academic_year_id.name, line_y, 'Helvetica', 12, '#555555')
            line_y -= 30

        detail_y = line_y - 10
        details = []
        if self.final_percentage:
            details.append('Final Percentage: %.1f%%' % self.final_percentage)
        if self.final_grade:
            details.append('Grade: %s' % self.final_grade)
        if self.result:
            details.append('Result: %s' % dict(self._fields['result'].selection).get(self.result, ''))
        for d in details:
            centered(d, detail_y, 'Helvetica-Bold', 12, accent_hex)
            detail_y -= 18

        footer_line = footer_text or ('Issued on %s — Certificate No. %s' % (self.issue_date, self.certificate_number))
        centered(footer_line, detail_y - 15, 'Helvetica', 9, '#888888')
        if footer_text:
            centered('Issued on %s — Certificate No. %s' % (self.issue_date, self.certificate_number),
                      detail_y - 30, 'Helvetica', 8, '#aaaaaa')

        # Signature line (left) + QR code (right)
        if show_signature:
            sig_x = width / 2 - 220
            c.setStrokeColor(rl_colors.HexColor('#333333'))
            c.setLineWidth(1)
            c.line(sig_x, 110, sig_x + 140, 110)
            c.setFont('Helvetica', 9)
            c.setFillColor(rl_colors.HexColor('#888888'))
            c.drawCentredString(sig_x + 70, 96, 'Signature')

        if self.qr_token and show_qr:
            qr_x = width / 2 + 90
            Utils.draw_qr_code(c, self.verification_url, qr_x, 90, size=80)
            c.setFont('Helvetica', 8)
            c.drawCentredString(qr_x + 40, 78, 'Scan to verify')

        c.showPage()
        c.save()
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes


class EducationExamReports(models.Model):
    _inherit = 'education.exam'

    def action_print_group_result(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': '/education/report/pdf/group_result/%s' % self.id, 'target': 'new'}

    def get_group_result_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = self.env['education.report.utils'].get_report_language()
        meta = [
            (_('Exam'), self.name),
            (_('Group'), self.group_id.name),
            (_('Subject'), self.subject_id.name or ''),
            (_('Date'), str(self.exam_date or '')),
        ]
        header = [_('Rank'), _('Student'), _('Mark / Max'), _('%'), _('Grade'), _('Result')]
        rows = [[
            str(r.rank or ''), r.student_id.name, '%.1f / %.1f' % (r.mark, r.max_mark),
            '%.1f%%' % r.percentage, r.grade or '', _('Pass') if r.passed else _('Fail'),
        ] for r in self.result_ids.sorted('rank')]
        totals = [
            (_('Average %'), '%.1f%%' % self.average_percentage),
            (_('Pass Rate'), '%.1f%%' % self.pass_rate),
        ]
        return Utils.build_simple_report(
            title=_('Group Result Report'), subtitle='%s - %s' % (self.name, self.group_id.name),
            meta_pairs=meta, table_header=header, table_rows=rows, totals=totals, lang=lang,
        )


class EducationTeacherReports(models.Model):
    _inherit = 'education.teacher'

    def action_print_performance_report(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url',
                'url': '/education/report/pdf/teacher_performance/%s' % self.id, 'target': 'new'}

    def action_print_id_card(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url',
                'url': '/education/report/pdf/teacher_id_card/%s' % self.id, 'target': 'new'}

    def get_id_card_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        photo_bytes = base64.b64decode(self.photo) if self.photo else None
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        qr_value = '%s/education/teacher/portal' % base_url
        return Utils.build_id_card_pdf(
            name=self.name, code=self.teacher_code, role_label=_('Teacher'),
            qr_value=qr_value, photo_bytes=photo_bytes,
            company_name=self.company_id.name,
        )

    def get_performance_report_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = self.env['education.report.utils'].get_report_language()
        ExamResult = self.env['education.exam.result'].sudo()
        Attendance = self.env['education.attendance'].sudo()

        groups = self.group_ids.filtered(lambda g: g.active)
        group_ids = groups.ids

        attendance_lines = Attendance.search([('group_id', 'in', group_ids)]) if group_ids else Attendance
        if attendance_lines:
            present = len(attendance_lines.filtered(lambda a: a.status in ('present', 'late')))
            overall_attendance_pct = round(present / len(attendance_lines) * 100.0, 1)
        else:
            overall_attendance_pct = 0.0

        exam_results = ExamResult.search([('group_id', 'in', group_ids)]) if group_ids else ExamResult
        avg_exam_pct = round(sum(exam_results.mapped('percentage')) / len(exam_results), 1) if exam_results else 0.0

        meta = [
            (_('Teacher Code'), self.teacher_code),
            (_('Full Name'), self.name),
            (_('Mobile'), self.mobile or ''),
            (_('Subjects'), ', '.join(self.subject_ids.mapped('name')) or '-'),
            (_('Groups Taught'), str(self.group_count)),
        ]
        header = [_('Group'), _('Subject'), _('Students'), _('Avg Attendance %'), _('Sessions')]
        rows = [[
            g.name, g.subject_id.name or '', str(g.current_student_count),
            '%.1f%%' % g.average_attendance_percentage, str(g.session_count),
        ] for g in groups]
        totals = [
            (_('Total Sessions'), str(self.session_count)),
            (_('Completed Sessions'), str(self.session_completed_count)),
            (_('Overall Attendance % (all groups)'), '%.1f%%' % overall_attendance_pct),
            (_('Average Exam Result % (all groups)'), '%.1f%%' % avg_exam_pct),
        ]
        return Utils.build_simple_report(
            title=_('Teacher Performance Report'), subtitle=self.name,
            meta_pairs=meta, table_header=header, table_rows=rows, totals=totals, lang=lang,
        )
