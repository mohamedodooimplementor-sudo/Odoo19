# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import fields, models, _
from odoo.exceptions import UserError


class EducationIncomeStatementWizard(models.TransientModel):
    """Profit & Loss for the center over a period:
    Net Revenue (Fees Collected - Refunds Paid)
    minus Total Expenses (Teacher Payouts + Operating Expenses, by category)
    = Net Profit."""
    _name = 'education.income.statement.wizard'
    _description = 'Income Statement (Profit & Loss) Wizard'

    date_from = fields.Date(string='From', required=True,
                             default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)

    def action_print(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('"From" date must be before "To" date.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/pdf/income_statement/%s' % self.id,
            'target': 'new',
        }

    def action_export_excel(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('"From" date must be before "To" date.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/xlsx/income_statement/%s' % self.id,
            'target': 'new',
        }

    def _get_report_data(self):
        self.ensure_one()
        Payment = self.env['education.payment']
        Refund = self.env['education.refund']
        Payout = self.env['education.teacher.payout']
        Expense = self.env['education.expense']

        payments = Payment.search([
            ('state', '=', 'confirmed'),
            ('payment_date', '>=', self.date_from), ('payment_date', '<=', self.date_to),
        ])
        refunds = Refund.search([
            ('state', '=', 'paid'),
            ('refund_date', '>=', self.date_from), ('refund_date', '<=', self.date_to),
        ])
        payouts = Payout.search([
            ('state', '=', 'paid'),
            ('payment_date', '>=', self.date_from), ('payment_date', '<=', self.date_to),
        ])
        expenses = Expense.search([
            ('state', '=', 'paid'),
            ('expense_date', '>=', self.date_from), ('expense_date', '<=', self.date_to),
        ])

        gross_income = sum(payments.mapped('amount'))
        total_refunds = sum(refunds.mapped('amount'))
        net_revenue = gross_income - total_refunds

        by_category = {}
        for exp in expenses:
            cat = exp.category_id.name or _('Uncategorized')
            by_category[cat] = by_category.get(cat, 0.0) + exp.amount
        teacher_payouts_total = sum(payouts.mapped('amount'))
        total_expenses = sum(by_category.values()) + teacher_payouts_total

        net_profit = net_revenue - total_expenses

        header = [_('Line'), _('Amount')]
        rows = [
            [_('Fees Collected (Gross)'), '%.2f' % gross_income],
            [_('Less: Refunds Paid'), '(%.2f)' % total_refunds],
            [_('Net Revenue'), '%.2f' % net_revenue],
            ['', ''],
            [_('Teacher Payouts'), '%.2f' % teacher_payouts_total],
        ]
        for cat, amount in sorted(by_category.items()):
            rows.append(['%s - %s' % (_('Expense'), cat), '%.2f' % amount])
        rows.append([_('Total Expenses'), '%.2f' % total_expenses])
        rows.append(['', ''])
        rows.append([_('Net Profit / (Loss)'), '%.2f' % net_profit])

        totals = [(_('Net Profit / (Loss)'), '%.2f' % net_profit)]
        meta = [
            (_('Period From'), str(self.date_from)),
            (_('Period To'), str(self.date_to)),
        ]
        return meta, header, rows, totals

    def get_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = Utils.get_report_language()
        meta, header, rows, totals = self._get_report_data()
        return Utils.build_simple_report(
            title=_('Income Statement (Profit & Loss)'),
            subtitle='%s - %s' % (self.date_from, self.date_to),
            meta_pairs=meta, table_header=header, table_rows=rows, totals=totals, lang=lang,
        )

    def get_excel(self):
        self.ensure_one()
        ExcelUtils = self.env['education.excel.utils']
        meta, header, rows, totals = self._get_report_data()
        return ExcelUtils.build_simple_excel(
            title=_('Income Statement'), meta_pairs=meta,
            table_header=header, table_rows=rows, totals=totals, sheet_name='Income Statement',
        )


class EducationCashBookWizard(models.TransientModel):
    """A chronological ledger (a 'bank statement') of every money movement
    in/out of one cash/bank account (or all of them combined), with a
    running balance - the module's answer to Odoo Accounting's Cash Book /
    Bank Book report."""
    _name = 'education.cash.book.wizard'
    _description = 'Cash Book / Treasury Ledger Wizard'

    cash_account_id = fields.Many2one('education.cash.account', string='Account (leave empty for all)')
    date_from = fields.Date(string='From', required=True,
                             default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)

    def action_print(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('"From" date must be before "To" date.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/pdf/cash_book/%s' % self.id,
            'target': 'new',
        }

    def action_export_excel(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('"From" date must be before "To" date.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/xlsx/cash_book/%s' % self.id,
            'target': 'new',
        }

    def _get_report_data(self):
        self.ensure_one()
        accounts = self.cash_account_id or self.env['education.cash.account'].search([])
        header = [_('Date'), _('Document'), _('Description'), _('In'), _('Out'), _('Balance')]
        rows = []
        grand_total_in = 0.0
        grand_total_out = 0.0
        extra_tables = []
        for account in accounts:
            opening_in, opening_out = account._get_movement_totals(date_to=self.date_from - timedelta(days=1))
            balance = account.opening_balance + opening_in - opening_out
            account_rows = [['', '', _('Opening Balance'), '', '', '%.2f' % balance]]
            for line in account.get_ledger_lines(self.date_from, self.date_to):
                balance += line['in_amount'] - line['out_amount']
                account_rows.append([
                    str(line['date'] or ''), line['doc'] or '', line['description'],
                    '%.2f' % line['in_amount'] if line['in_amount'] else '',
                    '%.2f' % line['out_amount'] if line['out_amount'] else '',
                    '%.2f' % balance,
                ])
                grand_total_in += line['in_amount']
                grand_total_out += line['out_amount']
            account_rows.append(['', '', _('Closing Balance'), '', '', '%.2f' % balance])
            if len(accounts) > 1:
                extra_tables.append((account.name, header, account_rows))
            else:
                rows = account_rows

        totals = [
            (_('Total In'), '%.2f' % grand_total_in),
            (_('Total Out'), '%.2f' % grand_total_out),
        ]
        meta = [
            (_('Account'), self.cash_account_id.name or _('All Accounts')),
            (_('Period From'), str(self.date_from)),
            (_('Period To'), str(self.date_to)),
        ]
        return meta, header, rows, totals, extra_tables

    def get_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = Utils.get_report_language()
        meta, header, rows, totals, extra_tables = self._get_report_data()
        return Utils.build_simple_report(
            title=_('Cash Book'), subtitle='%s - %s' % (self.date_from, self.date_to),
            meta_pairs=meta, table_header=header if rows else None, table_rows=rows if rows else None,
            totals=totals, lang=lang, extra_tables=extra_tables,
        )

    def get_excel(self):
        self.ensure_one()
        ExcelUtils = self.env['education.excel.utils']
        meta, header, rows, totals, extra_tables = self._get_report_data()
        if not rows and extra_tables:
            # Multi-account export: flatten each account's section into the
            # single sheet build_simple_excel supports, with a header row
            # per account so the split is still visible in the spreadsheet.
            rows = []
            for account_name, section_header, section_rows in extra_tables:
                rows.append([account_name, '', '', '', '', ''])
                rows.extend(section_rows)
        return ExcelUtils.build_simple_excel(
            title=_('Cash Book'), meta_pairs=meta,
            table_header=header, table_rows=rows, totals=totals, sheet_name='Cash Book',
        )


class EducationExpenseReportWizard(models.TransientModel):
    """A simple ledger of paid/approved expenses over a period, grouped by
    category - the module's version of Odoo Accounting's expense analysis."""
    _name = 'education.expense.report.wizard'
    _description = 'Expense Report Wizard'

    category_id = fields.Many2one('education.expense.category', string='Category (optional filter)')
    date_from = fields.Date(string='From', required=True,
                             default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(string='To', required=True, default=fields.Date.context_today)
    include_states = fields.Selection([
        ('paid', 'Paid Only'),
        ('approved_paid', 'Approved & Paid'),
        ('all', 'All (except cancelled/rejected)'),
    ], string='Include', default='paid', required=True)

    def action_print(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('"From" date must be before "To" date.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/pdf/expense_report/%s' % self.id,
            'target': 'new',
        }

    def action_export_excel(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_('"From" date must be before "To" date.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/education/report/xlsx/expense_report/%s' % self.id,
            'target': 'new',
        }

    def _get_states(self):
        return {
            'paid': ['paid'],
            'approved_paid': ['approved', 'paid'],
            'all': ['draft', 'submitted', 'approved', 'paid'],
        }[self.include_states]

    def _get_report_data(self):
        self.ensure_one()
        domain = [
            ('expense_date', '>=', self.date_from), ('expense_date', '<=', self.date_to),
            ('state', 'in', self._get_states()),
        ]
        if self.category_id:
            domain.append(('category_id', '=', self.category_id.id))
        expenses = self.env['education.expense'].search(domain, order='expense_date')

        header = [_('Ref'), _('Date'), _('Category'), _('Description'), _('Paid To'), _('Amount'), _('Status')]
        rows = [[
            e.name, str(e.expense_date), e.category_id.name or '', e.description or '',
            e.payee or '', '%.2f' % e.amount, dict(e._fields['state'].selection).get(e.state, e.state),
        ] for e in expenses]

        by_category = {}
        for e in expenses:
            cat = e.category_id.name or _('Uncategorized')
            by_category[cat] = by_category.get(cat, 0.0) + e.amount

        totals = [(cat, '%.2f' % amount) for cat, amount in sorted(by_category.items())]
        totals.append((_('Grand Total'), '%.2f' % sum(expenses.mapped('amount'))))
        meta = [
            (_('Period From'), str(self.date_from)),
            (_('Period To'), str(self.date_to)),
            (_('Category Filter'), self.category_id.name or _('All Categories')),
        ]
        return meta, header, rows, totals

    def get_pdf(self):
        self.ensure_one()
        Utils = self.env['education.report.utils']
        lang = Utils.get_report_language()
        meta, header, rows, totals = self._get_report_data()
        return Utils.build_simple_report(
            title=_('Expense Report'), subtitle='%s - %s' % (self.date_from, self.date_to),
            meta_pairs=meta, table_header=header, table_rows=rows, totals=totals, lang=lang,
        )

    def get_excel(self):
        self.ensure_one()
        ExcelUtils = self.env['education.excel.utils']
        meta, header, rows, totals = self._get_report_data()
        return ExcelUtils.build_simple_excel(
            title=_('Expense Report'), meta_pairs=meta,
            table_header=header, table_rows=rows, totals=totals, sheet_name='Expense Report',
        )
