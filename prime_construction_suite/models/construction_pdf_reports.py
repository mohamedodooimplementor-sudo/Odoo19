# -*- coding: utf-8 -*-
"""All PDF reports for Prime Construction Suite, built directly with ReportLab (same approach
as the Stock Card module) instead of QWeb + wkhtmltopdf. Each method returns raw PDF bytes;
the routes in controllers/main.py stream them to the browser."""
from datetime import timedelta

from odoo import models, api, fields

from .construction_pdf_builder import (
    build_pdf_bytes, header_block, kpi_row, section_title, data_table, signature_block,
    get_styles, fmt, PRIMARY, SUCCESS, DANGER, WARNING, MUTED, TEXT_DARK,
)

try:
    from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.units import mm
except ImportError:
    # construction_pdf_builder.require_reportlab() raises a clean, user-facing error before any
    # of these names would actually be used to build a document — this only prevents the whole
    # addon from failing to load when reportlab isn't installed on the server yet.
    Paragraph = Spacer = Table = TableStyle = None
    mm = 1


# ═══════════════════════════════════════════════════════════════════════════
# Project: Project Summary, Executive Dashboard (portfolio), Cost Analysis
# ═══════════════════════════════════════════════════════════════════════════
class ConstructionProject(models.Model):
    _inherit = 'construction.project'

    def action_print_project_summary_pdf(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/prime_construction_suite/report/project_summary/%s' % self.id,
            'target': 'self',
        }

    def action_print_cost_analysis_pdf(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/prime_construction_suite/report/cost_analysis/%s' % self.id,
            'target': 'self',
        }

    @api.model
    def action_print_executive_dashboard_pdf(self, project_ids=None):
        ids_param = ','.join(str(i) for i in project_ids) if project_ids else ''
        return {
            'type': 'ir.actions.act_url',
            'url': '/prime_construction_suite/report/executive_dashboard' + (
                '?ids=%s' % ids_param if ids_param else ''),
            'target': 'self',
        }

    def _build_pdf_project_summary(self):
        self.ensure_one()
        doc = self
        styles = get_styles()
        story = header_block('Project Summary', doc.name, doc.code or '')

        info_rows = [
            ['Client', doc.client_id.name or '—'],
            ['Project Manager', doc.project_manager_id.name or '—'],
            ['Site Address', doc.site_address or '—'],
            ['Start Date', str(doc.date_start or '—')],
            ['End Date', str(doc.date_end or '—')],
            ['Status', (doc.state or '').title()],
        ]
        fin_rows = [['Contract Value', fmt(doc.contract_value, 2) + ' ' + (doc.currency_id.symbol or '')]]
        if doc.contract_id:
            fin_rows += [
                ['Revised Value', fmt(doc.contract_id.revised_contract_value, 2)],
                ['Total Invoiced', fmt(doc.contract_id.invoiced_amount, 2)],
                ['Remaining Balance', fmt(doc.contract_id.remaining_amount, 2)],
            ]
        fin_rows.append(['Progress', '{:.1f}%'.format(doc.progress_percent)])

        two_col = Table([[
            data_table(['Project Information', ''], info_rows, col_widths=[45 * mm, 40 * mm]),
            data_table(['Financial Summary', ''], fin_rows, col_widths=[45 * mm, 40 * mm]),
        ]], colWidths=[87 * mm, 87 * mm])
        two_col.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
        story.append(two_col)

        if doc.contract_id and doc.contract_id.boq_line_ids:
            story.append(section_title('Bill of Quantities'))
            rows = []
            for i, line in enumerate(doc.contract_id.boq_line_ids, 1):
                rows.append([
                    i, line.description or '', line.uom_id.name or '—',
                    fmt(line.qty_contract, 3), fmt(line.unit_price, 2), fmt(line.total_price, 2),
                    '{:.1f}%'.format(line.physical_completion_percent),
                ])
            story.append(data_table(
                ['#', 'Description', 'UoM', 'Qty', 'Price', 'Total', 'Progress %'], rows,
                col_widths=[10 * mm, 60 * mm, 15 * mm, 22 * mm, 22 * mm, 25 * mm, 24 * mm],
                align_right_cols=[3, 4, 5]))

        if doc.contract_id and doc.contract_id.progress_invoice_ids:
            story.append(section_title('Progress Invoice History'))
            rows = []
            for inv in doc.contract_id.progress_invoice_ids:
                rows.append([inv.name, str(inv.date or ''), fmt(inv.gross_amount, 2),
                             fmt(inv.retention_amount, 2), fmt(inv.net_amount, 2), (inv.state or '').title()])
            story.append(data_table(
                ['Invoice No.', 'Date', 'Gross', 'Retention', 'Net', 'Status'], rows,
                col_widths=[30 * mm, 22 * mm, 28 * mm, 28 * mm, 28 * mm, 38 * mm],
                align_right_cols=[2, 3, 4]))

        story.append(Spacer(1, 30))
        story.append(signature_block(['Project Manager', 'Financial Manager', 'General Manager']))
        return build_pdf_bytes(story, title='Project Summary - %s' % doc.name)

    def _build_pdf_cost_analysis(self):
        self.ensure_one()
        project = self
        contract = project.contract_id
        boq_lines = contract.boq_line_ids if contract else self.env['construction.boq.line']
        costs = project.cost_ids

        codes = (boq_lines.mapped('cost_code_id') | costs.mapped('cost_code_id'))
        by_code = []
        for code in codes:
            budget = sum(boq_lines.filtered(lambda l: l.cost_code_id == code).mapped('total_price'))
            actual = sum(costs.filtered(lambda c: c.cost_code_id == code and c.state == 'approved').mapped('amount'))
            by_code.append({'code': code.display_name, 'budget': budget, 'actual': actual, 'variance': budget - actual})
        uncoded_budget = sum(boq_lines.filtered(lambda l: not l.cost_code_id).mapped('total_price'))
        uncoded_actual = sum(costs.filtered(lambda c: not c.cost_code_id and c.state == 'approved').mapped('amount'))
        if uncoded_budget or uncoded_actual:
            by_code.append({'code': 'Uncoded', 'budget': uncoded_budget, 'actual': uncoded_actual,
                             'variance': uncoded_budget - uncoded_actual})
        by_code.sort(key=lambda r: r['budget'], reverse=True)

        type_labels = {'material': 'Materials', 'labor': 'Labor', 'equipment': 'Equipment',
                       'subcontract': 'Subcontractors', 'overhead': 'Overhead', 'other': 'Other'}
        approved_costs = costs.filtered(lambda c: c.state == 'approved')
        total_actual = sum(approved_costs.mapped('amount'))
        by_type = []
        for key, label in type_labels.items():
            amount = sum(approved_costs.filtered(lambda c: c.cost_type == key).mapped('amount'))
            if amount:
                by_type.append({'label': label, 'amount': amount,
                                 'percent': (amount / total_actual * 100) if total_actual else 0.0})

        contract_value = (contract.revised_contract_value if contract else project.contract_value) or 0.0
        variance = contract_value - total_actual

        styles = get_styles()
        story = header_block('Cost Analysis', project.name)
        story.append(kpi_row([
            ('Contract Value', fmt(contract_value), TEXT_DARK),
            ('Total Actual Cost', fmt(total_actual), TEXT_DARK),
            ('Variance', fmt(variance), SUCCESS if variance >= 0 else DANGER),
        ]))
        story.append(Spacer(1, 10))

        story.append(section_title('Actual Cost by Type'))
        if by_type:
            rows = [[r['label'], fmt(r['amount'], 2), '{:.1f}%'.format(r['percent'])] for r in by_type]
            story.append(data_table(['Cost Type', 'Amount', '% of Total'], rows,
                                     col_widths=[80 * mm, 45 * mm, 45 * mm], align_right_cols=[1, 2]))
        else:
            story.append(Paragraph('No approved costs yet', styles['normal_muted']))

        story.append(section_title('Budget vs. Actual by Cost Code (WBS)'))
        if by_code:
            rows = [[r['code'], fmt(r['budget'], 2), fmt(r['actual'], 2), fmt(r['variance'], 2)] for r in by_code]
            story.append(data_table(['Cost Code', 'Budget (BOQ)', 'Actual', 'Variance'], rows,
                                     col_widths=[60 * mm, 40 * mm, 40 * mm, 30 * mm], align_right_cols=[1, 2, 3]))
        else:
            story.append(Paragraph('No cost codes assigned yet', styles['normal_muted']))

        s_curve = self._compute_s_curve(project, contract_value)
        if s_curve:
            story.append(section_title('S-Curve: Cumulative Planned vs. Actual'))
            story.append(Paragraph(
                "Planned is a straight-line distribution of contract value across the project's "
                "dates (a simplified baseline pending a fully cash-flow-loaded schedule).",
                styles['normal_muted']))
            story.append(Spacer(1, 4))
            rows = [[r['month'], fmt(r['planned_cum']), fmt(r['invoiced_cum']), fmt(r['cost_cum'])] for r in s_curve]
            story.append(data_table(['Month', 'Planned (Cum.)', 'Invoiced (Cum.)', 'Actual Cost (Cum.)'], rows,
                                     col_widths=[35 * mm, 45 * mm, 45 * mm, 45 * mm], align_right_cols=[1, 2, 3]))

        return build_pdf_bytes(story, title='Cost Analysis - %s' % project.name)

    def _compute_s_curve(self, project, contract_value):
        """MVP S-Curve: cumulative Planned value (linear distribution of contract value across
        the project's Start→End dates) vs cumulative Invoiced and cumulative Actual Cost, by month."""
        from dateutil.relativedelta import relativedelta

        if not project.date_start or not project.date_end or project.date_end <= project.date_start:
            return []
        months = []
        cursor = project.date_start.replace(day=1)
        end_month = project.date_end.replace(day=1)
        while cursor <= end_month:
            months.append(cursor)
            cursor = cursor + relativedelta(months=1)
        if not months:
            return []

        total_days = (project.date_end - project.date_start).days or 1
        invoices = project.contract_id.progress_invoice_ids.filtered(
            lambda i: i.state in ('approved', 'invoiced', 'paid')) if project.contract_id else self.env['construction.progress.invoice']
        costs = project.cost_ids.filtered(lambda c: c.state == 'approved')

        rows = []
        for month_start in months:
            month_end = (month_start + relativedelta(months=1)) - relativedelta(days=1)
            elapsed_days = max(min((month_end - project.date_start).days + 1, total_days), 0)
            planned_to_date = contract_value * (elapsed_days / total_days)
            invoiced_to_date = sum(invoices.filtered(lambda inv: inv.date and inv.date <= month_end).mapped('gross_amount'))
            cost_to_date = sum(costs.filtered(lambda c: c.date and c.date <= month_end).mapped('amount'))
            rows.append({'month': month_start.strftime('%b %Y'), 'planned_cum': planned_to_date,
                         'invoiced_cum': invoiced_to_date, 'cost_cum': cost_to_date})
        return rows

    @api.model
    def _build_pdf_executive_dashboard(self, projects):
        Project = self.env['construction.project']
        if not projects:
            projects = Project.search([])
        dash_rows = self.env['construction.project.dashboard'].search([('project_id', 'in', projects.ids)])
        dash_by_project = {d.project_id.id: d for d in dash_rows}

        rows = []
        total_invoiced = total_cost = total_contract = 0.0
        profit_count = loss_count = neutral_count = 0
        for p in projects:
            d = dash_by_project.get(p.id)
            invoiced = d.invoiced_amount if d else 0.0
            cost = d.actual_cost if d else 0.0
            contract_value = (d.contract_value if d else p.contract_value) or 0.0
            profit = invoiced - cost
            if invoiced or cost:
                status = 'Profitable' if profit >= 0 else 'At Loss'
                profit_count += 1 if profit >= 0 else 0
                loss_count += 1 if profit < 0 else 0
            else:
                status = 'No Data Yet'
                neutral_count += 1
            total_invoiced += invoiced
            total_cost += cost
            total_contract += contract_value
            rows.append({'project': p, 'invoiced': invoiced, 'cost': cost, 'profit': profit, 'status': status})
        rows.sort(key=lambda r: abs(r['profit']), reverse=True)

        today = fields.Date.context_today(self)
        in_30_days = today + timedelta(days=30)
        boq_lines = self.env['construction.boq.line'].search([('contract_id.project_id', 'in', projects.ids)])
        boq_value_total = sum(boq_lines.mapped('total_price'))
        overall_physical_completion = (
            sum(l.total_price * l.physical_completion_percent for l in boq_lines) / boq_value_total
            if boq_value_total else 0.0)
        delayed_projects = projects.filtered(lambda p: p.state == 'running' and p.date_end and p.date_end < today)
        contracts = self.env['construction.contract'].search([('project_id', 'in', projects.ids)])
        near_completion_contracts = contracts.filtered(
            lambda c: c.state == 'active' and c.date_end and today <= c.date_end <= in_30_days)
        open_breakdowns = self.env['construction.equipment.breakdown'].search_count(
            [('project_id', 'in', projects.ids), ('status', '!=', 'resolved')])

        styles = get_styles()
        story = header_block('Executive Dashboard', 'Construction Portfolio Overview',
                              'Generated on %s' % fields.Date.context_today(self))
        story.append(kpi_row([
            ('Contract Value', fmt(total_contract), TEXT_DARK),
            ('Total Invoiced', fmt(total_invoiced), TEXT_DARK),
            ('Actual Cost', fmt(total_cost), TEXT_DARK),
            ('Net Profit', fmt(total_invoiced - total_cost), SUCCESS if total_invoiced >= total_cost else DANGER),
        ]))
        story.append(Spacer(1, 8))
        story.append(kpi_row([
            ('Physical Completion', '{:.0f}%'.format(overall_physical_completion), PRIMARY),
            ('Delayed Projects', str(len(delayed_projects)), DANGER if delayed_projects else TEXT_DARK),
            ('Open Equip. Breakdowns', str(open_breakdowns), DANGER if open_breakdowns else TEXT_DARK),
            ('Ending Within 30d', str(len(near_completion_contracts)), WARNING if near_completion_contracts else TEXT_DARK),
        ]))
        story.append(Spacer(1, 10))
        story.append(Paragraph(
            'Profitable: %d &nbsp;&nbsp; At Loss: %d &nbsp;&nbsp; No Data Yet: %d' % (
                profit_count, loss_count, neutral_count), styles['normal']))

        story.append(section_title('Projects'))
        row_data = [[r['project'].name, fmt(r['invoiced']), fmt(r['cost']), fmt(r['profit']), r['status']]
                    for r in rows]
        story.append(data_table(['Project', 'Invoiced', 'Actual Cost', 'Profit / Loss', 'Status'], row_data,
                                 col_widths=[50 * mm, 32 * mm, 32 * mm, 32 * mm, 28 * mm],
                                 align_right_cols=[1, 2, 3]))

        if near_completion_contracts:
            story.append(section_title('Contracts Nearing Completion (next 30 days)'))
            rows2 = [[c.project_id.name, str(c.date_end), fmt(c.remaining_amount)] for c in near_completion_contracts]
            story.append(data_table(['Project', 'End Date', 'Remaining Amount'], rows2,
                                     col_widths=[80 * mm, 40 * mm, 50 * mm], align_right_cols=[2]))

        return build_pdf_bytes(story, title='Executive Dashboard')

    def action_print_procurement_report_pdf(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url',
                'url': '/prime_construction_suite/report/procurement/%s' % self.id, 'target': 'self'}

    def _build_pdf_procurement_report(self):
        self.ensure_one()
        project = self
        styles = get_styles()
        story = header_block('Procurement Report', project.name,
                              'Generated on %s' % fields.Date.context_today(self))

        mrs = self.env['construction.material.request'].search([('project_id', '=', project.id)])
        rfqs = self.env['construction.rfq'].search([('project_id', '=', project.id)])
        pos = self.env['purchase.order'].search([('construction_project_id', '=', project.id)])
        issues = self.env['construction.site.issue'].search([('project_id', '=', project.id)])
        returns = self.env['construction.material.return'].search([('project_id', '=', project.id)])

        story.append(kpi_row([
            ('Material Requests', str(len(mrs)), TEXT_DARK),
            ('RFQs', str(len(rfqs)), TEXT_DARK),
            ('Purchase Orders', str(len(pos)), TEXT_DARK),
            ('PO Value', fmt(sum(pos.mapped('amount_total'))), PRIMARY),
        ]))
        story.append(Spacer(1, 8))

        story.append(section_title('Purchase Orders'))
        if pos:
            rows = [[po.name, po.partner_id.name or '', (po.state or '').title(), fmt(po.amount_total, 2)]
                    for po in pos]
            story.append(data_table(['PO Number', 'Vendor', 'Status', 'Amount'], rows,
                                     col_widths=[40 * mm, 60 * mm, 34 * mm, 34 * mm], align_right_cols=[3]))
        else:
            story.append(Paragraph('No purchase orders yet', styles['normal_muted']))

        story.append(section_title('Material Requests'))
        if mrs:
            rows = [[mr.name, str(mr.date or ''), mr.priority.title(), (mr.state or '').title()] for mr in mrs]
            story.append(data_table(['Request No.', 'Date', 'Priority', 'Status'], rows,
                                     col_widths=[40 * mm, 30 * mm, 34 * mm, 34 * mm]))
        else:
            story.append(Paragraph('No material requests yet', styles['normal_muted']))

        story.append(section_title('Site Issues &amp; Returns'))
        rows = [[si.name, str(si.date or ''), 'Site Issue', (si.state or '').title()] for si in issues] + \
               [[r.name, str(r.date or ''), 'Return (%s)' % r.return_type, (r.state or '').title()] for r in returns]
        if rows:
            story.append(data_table(['Reference', 'Date', 'Type', 'Status'], rows,
                                     col_widths=[40 * mm, 30 * mm, 40 * mm, 28 * mm]))
        else:
            story.append(Paragraph('No site issues or returns yet', styles['normal_muted']))

        return build_pdf_bytes(story, title='Procurement Report - %s' % project.name)


# ═══════════════════════════════════════════════════════════════════════════
# Contract: BOQ, Contract Summary, BOQ Comparison
# ═══════════════════════════════════════════════════════════════════════════
class ConstructionContract(models.Model):
    _inherit = 'construction.contract'

    def action_print_boq_pdf(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url',
                'url': '/prime_construction_suite/report/boq/%s' % self.id, 'target': 'self'}

    def action_print_contract_summary_pdf(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url',
                'url': '/prime_construction_suite/report/contract_summary/%s' % self.id, 'target': 'self'}

    def action_print_boq_comparison_pdf(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url',
                'url': '/prime_construction_suite/report/boq_comparison/%s' % self.id, 'target': 'self'}

    def action_print_client_statement_pdf(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url',
                'url': '/prime_construction_suite/report/client_statement/%s' % self.id, 'target': 'self'}

    def _build_pdf_client_statement(self):
        self.ensure_one()
        doc = self
        styles = get_styles()
        story = header_block('Client Statement of Account', doc.project_id.client_id.name or '', doc.name)

        invoices = doc.progress_invoice_ids.sorted(key=lambda i: i.date or fields.Date.today())
        total_gross = sum(invoices.mapped('gross_amount'))
        total_retention = sum(invoices.mapped('retention_amount'))
        total_net = sum(invoices.mapped('net_amount'))
        paid = sum(invoices.filtered(lambda i: i.state == 'paid').mapped('net_amount'))
        outstanding = total_net - paid

        story.append(kpi_row([
            ('Contract Value', fmt(doc.revised_contract_value), TEXT_DARK),
            ('Total Invoiced (Net)', fmt(total_net), TEXT_DARK),
            ('Paid to Date', fmt(paid), SUCCESS),
            ('Outstanding Balance', fmt(outstanding), DANGER if outstanding > 0 else SUCCESS),
        ]))
        story.append(Spacer(1, 10))

        rows = []
        running_balance = 0.0
        for inv in invoices:
            running_balance += inv.net_amount
            rows.append([inv.name, str(inv.date or ''), fmt(inv.gross_amount, 2), fmt(inv.retention_amount, 2),
                         fmt(inv.net_amount, 2), (inv.state or '').title(), fmt(running_balance, 2)])
        story.append(data_table(
            ['Invoice No.', 'Date', 'Gross', 'Retention', 'Net', 'Status', 'Cumulative'],
            rows, col_widths=[26 * mm, 20 * mm, 24 * mm, 24 * mm, 24 * mm, 28 * mm, 28 * mm],
            align_right_cols=[2, 3, 4, 6]))

        story.append(Spacer(1, 20))
        story.append(signature_block(['Prepared By', 'Client Acknowledgement']))
        return build_pdf_bytes(story, title='Client Statement - %s' % doc.name)

    def _build_pdf_boq(self):
        self.ensure_one()
        doc = self
        styles = get_styles()
        story = header_block('Bill of Quantities', doc.project_id.name, doc.name)

        sections = doc.boq_line_ids.mapped('section_id')
        unsectioned = doc.boq_line_ids.filtered(lambda l: not l.section_id)

        def _section_table(lines):
            rows = []
            for line in lines:
                rows.append([line.item_code or '', line.description or '', (line.line_type or '').title(),
                             line.uom_id.name or '—', fmt(line.qty_contract, 3), fmt(line.unit_price, 2),
                             fmt(line.total_price, 2), line.cost_code_id.display_name or ''])
            return data_table(
                ['Code', 'Description', 'Type', 'UoM', 'Qty', 'Unit Price', 'Total', 'Cost Code'], rows,
                col_widths=[16 * mm, 48 * mm, 16 * mm, 12 * mm, 18 * mm, 20 * mm, 22 * mm, 22 * mm],
                align_right_cols=[4, 5, 6])

        for section in sections:
            story.append(section_title(section.name))
            lines = doc.boq_line_ids.filtered(lambda l: l.section_id == section)
            story.append(_section_table(lines))
            subtotal = sum(lines.mapped('total_price'))
            story.append(Paragraph('Section Subtotal: %s' % fmt(subtotal, 2), styles['cell_bold']))
            story.append(Spacer(1, 6))

        if unsectioned:
            story.append(section_title('Other Items'))
            story.append(_section_table(unsectioned))

        grand_total = sum(doc.boq_line_ids.mapped('total_price'))
        story.append(Spacer(1, 8))
        story.append(Paragraph('Grand Total: %s %s' % (fmt(grand_total, 2), doc.currency_id.symbol or ''),
                                get_styles()['h2']))
        story.append(Spacer(1, 30))
        story.append(signature_block(['Prepared By', 'Reviewed By', 'Approved By']))
        return build_pdf_bytes(story, landscape_mode=True, title='BOQ - %s' % doc.name)

    def _build_pdf_contract_summary(self):
        self.ensure_one()
        doc = self
        styles = get_styles()
        story = header_block('Contract Summary', doc.project_id.name, doc.name)

        info_rows = [
            ['Client', doc.project_id.client_id.name or '—'],
            ['Start Date', str(doc.date_start or '—')],
            ['End Date', str(doc.date_end or '—')],
            ['Duration', '%s days' % (doc.duration_days or 0)],
            ['Status', (doc.state or '').title()],
        ]
        fin_rows = [
            ['Original Value', fmt(doc.contract_value, 2)],
            ['Change Orders', fmt(doc.change_orders_total, 2)],
            ['Revised Value', fmt(doc.revised_contract_value, 2)],
            ['Invoiced to Date', fmt(doc.invoiced_amount, 2)],
            ['Retention Outstanding', fmt(doc.retention_outstanding, 2)],
            ['Remaining Amount', fmt(doc.remaining_amount, 2)],
        ]
        two_col = Table([[
            data_table(['Contract Information', ''], info_rows, col_widths=[45 * mm, 40 * mm]),
            data_table(['Financial Summary', ''], fin_rows, col_widths=[45 * mm, 40 * mm]),
        ]], colWidths=[87 * mm, 87 * mm])
        two_col.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
        story.append(two_col)

        story.append(section_title('Progress Invoices'))
        if doc.progress_invoice_ids:
            rows = [[inv.name, str(inv.date or ''), fmt(inv.gross_amount, 2), fmt(inv.retention_amount, 2),
                     fmt(inv.net_amount, 2), (inv.state or '').title()] for inv in doc.progress_invoice_ids]
            story.append(data_table(['Invoice No.', 'Date', 'Gross', 'Retention', 'Net', 'Status'], rows,
                                     col_widths=[30 * mm, 22 * mm, 28 * mm, 28 * mm, 28 * mm, 38 * mm],
                                     align_right_cols=[2, 3, 4]))
        else:
            story.append(Paragraph('No progress invoices yet', styles['normal_muted']))

        story.append(section_title('Change Orders'))
        if doc.change_order_ids:
            rows = [[co.name, str(co.date or ''), (co.state or '').title()] for co in doc.change_order_ids]
            story.append(data_table(['Reference', 'Date', 'Status'], rows, col_widths=[80 * mm, 40 * mm, 54 * mm]))
        else:
            story.append(Paragraph('No change orders yet', styles['normal_muted']))

        story.append(Spacer(1, 30))
        story.append(signature_block(['Project Manager', 'Financial Manager', 'Client']))
        return build_pdf_bytes(story, title='Contract Summary - %s' % doc.name)

    def _build_pdf_boq_comparison(self):
        self.ensure_one()
        contract = self
        styles = get_styles()
        story = header_block('BOQ Comparison Report', contract.project_id.name, contract.name)
        story.append(Paragraph(
            'Original Contract Qty vs Current (After Variations) vs Executed on Site', styles['normal_muted']))
        story.append(Spacer(1, 6))

        rows = []
        total_original = total_current = total_executed_value = 0.0
        for line in contract.boq_line_ids:
            qty_changes = line.change_order_line_ids.filtered(
                lambda l: l.change_order_id.state == 'approved' and l.change_type == 'qty'
            ).sorted(key=lambda l: (l.change_order_id.date or fields.Date.today(), l.id))
            original_qty = qty_changes[0].qty_original if qty_changes else line.qty_contract
            current_qty = line.qty_contract
            qty_variance = current_qty - original_qty
            total_original += original_qty * line.unit_price
            total_current += current_qty * line.unit_price
            total_executed_value += line.qty_measured * line.unit_price
            rows.append([
                line.description or '', fmt(original_qty, 2), fmt(current_qty, 2),
                ('+' if qty_variance > 0 else '') + fmt(qty_variance, 2), fmt(qty_variance * line.unit_price, 2),
                fmt(line.qty_measured, 2), fmt(current_qty - line.qty_measured, 2), len(qty_changes),
            ])
        total_variance = total_current - total_original

        story.append(kpi_row([
            ('Original BOQ Value', fmt(total_original), TEXT_DARK),
            ('Current BOQ Value', fmt(total_current), TEXT_DARK),
            ('Net Variation', fmt(total_variance), SUCCESS if total_variance >= 0 else DANGER),
            ('Executed Value', fmt(total_executed_value), PRIMARY),
        ]))
        story.append(Spacer(1, 8))
        story.append(data_table(
            ['Item', 'Original Qty', 'Current Qty', 'Variation', 'Variation Value',
             'Executed Qty', 'Remaining Qty', 'Rev.'],
            rows,
            col_widths=[46 * mm, 20 * mm, 20 * mm, 20 * mm, 24 * mm, 20 * mm, 22 * mm, 12 * mm],
            align_right_cols=[1, 2, 3, 4, 5, 6]))

        return build_pdf_bytes(story, landscape_mode=True, title='BOQ Comparison - %s' % contract.name)


# ═══════════════════════════════════════════════════════════════════════════
# Progress Invoice
# ═══════════════════════════════════════════════════════════════════════════
class ConstructionSubcontractor(models.Model):
    _inherit = 'construction.subcontractor'

    def action_print_vendor_statement_pdf(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url',
                'url': '/prime_construction_suite/report/vendor_statement/%s' % self.id, 'target': 'self'}

    def _build_pdf_vendor_statement(self):
        self.ensure_one()
        doc = self
        styles = get_styles()
        story = header_block('Vendor / Subcontractor Statement', doc.name, doc.project_id.name)

        story.append(kpi_row([
            ('Contract Value', fmt(doc.contract_value), TEXT_DARK),
            ('Paid to Date', fmt(doc.paid_amount), SUCCESS),
            ('Remaining Balance', fmt(doc.contract_value - doc.paid_amount), TEXT_DARK),
            ('Performance Score', '{:.0f}'.format(doc.performance_score), PRIMARY),
        ]))
        story.append(Spacer(1, 8))

        if doc.penalty_ids:
            story.append(section_title('Penalties (Liquidated Damages)'))
            rows = [[p.date, p.reason, fmt(p.amount, 2), (p.state or '').title()] for p in doc.penalty_ids]
            story.append(data_table(['Date', 'Reason', 'Amount', 'Status'], rows,
                                     col_widths=[24 * mm, 80 * mm, 30 * mm, 30 * mm], align_right_cols=[2]))

        if doc.purchase_order_ids:
            story.append(section_title('Purchase Orders'))
            rows = [[po.name, str(po.date_order)[:10] if po.date_order else '', (po.state or '').title(),
                     fmt(po.amount_total, 2)] for po in doc.purchase_order_ids]
            story.append(data_table(['PO Number', 'Date', 'Status', 'Amount'], rows,
                                     col_widths=[40 * mm, 30 * mm, 40 * mm, 34 * mm], align_right_cols=[3]))

        story.append(Spacer(1, 20))
        story.append(signature_block(['Prepared By', 'Vendor Acknowledgement']))
        return build_pdf_bytes(story, title='Vendor Statement - %s' % doc.name)


class ConstructionProgressInvoice(models.Model):
    _inherit = 'construction.progress.invoice'

    def action_print_progress_invoice_pdf(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url',
                'url': '/prime_construction_suite/report/progress_invoice/%s' % self.id, 'target': 'self'}

    def _build_pdf_progress_invoice(self):
        self.ensure_one()
        doc = self
        styles = get_styles()
        story = header_block('Progress Invoice', doc.name)
        story.append(Paragraph(
            'Date: %s &nbsp;&nbsp; Contract: %s &nbsp;&nbsp; Project: %s' % (
                doc.date, doc.contract_id.name, doc.project_id.name), styles['normal']))
        story.append(Paragraph(
            'Client: %s &nbsp;&nbsp; Period: %s to %s &nbsp;&nbsp; Invoice #: %s &nbsp;&nbsp; Status: %s' % (
                doc.client_id.name, doc.date_from or '—', doc.date_to or '—', doc.sequence,
                (doc.state or '').title()), styles['normal_muted']))
        story.append(Spacer(1, 8))

        rows = []
        for i, line in enumerate(doc.line_ids, 1):
            rows.append([i, line.description or '', line.uom_id.name or '—', fmt(line.qty_contract, 3),
                         fmt(line.qty_previous, 3), fmt(line.qty_this_invoice, 3), fmt(line.unit_price, 2),
                         fmt(line.line_amount, 2)])
        story.append(data_table(
            ['#', 'Description', 'UoM', 'Contract Qty', 'Previous Qty', 'This Invoice', 'Unit Price', 'Amount'],
            rows, col_widths=[8 * mm, 45 * mm, 14 * mm, 20 * mm, 20 * mm, 20 * mm, 20 * mm, 22 * mm],
            align_right_cols=[3, 4, 5, 6, 7]))

        totals_rows = [
            ['Gross Amount', fmt(doc.gross_amount, 2)],
            ['Retention (%s%%)' % doc.retention_percent, '(%s)' % fmt(doc.retention_amount, 2)],
            ['Advance Deduction (%s%%)' % doc.advance_deduction_percent, '(%s)' % fmt(doc.advance_deduction, 2)],
        ]
        totals_table = data_table(['', ''], totals_rows, col_widths=[130 * mm, 39 * mm], align_right_cols=[1])
        story.append(Spacer(1, 6))
        story.append(totals_table)
        story.append(Paragraph(
            'Net Amount Due: %s %s' % (fmt(doc.net_amount, 2), doc.currency_id.symbol or ''), get_styles()['h2']))

        story.append(Spacer(1, 30))
        story.append(signature_block(['Prepared By', 'Reviewed By', 'Approved By', 'Client']))
        return build_pdf_bytes(story, title='Progress Invoice - %s' % doc.name)


# ═══════════════════════════════════════════════════════════════════════════
# Equipment Utilization
# ═══════════════════════════════════════════════════════════════════════════
class ConstructionEquipment(models.Model):
    _inherit = 'construction.equipment'

    @api.model
    def action_print_equipment_utilization_pdf(self, equipment_ids=None):
        ids_param = ','.join(str(i) for i in equipment_ids) if equipment_ids else ''
        return {
            'type': 'ir.actions.act_url',
            'url': '/prime_construction_suite/report/equipment_utilization' + (
                '?ids=%s' % ids_param if ids_param else ''),
            'target': 'self',
        }

    @api.model
    def _build_pdf_equipment_utilization(self, equipments):
        if not equipments:
            equipments = self.search([])
        styles = get_styles()
        story = header_block('Equipment Utilization Report', '',
                              'Generated on %s' % fields.Date.context_today(self))
        story.append(kpi_row([
            ('Total Hours Operated', fmt(sum(equipments.mapped('total_hours_operated'))), TEXT_DARK),
            ('Total Fuel Cost', fmt(sum(equipments.mapped('total_fuel_cost'))), TEXT_DARK),
            ('Total Maintenance Cost', fmt(sum(equipments.mapped('total_maintenance_cost'))), TEXT_DARK),
            ('Open Breakdowns', str(sum(equipments.mapped('open_breakdown_count'))),
             DANGER if sum(equipments.mapped('open_breakdown_count')) else TEXT_DARK),
        ]))
        story.append(Spacer(1, 8))

        rows = []
        for eq in equipments:
            rows.append([eq.code or '', eq.name or '', (eq.equipment_type or '').title(),
                         (eq.ownership_type or '').title(), (eq.status or '').title(),
                         fmt(eq.total_hours_operated, 1), fmt(eq.total_fuel_cost, 2),
                         fmt(eq.total_maintenance_cost, 2), eq.open_breakdown_count])
        story.append(data_table(
            ['Asset Code', 'Equipment', 'Type', 'Ownership', 'Status', 'Hours', 'Fuel Cost',
             'Maint. Cost', 'Open Faults'],
            rows, col_widths=[18 * mm, 32 * mm, 20 * mm, 20 * mm, 20 * mm, 16 * mm, 20 * mm, 20 * mm, 18 * mm],
            align_right_cols=[5, 6, 7, 8]))

        return build_pdf_bytes(story, landscape_mode=True, title='Equipment Utilization Report')
