from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SeedsSeason(models.Model):
    _name = 'seeds.season'
    _description = 'Farming Season'
    _order = 'date_start desc'

    name = fields.Char(required=True)
    date_start = fields.Date(required=True)
    date_end = fields.Date(required=True)
    active = fields.Boolean(default=True)

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_end < rec.date_start:
                raise ValidationError(self.env._('Season end date cannot be before the start date.'))


class SeedsLand(models.Model):
    _name = 'seeds.land'
    _description = 'Farmer Field'

    name = fields.Char(string='Field Name', required=True)
    farmer_id = fields.Many2one('seeds.farmer', required=True, ondelete='cascade')
    area = fields.Float(string='Area (Feddan)', digits=(16, 2))
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    notes = fields.Text()
    active = fields.Boolean(default=True)
