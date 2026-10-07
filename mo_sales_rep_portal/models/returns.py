from odoo import fields, models


class ReturnReason(models.Model):
    _name = 'mo.return.reason'
    _description = 'Customer Return Reason'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
