from odoo import api, fields, models


class SeedsFarmer(models.Model):
    _name = 'seeds.farmer'
    _inherit = ['mail.thread']
    _description = 'Seeds Farmer'
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    phone = fields.Char()
    street = fields.Char()
    city = fields.Char(string='City')
    state_id = fields.Many2one('res.country.state', string='State',
                               domain="[('country_id', '=?', country_id)]")
    country_id = fields.Many2one('res.country', string='Country')
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    notes = fields.Text()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company)
    receipt_ids = fields.One2many('seeds.receipt', 'farmer_id')
    land_ids = fields.One2many('seeds.land', 'farmer_id', string='Fields')
    receipt_count = fields.Integer(compute='_compute_receipt_count')

    @api.depends('receipt_ids')
    def _compute_receipt_count(self):
        for rec in self:
            rec.receipt_count = len(rec.receipt_ids)

    def action_view_receipts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Seed Receipts',
            'res_model': 'seeds.receipt',
            'view_mode': 'list,form',
            'domain': [('farmer_id', '=', self.id)],
            'context': {'default_farmer_id': self.id},
        }
