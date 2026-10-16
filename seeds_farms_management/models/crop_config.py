from odoo import fields, models


class SeedsCropConfig(models.Model):
    _name = 'seeds.crop.config'
    _description = 'Crop Calculation Settings'

    name = fields.Char(required=True)
    crop_type = fields.Selection([('corn', 'Corn'), ('wheat', 'Wheat')], required=True)
    weight_per_ardab = fields.Float(string='Weight / Ardab (kg)', digits=(16, 2), required=True)
    ardab_wg = fields.Float(string='Ardab WG (kg)', digits=(16, 2), required=True)
    standard_moisture = fields.Float(string='Standard Moisture %', digits=(16, 2), default=14.0)
    moisture_rate = fields.Float(string='Deduction % per 1% Excess', digits=(16, 2), default=1.0)

    _crop_type_uniq = models.Constraint('unique(crop_type)', 'Each crop type can only have one configuration.')
