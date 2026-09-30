from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def _post(self, soft=True):
        """Force posting of stock journal entries that use the picking's
        accounting date, even when that date is in the future (Odoo would
        otherwise leave them as draft with auto-post at date)."""
        if soft:
            today = fields.Date.context_today(self)
            forced = self.filtered(
                lambda m: m.state == 'draft'
                and m.date and m.date > today
                and m.stock_move_id.picking_id.use_accounting_date
                and m.stock_move_id.picking_id.accounting_date
            )
            if forced:
                rest = self - forced
                posted = super(AccountMove, forced)._post(soft=False)
                if rest:
                    posted |= super(AccountMove, rest)._post(soft=True)
                return posted
        return super()._post(soft=soft)
