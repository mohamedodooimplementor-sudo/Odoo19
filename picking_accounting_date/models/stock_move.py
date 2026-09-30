from odoo import models


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _prepare_account_move_vals(self, credit_account_id, debit_account_id, journal_id,
                                   qty, description, svl_id, cost):
        vals = super()._prepare_account_move_vals(
            credit_account_id, debit_account_id, journal_id,
            qty, description, svl_id, cost,
        )
        picking = self.picking_id
        if picking and picking.use_accounting_date and picking.accounting_date:
            vals['date'] = picking.accounting_date
        return vals
