# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class ConstructionProgressInvoice(models.Model):
    _name = 'construction.progress.invoice'
    _description = 'Progress Invoice'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'date desc, sequence desc'

    name        = fields.Char(string='Invoice No.', required=True, copy=False, readonly=True, default='New')
    sequence    = fields.Integer(string='Invoice #', default=1)
    contract_id = fields.Many2one('construction.contract', string='Contract', required=True, ondelete='restrict', tracking=True)
    project_id  = fields.Many2one(related='contract_id.project_id', store=True)
    client_id   = fields.Many2one(related='contract_id.client_id',  store=True)
    currency_id = fields.Many2one(related='contract_id.currency_id', store=True)
    company_id  = fields.Many2one(related='contract_id.company_id',  store=True)

    date          = fields.Date(string='Invoice Date', required=True, default=fields.Date.today, tracking=True, index=True)
    date_from     = fields.Date(string='Period From')
    date_to       = fields.Date(string='Period To')
    submitted_by  = fields.Many2one('res.users', string='Submitted By', default=lambda s: s.env.user)
    approved_by   = fields.Many2one('res.users', string='Approved By',  tracking=True)
    date_approved = fields.Date(string='Approval Date')

    state = fields.Selection([
        ('draft',     'Draft'),
        ('submitted', 'Submitted'),
        ('approved',  'Approved'),
        ('invoiced',  'Invoiced'),
        ('paid',      'Paid'),
        ('cancelled', 'Cancelled'),
    ], default='draft', string='Status', tracking=True, required=True)

    line_ids = fields.One2many('construction.progress.invoice.line', 'invoice_id', string='Invoice Lines')

    gross_amount              = fields.Monetary(string='Gross Amount',         currency_field='currency_id', compute='_compute_financials', store=True)
    retention_percent         = fields.Float(string='Retention %',    compute='_compute_defaults', store=True)
    retention_amount          = fields.Monetary(string='Retention Amount',     currency_field='currency_id', compute='_compute_financials', store=True)
    advance_deduction_percent = fields.Float(string='Advance Deduction %', compute='_compute_defaults', store=True)
    advance_deduction         = fields.Monetary(string='Advance Deduction',    currency_field='currency_id', compute='_compute_financials', store=True)
    net_amount                = fields.Monetary(string='Net Amount Due',       currency_field='currency_id', compute='_compute_financials', store=True)
    wht_percent               = fields.Float(string='WHT %', default=1.0,
                                              help='Withholding tax the client deducts when paying this invoice (informational; does not affect the posted invoice amount).')
    wht_amount                = fields.Monetary(string='WHT Amount', currency_field='currency_id', compute='_compute_wht', store=True)
    net_after_wht             = fields.Monetary(string='Expected Cash Receipt (after WHT)', currency_field='currency_id',
                                                 compute='_compute_wht', store=True)

    insurance_percent = fields.Float(string='Social Insurance Deduction %', default=1.0,
                                      help='Statutory social/labor insurance percentage the client deducts (informational).')
    insurance_amount  = fields.Monetary(string='Insurance Deduction Amount', currency_field='currency_id',
                                        compute='_compute_wht', store=True)
    penalty_deduction = fields.Monetary(string='Delay Penalty Deduction', currency_field='currency_id',
                                         help='Manually confirm the delay-penalty amount to withhold on this invoice (defaults from the contract\'s computed penalty).')
    final_expected_receipt = fields.Monetary(string='Final Expected Receipt', currency_field='currency_id',
                                              compute='_compute_wht', store=True,
                                              help='Net Amount - WHT - Insurance Deduction - Delay Penalty Deduction.')
    cumulative_gross          = fields.Monetary(string='Cumulative Gross',     currency_field='currency_id', compute='_compute_cumulative', store=True)
    cumulative_net            = fields.Monetary(string='Cumulative Net',       currency_field='currency_id', compute='_compute_cumulative', store=True)
    remaining_contract        = fields.Monetary(string='Contract Balance',     currency_field='currency_id', compute='_compute_cumulative', store=True)

    invoice_id    = fields.Many2one('account.move', string='Odoo Invoice', copy=False, readonly=True)
    invoice_state = fields.Selection(related='invoice_id.payment_state', string='Payment Status')
    invoice_due_date = fields.Date(related='invoice_id.invoice_date_due', string='Due Date', store=True)
    notes         = fields.Html(string='Notes')

    retention_released      = fields.Boolean(string='Retention Released', copy=False, tracking=True)
    retention_release_date  = fields.Date(string='Retention Release Date', copy=False, tracking=True)
    retention_released_by   = fields.Many2one('res.users', string='Released By', copy=False, readonly=True)

    @api.depends('contract_id')
    def _compute_defaults(self):
        for rec in self:
            rec.retention_percent         = rec.contract_id.retention_percent or 5.0
            rec.advance_deduction_percent = rec.contract_id.advance_payment_percent or 10.0

    @api.depends('line_ids.line_amount', 'retention_percent', 'advance_deduction_percent')
    def _compute_financials(self):
        for rec in self:
            rec.gross_amount      = sum(rec.line_ids.mapped('line_amount'))
            rec.retention_amount  = rec.gross_amount * rec.retention_percent / 100
            rec.advance_deduction = rec.gross_amount * rec.advance_deduction_percent / 100
            rec.net_amount        = rec.gross_amount - rec.retention_amount - rec.advance_deduction

    @api.depends('net_amount', 'wht_percent', 'insurance_percent', 'penalty_deduction')
    def _compute_wht(self):
        for rec in self:
            rec.wht_amount       = rec.net_amount * rec.wht_percent / 100
            rec.insurance_amount = rec.net_amount * rec.insurance_percent / 100
            rec.net_after_wht    = rec.net_amount - rec.wht_amount
            rec.final_expected_receipt = (rec.net_amount - rec.wht_amount
                                           - rec.insurance_amount - (rec.penalty_deduction or 0.0))

    @api.depends('contract_id', 'gross_amount', 'net_amount', 'state')
    def _compute_cumulative(self):
        for rec in self:
            prev = self.search([('contract_id','=',rec.contract_id.id),
                                ('state','in',('approved','invoiced','paid')),('id','!=',rec.id)])
            in_state = rec.state in ('approved','invoiced','paid')
            rec.cumulative_gross   = sum(prev.mapped('gross_amount')) + (rec.gross_amount if in_state else 0)
            rec.cumulative_net     = sum(prev.mapped('net_amount'))   + (rec.net_amount   if in_state else 0)
            rec.remaining_contract = (rec.contract_id.revised_contract_value or 0) - rec.cumulative_gross

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.progress.invoice') or 'New'
            if vals.get('contract_id'):
                vals['sequence'] = self.search_count([('contract_id','=',vals['contract_id'])]) + 1
        return super().create(vals_list)

    def action_load_boq_lines(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Can only load lines in Draft status.'))
        existing = self.line_ids.mapped('boq_line_id')
        new_lines = []
        for bl in self.contract_id.boq_line_ids.filtered(lambda l: l not in existing and l.state != 'completed'):
            prev_qty = sum(self.env['construction.progress.invoice.line'].search([
                ('boq_line_id','=',bl.id),
                ('invoice_id.state','in',('approved','invoiced','paid')),
                ('invoice_id','!=',self.id),
            ]).mapped('qty_this_invoice'))
            # Auto-suggest this invoice's quantity from approved Measurement Sheets that
            # haven't been picked up on a previous invoice yet. Still fully editable below.
            suggested_qty = min(max(bl.qty_measured - prev_qty, 0.0), max(bl.qty_contract - prev_qty, 0.0))
            new_lines.append({'invoice_id':self.id,'boq_line_id':bl.id,'description':bl.description,
                              'uom_id':bl.uom_id.id,'qty_contract':bl.qty_contract,
                              'qty_previous':prev_qty,'qty_this_invoice':suggested_qty,'unit_price':bl.unit_price})
        self.env['construction.progress.invoice.line'].create(new_lines)

    def action_submit(self):
        for rec in self:
            if not rec.line_ids.filtered(lambda l: l.qty_this_invoice > 0):
                raise UserError(_('Please enter quantities before submitting!'))
            rec.write({'state': 'submitted'})

    def action_approve(self):
        for rec in self:
            rec.write({'state':'approved','approved_by':self.env.user.id,'date_approved':fields.Date.today()})
            for line in rec.line_ids:
                if line.boq_line_id:
                    boq = line.boq_line_id
                    boq.state = 'completed' if boq.qty_executed >= boq.qty_contract else 'in_progress' if boq.qty_executed > 0 else boq.state

    def action_create_invoice(self):
        self.ensure_one()
        if self.state != 'approved':
            raise UserError(_('Invoice must be approved first.'))
        if self.invoice_id:
            raise UserError(_('An invoice already exists for this progress invoice.'))
        account = self.env['account.account'].search([('account_type','=','income'),('company_id','=',self.company_id.id)], limit=1)
        invoice_lines = [(0, 0, {
            'name': line.description,
            'quantity': line.qty_this_invoice,
            'price_unit': line.unit_price,
            'product_uom_id': line.uom_id.id if line.uom_id else False,
            'account_id': account.id if account else False,
            'analytic_distribution': {str(self.project_id.analytic_account_id.id): 100} if self.project_id.analytic_account_id else {},
        }) for line in self.line_ids.filtered(lambda l: l.qty_this_invoice > 0)]
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.client_id.id,
            'invoice_date': self.date, 'ref': self.name, 'company_id': self.company_id.id,
            'invoice_line_ids': invoice_lines,
            'narration': _('Progress Invoice %s - Project: %s') % (self.name, self.project_id.name),
        })
        self.write({'invoice_id': invoice.id, 'state': 'invoiced'})
        return {'type':'ir.actions.act_window','res_model':'account.move','res_id':invoice.id,'view_mode':'form'}

    def action_view_invoice(self):
        return {'type':'ir.actions.act_window','res_model':'account.move','res_id':self.invoice_id.id,'view_mode':'form'}

    def action_cancel(self):
        for rec in self:
            if rec.invoice_id and rec.invoice_id.state == 'posted':
                raise UserError(_('Cannot cancel: invoice is already posted.'))
            rec.write({'state': 'cancelled'})

    def action_reset_draft(self): self.write({'state': 'draft'})

    def action_release_retention(self):
        for rec in self:
            if rec.state not in ('invoiced', 'paid'):
                raise UserError(_('Retention can only be released for invoiced or paid progress invoices.'))
            if not rec.retention_amount:
                raise UserError(_('There is no retention amount to release for this invoice.'))
            rec.write({
                'retention_released': True,
                'retention_release_date': fields.Date.today(),
                'retention_released_by': self.env.user.id,
            })

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError(_('Period start must be before end!'))

    def _cron_remind_pending_invoices(self):
        """Nudge the project manager about progress invoices stuck in Submitted for too long."""
        from datetime import date, timedelta
        threshold = fields.Datetime.to_string(date.today() - timedelta(days=5))
        stale = self.search([('state', '=', 'submitted'), ('write_date', '<=', threshold)])
        for rec in stale:
            already = rec.activity_ids.filtered(lambda a: a.summary == _('Progress Invoice Pending Approval'))
            if already:
                continue
            responsible = rec.project_id.project_manager_id.id or self.env.user.id
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('Progress Invoice Pending Approval'),
                note=_('Progress Invoice %s (Project: %s) has been awaiting approval for more than 5 days.')
                     % (rec.name, rec.project_id.name),
                user_id=responsible,
            )


class ConstructionProgressInvoiceLine(models.Model):
    _name = 'construction.progress.invoice.line'
    _description = 'Progress Invoice Line'
    _order = 'sequence, id'

    sequence         = fields.Integer(default=10)
    invoice_id       = fields.Many2one('construction.progress.invoice', ondelete='cascade')
    boq_line_id      = fields.Many2one('construction.boq.line', string='BOQ Item')
    currency_id      = fields.Many2one(related='invoice_id.currency_id', store=True)
    section_name     = fields.Char(related='boq_line_id.section_name', store=True, string='Section')
    description      = fields.Text(string='Description', required=True)
    uom_id           = fields.Many2one('uom.uom', string='UoM')
    qty_contract     = fields.Float(string='Contract Qty',   digits=(12,3))
    qty_previous     = fields.Float(string='Previous Qty',   digits=(12,3), readonly=True)
    qty_this_invoice = fields.Float(string='This Invoice Qty', digits=(12,3))
    qty_cumulative   = fields.Float(string='Cumulative Qty', digits=(12,3), compute='_compute_totals', store=True)
    unit_price       = fields.Monetary(string='Unit Price', currency_field='currency_id')
    line_amount      = fields.Monetary(string='Amount',     currency_field='currency_id', compute='_compute_totals', store=True)
    cumulative_percent=fields.Float(string='Completion %',  compute='_compute_totals', store=True)

    @api.depends('qty_previous', 'qty_this_invoice', 'unit_price', 'qty_contract')
    def _compute_totals(self):
        for rec in self:
            rec.qty_cumulative     = rec.qty_previous + rec.qty_this_invoice
            rec.line_amount        = rec.qty_this_invoice * rec.unit_price
            rec.cumulative_percent = min(rec.qty_cumulative / rec.qty_contract * 100, 100.0) if rec.qty_contract else 0.0

    @api.constrains('qty_this_invoice', 'qty_contract', 'qty_previous')
    def _check_qty(self):
        for rec in self:
            if rec.qty_this_invoice < 0:
                raise ValidationError(_('Quantity cannot be negative: %s') % rec.description)
            if rec.qty_this_invoice > rec.qty_contract - rec.qty_previous + 0.001:
                raise ValidationError(_('Quantity exceeds remaining contract qty: %s') % rec.description)
