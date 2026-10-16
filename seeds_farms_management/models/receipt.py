from dateutil.relativedelta import relativedelta

from odoo import _, api, Command, fields, models
from odoo.exceptions import UserError, ValidationError


class SeedsReceipt(models.Model):
    _name = 'seeds.receipt'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Seed Receipt'
    _order = 'date desc, id desc'

    name = fields.Char(default='New', readonly=True, copy=False, index=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('po_created', 'Purchase Order Created'),
        ('cancel', 'Cancelled'),
    ], default='draft', tracking=True, copy=False)
    date = fields.Date(default=fields.Date.context_today, required=True, tracking=True)
    engineer_id = fields.Many2one('res.users', string='Engineer', default=lambda s: s.env.user)
    contractor_id = fields.Many2one('res.partner', string='Contractor', required=True, tracking=True)
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company, required=True)
    farmer_id = fields.Many2one('seeds.farmer', string='Farmers', required=True, tracking=True)
    season_id = fields.Many2one('seeds.season', string='Season', tracking=True)
    land_id = fields.Many2one('seeds.land', string='Field', domain="[('farmer_id', '=', farmer_id)]")
    contract_id = fields.Many2one(
        'seeds.contract', string='Contract', tracking=True, copy=False,
        domain="[('farmer_id', '=', farmer_id), ('state', '=', 'running')]")
    country_id = fields.Many2one(related='farmer_id.country_id', store=True, string='Country')
    state_id = fields.Many2one(related='farmer_id.state_id', store=True, string='State')
    city = fields.Char(related='farmer_id.city', store=True, string='City')

    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Delivery To', required=True,
        default=lambda s: s.env['stock.warehouse'].search([('company_id', '=', s.env.company.id)], limit=1))
    product_id = fields.Many2one('product.product', string='Product', required=True,
                                 domain="[('type', '=', 'consu')]")
    vehicle = fields.Char()
    crop_type = fields.Selection([('corn', 'Corn'), ('wheat', 'Wheat')], string='Crop Type',
                                 default='corn', required=True)
    contractor_weight = fields.Float(digits=(16, 2))
    gross_weight = fields.Float(string='Gross Weight (Loaded)', digits=(16, 2))
    tare_weight = fields.Float(string='Tare Weight (Empty)', digits=(16, 2))
    factory_weight = fields.Float(digits=(16, 2), compute='_compute_factory_weight',
                                  store=True, readonly=False)
    difference_weight = fields.Float(compute='_compute_difference', store=True, digits=(16, 2))
    humidity_temp = fields.Float(string='Humidity Temp', digits=(16, 2))

    # Moisture deduction
    moisture_percent = fields.Float(string='Moisture %', digits=(16, 2))
    standard_moisture = fields.Float(string='Standard Moisture %', digits=(16, 2),
                                     compute='_compute_crop_defaults', store=True, readonly=False)
    moisture_rate = fields.Float(string='Deduction % per 1% Excess', digits=(16, 2),
                                 compute='_compute_crop_defaults', store=True, readonly=False)
    moisture_deduction = fields.Float(string='Moisture Deduction (kg)', digits=(16, 2),
                                      compute='_compute_moisture_deduction', store=True)
    # Quality & pricing
    grade_id = fields.Many2one('seeds.quality.grade', string='Quality Grade', tracking=True)
    grade_adjustment = fields.Float(related='grade_id.price_adjustment', string='Grade Adjustment %')
    price_per_ardab = fields.Float(string='Price / Ardab', digits='Product Price',
                                   compute='_compute_price_per_ardab', store=True, readonly=False)
    adjusted_price = fields.Float(string='Adjusted Price / Ardab', digits='Product Price',
                                  compute='_compute_adjusted_price', store=True)
    settlement_amount = fields.Float(string='Amount', digits='Product Price',
                                     compute='_compute_adjusted_price', store=True)
    settlement_id = fields.Many2one('seeds.settlement', string='Settlement', readonly=True, copy=False)

    weight_per_ardab = fields.Float(string='Weight / Ardab', digits=(16, 2),
                                    compute='_compute_crop_defaults', store=True, readonly=False)
    ardab_count = fields.Float(string='Number', digits=(16, 2), compute='_compute_ardab_count', store=True)
    sorting = fields.Float(digits=(16, 2))
    net_weight = fields.Float(string='Net', digits=(16, 2), compute='_compute_net', store=True)
    number_of_box = fields.Float(string='Number of Box', digits=(16, 2))
    weight_per_unit = fields.Float(string='Weight Per Unit', digits=(16, 2))
    total_weight = fields.Float(digits=(16, 2), compute='_compute_total_weight', store=True)
    ardab_wg = fields.Float(string='Ardab WG', digits=(16, 2),
                            compute='_compute_crop_defaults', store=True, readonly=False)
    number_of_ardab = fields.Float(string='Number of Ardab', digits=(16, 2),
                                   compute='_compute_number_of_ardab', store=True)
    notes = fields.Text()

    purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order', readonly=True, copy=False)
    picking_ids = fields.Many2many('stock.picking', compute='_compute_pickings')
    purchase_count = fields.Integer(compute='_compute_pickings')
    picking_count = fields.Integer(compute='_compute_pickings')

    @api.depends('crop_type')
    def _compute_crop_defaults(self):
        configs = {c.crop_type: c for c in self.env['seeds.crop.config'].search([])}
        for rec in self:
            cfg = configs.get(rec.crop_type)
            if cfg:
                rec.weight_per_ardab = cfg.weight_per_ardab
                rec.ardab_wg = cfg.ardab_wg
                rec.standard_moisture = cfg.standard_moisture
                rec.moisture_rate = cfg.moisture_rate

    @api.depends('gross_weight', 'tare_weight')
    def _compute_factory_weight(self):
        for rec in self:
            if rec.gross_weight:
                rec.factory_weight = rec.gross_weight - rec.tare_weight

    @api.depends('factory_weight', 'moisture_percent', 'standard_moisture', 'moisture_rate')
    def _compute_moisture_deduction(self):
        for rec in self:
            excess = max(rec.moisture_percent - rec.standard_moisture, 0.0)
            rec.moisture_deduction = rec.factory_weight * excess * rec.moisture_rate / 100.0

    @api.depends('product_id', 'contract_id.price_per_ardab')
    def _compute_price_per_ardab(self):
        for rec in self:
            rec.price_per_ardab = rec.contract_id.price_per_ardab or rec.product_id.standard_price

    @api.depends('price_per_ardab', 'grade_id.price_adjustment', 'number_of_ardab')
    def _compute_adjusted_price(self):
        for rec in self:
            rec.adjusted_price = rec.price_per_ardab * (1 + rec.grade_id.price_adjustment / 100.0)
            rec.settlement_amount = rec.adjusted_price * rec.number_of_ardab

    @api.depends('contractor_weight', 'factory_weight')
    def _compute_difference(self):
        for rec in self:
            rec.difference_weight = rec.factory_weight - rec.contractor_weight

    @api.depends('factory_weight', 'weight_per_ardab')
    def _compute_ardab_count(self):
        for rec in self:
            rec.ardab_count = rec.factory_weight / rec.weight_per_ardab if rec.weight_per_ardab else 0.0

    @api.depends('factory_weight', 'sorting', 'moisture_deduction')
    def _compute_net(self):
        for rec in self:
            rec.net_weight = rec.factory_weight - rec.sorting - rec.moisture_deduction

    @api.depends('number_of_box', 'weight_per_unit')
    def _compute_total_weight(self):
        for rec in self:
            rec.total_weight = rec.number_of_box * rec.weight_per_unit

    @api.depends('total_weight', 'ardab_wg')
    def _compute_number_of_ardab(self):
        for rec in self:
            rec.number_of_ardab = rec.total_weight / rec.ardab_wg if rec.ardab_wg else 0.0

    @api.depends('purchase_order_id', 'purchase_order_id.picking_ids')
    def _compute_pickings(self):
        for rec in self:
            pickings = rec.purchase_order_id.picking_ids
            rec.picking_ids = pickings
            rec.picking_count = len(pickings)
            rec.purchase_count = 1 if rec.purchase_order_id else 0

    @api.constrains('contractor_weight', 'factory_weight', 'sorting', 'number_of_box',
                    'weight_per_unit', 'weight_per_ardab', 'ardab_wg', 'gross_weight',
                    'tare_weight', 'moisture_percent')
    def _check_values(self):
        for rec in self:
            if rec.gross_weight and rec.tare_weight > rec.gross_weight:
                raise ValidationError(_('Tare weight cannot be greater than the gross weight.'))
            if not 0 <= rec.moisture_percent <= 100:
                raise ValidationError(_('Moisture % must be between 0 and 100.'))
            if min(rec.contractor_weight, rec.factory_weight, rec.sorting, rec.number_of_box,
                   rec.weight_per_unit, rec.weight_per_ardab, rec.ardab_wg) < 0:
                raise ValidationError(_('Weights and quantities cannot be negative.'))
            if rec.sorting > rec.factory_weight:
                raise ValidationError(_('Sorting cannot be greater than the factory weight.'))

    @api.onchange('contract_id')
    def _onchange_contract_id(self):
        contract = self.contract_id
        if contract:
            self.contractor_id = contract.partner_id
            self.product_id = contract.product_id
            self.crop_type = contract.crop_type
            self.season_id = contract.season_id

    @api.onchange('farmer_id')
    def _onchange_farmer_id(self):
        if self.land_id.farmer_id != self.farmer_id:
            self.land_id = False
        if self.contract_id.farmer_id != self.farmer_id:
            self.contract_id = False

    @api.model
    def get_dashboard_data(self):
        today = fields.Date.context_today(self)
        base = [('state', '!=', 'cancel'), ('company_id', 'in', self.env.companies.ids)]
        recs = self.search(base)
        unsettled = recs.filtered(lambda r: r.state == 'po_created' and not r.settlement_id)
        start = today.replace(day=1) - relativedelta(months=5)
        groups = self._read_group(base + [('date', '>=', start)], ['date:month'], ['factory_weight:sum'])
        contracts = self.env['seeds.contract'].search([('state', '=', 'running')])
        return {
            'receipts': len(recs),
            'draft': len(recs.filtered(lambda r: r.state == 'draft')),
            'factory_weight': sum(recs.mapped('factory_weight')),
            'ardab': sum(recs.mapped('number_of_ardab')),
            'unsettled_count': len(unsettled),
            'unsettled_amount': sum(unsettled.mapped('settlement_amount')),
            'corn': sum(recs.filtered(lambda r: r.crop_type == 'corn').mapped('number_of_ardab')),
            'wheat': sum(recs.filtered(lambda r: r.crop_type == 'wheat').mapped('number_of_ardab')),
            'contracts': len(contracts),
            'contracted': sum(contracts.mapped('contracted_qty')),
            'delivered': sum(contracts.mapped('delivered_qty')),
            'monthly': [{'label': d.strftime('%b %y') if d else '', 'value': v} for d, v in groups],
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('seeds.receipt') or 'New'
        return super().create(vals_list)

    def unlink(self):
        if any(rec.state not in ('draft', 'cancel') for rec in self):
            raise UserError(_('You can only delete draft or cancelled receipts.'))
        return super().unlink()

    def action_confirm(self):
        for rec in self:
            contract = rec.contract_id
            if contract:
                if contract.state != 'running':
                    raise UserError(_('Contract %s is not running.', contract.name))
                if contract.delivered_qty + rec.number_of_ardab > contract.contracted_qty:
                    raise UserError(_('This receipt exceeds the contracted quantity of %(c)s. '
                                      'Delivered so far: %(d)s ardab.',
                                      c=contract.name, d=contract.delivered_qty))
            if rec.factory_weight <= 0:
                raise UserError(_('Factory weight must be greater than zero.'))
            if rec.number_of_ardab <= 0:
                raise UserError(_('Number of Ardab must be greater than zero. Check Number of Box, '
                                  'Weight Per Unit and Ardab WG.'))
            rec.state = 'confirmed'

    def action_create_purchase_order(self):
        for rec in self:
            if rec.state != 'confirmed':
                raise UserError(_('Only confirmed receipts can create a purchase order.'))
            if rec.purchase_order_id:
                raise UserError(_('A purchase order was already created for this receipt.'))
            po = self.env['purchase.order'].create({
                'partner_id': rec.contractor_id.id,
                'company_id': rec.company_id.id,
                'picking_type_id': rec.warehouse_id.in_type_id.id,
                'origin': rec.name,
                'seeds_receipt_id': rec.id,
                'order_line': [Command.create({
                    'product_id': rec.product_id.id,
                    'name': rec.product_id.display_name,
                    'product_qty': rec.number_of_ardab,
                    'price_unit': rec.adjusted_price,
                })],
            })
            rec.write({'purchase_order_id': po.id, 'state': 'po_created'})
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state == 'po_created':
                raise UserError(_('Cancel the purchase order first.'))
            if rec.settlement_id:
                raise UserError(_('This receipt is part of a settlement.'))
            rec.state = 'cancel'

    def action_draft(self):
        self.write({'state': 'draft'})

    def action_view_purchase_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': self.purchase_order_id.id,
            'view_mode': 'form',
        }

    def action_view_pickings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Receipts'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.picking_ids.ids)],
        }
