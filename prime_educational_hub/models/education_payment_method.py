# -*- coding: utf-8 -*-
from odoo import api, fields, models


class EducationPaymentMethod(models.Model):
    _name = 'education.payment.method'
    _description = 'Payment Method'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    code = fields.Char(string='Code')
    active = fields.Boolean(default=True)
    requires_reference = fields.Boolean(string='Requires Reference', default=False,
                                         help='If checked, a reference number is mandatory when this '
                                              'method is used on a payment.')
    cash_account_id = fields.Many2one('education.cash.account', string='Deposits Into',
                                       help='The cash drawer or bank account that payments received through '
                                            'this method actually land in. Used to compute each account\'s '
                                            'running balance in the Cash Book / Treasury reports.')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    sequence_id = fields.Many2one('ir.sequence', string='Receipt Sequence', copy=False, readonly=True,
                                   help='Auto-managed: gives this method its own receipt numbering '
                                        '(e.g. CASH-000001, BANK-000001) instead of one shared counter '
                                        'across every payment method.')

    _sql_constraints = [
        ('code_uniq', 'unique(code, company_id)', 'Payment method code must be unique per company.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        methods = super().create(vals_list)
        for method in methods:
            method._ensure_sequence()
        return methods

    def write(self, vals):
        res = super().write(vals)
        if 'code' in vals:
            for method in self:
                method._ensure_sequence()
        return res

    def _ensure_sequence(self):
        """Creates (or renames, if the code changed) a dedicated ir.sequence
        for this payment method, so its receipts number independently --
        e.g. CASH-000001, BANK-000001 -- instead of sharing one counter
        across every method. Falls back to the method's id when no code is
        set yet, so numbering never breaks even before someone fills in
        a code."""
        self.ensure_one()
        prefix = (self.code or 'method%d' % self.id).upper() + '-'
        seq_code = 'education.payment.method.%d' % self.id
        if self.sequence_id:
            if self.sequence_id.prefix != prefix:
                self.sequence_id.write({'name': 'Payment Receipt - %s' % self.name, 'prefix': prefix})
            return
        sequence = self.env['ir.sequence'].sudo().create({
            'name': 'Payment Receipt - %s' % self.name,
            'code': seq_code,
            'prefix': prefix,
            'padding': 6,
            'number_next': 1,
            'number_increment': 1,
            'company_id': self.company_id.id,
        })
        self.sequence_id = sequence.id
