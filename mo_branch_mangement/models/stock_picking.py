# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    branch_id = fields.Many2one(
        'res.branch', string='Branch',
        compute='_compute_branch_id', store=True, readonly=False,
        precompute=True,
        help='Branch this stock picking belongs to. For Inter-Branch '
             'Transfers this is the Source Branch on the Source \u2192 '
             'Transit picking, and the Destination Branch on the '
             'Transit \u2192 Destination picking.\n'
             'Defaults to the Branch of the picking\'s Warehouse (via its '
             'Operation Type) so pickings created outside a Purchase '
             'Order / Sale Order / Inter-Branch Transfer (manual '
             'receipts/deliveries, returns, ...) still get a Branch '
             'instead of being left empty and hidden from restricted '
             'users.')

    @api.depends('picking_type_id', 'picking_type_id.warehouse_id')
    def _compute_branch_id(self):
        for picking in self:
            if picking.branch_id:
                continue
            if picking.picking_type_id.warehouse_id.branch_id:
                picking.branch_id = picking.picking_type_id.warehouse_id.branch_id
            else:
                picking.branch_id = self.env.user.branch_id

    transfer_source_branch_id = fields.Many2one(
        'res.branch', string='Source Branch', readonly=True, copy=False,
        help='The Branch that sent the stock on an Inter-Branch Transfer. '
             'Always the same on both legs (Source \u2192 Transit and '
             'Transit \u2192 Destination) of the transfer, and cannot be '
             'edited manually. Only shown for pickings created from an '
             'Inter-Branch Transfer.')

    def button_validate(self):
        # For Inter-Branch Transfers, the Transit -> Destination picking
        # cannot be validated before the Source -> Transit picking is done:
        # the stock must actually be sitting in the transit location first.
        transfers = self.env['inter.branch.transfer'].search(
            [('picking_id_2', 'in', self.ids)])
        for transfer in transfers:
            if transfer.picking_id_1 and transfer.picking_id_1.state != 'done':
                raise UserError(_(
                    "You cannot validate the Transit \u2192 Destination picking "
                    "of %(name)s before the Source \u2192 Transit picking has "
                    "been validated.", name=transfer.name))
        return super().button_validate()

    def _action_done(self):
        res = super()._action_done()
        # Auto-close the transfer as soon as its Transit -> Destination leg
        # is actually validated, instead of requiring a separate manual
        # "confirm receipt" click.
        #
        # This hooks _action_done() (the method Odoo actually calls to
        # finalize a picking) rather than write(), because stock.picking's
        # 'state' is a stored COMPUTED field: it is recomputed internally
        # and never passes through write() with 'state' in vals, so a
        # write() override checking for that would silently never fire.
        # _action_done() is also the single place this happens regardless
        # of whether validation went through a backorder or immediate
        # transfer wizard.
        #
        # sudo(): the user validating the picking (warehouse/destination
        # team) may not have write access to the inter.branch.transfer
        # record itself under the branch rule (e.g. they only have the
        # Destination Branch, not the Source Branch that rule checks), but
        # closing the transfer is a direct, automatic consequence of their
        # own validation action, not a separate request.
        done_pickings = self.filtered(lambda p: p.state == 'done')
        if done_pickings:
            transfers = self.env['inter.branch.transfer'].sudo().search([
                ('picking_id_2', 'in', done_pickings.ids),
                ('state', '=', 'in_transit'),
            ])
            for transfer in transfers:
                if transfer.picking_id_2.state == 'done':
                    transfer.state = 'done'
        return res
