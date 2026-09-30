# -*- coding: utf-8 -*-
import base64
import io

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError


class ConstructionContract(models.Model):
    _name = 'construction.contract'
    _description = 'Construction Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'date_signed desc, id desc'

    name = fields.Char(string='Contract Number', required=True, copy=False, readonly=True, default='New')
    project_id  = fields.Many2one('construction.project', string='Project', required=True, ondelete='restrict', tracking=True)
    client_id   = fields.Many2one(related='project_id.client_id', string='Client', store=True)
    company_id  = fields.Many2one(related='project_id.company_id', store=True)
    currency_id = fields.Many2one(related='project_id.currency_id', store=True)

    contract_type = fields.Selection([
        ('lump_sum',      'Lump Sum'),
        ('unit_price',    'Unit Price'),
        ('cost_plus',     'Cost Plus'),
        ('remeasurement', 'Remeasurement'),
    ], string='Contract Type', required=True, default='unit_price', tracking=True)

    date_signed = fields.Date(string='Signing Date', required=True, tracking=True)
    date_start  = fields.Date(related='project_id.date_start', store=True, string='Start Date')
    date_end    = fields.Date(related='project_id.date_end',   store=True, string='End Date')
    duration_days = fields.Integer(string='Duration (Days)', compute='_compute_duration', store=True)

    state = fields.Selection([
        ('draft',     'Draft'),
        ('active',    'Active'),
        ('completed', 'Completed'),
        ('terminated','Terminated'),
    ], string='Status', default='draft', tracking=True, required=True)

    contract_value        = fields.Monetary(string='Original Contract Value',  currency_field='currency_id', required=True, tracking=True)
    change_orders_total   = fields.Monetary(string='Change Orders Total',      currency_field='currency_id', compute='_compute_financials', store=True)
    revised_contract_value= fields.Monetary(string='Revised Contract Value',   currency_field='currency_id', compute='_compute_financials', store=True)
    invoiced_amount       = fields.Monetary(string='Invoiced Amount',          currency_field='currency_id', compute='_compute_financials', store=True)
    remaining_amount      = fields.Monetary(string='Remaining Amount',         currency_field='currency_id', compute='_compute_financials', store=True)
    retention_percent     = fields.Float(string='Retention %', default=5.0)
    advance_payment_percent = fields.Float(string='Advance Payment %', default=10.0)

    penalty_percent_per_day = fields.Float(string='Delay Penalty % per Day', default=0.1,
                                            help='Percentage of contract value deducted per day of delay.')
    penalty_cap_percent     = fields.Float(string='Penalty Cap %', default=10.0,
                                            help='Maximum penalty as a percentage of contract value.')
    delay_days      = fields.Integer(string='Delay (Days)', compute='_compute_penalty', store=True)
    penalty_amount  = fields.Monetary(string='Delay Penalty Amount', currency_field='currency_id',
                                       compute='_compute_penalty', store=True)

    @api.depends('project_id.date_end', 'project_id.date_actual_end', 'project_id.state',
                 'penalty_percent_per_day', 'penalty_cap_percent', 'contract_value')
    def _compute_penalty(self):
        from datetime import date
        today = date.today()
        for rec in self:
            proj = rec.project_id
            planned_end = proj.date_end if proj else False
            if not planned_end:
                rec.delay_days = 0
                rec.penalty_amount = 0.0
                continue
            reference_end = proj.date_actual_end or (today if proj.state == 'running' else False)
            if reference_end and reference_end > planned_end:
                rec.delay_days = (reference_end - planned_end).days
            else:
                rec.delay_days = 0
            raw_penalty = rec.contract_value * rec.penalty_percent_per_day / 100 * rec.delay_days
            cap = rec.contract_value * rec.penalty_cap_percent / 100
            rec.penalty_amount = min(raw_penalty, cap) if rec.delay_days > 0 else 0.0
    advance_payment_amount  = fields.Monetary(string='Advance Payment Amount', currency_field='currency_id', compute='_compute_advance', store=True)
    retention_held        = fields.Monetary(string='Retention Held', currency_field='currency_id',
                                             compute='_compute_retention', store=True)
    retention_released_amt= fields.Monetary(string='Retention Released', currency_field='currency_id',
                                             compute='_compute_retention', store=True)
    retention_outstanding = fields.Monetary(string='Retention Outstanding', currency_field='currency_id',
                                             compute='_compute_retention', store=True)

    payment_terms = fields.Text(string='Payment Terms')
    notes         = fields.Html(string='Notes')

    boq_line_ids         = fields.One2many('construction.boq.line',          'contract_id', string='BOQ Lines')
    change_order_ids     = fields.One2many('construction.change.order',       'contract_id', string='Change Orders')
    progress_invoice_ids = fields.One2many('construction.progress.invoice',   'contract_id', string='Progress Invoices')

    boq_line_count    = fields.Integer(compute='_compute_counts')
    change_order_count= fields.Integer(compute='_compute_counts')
    invoice_count     = fields.Integer(compute='_compute_counts')

    @api.depends('date_start', 'date_end')
    def _compute_duration(self):
        for rec in self:
            rec.duration_days = (rec.date_end - rec.date_start).days if rec.date_start and rec.date_end else 0

    @api.depends('contract_value', 'change_order_ids.approved_amount', 'change_order_ids.state',
                 'progress_invoice_ids.gross_amount', 'progress_invoice_ids.state')
    def _compute_financials(self):
        for rec in self:
            approved = rec.change_order_ids.filtered(lambda c: c.state == 'approved')
            rec.change_orders_total    = sum(approved.mapped('approved_amount'))
            rec.revised_contract_value = rec.contract_value + rec.change_orders_total
            confirmed = rec.progress_invoice_ids.filtered(lambda i: i.state in ('approved','invoiced','paid'))
            rec.invoiced_amount  = sum(confirmed.mapped('gross_amount'))
            rec.remaining_amount = rec.revised_contract_value - rec.invoiced_amount

    @api.depends('contract_value', 'advance_payment_percent')
    def _compute_advance(self):
        for rec in self:
            rec.advance_payment_amount = rec.contract_value * rec.advance_payment_percent / 100

    @api.depends('progress_invoice_ids.retention_amount', 'progress_invoice_ids.state',
                 'progress_invoice_ids.retention_released')
    def _compute_retention(self):
        for rec in self:
            confirmed = rec.progress_invoice_ids.filtered(lambda i: i.state in ('approved', 'invoiced', 'paid'))
            rec.retention_held = sum(confirmed.mapped('retention_amount'))
            released = confirmed.filtered('retention_released')
            rec.retention_released_amt = sum(released.mapped('retention_amount'))
            rec.retention_outstanding = rec.retention_held - rec.retention_released_amt

    @api.depends('boq_line_ids', 'change_order_ids', 'progress_invoice_ids')
    def _compute_counts(self):
        for rec in self:
            rec.boq_line_count     = len(rec.boq_line_ids)
            rec.change_order_count = len(rec.change_order_ids)
            rec.invoice_count      = len(rec.progress_invoice_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.contract') or 'New'
        records = super().create(vals_list)
        for rec in records:
            if rec.project_id and not rec.project_id.contract_id:
                rec.project_id.write({'contract_id': rec.id, 'contract_value': rec.contract_value})
        return records

    @api.constrains('project_id')
    def _check_one_contract(self):
        for rec in self:
            if self.search([('project_id','=',rec.project_id.id),('id','!=',rec.id),('state','!=','terminated')]):
                raise ValidationError(_('Project "%s" already has an active contract!') % rec.project_id.name)

    def action_activate(self):
        for rec in self:
            rec.write({'state': 'active'})
            rec.project_id.action_confirm()

    def action_complete(self):    self.write({'state': 'completed'})
    def action_terminate(self):   self.write({'state': 'terminated'})
    def action_reset_draft(self): self.write({'state': 'draft'})

    def action_view_boq(self):
        return {'type':'ir.actions.act_window','name':_('BOQ Lines'),'res_model':'construction.boq.line',
                'view_mode':'list,form','domain':[('contract_id','=',self.id)],
                'context':{'default_contract_id':self.id,'default_project_id':self.project_id.id}}

    def action_view_change_orders(self):
        return {'type':'ir.actions.act_window','name':_('Change Orders'),'res_model':'construction.change.order',
                'view_mode':'list,form','domain':[('contract_id','=',self.id)],
                'context':{'default_contract_id':self.id}}

    def action_view_invoices(self):
        return {'type':'ir.actions.act_window','name':_('Progress Invoices'),'res_model':'construction.progress.invoice',
                'view_mode':'list,form','domain':[('contract_id','=',self.id)],
                'context':{'default_contract_id':self.id}}

    def action_import_boq_excel(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Import BOQ from Excel'),
            'res_model': 'construction.boq.import.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_contract_id': self.id},
        }

    def action_export_boq_excel(self):
        self.ensure_one()
        try:
            import xlsxwriter
        except ImportError:
            raise UserError(_(
                'The "xlsxwriter" Python library is required to export to Excel. '
                'Please ask your administrator to install it on the server (pip install xlsxwriter).'))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('BOQ')

        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#4f46e5', 'font_color': '#ffffff', 'border': 1})
        cell_fmt   = workbook.add_format({'border': 1})
        num_fmt    = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})

        headers = ['Section', 'Item Code', 'Description', 'Type', 'UoM',
                   'Contract Qty', 'Unit Price', 'Total Price', 'Cost Code']
        for col, h in enumerate(headers):
            sheet.write(0, col, h, header_fmt)

        row = 1
        lines = self.boq_line_ids.sorted(key=lambda l: (l.section_id.sequence if l.section_id else 0, l.sequence))
        for line in lines:
            sheet.write(row, 0, line.section_name or '', cell_fmt)
            sheet.write(row, 1, line.item_code or '', cell_fmt)
            sheet.write(row, 2, line.description or '', cell_fmt)
            sheet.write(row, 3, line.line_type or '', cell_fmt)
            sheet.write(row, 4, line.uom_id.name or '', cell_fmt)
            sheet.write_number(row, 5, line.qty_contract or 0.0, num_fmt)
            sheet.write_number(row, 6, line.unit_price or 0.0, num_fmt)
            sheet.write_number(row, 7, line.total_price or 0.0, num_fmt)
            sheet.write(row, 8, line.cost_code_id.name or '', cell_fmt)
            row += 1

        for col, width in enumerate([18, 14, 42, 12, 10, 14, 14, 16, 18]):
            sheet.set_column(col, col, width)
        workbook.close()
        output.seek(0)

        attachment = self.env['ir.attachment'].create({
            'name': 'BOQ_%s.xlsx' % (self.name or 'contract'),
            'type': 'binary',
            'datas': base64.b64encode(output.read()),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/%s?download=true' % attachment.id,
            'target': 'self',
        }
