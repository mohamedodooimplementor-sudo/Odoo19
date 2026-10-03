# -*- coding: utf-8 -*-
from odoo import api, models


class BranchSalesReport(models.AbstractModel):
    _name = 'branch.sales.report'
    _description = 'Branch Sales Performance Report'

    @api.model
    def get_dashboard_data(self, date_from=False, date_to=False,
                            branch_id=False, partner_id=False, user_id=False):
        move_domain = [('move_type', '=', 'out_invoice'), ('state', '=', 'posted')]
        so_domain = [('state', 'in', ('sale', 'done'))]

        if date_from:
            move_domain.append(('invoice_date', '>=', date_from))
            so_domain.append(('date_order', '>=', date_from))
        if date_to:
            move_domain.append(('invoice_date', '<=', date_to))
            so_domain.append(('date_order', '<=', date_to))
        if branch_id:
            move_domain.append(('branch_id', '=', branch_id))
            so_domain.append(('branch_id', '=', branch_id))
        if partner_id:
            move_domain.append(('partner_id', '=', partner_id))
            so_domain.append(('partner_id', '=', partner_id))
        if user_id:
            move_domain.append(('invoice_user_id', '=', user_id))
            so_domain.append(('user_id', '=', user_id))

        moves = self.env['account.move'].search(move_domain)
        orders = self.env['sale.order'].search(so_domain)
        branches = self.env['res.branch'].search(
            [('id', '=', branch_id)] if branch_id else [])

        lines = []
        for branch in branches:
            b_moves = moves.filtered(lambda m, b=branch: m.branch_id.id == b.id)
            b_orders = orders.filtered(lambda o, b=branch: o.branch_id.id == b.id)
            sales_amount = sum(b_moves.mapped('amount_total'))
            outstanding_amount = sum(b_moves.mapped('amount_residual'))
            paid_amount = sales_amount - outstanding_amount
            if not b_moves and not b_orders:
                continue
            lines.append({
                'branch_id': branch.id,
                'branch_name': branch.name,
                'sales_amount': sales_amount,
                'paid_amount': paid_amount,
                'outstanding_amount': outstanding_amount,
                'orders_count': len(b_orders),
                'customers_count': len(set(b_orders.mapped('partner_id.id'))),
            })

        totals = {
            'sales_amount': sum(l['sales_amount'] for l in lines),
            'paid_amount': sum(l['paid_amount'] for l in lines),
            'outstanding_amount': sum(l['outstanding_amount'] for l in lines),
            'orders_count': sum(l['orders_count'] for l in lines),
            'customers_count': len(set(orders.mapped('partner_id.id'))),
        }

        return {
            'lines': lines,
            'totals': totals,
            'currency_symbol': self.env.company.currency_id.symbol,
        }
