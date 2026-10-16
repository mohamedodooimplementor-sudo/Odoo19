from odoo import _, api, Command, fields, models
from odoo.exceptions import UserError


class SeedsSettlement(models.Model):
    _name = 'seeds.settlement'
    _inherit = ['mail.thread']
    _description = 'Farmer / Contractor Settlement'
    _order = 'date desc, id desc'

    name = fields.Char(default='New', readonly=True, copy=False)
    state = fields.Selection([('draft', 'Draft'), ('billed', 'Billed'), ('cancel', 'Cancelled')],
                             default='draft', tracking=True, copy=False)
    date = fields.Date(default=fields.Date.context_today, required=True)
    partner_id = fields.Many2one('res.partner', string='Contractor / Supplier', required=True, tracking=True)
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company, required=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    receipt_ids = fields.One2many('seeds.receipt', 'settlement_id', string='Receipts', readonly=True)
    total_amount = fields.Monetary(compute='_compute_amounts', store=True)
    advance_amount = fields.Monetary(string='Advance Payments Deducted')
    net_amount = fields.Monetary(compute='_compute_amounts', store=True)
    invoice_id = fields.Many2one('account.move', string='Vendor Bill', readonly=True, copy=False)

    @api.depends('receipt_ids.settlement_amount', 'advance_amount')
    def _compute_amounts(self):
        for rec in self:
            rec.total_amount = sum(rec.receipt_ids.mapped('settlement_amount'))
            rec.net_amount = rec.total_amount - rec.advance_amount

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('seeds.settlement') or 'New'
        return super().create(vals_list)

    def unlink(self):
        if any(rec.state == 'billed' for rec in self):
            raise UserError(_('You cannot delete a billed settlement.'))
        return super().unlink()

    def action_load_receipts(self):
        for rec in self:
            receipts = self.env['seeds.receipt'].search([
                ('contractor_id', '=', rec.partner_id.id),
                ('company_id', '=', rec.company_id.id),
                ('state', '=', 'po_created'),
                ('settlement_id', '=', False),
            ])
            if not receipts:
                raise UserError(_('No unsettled receipts with a purchase order for this contractor.'))
            receipts.write({'settlement_id': rec.id})

    def action_create_bill(self):
        for rec in self:
            if not rec.receipt_ids:
                raise UserError(_('Load receipts first.'))
            lines = []
            for receipt in rec.receipt_ids:
                po = receipt.purchase_order_id
                if po.state not in ('purchase', 'done'):
                    raise UserError(_('Confirm purchase order %s first.', po.name))
                pol = po.order_line[:1]
                lines.append(Command.create({
                    'product_id': receipt.product_id.id,
                    'name': '%s - %s' % (receipt.name, receipt.grade_id.name or receipt.crop_type),
                    'quantity': receipt.number_of_ardab,
                    'price_unit': receipt.adjusted_price,
                    'purchase_line_id': pol.id,
                }))
            bill = self.env['account.move'].create({
                'move_type': 'in_invoice',
                'partner_id': rec.partner_id.id,
                'invoice_date': rec.date,
                'invoice_origin': rec.name,
                'company_id': rec.company_id.id,
                'invoice_line_ids': lines,
            })
            if rec.advance_amount:
                bill.write({'invoice_line_ids': [Command.create({
                    'name': _('Advance payments deduction'),
                    'quantity': 1,
                    'price_unit': -rec.advance_amount,
                    'account_id': bill.invoice_line_ids[:1].account_id.id,
                })]})
            rec.write({'invoice_id': bill.id, 'state': 'billed'})

    def action_cancel(self):
        for rec in self:
            if rec.invoice_id and rec.invoice_id.state != 'cancel':
                raise UserError(_('Cancel the vendor bill first.'))
            rec.receipt_ids.write({'settlement_id': False})
            rec.state = 'cancel'

    def action_draft(self):
        self.write({'state': 'draft', 'invoice_id': False})

    def action_view_bill(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
        }
