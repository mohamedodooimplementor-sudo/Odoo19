from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    check_id = fields.Many2one(
        "check.management", string="Check", copy=False, readonly=True, index="btree_not_null"
    )
    check_role = fields.Selection(
        [
            ("receive", "Check Received"),
            ("deposit", "Check Deposited"),
            ("collect", "Check Collected"),
            ("handover", "Check Handed Over"),
            ("clear", "Check Cleared"),
            ("bounce", "Check Bounced"),
            ("bounce_fee", "Bounce Bank Charges"),
            ("reversal", "Reversal"),
        ],
        string="Check Operation", copy=False, readonly=True,
    )
