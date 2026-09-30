# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class ConstructionMeasurementSheet(models.Model):
    _name = 'construction.measurement.sheet'
    _description = 'Measurement Sheet (Daily Executed Quantities)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'date desc, id desc'

    name        = fields.Char(string='Sheet No.', required=True, copy=False, readonly=True, default='New')
    contract_id = fields.Many2one('construction.contract', string='Contract', required=True, ondelete='restrict', tracking=True)
    project_id  = fields.Many2one(related='contract_id.project_id', store=True)
    currency_id = fields.Many2one(related='contract_id.currency_id', store=True)
    company_id  = fields.Many2one(related='contract_id.company_id',  store=True)

    date          = fields.Date(string='Measurement Date', required=True, default=fields.Date.today, tracking=True)
    measured_by   = fields.Many2one('res.users', string='Measured By', default=lambda s: s.env.user)
    approved_by   = fields.Many2one('res.users', string='Approved By', tracking=True, readonly=True)
    date_approved = fields.Date(string='Approval Date', readonly=True)
    location      = fields.Char(string='Location / Area')
    weather       = fields.Char(string='Weather Conditions')
    notes         = fields.Text(string='Site Notes')

    state = fields.Selection([
        ('draft',     'Draft'),
        ('submitted', 'Submitted'),
        ('approved',  'Approved'),
        ('rejected',  'Rejected'),
    ], default='draft', string='Status', tracking=True, required=True)

    line_ids     = fields.One2many('construction.measurement.sheet.line', 'sheet_id', string='Measured Items')
    line_count   = fields.Integer(compute='_compute_totals', store=True)
    total_amount = fields.Monetary(string='Total Value', currency_field='currency_id', compute='_compute_totals', store=True)

    @api.depends('line_ids.amount')
    def _compute_totals(self):
        for rec in self:
            rec.line_count   = len(rec.line_ids)
            rec.total_amount = sum(rec.line_ids.mapped('amount'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.measurement.sheet') or 'New'
        return super().create(vals_list)

    def action_load_boq_lines(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Can only load lines in Draft status.'))
        existing = self.line_ids.mapped('boq_line_id')
        Line = self.env['construction.measurement.sheet.line']
        new_lines = []
        for bl in self.contract_id.boq_line_ids.filtered(lambda l: l not in existing and l.state != 'completed'):
            prev_qty = sum(Line.search([
                ('boq_line_id', '=', bl.id),
                ('sheet_id.state', '=', 'approved'),
                ('sheet_id', '!=', self.id),
            ]).mapped('qty_today'))
            new_lines.append({
                'sheet_id': self.id, 'boq_line_id': bl.id, 'description': bl.description,
                'uom_id': bl.uom_id.id, 'qty_contract': bl.qty_contract,
                'qty_previous': prev_qty, 'qty_today': 0.0, 'unit_price': bl.unit_price,
            })
        Line.create(new_lines)

    def action_submit(self):
        for rec in self:
            if not rec.line_ids.filtered(lambda l: l.qty_today > 0):
                raise UserError(_('Please enter today\'s executed quantities before submitting!'))
            rec.write({'state': 'submitted'})

    def action_approve(self):
        for rec in self:
            rec.write({
                'state': 'approved',
                'approved_by': self.env.user.id,
                'date_approved': fields.Date.today(),
            })

    def action_reject(self):
        self.write({'state': 'rejected'})

    def action_reset_draft(self):
        self.write({'state': 'draft', 'approved_by': False, 'date_approved': False})

    def _cron_remind_pending_sheets(self):
        """Nudge the project manager about measurement sheets stuck in Submitted for too long."""
        from datetime import date, timedelta
        threshold = fields.Datetime.to_string(date.today() - timedelta(days=3))
        stale = self.search([('state', '=', 'submitted'), ('write_date', '<=', threshold)])
        for rec in stale:
            already = rec.activity_ids.filtered(lambda a: a.summary == _('Measurement Sheet Pending Approval'))
            if already:
                continue
            responsible = rec.project_id.project_manager_id.id or self.env.user.id
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('Measurement Sheet Pending Approval'),
                note=_('Measurement Sheet %s (Project: %s) has been awaiting approval for more than 3 days.')
                     % (rec.name, rec.project_id.name),
                user_id=responsible,
            )


class ConstructionMeasurementSheetLine(models.Model):
    _name = 'construction.measurement.sheet.line'
    _description = 'Measurement Sheet Line'
    _order = 'sequence, id'

    sequence      = fields.Integer(default=10)
    sheet_id      = fields.Many2one('construction.measurement.sheet', ondelete='cascade')
    boq_line_id   = fields.Many2one('construction.boq.line', string='BOQ Item', required=True)
    currency_id   = fields.Many2one(related='sheet_id.currency_id', store=True)
    section_name  = fields.Char(related='boq_line_id.section_name', store=True, string='Section')
    description   = fields.Text(string='Description', required=True)
    uom_id        = fields.Many2one('uom.uom', string='UoM')
    qty_contract  = fields.Float(string='Contract Qty', digits=(12, 3))
    qty_previous  = fields.Float(string='Previously Measured Qty', digits=(12, 3), readonly=True)
    qty_today     = fields.Float(string="Today's Executed Qty", digits=(12, 3))
    qty_cumulative= fields.Float(string='Cumulative Measured Qty', digits=(12, 3), compute='_compute_totals', store=True)
    unit_price    = fields.Monetary(string='Unit Price', currency_field='currency_id')
    amount        = fields.Monetary(string='Amount', currency_field='currency_id', compute='_compute_totals', store=True)
    cumulative_percent = fields.Float(string='Measured Completion %', compute='_compute_totals', store=True)

    @api.depends('qty_previous', 'qty_today', 'unit_price', 'qty_contract')
    def _compute_totals(self):
        for rec in self:
            rec.qty_cumulative     = rec.qty_previous + rec.qty_today
            rec.amount             = rec.qty_today * rec.unit_price
            rec.cumulative_percent = min(rec.qty_cumulative / rec.qty_contract * 100, 100.0) if rec.qty_contract else 0.0

    @api.constrains('qty_today', 'qty_contract', 'qty_previous')
    def _check_qty(self):
        for rec in self:
            if rec.qty_today < 0:
                raise ValidationError(_('Executed quantity cannot be negative: %s') % rec.description)
            if rec.qty_today > rec.qty_contract - rec.qty_previous + 0.001:
                raise ValidationError(_(
                    'Today\'s executed quantity exceeds the remaining contract quantity for: %s') % rec.description)

    @api.onchange('boq_line_id')
    def _onchange_boq_line(self):
        if self.boq_line_id:
            self.description  = self.boq_line_id.description
            self.uom_id       = self.boq_line_id.uom_id
            self.qty_contract = self.boq_line_id.qty_contract
            self.unit_price   = self.boq_line_id.unit_price
            self.qty_previous = sum(self.env['construction.measurement.sheet.line'].search([
                ('boq_line_id', '=', self.boq_line_id.id),
                ('sheet_id.state', '=', 'approved'),
            ]).mapped('qty_today'))
