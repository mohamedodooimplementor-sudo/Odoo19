# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class IntercompanyDashboard(http.Controller):

    @http.route('/intercompany/dashboard_data', type='json', auth='user')
    def dashboard_data(self, company_id=False, months=6):
        Op  = request.env['intercompany.operation']
        Pay = request.env['intercompany.payment']
        Ret = request.env['intercompany.return']
        PickTr = request.env['intercompany.picking.transfer']
        PayTr = request.env['intercompany.payment.transfer']

        currency_symbol = request.env.company.currency_id.symbol or ''

        # ── Filters: company + chart time-window ─────────────────
        try:
            months = int(months) if months else 0
            # منع قيم غير منطقية
            if months < 0 or months > 120:
                months = 6
        except (TypeError, ValueError):
            months = 6
        company_id = int(company_id) if company_id else False

        op_domain = []
        pay_domain = []
        if company_id:
            op_domain.append(('company_ids', 'in', [company_id]))
            pay_domain.append(('line_ids.company_id', '=', company_id))

        ret_domain = []
        if company_id:
            ret_domain.append(('company_id', '=', company_id))

        pt_domain = []
        if company_id:
            pt_domain.append('|')
            pt_domain.append(('company_sent_id', '=', company_id))
            pt_domain.append(('company_receive_id', '=', company_id))
        payt_domain = pt_domain

        # List of companies the current user can switch to, for the selector
        companies = [{'id': c.id, 'name': c.name} for c in request.env.user.company_ids]

        # ── KPI: Operation counts ────────────────────────────────
        total        = Op.search_count(op_domain)
        total_sale   = Op.search_count(op_domain + [('operation_type', '=', 'sale')])
        total_pur    = Op.search_count(op_domain + [('operation_type', '=', 'purchase')])
        total_lc     = Op.search_count(op_domain + [('operation_type', '=', 'landed_cost')])
        total_done   = Op.search_count(op_domain + [('state', '=', 'done')])
        total_draft  = Op.search_count(op_domain + [('state', '=', 'draft')])
        total_to_approve   = Op.search_count(op_domain + [('state', '=', 'to_approve')])
        total_approved     = Op.search_count(op_domain + [('state', '=', 'approved')])
        total_conf         = Op.search_count(op_domain + [('state', '=', 'confirmed')])
        total_pick_conf    = Op.search_count(op_domain + [('state', '=', 'pickings_confirmed')])
        total_cancel = Op.search_count(op_domain + [('state', '=', 'cancelled')])
        total_refused = Op.search_count(op_domain + [('state', '=', 'refused')])

        # ── KPI: Per-type state breakdown ────────────────────────
        sale_base = op_domain + [('operation_type', '=', 'sale')]
        pur_base  = op_domain + [('operation_type', '=', 'purchase')]
        lc_base   = op_domain + [('operation_type', '=', 'landed_cost')]
        pay_base  = op_domain + [('operation_type', '=', 'payment')]

        sale_draft    = Op.search_count(sale_base + [('state', '=', 'draft')])
        sale_progress = Op.search_count(sale_base + [('state', 'not in', ['draft', 'done', 'cancelled', 'refused'])])
        sale_done     = Op.search_count(sale_base + [('state', '=', 'done')])

        purchase_draft    = Op.search_count(pur_base + [('state', '=', 'draft')])
        purchase_progress = Op.search_count(pur_base + [('state', 'not in', ['draft', 'done', 'cancelled', 'refused'])])
        purchase_done     = Op.search_count(pur_base + [('state', '=', 'done')])

        lc_draft    = Op.search_count(lc_base + [('state', '=', 'draft')])
        lc_progress = Op.search_count(lc_base + [('state', 'not in', ['draft', 'done', 'cancelled', 'refused'])])
        lc_done     = Op.search_count(lc_base + [('state', '=', 'done')])

        payment_draft = Op.search_count(pay_base + [('state', '=', 'draft')])
        payment_done  = Op.search_count(pay_base + [('state', '=', 'done')])

        # ── KPI: Returns ─────────────────────────────────────────
        ret_total      = Ret.search_count(ret_domain)
        ret_draft      = Ret.search_count(ret_domain + [('state', '=', 'draft')])
        ret_to_approve = Ret.search_count(ret_domain + [('state', '=', 'to_approve')])
        ret_approved   = Ret.search_count(ret_domain + [('state', '=', 'approved')])
        ret_confirmed  = Ret.search_count(ret_domain + [('state', '=', 'confirmed')])
        ret_returned   = Ret.search_count(ret_domain + [('state', '=', 'returned')])
        ret_done       = Ret.search_count(ret_domain + [('state', '=', 'done')])
        ret_cancelled  = Ret.search_count(ret_domain + [('state', '=', 'cancelled')])
        ret_refused    = Ret.search_count(ret_domain + [('state', '=', 'refused')])

        # ── KPI: Branches Transfer — Picking Transfer ────────────
        pt_total         = PickTr.search_count(pt_domain)
        pt_draft         = PickTr.search_count(pt_domain + [('state', '=', 'draft')])
        pt_to_approve    = PickTr.search_count(pt_domain + [('state', '=', 'to_approve')])
        pt_approved      = PickTr.search_count(pt_domain + [('state', '=', 'approved')])
        pt_send_approved = PickTr.search_count(pt_domain + [('state', '=', 'send_approved')])
        pt_received      = PickTr.search_count(pt_domain + [('state', '=', 'received')])
        pt_cancelled     = PickTr.search_count(pt_domain + [('state', '=', 'cancelled')])
        pt_refused       = PickTr.search_count(pt_domain + [('state', '=', 'refused')])

        # ── KPI: Branches Transfer — Payment Transfer ─────────────
        payt_total      = PayTr.search_count(payt_domain)
        payt_draft      = PayTr.search_count(payt_domain + [('state', '=', 'draft')])
        payt_to_approve = PayTr.search_count(payt_domain + [('state', '=', 'to_approve')])
        payt_approved   = PayTr.search_count(payt_domain + [('state', '=', 'approved')])
        payt_posted     = PayTr.search_count(payt_domain + [('state', '=', 'posted')])
        payt_cancelled  = PayTr.search_count(payt_domain + [('state', '=', 'cancelled')])
        payt_refused    = PayTr.search_count(payt_domain + [('state', '=', 'refused')])


        # ── KPI: Payment ───────────────────────────────────────────
        pay_ops        = Op.search(op_domain + [('operation_type', '=', 'payment')])
        pay_ops_count  = len(pay_ops)
        pay_ops_amount = sum(pay_ops.mapped('amount_total'))

        all_pay_dist = Pay.search(pay_domain)
        standalone_pay_dist = all_pay_dist.filtered(
            lambda p: not any(pay.intercompany_operation_id for pay in p.payment_ids)
        )
        pay_dist_count  = len(standalone_pay_dist)
        pay_dist_amount = sum(standalone_pay_dist.mapped('amount_total'))

        pay_total_count  = pay_ops_count + pay_dist_count
        pay_total_amount = pay_ops_amount + pay_dist_amount

        # ── KPI: Payment Distribution pipeline (by state) ───────
        pd_draft      = Pay.search_count(pay_domain + [('state', '=', 'draft')])
        pd_to_approve = Pay.search_count(pay_domain + [('state', '=', 'to_approve')])
        pd_approved   = Pay.search_count(pay_domain + [('state', '=', 'approved')])
        pd_posted     = Pay.search_count(pay_domain + [('state', '=', 'posted')])
        pd_cancelled  = Pay.search_count(pay_domain + [('state', '=', 'cancelled')])
        pd_refused    = Pay.search_count(pay_domain + [('state', '=', 'refused')])

        # ── KPI: Pending Approvals ──────────────────────────────
        pending_ops_count = total_to_approve
        pending_pay_count = pd_to_approve
        pending_ret_count = ret_to_approve
        pending_transfer_count = pt_to_approve + payt_to_approve
        pending_total     = pending_ops_count + pending_pay_count + pending_ret_count + pending_transfer_count

        # ── Amounts for Sale / Purchase ──────────────────────────
        def sum_amount(domain):
            return sum(Op.search(domain).mapped('amount_total'))

        amount_sale = sum_amount(op_domain + [('operation_type', '=', 'sale')])
        amount_pur  = sum_amount(op_domain + [('operation_type', '=', 'purchase')])
        amount_lc   = sum_amount(op_domain + [('operation_type', '=', 'landed_cost')])

        # ── Monthly data ─────────────────────────────────────────
        query_params = {'months': f'{months} months', 'company_id': company_id}

        sql_monthly = """
            SELECT
                TO_CHAR(operation_date, 'Mon YYYY') AS month,
                DATE_TRUNC('month', operation_date) AS month_date,
                operation_type,
                SUM(amount_total) AS total
            FROM intercompany_operation
            WHERE operation_type IN ('sale', 'purchase', 'landed_cost')
        """
        if months:
            sql_monthly += " AND operation_date >= NOW() - INTERVAL %(months)s"
        if company_id:
            sql_monthly += """ AND id IN (
                SELECT operation_id FROM intercompany_operation_line WHERE company_id = %(company_id)s
            )"""
        sql_monthly += " GROUP BY month, month_date, operation_type ORDER BY month_date"

        request.env.cr.execute(sql_monthly, query_params)
        monthly_rows = request.env.cr.dictfetchall()

        sql_pay_op = """
            SELECT
                TO_CHAR(operation_date, 'Mon YYYY') AS month,
                DATE_TRUNC('month', operation_date) AS month_date,
                'payment' AS operation_type,
                SUM(amount_total) AS total
            FROM intercompany_operation
            WHERE operation_type = 'payment'
        """
        if months:
            sql_pay_op += " AND operation_date >= NOW() - INTERVAL %(months)s"
        if company_id:
            sql_pay_op += """ AND id IN (
                SELECT operation_id FROM intercompany_operation_payment_line WHERE company_id = %(company_id)s
            )"""
        sql_pay_op += " GROUP BY month, month_date"

        request.env.cr.execute(sql_pay_op, query_params)
        pay_op_rows = request.env.cr.dictfetchall()

        sql_pay_dist = """
            SELECT
                TO_CHAR(ip.payment_date, 'Mon YYYY') AS month,
                DATE_TRUNC('month', ip.payment_date) AS month_date,
                'payment' AS operation_type,
                SUM(ip.amount_total) AS total
            FROM intercompany_payment ip
            WHERE NOT EXISTS (
                  SELECT 1 FROM account_payment ap
                  WHERE ap.intercompany_payment_id = ip.id
                    AND ap.intercompany_operation_id IS NOT NULL
              )
        """
        if months:
            sql_pay_dist += " AND ip.payment_date >= NOW() - INTERVAL %(months)s"
        if company_id:
            sql_pay_dist += """ AND ip.id IN (
                SELECT payment_id FROM intercompany_payment_line WHERE company_id = %(company_id)s
            )"""
        sql_pay_dist += " GROUP BY month, month_date"

        request.env.cr.execute(sql_pay_dist, query_params)
        pay_dist_rows = request.env.cr.dictfetchall()

        for row in pay_op_rows:
            row['operation_type'] = 'payment'
        for row in pay_dist_rows:
            row['operation_type'] = 'payment_dist'

        sql_pay_transfer = """
            SELECT
                TO_CHAR(date, 'Mon YYYY') AS month,
                DATE_TRUNC('month', date) AS month_date,
                'branches_payment_transfer' AS operation_type,
                SUM(amount) AS total
            FROM intercompany_payment_transfer
            WHERE state != 'cancelled'
        """
        if months:
            sql_pay_transfer += " AND date >= NOW() - INTERVAL %(months)s"
        if company_id:
            sql_pay_transfer += """ AND (company_sent_id = %(company_id)s
                OR company_receive_id = %(company_id)s)"""
        sql_pay_transfer += " GROUP BY month, month_date"

        request.env.cr.execute(sql_pay_transfer, query_params)
        pay_transfer_rows = request.env.cr.dictfetchall()

        all_monthly = monthly_rows + pay_op_rows + pay_dist_rows + pay_transfer_rows
        for r in all_monthly:
            r['total'] = float(r['total'])
            r['month_date'] = str(r['month_date'])

        # ── Recent 8 operations ──────────────────────────────────
        recent = Op.search(op_domain, limit=8, order='id desc')
        recent_data = []
        for r in recent:
            recent_data.append({
                'id': r.id,
                'name': r.name,
                'partner': r.partner_id.name or '',
                'type': r.operation_type,
                'date': str(r.operation_date),
                'amount': r.amount_total,
                'state': r.state,
                'currency': currency_symbol,
            })

        # ── Recent 5 standalone payment distributions ─────────────
        recent_pay_dist = standalone_pay_dist.sorted('id', reverse=True)[:5]
        recent_pay_data = []
        for p in recent_pay_dist:
            recent_pay_data.append({
                'id': p.id,
                'name': p.name,
                'partner': p.partner_id.name or '',
                'date': str(p.payment_date),
                'amount': p.amount_total,
                'state': p.state,
                'currency': currency_symbol,
            })

        # ── Recent 5 returns ─────────────────────────────────────
        recent_returns = Ret.search(ret_domain, limit=5, order='id desc')
        recent_returns_data = []
        for r in recent_returns:
            recent_returns_data.append({
                'id': r.id,
                'name': r.name,
                'partner': r.partner_id.name or '',
                'type': r.return_type,
                'state': r.state,
            })

        # ── Recent 5 Branches Picking Transfers ───────────────────
        recent_picking_transfer = PickTr.search(pt_domain, limit=5, order='id desc')
        recent_picking_transfer_data = []
        for t in recent_picking_transfer:
            recent_picking_transfer_data.append({
                'id': t.id,
                'name': t.name,
                'from_company': t.company_sent_id.name or '',
                'to_company': t.company_receive_id.name or '',
                'state': t.state,
            })

        # ── Recent 5 Branches Payment Transfers ───────────────────
        recent_payment_transfer = PayTr.search(payt_domain, limit=5, order='id desc')
        recent_payment_transfer_data = []
        for t in recent_payment_transfer:
            recent_payment_transfer_data.append({
                'id': t.id,
                'name': t.name,
                'from_company': t.company_sent_id.name or '',
                'to_company': t.company_receive_id.name or '',
                'amount': t.amount,
                'date': str(t.date or ''),
                'state': t.state,
                'currency': currency_symbol,
            })

        return {
            'filters': {
                'company_id': company_id,
                'months': months,
                'companies': companies,
            },
            'kpi': {
                'total': total,
                'sale': total_sale,
                'sale_draft': sale_draft,
                'sale_progress': sale_progress,
                'sale_done': sale_done,
                'purchase': total_pur,
                'purchase_draft': purchase_draft,
                'purchase_progress': purchase_progress,
                'purchase_done': purchase_done,
                'landed_cost': total_lc,
                'lc_draft': lc_draft,
                'lc_progress': lc_progress,
                'lc_done': lc_done,
                'payment_draft': payment_draft,
                'payment_done': payment_done,
                'done': total_done,
                'draft': total_draft,
                'to_approve': total_to_approve,
                'approved': total_approved,
                'confirmed': total_conf,
                'pickings_confirmed': total_pick_conf,
                'cancelled': total_cancel,
                'refused': total_refused,
                'payment_total': pay_total_count,
                'payment_ops': pay_ops_count,
                'payment_dist': pay_dist_count,
                'pd_draft': pd_draft,
                'pd_to_approve': pd_to_approve,
                'pd_approved': pd_approved,
                'pd_posted': pd_posted,
                'pd_cancelled': pd_cancelled,
                'pd_refused': pd_refused,
                'pending_ops': pending_ops_count,
                'pending_pay': pending_pay_count,
                'pending_ret': pending_ret_count,
                'pending_transfer': pending_transfer_count,
                'pending_total': pending_total,
                # Returns KPI
                'ret_total': ret_total,
                'ret_draft': ret_draft,
                'ret_to_approve': ret_to_approve,
                'ret_approved': ret_approved,
                'ret_confirmed': ret_confirmed,
                'ret_returned': ret_returned,
                'ret_done': ret_done,
                'ret_cancelled': ret_cancelled,
                'ret_refused': ret_refused,
                # Branches Transfer — Picking Transfer
                'pt_total': pt_total,
                'pt_draft': pt_draft,
                'pt_to_approve': pt_to_approve,
                'pt_approved': pt_approved,
                'pt_send_approved': pt_send_approved,
                'pt_received': pt_received,
                'pt_cancelled': pt_cancelled,
                'pt_refused': pt_refused,
                # Branches Transfer — Payment Transfer
                'payt_total': payt_total,
                'payt_draft': payt_draft,
                'payt_to_approve': payt_to_approve,
                'payt_approved': payt_approved,
                'payt_posted': payt_posted,
                'payt_cancelled': payt_cancelled,
                'payt_refused': payt_refused,
            },
            'amounts': {
                'sale': amount_sale,
                'purchase': amount_pur,
                'landed_cost': amount_lc,
                'payment': pay_total_amount,
                'payment_ops': pay_ops_amount,
                'payment_dist': pay_dist_amount,
                'currency': currency_symbol,
            },
            'monthly': all_monthly,
            'recent': recent_data,
            'recent_pay_dist': recent_pay_data,
            'recent_returns': recent_returns_data,
            'recent_picking_transfer': recent_picking_transfer_data,
            'recent_payment_transfer': recent_payment_transfer_data,
        }
