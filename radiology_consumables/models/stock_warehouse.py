from odoo import fields, models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    rc_auto_fulfill_on_confirm = fields.Boolean(
        string='Auto Deliver & Invoice on Sale Confirmation',
        help='When enabled, confirming a sales order of this warehouse validates its '
             'delivery transfers (if any), then creates and posts the customer invoice.')
