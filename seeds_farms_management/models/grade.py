from odoo import fields, models


class SeedsQualityGrade(models.Model):
    _name = 'seeds.quality.grade'
    _description = 'Seeds Quality Grade'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    code = fields.Char()
    sequence = fields.Integer(default=10)
    price_adjustment = fields.Float(
        string='Price Adjustment %', digits=(16, 2),
        help='Positive = bonus, negative = penalty, applied on the price per ardab.')
    active = fields.Boolean(default=True)
