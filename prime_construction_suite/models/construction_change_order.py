# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionChangeOrder(models.Model):
    _name = 'construction.change.order'
    _description = 'Change Order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'date desc, id desc'

    name        = fields.Char(string='Change Order No.', required=True, copy=False, readonly=True, default='New')
    contract_id = fields.Many2one('construction.contract', string='Contract', required=True, ondelete='restrict', tracking=True)
    project_id  = fields.Many2one(related='contract_id.project_id', store=True)
    currency_id = fields.Many2one(related='contract_id.currency_id', store=True)
    company_id  = fields.Many2one(related='contract_id.company_id',  store=True)

    date          = fields.Date(string='Request Date', required=True, default=fields.Date.today)
    date_approved = fields.Date(string='Approval Date', tracking=True)
    requested_by  = fields.Many2one('res.users', string='Requested By', default=lambda s: s.env.user)
    approved_by   = fields.Many2one('res.users', string='Approved By',  tracking=True)

    state = fields.Selection([
        ('draft',     'Draft'),
        ('submitted', 'Submitted'),
        ('reviewed',  'Under Review'),
        ('approved',  'Approved'),
        ('rejected',  'Rejected'),
        ('cancelled', 'Cancelled'),
    ], default='draft', string='Status', tracking=True, required=True)

    change_type = fields.Selection([
        ('scope',    'Scope Change'),
        ('quantity', 'Quantity Change'),
        ('price',    'Price Change'),
        ('time',     'Time Extension'),
        ('other',    'Other'),
    ], string='Change Type', required=True, default='quantity')

    reason           = fields.Text(string='Reason / Description', required=True)
    impact           = fields.Text(string='Impact on Project')
    rejection_reason = fields.Text(string='Rejection Reason')
    time_extension_days = fields.Integer(string='Time Extension (Days)', default=0)

    line_ids = fields.One2many('construction.change.order.line', 'change_order_id', string='Change Lines')

    requested_amount = fields.Monetary(string='Requested Amount', currency_field='currency_id',
                                        compute='_compute_amounts', store=True)
    approved_amount  = fields.Monetary(string='Approved Amount',  currency_field='currency_id', tracking=True)
    amount_difference= fields.Monetary(string='Difference',       currency_field='currency_id',
                                        compute='_compute_amounts', store=True)

    @api.depends('line_ids.total_amount', 'approved_amount')
    def _compute_amounts(self):
        for rec in self:
            rec.requested_amount   = sum(rec.line_ids.mapped('total_amount'))
            rec.amount_difference  = rec.approved_amount - rec.requested_amount

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.change.order') or 'New'
        return super().create(vals_list)

    def action_submit(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_('Please add change lines before submitting!'))
            rec.write({'state': 'submitted'})

    def action_review(self):   self.write({'state': 'reviewed'})
    def action_cancel(self):   self.write({'state': 'cancelled'})
    def action_reset_draft(self): self.write({'state': 'draft', 'approved_by': False, 'date_approved': False})

    def action_approve(self):
        for rec in self:
            self.env['construction.approval.rule'].check_approval(
                'change_order', abs(rec.requested_amount), rec.contract_id.company_id if rec.contract_id else None)
            if not rec.approved_amount:
                rec.approved_amount = rec.requested_amount
            rec.write({'state': 'approved', 'approved_by': self.env.user.id, 'date_approved': fields.Date.today()})
            rec._apply_to_boq()

    def action_reject(self):
        return {'type': 'ir.actions.act_window', 'res_model': 'construction.change.order.reject.wizard',
                'view_mode': 'form', 'target': 'new', 'context': {'default_change_order_id': self.id}}

    def _apply_to_boq(self):
        self.ensure_one()
        for line in self.line_ids:
            if line.boq_line_id:
                if line.change_type == 'qty':      line.boq_line_id.qty_contract += line.qty_change
                elif line.change_type == 'price':  line.boq_line_id.unit_price = line.new_unit_price
                elif line.change_type == 'delete':
                    line.boq_line_id.qty_contract = 0
                    line.boq_line_id.notes = (line.boq_line_id.notes or '') + '\n' + _(
                        'Cancelled by Change Order %s') % self.name
            elif line.change_type == 'new' and line.description:
                self.env['construction.boq.line'].create({
                    'contract_id': self.contract_id.id,
                    'description': line.description,
                    'uom_id': line.uom_id.id,
                    'qty_contract': line.qty_change,
                    'unit_price': line.unit_price,
                    'notes': _('Added by Change Order %s') % self.name,
                })

    def _cron_remind_pending_change_orders(self):
        """Nudge the project manager about change orders stuck in review for too long."""
        from datetime import date, timedelta
        threshold = fields.Datetime.to_string(date.today() - timedelta(days=5))
        stale = self.search([('state', 'in', ('submitted', 'reviewed')), ('write_date', '<=', threshold)])
        for rec in stale:
            already = rec.activity_ids.filtered(lambda a: a.summary == _('Change Order Pending Approval'))
            if already:
                continue
            responsible = rec.project_id.project_manager_id.id or self.env.user.id
            rec.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('Change Order Pending Approval'),
                note=_('Change Order %s (Project: %s) has been pending review/approval for more than 5 days.')
                     % (rec.name, rec.project_id.name),
                user_id=responsible,
            )


class ConstructionChangeOrderLine(models.Model):
    _name = 'construction.change.order.line'
    _description = 'Change Order Line'
    _order = 'sequence, id'

    sequence        = fields.Integer(default=10)
    change_order_id = fields.Many2one('construction.change.order', ondelete='cascade')
    contract_id     = fields.Many2one(related='change_order_id.contract_id', store=True)
    currency_id     = fields.Many2one(related='change_order_id.currency_id', store=True)

    change_type = fields.Selection([
        ('qty',    'Modify Existing Qty'),
        ('price',  'Modify Existing Price'),
        ('new',    'New Item'),
        ('delete', 'Delete Item'),
    ], string='Change Type', required=True, default='qty')

    boq_line_id  = fields.Many2one('construction.boq.line', string='Affected Item',
                                    domain="[('contract_id','=',contract_id)]")
    description  = fields.Text(string='Description', required=True)
    uom_id       = fields.Many2one('uom.uom', string='UoM')
    qty_original = fields.Float(string='Original Qty',  digits=(12,3), readonly=True)
    qty_change   = fields.Float(string='Qty Change',    digits=(12,3))
    qty_new      = fields.Float(string='New Qty',       digits=(12,3), compute='_compute_qty_new', store=True)
    unit_price   = fields.Monetary(string='Original Price',  currency_field='currency_id')
    new_unit_price=fields.Monetary(string='New Unit Price',  currency_field='currency_id')
    total_amount = fields.Monetary(string='Change Value',    currency_field='currency_id',
                                    compute='_compute_total', store=True)

    @api.depends('qty_original', 'qty_change')
    def _compute_qty_new(self):
        for rec in self:
            rec.qty_new = rec.qty_original + rec.qty_change

    @api.depends('change_type', 'qty_change', 'unit_price', 'new_unit_price', 'boq_line_id')
    def _compute_total(self):
        for rec in self:
            if rec.change_type == 'qty':
                rec.total_amount = rec.qty_change * (rec.unit_price or 0)
            elif rec.change_type == 'price':
                qty = rec.boq_line_id.qty_contract if rec.boq_line_id else 0
                rec.total_amount = qty * ((rec.new_unit_price or 0) - (rec.unit_price or 0))
            elif rec.change_type == 'new':
                rec.total_amount = rec.qty_change * (rec.unit_price or 0)
            elif rec.change_type == 'delete':
                rec.total_amount = -(rec.qty_original * (rec.unit_price or 0))
            else:
                rec.total_amount = 0.0

    @api.onchange('boq_line_id')
    def _onchange_boq_line(self):
        if self.boq_line_id:
            self.description    = self.boq_line_id.description
            self.uom_id         = self.boq_line_id.uom_id
            self.unit_price     = self.boq_line_id.unit_price
            self.new_unit_price = self.boq_line_id.unit_price
            self.qty_original   = self.boq_line_id.qty_contract
