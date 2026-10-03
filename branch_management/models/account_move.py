# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    branch_id = fields.Many2one(
        'res.branch', string='Branch', store=True, readonly=False,
        default=lambda self: self.env.user.branch_id or self.env.user.branch_ids[:1],
        help='Branch this invoice/bill belongs to, used for branch credit '
             'limit exposure calculation.')

    def write(self, vals):
        if 'branch_id' in vals:
            for move in self:
                if move.state == 'posted' and move.branch_id.id != vals['branch_id']:
                    raise UserError(_(
                        "You cannot change the Branch of %(name)s because it is "
                        "already posted. Reset it to draft first.", name=move.name))
        return super().write(vals)

    @api.depends('branch_id')
    def _compute_suitable_journal_ids(self):
        # Core already scopes this to journals of the right type/company,
        # and the account.journal branch record rule already hides
        # journals belonging to a branch outside the current user's
        # Allowed Branches. This further narrows the choice to journals of
        # THIS move's specific branch (or unbranded/shared journals) when
        # the user is allowed more than one branch.
        super()._compute_suitable_journal_ids()
        for move in self:
            if move.branch_id:
                move.suitable_journal_ids = move.suitable_journal_ids.filtered(
                    lambda j: not j.branch_id or j.branch_id == move.branch_id)

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        for move in self:
            account = move.branch_id.analytic_account_id if move.branch_id else False
            if not account:
                continue
            # By posting time all lines exist (product, tax, receivable/payable).
            # Only fill in lines the product-line hook below didn't already tag.
            lines = move.line_ids.filtered(
                lambda l: l.account_id and not l.analytic_distribution)
            if lines:
                lines.write({'analytic_distribution': {str(account.id): 100}})
        return posted


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    branch_id = fields.Many2one(
        'res.branch', string='Branch', related='move_id.branch_id',
        store=True, readonly=False, required=True,
        default=lambda self: self.env.user.branch_id or self.env.user.branch_ids[:1],
        help='Branch this payment belongs to. Kept in sync with the '
             "underlying journal entry's Branch (they are the same field) "
             'so analytic tagging always matches what is shown here. '
             "Defaults to the current user's Branch when the payment is "
             'created directly (outside the Register Payment wizard, '
             'which already defaults it from the invoice(s) being paid).')

    def write(self, vals):
        if 'branch_id' in vals:
            for payment in self:
                if payment.state in ('in_process', 'paid', 'reconciled') \
                        and payment.branch_id.id != vals['branch_id']:
                    raise UserError(_(
                        "You cannot change the Branch of %(name)s because it is "
                        "already posted. Reset it to draft first.", name=payment.name))
        return super().write(vals)

    @api.depends('branch_id')
    def _compute_available_journal_ids(self):
        # See account.payment.register's override of the same method for
        # why this extra narrowing (by this payment's own Branch) is done
        # on top of what core and the account.journal branch record rule
        # already filter out.
        super()._compute_available_journal_ids()
        for payment in self:
            if payment.branch_id:
                payment.available_journal_ids = payment.available_journal_ids.filtered(
                    lambda j: not j.branch_id or j.branch_id == payment.branch_id)


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            branch = line.move_id.branch_id
            account = branch.analytic_account_id if branch else False
            if account and not line.analytic_distribution:
                line.analytic_distribution = {str(account.id): 100}
        return lines
