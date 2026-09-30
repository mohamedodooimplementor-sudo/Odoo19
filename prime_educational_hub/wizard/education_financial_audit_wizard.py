# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EducationFinancialAuditWizard(models.TransientModel):
    _name = 'education.financial.audit.wizard'
    _description = 'Student Financial Audit Wizard'

    student_id = fields.Many2one('education.student', string='Student', required=True)
    date_from = fields.Date(string='From')
    date_to = fields.Date(string='To')

    def action_print(self):
        self.ensure_one()
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise UserError(_('"From" date must be before "To" date.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/pdf/financial_audit/%s' % self.id,
            'target': 'new',
        }

    def action_export_excel(self):
        self.ensure_one()
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise UserError(_('"From" date must be before "To" date.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/xlsx/financial_audit/%s' % self.id,
            'target': 'new',
        }

    def _in_range(self, d):
        if not d:
            return True
        if self.date_from and d < self.date_from:
            return False
        if self.date_to and d > self.date_to:
            return False
        return True

    def _get_timeline_data(self):
        """Builds one unified, chronologically-sorted timeline mixing every
        money-moving event on this student's account: each Fee's creation,
        every installment's late penalty / early-settlement discount, every
        confirmed Payment (with its allocation breakdown showing exactly
        which installment(s) it funded), and every approved/paid Refund
        (with the allocations it reversed). A running balance column makes
        it usable on its own to settle a dispute with a parent, without
        needing to cross-reference four other screens."""
        self.ensure_one()
        student = self.student_id
        events = []  # each: (date, sort_key, description, charge, payment, is_sub_row)

        for fee in student.fee_ids.filtered(lambda f: f.state == 'confirmed'):
            if self._in_range(fee.date):
                desc = _('Fee Confirmed - %s') % (fee.fee_plan_id.name or fee.display_name)
                if fee.discount_amount:
                    desc += _(' (discount %.1f%% = %.2f applied)') % (fee.discount_percent, fee.discount_amount)
                events.append((fee.date, 0, desc, fee.net_amount, 0.0, False))

            for inst in fee.installment_ids:
                if inst.penalty_applied_on and self._in_range(inst.penalty_applied_on):
                    events.append((
                        inst.penalty_applied_on, 1,
                        _('Late Penalty - Installment #%s (due %s)') % (inst.sequence, inst.due_date),
                        inst.penalty_amount, 0.0, False,
                    ))
                if inst.early_discount_applied_on and self._in_range(inst.early_discount_applied_on):
                    events.append((
                        inst.early_discount_applied_on, 1,
                        _('Early Settlement Discount - Installment #%s (due %s)') % (inst.sequence, inst.due_date),
                        0.0, inst.early_discount_amount, False,
                    ))

        payments = self.env['education.payment'].search([
            ('student_id', '=', student.id), ('state', '=', 'confirmed'),
        ])
        for pay in payments:
            if not self._in_range(pay.payment_date):
                continue
            events.append((
                pay.payment_date, 2,
                _('Payment Received - Receipt %s (%s)') % (pay.receipt_number, pay.payment_method_id.name),
                0.0, pay.amount, False,
            ))
            for alloc in pay.allocation_ids:
                inst = alloc.installment_id
                net = alloc.amount - alloc.refunded_amount
                events.append((
                    pay.payment_date, 3,
                    _('   -> Applied to Installment #%s (due %s): %.2f') % (inst.sequence, inst.due_date, net),
                    0.0, 0.0, True,
                ))
            if pay.unallocated_amount:
                events.append((
                    pay.payment_date, 3,
                    _('   -> Unapplied credit remaining on this payment: %.2f') % pay.unallocated_amount,
                    0.0, 0.0, True,
                ))

        refunds = self.env['education.refund'].search([
            ('student_id', '=', student.id), ('state', 'in', ('approved', 'paid')),
        ])
        for ref in refunds:
            if not self._in_range(ref.refund_date):
                continue
            status = _('paid out') if ref.state == 'paid' else _('approved')
            events.append((
                ref.refund_date, 2,
                _('Refund %s - against Receipt %s (%s)') % (status, ref.payment_id.receipt_number, ref.reason or ''),
                ref.amount, 0.0, False,
            ))
            for line in ref.refund_line_ids:
                inst = line.allocation_id.installment_id
                events.append((
                    ref.refund_date, 3,
                    _('   -> Reversed from Installment #%s (due %s): %.2f') % (inst.sequence, inst.due_date, line.amount),
                    0.0, 0.0, True,
                ))

        events.sort(key=lambda e: (e[0] or fields.Date.today(), e[1]))

        header = [_('Date'), _('Description'), _('Charge'), _('Payment'), _('Balance')]
        rows = []
        balance = 0.0
        total_charge = 0.0
        total_payment = 0.0
        for date, _sort, desc, charge, payment, is_sub in events:
            if not is_sub:
                balance += charge - payment
                total_charge += charge
                total_payment += payment
            rows.append([
                date.strftime('%Y-%m-%d') if date and not is_sub else '',
                desc,
                ('%.2f' % charge) if charge else '',
                ('%.2f' % payment) if payment else '',
                ('%.2f' % balance) if not is_sub else '',
            ])

        meta = [
            (_('Student'), student.name),
            (_('Student Code'), student.student_code),
            (_('Period'), '%s - %s' % (self.date_from or _('Beginning'), self.date_to or _('Today'))),
            (_('Closing Balance'), '%.2f' % balance),
        ]
        totals = ['', _('Totals'), '%.2f' % total_charge, '%.2f' % total_payment, '%.2f' % balance]
        return meta, header, rows, totals

    def get_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = Utils.get_report_language()
        meta, header, rows, totals = self._get_timeline_data()
        return Utils.build_simple_report(
            title=_('Student Financial Audit'), subtitle=self.student_id.name,
            meta_pairs=meta, table_header=header, table_rows=rows, lang=lang,
        )

    def get_excel(self):
        self.ensure_one()
        ExcelUtils = self.env['education.excel.utils']
        meta, header, rows, totals = self._get_timeline_data()
        return ExcelUtils.build_simple_excel(
            title=_('Student Financial Audit'), meta_pairs=meta,
            table_header=header, table_rows=rows, totals=totals, sheet_name='Financial Audit',
        )
