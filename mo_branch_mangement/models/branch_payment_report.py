# -*- coding: utf-8 -*-
from odoo import api, models


class BranchPaymentReport(models.AbstractModel):
    _name = 'branch.payment.report'
    _description = 'Branch Payments Report'

    @api.model
    def get_dashboard_data(self, date_from=False, date_to=False, branch_id=False):
        domain = [('state', '=', 'paid')]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        if branch_id:
            domain.append(('branch_id', '=', branch_id))

        payments = self.env['account.payment'].search(domain)
        branches = self.env['res.branch'].search(
            [('id', '=', branch_id)] if branch_id else [])

        lines = []
        for branch in branches:
            b_payments = payments.filtered(lambda p, b=branch: p.branch_id.id == b.id)
            inbound = b_payments.filtered(lambda p: p.payment_type == 'inbound')
            outbound = b_payments.filtered(lambda p: p.payment_type == 'outbound')
            if not b_payments:
                continue
            lines.append({
                'branch_id': branch.id,
                'branch_name': branch.name,
                'inbound_amount': sum(inbound.mapped('amount')),
                'outbound_amount': sum(outbound.mapped('amount')),
                'net_amount': sum(inbound.mapped('amount')) - sum(outbound.mapped('amount')),
                'payments_count': len(b_payments),
            })

        totals = {
            'inbound_amount': sum(l['inbound_amount'] for l in lines),
            'outbound_amount': sum(l['outbound_amount'] for l in lines),
            'net_amount': sum(l['net_amount'] for l in lines),
            'payments_count': sum(l['payments_count'] for l in lines),
        }

        return {
            'lines': lines,
            'totals': totals,
            'currency_symbol': self.env.company.currency_id.symbol,
        }
