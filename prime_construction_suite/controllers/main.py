# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class PrimeConstructionSuiteReports(http.Controller):

    def _pdf_response(self, pdf_bytes, filename):
        headers = [
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf_bytes)),
            ('Content-Disposition', 'inline; filename="%s"' % filename),
        ]
        return request.make_response(pdf_bytes, headers=headers)

    def _parse_ids(self, ids):
        if not ids:
            return []
        return [int(i) for i in ids.split(',') if i.strip().isdigit()]

    @http.route('/prime_construction_suite/report/project_summary/<int:project_id>',
                type='http', auth='user')
    def report_project_summary(self, project_id, **kw):
        project = request.env['construction.project'].browse(project_id)
        pdf = project._build_pdf_project_summary()
        return self._pdf_response(pdf, 'Project_Summary_%s.pdf' % (project.name or project_id))

    @http.route('/prime_construction_suite/report/executive_dashboard', type='http', auth='user')
    def report_executive_dashboard(self, ids=None, **kw):
        Project = request.env['construction.project']
        projects = Project.browse(self._parse_ids(ids)).exists() if ids else Project.browse()
        pdf = Project._build_pdf_executive_dashboard(projects)
        return self._pdf_response(pdf, 'Executive_Dashboard.pdf')

    @http.route('/prime_construction_suite/report/cost_analysis/<int:project_id>',
                type='http', auth='user')
    def report_cost_analysis(self, project_id, **kw):
        project = request.env['construction.project'].browse(project_id)
        pdf = project._build_pdf_cost_analysis()
        return self._pdf_response(pdf, 'Cost_Analysis_%s.pdf' % (project.name or project_id))

    @http.route('/prime_construction_suite/report/boq/<int:contract_id>', type='http', auth='user')
    def report_boq(self, contract_id, **kw):
        contract = request.env['construction.contract'].browse(contract_id)
        pdf = contract._build_pdf_boq()
        return self._pdf_response(pdf, 'BOQ_%s.pdf' % (contract.name or contract_id))

    @http.route('/prime_construction_suite/report/contract_summary/<int:contract_id>',
                type='http', auth='user')
    def report_contract_summary(self, contract_id, **kw):
        contract = request.env['construction.contract'].browse(contract_id)
        pdf = contract._build_pdf_contract_summary()
        return self._pdf_response(pdf, 'Contract_Summary_%s.pdf' % (contract.name or contract_id))

    @http.route('/prime_construction_suite/report/boq_comparison/<int:contract_id>',
                type='http', auth='user')
    def report_boq_comparison(self, contract_id, **kw):
        contract = request.env['construction.contract'].browse(contract_id)
        pdf = contract._build_pdf_boq_comparison()
        return self._pdf_response(pdf, 'BOQ_Comparison_%s.pdf' % (contract.name or contract_id))

    @http.route('/prime_construction_suite/report/client_statement/<int:contract_id>',
                type='http', auth='user')
    def report_client_statement(self, contract_id, **kw):
        contract = request.env['construction.contract'].browse(contract_id)
        pdf = contract._build_pdf_client_statement()
        return self._pdf_response(pdf, 'Client_Statement_%s.pdf' % (contract.name or contract_id))

    @http.route('/prime_construction_suite/report/vendor_statement/<int:subcontractor_id>',
                type='http', auth='user')
    def report_vendor_statement(self, subcontractor_id, **kw):
        subcontractor = request.env['construction.subcontractor'].browse(subcontractor_id)
        pdf = subcontractor._build_pdf_vendor_statement()
        return self._pdf_response(pdf, 'Vendor_Statement_%s.pdf' % (subcontractor.name or subcontractor_id))

    @http.route('/prime_construction_suite/report/procurement/<int:project_id>',
                type='http', auth='user')
    def report_procurement(self, project_id, **kw):
        project = request.env['construction.project'].browse(project_id)
        pdf = project._build_pdf_procurement_report()
        return self._pdf_response(pdf, 'Procurement_Report_%s.pdf' % (project.name or project_id))

    @http.route('/prime_construction_suite/report/progress_invoice/<int:invoice_id>',
                type='http', auth='user')
    def report_progress_invoice(self, invoice_id, **kw):
        invoice = request.env['construction.progress.invoice'].browse(invoice_id)
        pdf = invoice._build_pdf_progress_invoice()
        return self._pdf_response(pdf, 'Progress_Invoice_%s.pdf' % (invoice.name or invoice_id))

    @http.route('/prime_construction_suite/report/equipment_utilization', type='http', auth='user')
    def report_equipment_utilization(self, ids=None, **kw):
        Equipment = request.env['construction.equipment']
        equipments = Equipment.browse(self._parse_ids(ids)).exists() if ids else Equipment.browse()
        pdf = Equipment._build_pdf_equipment_utilization(equipments)
        return self._pdf_response(pdf, 'Equipment_Utilization.pdf')
