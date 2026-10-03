# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    branch_id = fields.Many2one(
        'res.branch', string='Branch', compute='_compute_branch_id',
        store=True, readonly=False,
        help='Defaults to the Branch of the invoice(s) being paid.')

    @api.depends('line_ids')
    def _compute_branch_id(self):
        for wizard in self:
            branches = wizard.line_ids.move_id.branch_id
            if branches:
                wizard.branch_id = branches[0]
            else:
                wizard.branch_id = wizard.env.user.branch_id

    @api.depends('branch_id')
    def _compute_available_journal_ids(self):
        # Core already scopes this to journals with a matching payment
        # method for the batch's payment type/currency, and account.journal
        # 's own branch record rule already hides journals belonging to a
        # branch outside the current user's Allowed Branches. This further
        # narrows the choice to journals of THIS wizard's specific branch
        # (or unbranded/shared journals) when the user is allowed more than
        # one branch.
        super()._compute_available_journal_ids()
        for wizard in self:
            if wizard.branch_id:
                wizard.available_journal_ids = wizard.available_journal_ids.filtered(
                    lambda j: not j.branch_id or j.branch_id == wizard.branch_id)

    def _create_payment_vals_from_wizard(self, batch_result):
        payment_vals = super()._create_payment_vals_from_wizard(batch_result)
        if self.branch_id:
            payment_vals['branch_id'] = self.branch_id.id
        return payment_vals
