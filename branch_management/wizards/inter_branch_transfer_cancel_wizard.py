# -*- coding: utf-8 -*-
from odoo import fields, models


class InterBranchTransferCancelWizard(models.TransientModel):
    _name = 'inter.branch.transfer.cancel.wizard'
    _description = 'Cancel Inter-Branch Transfer'

    transfer_id = fields.Many2one(
        'inter.branch.transfer', string='Transfer', required=True)
    reason = fields.Text(string='Cancellation Reason', required=True)

    def action_confirm_cancel(self):
        self.ensure_one()
        self.transfer_id._do_cancel(self.reason)
