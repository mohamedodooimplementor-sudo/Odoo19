"""Portal v2 features: new customers, aging, targets, expenses, receipts, cheques, returns, follow-ups, ranking,
offline helpers."""
import re
from collections import defaultdict
from datetime import timedelta

from odoo import fields, http
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

from ..models import analytics
from .i18n import T
from .main import (RepPortal, _client_time, _date, _ensure_approved, _float, _forbidden, _invoices_domain, _money,
                   _payments_domain, _redir, _render, _save_attachments, _settings, _today, rep_required)

EXPENSE_STATES = ('draft', 'submitted', 'approved', 'refused')


def _env():
    return request.env


def _can(rep, key):
    return rep.permission(key)


def _visit_of(rep, visit_id):
    if not visit_id:
        return False
    visit = _env()['mo.sales.visit'].sudo().browse(int(visit_id)).exists()
    return visit if visit and visit.rep_id == rep else False


def _get_payment(rep, payment_id):
    Payment = _env()['account.payment'].sudo()
    pay = Payment.search(_payments_domain(rep) + [('id', '=', payment_id)], limit=1)
    if not pay:
        candidate = Payment.browse(payment_id).exists()
        Move = _env()['account.move'].sudo()
        if candidate and candidate.payment_type == 'inbound' and any(
                Move.search_count(_invoices_domain(rep) + [('id', '=', inv.id)]) for inv in candidate.reconciled_invoice_ids):
            pay = candidate
    return pay


def _returnable(order):
    """{stock.move id: (max returnable qty, move)} for the delivered lines of a sale order."""
    Move = _env()['stock.move'].sudo()
    res = {}
    for picking in order.picking_ids.filtered(lambda p: p.picking_type_code == 'outgoing' and p.state == 'done'):
        for m in picking.move_ids.filtered(lambda m: m.state == 'done' and m.product_id.type != 'service'):
            returned = sum((r.quantity if r.state == 'done' else r.product_uom_qty) for r in Move.search(
                [('origin_returned_move_id', '=', m.id), ('state', 'not in', ('cancel', 'draft'))]))
            left = m.quantity - returned
            if left > 1e-9:
                res[m.id] = (left, m)
    return res


class RepFeatures(http.Controller):

    # ================================================================ new customer
    @http.route('/rep/customer/new', type='http', auth='user')
    @rep_required
    def customer_new(self, rep, **kw):
        if not _can(rep, 'allow_new_customer'):
            return _redir('/rep/customers', T('This action is not allowed.'), 'err')
        env = _env()
        return _render('mo_sales_rep_portal.tpl_customer_form', rep, 'customers', T('New Customer'),
                       pricelists=env['product.pricelist'].sudo().search([]),
                       terms=env['account.payment.term'].sudo().search([]),
                       needs_approval=_settings(rep).customer_approval)

    @http.route('/rep/customer/create', type='http', auth='user', methods=['POST'])
    @rep_required
    def customer_create(self, rep, name=None, mobile=None, phone=None, whatsapp=None, street=None, city=None,
                        lat=None, lng=None, company_type='company', pricelist_id=None, payment_term_id=None,
                        notes=None, client_uid=None, **kw):
        S = _settings(rep)
        Partner = _env()['res.partner'].sudo()
        if client_uid:
            done = Partner.search([('mo_client_uid', '=', client_uid)], limit=1)
            if done:
                return _redir('/rep/customer/%s' % done.id, T('Customer saved.'))
        try:
            if not _can(rep, 'allow_new_customer'):
                raise AccessError(T('This action is not allowed.'))
            if not (name or '').strip():
                raise UserError(T('Enter the customer name.'))
            if not (mobile or phone):
                raise UserError(T('Enter a mobile or phone number.'))
            vals = {
                'name': name.strip(), 'phone': phone or False, 'street': street or False, 'city': city or False,
                'mo_whatsapp': whatsapp or False, 'company_type': company_type if company_type in ('company', 'person') else 'company',
                'comment': notes or False, 'user_id': rep.user_id.id, 'customer_rank': 1,
                'mo_created_by_rep_id': rep.id, 'mo_client_uid': client_uid or False,
                'mo_approval_state': 'waiting' if S.customer_approval else 'approved',
            }
            if 'mobile' in Partner._fields:
                vals['mobile'] = mobile or False
            elif mobile and not phone:
                vals['phone'] = mobile
            la, ln = _float(lat), _float(lng)
            if la or ln:
                vals.update({'partner_latitude': la, 'partner_longitude': ln})
            if pricelist_id:
                vals['property_product_pricelist'] = int(pricelist_id)
            if payment_term_id:
                vals['property_payment_term_id'] = int(payment_term_id)
            partner = Partner.with_company(rep.company_id).create(vals)
            rep.sudo().customer_ids = [(4, partner.id)]
            _save_attachments('res.partner', partner.id, request.httprequest.files.getlist('attachments'))
            rep._audit(partner, T('created the customer from the portal'))
        except (UserError, AccessError, ValidationError) as e:
            return _redir('/rep/customer/new', str(e), 'err')
        msg = T('Customer saved. It is waiting for approval.') if partner.mo_approval_state == 'waiting' else T('Customer saved.')
        return _redir('/rep/customer/%s' % partner.id, msg)

    # ================================================================ outstanding & aging
    @http.route('/rep/outstanding', type='http', auth='user')
    @rep_required
    def outstanding(self, rep, **kw):
        env = _env()
        today = _today()
        invoices = analytics.open_invoices(env, _invoices_domain(rep))
        ag = analytics.aging(invoices, today)
        per = defaultdict(lambda: {'total': 0.0, 'overdue': 0.0, 'count': 0})
        for inv in invoices:
            row = per[inv.partner_id]
            row['total'] += inv.amount_residual_signed
            row['count'] += 1
            if (inv.invoice_date_due or today) < today:
                row['overdue'] += inv.amount_residual_signed
        customers = sorted(per.items(), key=lambda kv: (-kv[1]['overdue'], -kv[1]['total']))
        return _render('mo_sales_rep_portal.tpl_outstanding', rep, 'more', T('Outstanding'), ag=ag,
                       customers=customers, bucket_order=analytics.BUCKETS)

    # ================================================================ targets & ranking
    @http.route('/rep/targets', type='http', auth='user')
    @rep_required
    def targets(self, rep, **kw):
        today = _today()
        current = rep.current_target(today)
        history = _env()['mo.sales.target'].sudo().search([('rep_id', '=', rep.id), ('date_to', '<', today)], limit=6)
        return _render('mo_sales_rep_portal.tpl_targets', rep, 'more', T('My Targets'), target=current,
                       rows=current.progress() if current else [], history=history)

    @http.route('/rep/ranking', type='http', auth='user')
    @rep_required
    def ranking(self, rep, **kw):
        if not _can(rep, 'allow_ranking'):
            return _redir('/rep', T('This action is not allowed.'), 'err')
        today = _today()
        glob = _settings()
        rows = analytics.ranking(_env(), glob, today.replace(day=1), today)
        return _render('mo_sales_rep_portal.tpl_ranking', rep, 'more', T('Ranking'), rows=rows,
                       metric=glob.ranking_metric, show_values=glob.ranking_show_values)

    # ================================================================ expenses
    def _get_expense(self, rep, expense_id):
        return _env()['mo.sales.expense'].sudo().search([('id', '=', expense_id), ('rep_id', '=', rep.id)], limit=1)

    @http.route('/rep/expenses', type='http', auth='user')
    @rep_required
    def expenses(self, rep, state='', **kw):
        if not _can(rep, 'allow_expense'):
            return _redir('/rep', T('This action is not allowed.'), 'err')
        domain = [('rep_id', '=', rep.id)]
        if state in EXPENSE_STATES:
            domain.append(('state', '=', state))
        recs = _env()['mo.sales.expense'].sudo().search(domain, limit=80)
        return _render('mo_sales_rep_portal.tpl_expenses', rep, 'more', T('Expenses'), recs=recs, state=state,
                       total=sum(recs.mapped('amount')))

    @http.route('/rep/expense/new', type='http', auth='user')
    @rep_required
    def expense_new(self, rep, partner_id=None, visit_id=None, **kw):
        if not _can(rep, 'allow_expense'):
            return _redir('/rep', T('This action is not allowed.'), 'err')
        visit = _visit_of(rep, visit_id)
        today = _today()
        visits = _env()['mo.sales.visit'].sudo().search([
            ('rep_id', '=', rep.id), ('visit_date', '>=', today - timedelta(days=7)), ('state', '!=', 'cancelled')], limit=30)
        return _render('mo_sales_rep_portal.tpl_expense_form', rep, 'more', T('New Expense'),
                       customers=rep.get_customers(), visits=visits, visit_id=visit.id if visit else 0,
                       partner_id=int(partner_id) if partner_id else (visit.partner_id.id if visit else 0), today=today,
                       types=_env()['mo.sales.expense']._fields['expense_type']._description_selection(_env()))

    @http.route('/rep/expense/create', type='http', auth='user', methods=['POST'])
    @rep_required
    def expense_create(self, rep, expense_type=None, amount=None, date=None, partner_id=None, visit_id=None,
                       notes=None, action='draft', client_uid=None, **kw):
        Expense = _env()['mo.sales.expense'].sudo()
        if client_uid:
            done = Expense.search([('client_uid', '=', client_uid)], limit=1)
            if done:
                return _redir('/rep/expense/%s' % done.id, T('Expense saved.'))
        visit = _visit_of(rep, visit_id)
        try:
            if not _can(rep, 'allow_expense'):
                raise AccessError(T('This action is not allowed.'))
            if expense_type not in dict(Expense._fields['expense_type']._description_selection(_env())):
                raise UserError(T('Choose the expense type.'))
            if _float(amount) <= 0:
                raise UserError(T('The expense amount must be greater than zero.'))
            if partner_id and not rep.can_access_partner(partner_id):
                raise AccessError(T('Choose one of your customers.'))
            exp = Expense.create({
                'rep_id': rep.id, 'expense_type': expense_type, 'amount': _float(amount),
                'date': _date(date, _today()), 'partner_id': int(partner_id) if partner_id else (visit.partner_id.id if visit else False),
                'visit_id': visit.id if visit else False, 'notes': notes or False, 'client_uid': client_uid or False})
            _save_attachments('mo.sales.expense', exp.id, request.httprequest.files.getlist('attachments'))
            rep._audit(exp, T('created the expense'))
            if action == 'submit':
                exp.action_submit()
        except (UserError, AccessError, ValidationError) as e:
            return _redir('/rep/expense/new', str(e), 'err')
        dest = '/rep/visit/%s' % visit.id if visit else '/rep/expense/%s' % exp.id
        return _redir(dest, T('Expense submitted for approval.') if action == 'submit' else T('Expense saved.'))

    @http.route('/rep/expense/<int:expense_id>', type='http', auth='user')
    @rep_required
    def expense(self, rep, expense_id, **kw):
        exp = self._get_expense(rep, expense_id)
        if not exp:
            return _forbidden()
        atts = _env()['ir.attachment'].sudo().search([('res_model', '=', 'mo.sales.expense'), ('res_id', '=', exp.id)])
        return _render('mo_sales_rep_portal.tpl_expense', rep, 'more', exp.name, exp=exp, attachments=atts)

    @http.route('/rep/expense/<int:expense_id>/submit', type='http', auth='user', methods=['POST'])
    @rep_required
    def expense_submit(self, rep, expense_id, **kw):
        exp = self._get_expense(rep, expense_id)
        if not exp or exp.state != 'draft':
            return _redir('/rep/expenses', T('This expense cannot be submitted.'), 'err')
        exp.action_submit()
        return _redir('/rep/expense/%s' % exp.id, T('Expense submitted for approval.'))

    @http.route('/rep/expense/<int:expense_id>/delete', type='http', auth='user', methods=['POST'])
    @rep_required
    def expense_delete(self, rep, expense_id, **kw):
        exp = self._get_expense(rep, expense_id)
        if not exp or exp.state != 'draft':
            return _redir('/rep/expenses', T('Only a draft expense can be deleted.'), 'err')
        exp.unlink()
        return _redir('/rep/expenses', T('Expense deleted.'))

    # ================================================================ payment receipt
    @http.route('/rep/payment/<int:payment_id>/receipt', type='http', auth='user')
    @rep_required
    def receipt(self, rep, payment_id, visit_id=None, **kw):
        pay = _get_payment(rep, payment_id)
        if not pay:
            return _forbidden()
        cheque = _env()['mo.sales.cheque'].sudo().search([('payment_id', '=', pay.id)], limit=1)
        memo = pay.memo if 'memo' in pay._fields else (pay.payment_reference if 'payment_reference' in pay._fields else '')
        return _render('mo_sales_rep_portal.tpl_receipt', rep, 'more', T('Payment Receipt'), pay=pay, cheque=cheque,
                       company=pay.company_id, memo=memo or '', visit=_visit_of(rep, visit_id),
                       invoices=pay.reconciled_invoice_ids)

    @http.route('/rep/payment/<int:payment_id>/receipt.pdf', type='http', auth='user')
    @rep_required
    def receipt_pdf(self, rep, payment_id, **kw):
        pay = _get_payment(rep, payment_id)
        if not pay:
            return _forbidden()
        pdf, _fmt = _env()['ir.actions.report'].sudo()._render_qweb_pdf(
            'mo_sales_rep_portal.action_report_payment_receipt', [pay.id])
        name = re.sub(r'[^\w\-]+', '_', pay.name or 'receipt')
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'), ('Content-Disposition', 'inline; filename="receipt_%s.pdf"' % name)])

    # ================================================================ cheques
    @http.route('/rep/cheques', type='http', auth='user')
    @rep_required
    def cheques(self, rep, state='', **kw):
        domain = [('rep_id', '=', rep.id)]
        if state in ('received', 'deposited', 'cleared', 'returned'):
            domain.append(('state', '=', state))
        recs = _env()['mo.sales.cheque'].sudo().search(domain, limit=80)
        return _render('mo_sales_rep_portal.tpl_cheques', rep, 'more', T('My Cheques'), recs=recs, state=state,
                       total=sum(recs.mapped('amount')))

    # ================================================================ customer returns
    @http.route('/rep/return/new', type='http', auth='user')
    @rep_required
    def return_new(self, rep, partner_id=None, visit_id=None, **kw):
        if not _can(rep, 'allow_customer_return'):
            return _redir('/rep', T('This action is not allowed.'), 'err')
        visit = _visit_of(rep, visit_id)
        return _render('mo_sales_rep_portal.tpl_return_form', rep, 'more', T('Customer Return'),
                       customers=rep.get_customers(), visit_id=visit.id if visit else 0,
                       partner_id=int(partner_id) if partner_id else (visit.partner_id.id if visit else 0),
                       reasons=_env()['mo.return.reason'].sudo().search([]))

    @http.route('/rep/customer/<int:partner_id>/returnable.json', type='http', auth='user')
    @rep_required
    def returnable_json(self, rep, partner_id, **kw):
        if not rep.can_access_partner(partner_id):
            return request.make_json_response([])
        orders = _env()['sale.order'].sudo().search(
            [('partner_id', '=', partner_id), ('state', 'in', ('sale', 'done'))], order='date_order desc', limit=25)
        out = []
        for order in orders:
            lines = [{'move_id': mid, 'product': m.product_id.display_name, 'uom': m.product_uom.name, 'max': left}
                     for mid, (left, m) in _returnable(order).items()]
            if lines:
                out.append({'id': order.id, 'name': order.name, 'date': str(order.date_order.date()),
                            'invoices': ', '.join(order.invoice_ids.filtered(lambda i: i.state == 'posted').mapped('name')),
                            'lines': lines})
        return request.make_json_response(out)

    @http.route('/rep/return/create', type='http', auth='user', methods=['POST'])
    @rep_required
    def return_create(self, rep, partner_id=None, order_id=None, visit_id=None, note=None, client_uid=None, **kw):
        env = _env()
        S = _settings(rep)
        form = request.httprequest.form
        back = '/rep/return/new?partner_id=%s&visit_id=%s' % (partner_id or '', visit_id or '')
        if client_uid:
            done = env['stock.picking'].sudo().search([('mo_client_uid', '=', client_uid)], limit=1)
            if done:
                return _redir('/rep/picking/%s' % done.id, T('Return %s created.', done.name))
        visit = _visit_of(rep, visit_id)
        try:
            if not S.allow_customer_return:
                raise AccessError(T('This action is not allowed.'))
            if not partner_id or not rep.can_access_partner(partner_id):
                raise AccessError(T('Choose one of your customers.'))
            _ensure_approved(partner_id)
            order = env['sale.order'].sudo().browse(int(order_id or 0)).exists()
            if not order or order.partner_id.id != int(partner_id):
                raise UserError(T('Choose the invoice or sales order to return from.'))
            allowed = _returnable(order)
            reasons = {r.id: r for r in env['mo.return.reason'].sudo().search([])}
            chosen = defaultdict(list)
            for mid, qty, rid in zip(form.getlist('move_id'), form.getlist('qty'), form.getlist('reason_id')):
                q = _float(qty)
                if q <= 0:
                    continue
                mid = int(mid)
                if mid not in allowed:
                    raise UserError(T('This product cannot be returned.'))
                left, move = allowed[mid]
                if q > left + 1e-6:
                    raise UserError(T('Return quantity for %(p)s cannot exceed %(m)s.', p=move.product_id.display_name, m=left))
                if not rid or int(rid) not in reasons:
                    raise UserError(T('Choose the return reason for every product.'))
                chosen[move.picking_id].append((move, q, reasons[int(rid)]))
            if not chosen:
                raise UserError(T('Enter the quantity to return.'))
            last = env['stock.picking']
            for picking, items in chosen.items():
                last = self._make_return(rep, picking, items, visit, note, client_uid)
        except (UserError, AccessError, ValidationError) as e:
            return _redir(back, str(e), 'err')
        dest = '/rep/visit/%s' % visit.id if visit else '/rep/picking/%s' % last.id
        return _redir(dest, T('Return %s created.', last.name))

    def _make_return(self, rep, picking, items, visit, note, client_uid):
        env = _env()
        Move = env['stock.move']
        ptype = picking.picking_type_id.return_picking_type_id or picking.picking_type_id.warehouse_id.in_type_id
        if not ptype:
            raise UserError(T('No return operation type is configured for this warehouse.'))
        dst = ptype.default_location_dest_id or picking.location_id
        moves = []
        for move, qty, reason in items:
            vals = {'product_id': move.product_id.id, 'product_uom_qty': qty, 'product_uom': move.product_uom.id,
                    'location_id': picking.location_dest_id.id, 'location_dest_id': dst.id,
                    'origin_returned_move_id': move.id, 'procure_method': 'make_to_stock',
                    'description_picking': reason.name}
            if 'to_refund' in Move._fields:
                vals['to_refund'] = True
            moves.append((0, 0, vals))
        ret = env['stock.picking'].sudo().with_company(rep.company_id).create({
            'picking_type_id': ptype.id, 'partner_id': picking.partner_id.id,
            'origin': T('Return of %s', picking.name), 'location_id': picking.location_dest_id.id,
            'location_dest_id': dst.id, 'mo_source': 'portal', 'mo_rep_id': rep.id, 'mo_operation': 'customer_return',
            'mo_return_reason_id': items[0][2].id, 'mo_client_uid': client_uid or False,
            'mo_visit_id': visit.id if visit else False, 'move_ids': moves})
        ret.action_confirm()
        ret.action_assign()
        lines = '; '.join('%s x %s (%s)' % (m.product_id.display_name, q, r.name) for m, q, r in items)
        rep._audit(ret, T('created the return of %(l)s from %(p)s', l=lines, p=picking.name))
        if note:
            ret.message_post(body=note)
        if rep.can_auto_validate():
            RepPortal._auto_validate(ret)
        return ret

    # ================================================================ follow-ups
    @http.route('/rep/followups', type='http', auth='user')
    @rep_required
    def followups(self, rep, **kw):
        today = _today()
        recs = _env()['mo.sales.followup'].sudo().search([('rep_id', '=', rep.id), ('state', '=', 'open')], order='due_date, priority desc')
        return _render('mo_sales_rep_portal.tpl_followups', rep, 'more', T('Follow-ups'),
                       overdue=recs.filtered(lambda f: f.due_date < today),
                       today_list=recs.filtered(lambda f: f.due_date == today),
                       upcoming=recs.filtered(lambda f: f.due_date > today))

    @http.route('/rep/followup/new', type='http', auth='user')
    @rep_required
    def followup_new(self, rep, partner_id=None, visit_id=None, order_id=None, **kw):
        visit = _visit_of(rep, visit_id)
        return _render('mo_sales_rep_portal.tpl_followup_form', rep, 'more', T('New Follow-up'),
                       customers=rep.get_customers(), visit_id=visit.id if visit else 0, order_id=int(order_id) if order_id else 0,
                       partner_id=int(partner_id) if partner_id else (visit.partner_id.id if visit else 0), today=_today())

    @http.route('/rep/followup/create', type='http', auth='user', methods=['POST'])
    @rep_required
    def followup_create(self, rep, partner_id=None, name=None, due_date=None, priority='0', notes=None,
                        visit_id=None, order_id=None, client_uid=None, **kw):
        Follow = _env()['mo.sales.followup'].sudo()
        if client_uid and Follow.search_count([('client_uid', '=', client_uid)]):
            return _redir('/rep/followups', T('Follow-up saved.'))
        visit = _visit_of(rep, visit_id)
        try:
            if not partner_id or not rep.can_access_partner(partner_id):
                raise AccessError(T('Choose one of your customers.'))
            if not (name or '').strip():
                raise UserError(T('Describe the task.'))
            order = _env()['sale.order'].sudo().browse(int(order_id)).exists() if order_id else False
            Follow.create({
                'name': name.strip(), 'rep_id': rep.id, 'partner_id': int(partner_id), 'due_date': _date(due_date, _today()),
                'priority': priority if priority in ('0', '1', '2') else '0', 'notes': notes or False,
                'visit_id': visit.id if visit else False,
                'order_id': order.id if order and order.partner_id.id == int(partner_id) else False,
                'client_uid': client_uid or False})
        except (UserError, AccessError, ValidationError) as e:
            return _redir('/rep/followup/new', str(e), 'err')
        return _redir('/rep/visit/%s' % visit.id if visit else '/rep/followups', T('Follow-up saved.'))

    @http.route('/rep/followup/<int:followup_id>/<string:what>', type='http', auth='user', methods=['POST'])
    @rep_required
    def followup_action(self, rep, followup_id, what, **kw):
        rec = _env()['mo.sales.followup'].sudo().search([('id', '=', followup_id), ('rep_id', '=', rep.id)], limit=1)
        if not rec or what not in ('done', 'cancel'):
            return _forbidden()
        rec.action_done() if what == 'done' else rec.action_cancel()
        return _redir('/rep/followups', T('Follow-up updated.'))

    # ================================================================ visit notes
    @http.route('/rep/visit/<int:visit_id>/note', type='http', auth='user', methods=['POST'])
    @rep_required
    def visit_note(self, rep, visit_id, text=None, **kw):
        visit = _visit_of(rep, visit_id)
        if not visit:
            return _forbidden()
        if (text or '').strip():
            visit.add_note(text.strip())
        return _redir('/rep/visit/%s' % visit.id, T('Note added.'))

    # ================================================================ offline helpers
    @http.route('/rep/csrf', type='http', auth='user')
    def csrf(self, **kw):
        return request.make_json_response({'token': request.csrf_token()})

    @http.route('/rep/offline/manifest.json', type='http', auth='user')
    @rep_required
    def offline_manifest(self, rep, **kw):
        """Pages the device pre-loads so the day's work stays usable without a connection."""
        today = _today()
        urls = ['/rep', '/rep/route', '/rep/customers', '/rep/followups', '/rep/outstanding', '/rep/targets',
                '/rep/cheques', '/rep/expenses', '/rep/more', '/rep/stock', '/rep/orders', '/rep/invoices',
                '/rep/payments', '/rep/visit/new', '/rep/order/new', '/rep/payment/new', '/rep/expense/new',
                '/rep/customer/new', '/rep/followup/new', '/rep/return/new', '/rep/stock/operation']
        visits = _env()['mo.sales.visit'].sudo().search(
            [('rep_id', '=', rep.id), ('visit_date', '=', today), ('state', '!=', 'cancelled')], limit=60)
        urls += ['/rep/visit/%s' % v.id for v in visits]
        partners = visits.mapped('partner_id') | rep.get_customers()[:80]
        urls += ['/rep/customer/%s' % p.id for p in partners[:100]]
        return request.make_json_response({'urls': urls})
