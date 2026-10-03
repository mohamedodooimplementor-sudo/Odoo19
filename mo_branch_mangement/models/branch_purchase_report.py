# -*- coding: utf-8 -*-
from odoo import api, models


class BranchPurchaseReport(models.AbstractModel):
    _name = 'branch.purchase.report'
    _description = 'Branch Purchase Performance Report'

    @api.model
    def get_dashboard_data(self, date_from=False, date_to=False,
                            branch_id=False, partner_id=False):
        move_domain = [('move_type', '=', 'in_invoice'), ('state', '=', 'posted')]
        po_domain = [('state', 'in', ('purchase', 'done'))]

        if date_from:
            move_domain.append(('invoice_date', '>=', date_from))
            po_domain.append(('date_order', '>=', date_from))
        if date_to:
            move_domain.append(('invoice_date', '<=', date_to))
            po_domain.append(('date_order', '<=', date_to))
        if branch_id:
            move_domain.append(('branch_id', '=', branch_id))
            po_domain.append(('branch_id', '=', branch_id))
        if partner_id:
            move_domain.append(('partner_id', '=', partner_id))
            po_domain.append(('partner_id', '=', partner_id))

        moves = self.env['account.move'].search(move_domain)
        orders = self.env['purchase.order'].search(po_domain)
        branches = self.env['res.branch'].search(
            [('id', '=', branch_id)] if branch_id else [])

        lines = []
        for branch in branches:
            b_moves = moves.filtered(lambda m, b=branch: m.branch_id.id == b.id)
            b_orders = orders.filtered(lambda o, b=branch: o.branch_id.id == b.id)
            purchase_amount = sum(b_moves.mapped('amount_total'))
            outstanding_amount = sum(b_moves.mapped('amount_residual'))
            paid_amount = purchase_amount - outstanding_amount
            if not b_moves and not b_orders:
                continue
            lines.append({
                'branch_id': branch.id,
                'branch_name': branch.name,
                'purchase_amount': purchase_amount,
                'paid_amount': paid_amount,
                'outstanding_amount': outstanding_amount,
                'orders_count': len(b_orders),
                'vendors_count': len(set(b_orders.mapped('partner_id.id'))),
            })

        totals = {
            'purchase_amount': sum(l['purchase_amount'] for l in lines),
            'paid_amount': sum(l['paid_amount'] for l in lines),
            'outstanding_amount': sum(l['outstanding_amount'] for l in lines),
            'orders_count': sum(l['orders_count'] for l in lines),
            'vendors_count': len(set(orders.mapped('partner_id.id'))),
        }

        return {
            'lines': lines,
            'totals': totals,
            'currency_symbol': self.env.company.currency_id.symbol,
        }
