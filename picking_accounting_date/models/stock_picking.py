from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    use_accounting_date = fields.Boolean(
        string='Use Accounting Date',
        default=True,
        copy=False,
    )
    accounting_date = fields.Date(
        string='Accounting Date',
        default=lambda self: fields.Date.context_today(self) + relativedelta(months=1),
        copy=False,
    )

    @api.constrains('use_accounting_date', 'accounting_date')
    def _check_accounting_date(self):
        for picking in self:
            if picking.use_accounting_date and not picking.accounting_date:
                raise UserError(_("Please set the Accounting Date or uncheck 'Use Accounting Date'."))

    def write(self, vals):
        if 'use_accounting_date' in vals or 'accounting_date' in vals:
            if any(p.state == 'done' for p in self):
                raise UserError(_("You cannot change the accounting date after the picking is validated."))
        return super().write(vals)
