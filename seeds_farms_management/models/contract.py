from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class SeedsContract(models.Model):
    _name = 'seeds.contract'
    _inherit = ['mail.thread']
    _description = 'Season Contract'
    _order = 'date_from desc, id desc'

    name = fields.Char(default='New', readonly=True, copy=False)
    state = fields.Selection([('draft', 'Draft'), ('running', 'Running'), ('done', 'Done'),
                              ('cancel', 'Cancelled')], default='draft', tracking=True, copy=False)
    farmer_id = fields.Many2one('seeds.farmer', required=True, tracking=True)
    partner_id = fields.Many2one('res.partner', string='Contractor', required=True)
    season_id = fields.Many2one('seeds.season', string='Season')
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company, required=True)
    crop_type = fields.Selection([('corn', 'Corn'), ('wheat', 'Wheat')], required=True, default='corn')
    product_id = fields.Many2one('product.product', required=True, domain="[('type', '=', 'consu')]")
    contracted_qty = fields.Float(string='Contracted Qty (Ardab)', digits=(16, 2), required=True)
    price_per_ardab = fields.Float(string='Agreed Price / Ardab', digits='Product Price', required=True)
    date_from = fields.Date(required=True, default=fields.Date.context_today)
    date_to = fields.Date(required=True)
    receipt_ids = fields.One2many('seeds.receipt', 'contract_id', string='Receipts')
    delivered_qty = fields.Float(string='Delivered (Ardab)', digits=(16, 2),
                                 compute='_compute_delivered', store=True)
    remaining_qty = fields.Float(string='Remaining (Ardab)', digits=(16, 2), compute='_compute_delivered')
    progress = fields.Float(compute='_compute_delivered')
    receipt_count = fields.Integer(compute='_compute_receipt_count')

    @api.depends('receipt_ids.state', 'receipt_ids.number_of_ardab', 'contracted_qty')
    def _compute_delivered(self):
        for rec in self:
            done = rec.receipt_ids.filtered(lambda r: r.state in ('confirmed', 'po_created'))
            rec.delivered_qty = sum(done.mapped('number_of_ardab'))
            rec.remaining_qty = rec.contracted_qty - rec.delivered_qty
            rec.progress = (rec.delivered_qty / rec.contracted_qty * 100.0) if rec.contracted_qty else 0.0

    @api.depends('receipt_ids')
    def _compute_receipt_count(self):
        for rec in self:
            rec.receipt_count = len(rec.receipt_ids)

    @api.constrains('contracted_qty', 'price_per_ardab', 'date_from', 'date_to')
    def _check_values(self):
        for rec in self:
            if rec.contracted_qty <= 0:
                raise ValidationError(_('Contracted quantity must be greater than zero.'))
            if rec.price_per_ardab < 0:
                raise ValidationError(_('Price cannot be negative.'))
            if rec.date_to < rec.date_from:
                raise ValidationError(_('Contract end date cannot be before the start date.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('seeds.contract') or 'New'
        return super().create(vals_list)

    def unlink(self):
        if any(rec.state not in ('draft', 'cancel') for rec in self):
            raise UserError(_('You can only delete draft or cancelled contracts.'))
        return super().unlink()

    def action_run(self):
        self.write({'state': 'running'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        for rec in self:
            if rec.receipt_ids.filtered(lambda r: r.state != 'cancel'):
                raise UserError(_('Cancel or unlink the receipts of this contract first.'))
        self.write({'state': 'cancel'})

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_view_receipts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Receipts'),
            'res_model': 'seeds.receipt',
            'view_mode': 'list,form',
            'domain': [('contract_id', '=', self.id)],
            'context': {'default_contract_id': self.id, 'default_farmer_id': self.farmer_id.id},
        }
