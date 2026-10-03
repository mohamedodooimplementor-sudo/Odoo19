# -*- coding: utf-8 -*-
from odoo import api, models


class BranchOverviewReport(models.AbstractModel):
    _name = 'branch.overview.report'
    _description = 'Branch Overview Dashboard'

    @api.model
    def get_dashboard_data(self, date_from=False, date_to=False, branch_id=False):
        branches = self.env['res.branch'].search(
            [('id', '=', branch_id)] if branch_id else [])

        sale_domain = [('move_type', '=', 'out_invoice'), ('state', '=', 'posted')]
        purchase_domain = [('move_type', '=', 'in_invoice'), ('state', '=', 'posted')]
        so_domain = [('state', 'in', ('sale', 'done'))]
        po_domain = [('state', 'in', ('purchase', 'done'))]

        if date_from:
            sale_domain.append(('invoice_date', '>=', date_from))
            purchase_domain.append(('invoice_date', '>=', date_from))
            so_domain.append(('date_order', '>=', date_from))
            po_domain.append(('date_order', '>=', date_from))
        if date_to:
            sale_domain.append(('invoice_date', '<=', date_to))
            purchase_domain.append(('invoice_date', '<=', date_to))
            so_domain.append(('date_order', '<=', date_to))
            po_domain.append(('date_order', '<=', date_to))
        if branch_id:
            sale_domain.append(('branch_id', '=', branch_id))
            purchase_domain.append(('branch_id', '=', branch_id))
            so_domain.append(('branch_id', '=', branch_id))
            po_domain.append(('branch_id', '=', branch_id))

        transfer_domain = [('state', '!=', 'cancel')]
        payment_domain = [('state', '=', 'paid')]
        if date_from:
            transfer_domain.append(('date', '>=', date_from))
            payment_domain.append(('date', '>=', date_from))
        if date_to:
            transfer_domain.append(('date', '<=', date_to))
            payment_domain.append(('date', '<=', date_to))
        if branch_id:
            transfer_domain.append('|')
            transfer_domain.append(('source_branch_id', '=', branch_id))
            transfer_domain.append(('destination_branch_id', '=', branch_id))
            payment_domain.append(('branch_id', '=', branch_id))

        sales_moves = self.env['account.move'].search(sale_domain)
        purchase_moves = self.env['account.move'].search(purchase_domain)
        sale_orders = self.env['sale.order'].search(so_domain)
        purchase_orders = self.env['purchase.order'].search(po_domain)
        transfers = self.env['inter.branch.transfer'].search(transfer_domain)
        payments = self.env['account.payment'].search(payment_domain)

        lines = []
        for branch in branches:
            b_sales = sales_moves.filtered(lambda m, b=branch: m.branch_id.id == b.id)
            b_purchases = purchase_moves.filtered(lambda m, b=branch: m.branch_id.id == b.id)
            b_so = sale_orders.filtered(lambda o, b=branch: o.branch_id.id == b.id)
            b_po = purchase_orders.filtered(lambda o, b=branch: o.branch_id.id == b.id)
            b_transfers = transfers.filtered(
                lambda t, b=branch: t.source_branch_id.id == b.id or t.destination_branch_id.id == b.id)
            b_payments = payments.filtered(lambda p, b=branch: p.branch_id.id == b.id)
            b_inbound = b_payments.filtered(lambda p: p.payment_type == 'inbound')
            b_outbound = b_payments.filtered(lambda p: p.payment_type == 'outbound')

            sales_amount = sum(b_sales.mapped('amount_total'))
            purchase_amount = sum(b_purchases.mapped('amount_total'))
            outstanding_amount = sum(b_sales.mapped('amount_residual'))
            payments_net_amount = sum(b_inbound.mapped('amount')) - sum(b_outbound.mapped('amount'))

            if not (b_sales or b_purchases or b_so or b_po or b_transfers or b_payments):
                continue

            lines.append({
                'branch_id': branch.id,
                'branch_name': branch.name,
                'sales_amount': sales_amount,
                'purchase_amount': purchase_amount,
                'net_amount': sales_amount - purchase_amount,
                'outstanding_amount': outstanding_amount,
                'credit_limit': 0.0 if branch.no_credit_limit else branch.credit_limit,
                'so_count': len(b_so),
                'po_count': len(b_po),
                'users_count': len(branch.user_ids),
                'transfers_count': len(b_transfers),
                'payments_count': len(b_payments),
                'payments_net_amount': payments_net_amount,
            })

        lines.sort(key=lambda l: l['sales_amount'], reverse=True)

        totals = {
            'sales_amount': sum(l['sales_amount'] for l in lines),
            'purchase_amount': sum(l['purchase_amount'] for l in lines),
            'net_amount': sum(l['net_amount'] for l in lines),
            'outstanding_amount': sum(l['outstanding_amount'] for l in lines),
            'branches_count': len(lines),
            'so_count': sum(l['so_count'] for l in lines),
            'po_count': sum(l['po_count'] for l in lines),
            'transfers_count': sum(l['transfers_count'] for l in lines),
            'payments_count': sum(l['payments_count'] for l in lines),
            'payments_net_amount': sum(l['payments_net_amount'] for l in lines),
        }

        return {
            'lines': lines,
            'totals': totals,
            'currency_symbol': self.env.company.currency_id.symbol,
        }
