"""Audit engine: controlled, predefined rule implementations.

No user supplied Python / SQL / eval is ever executed. Every rule is a method
registered with @audit_rule and only READS business data (sudo, with explicit
company domains). The engine never modifies business records.
"""
import logging
from collections import defaultdict
from datetime import datetime, time, timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

RULE_METHODS = {}

# Default segregation-of-duties pairs (group XML ids). Pairs whose groups are not installed are skipped.
DEFAULT_SOD_PAIRS = [
    ['purchase.group_purchase_manager', 'account.group_account_manager'],
    ['sales_team.group_sale_manager', 'account.group_account_manager'],
    ['stock.group_stock_manager', 'purchase.group_purchase_manager'],
]


def audit_rule(key, models_needed, label, needs=()):
    def deco(fn):
        RULE_METHODS[key] = {'fn': fn.__name__, 'models': list(models_needed), 'label': label, 'needs': list(needs)}
        return fn
    return deco


class AuditorEngine(models.AbstractModel):
    _name = 'odoo.auditor.engine'
    _description = 'Audit Engine'

    # ------------------------------------------------------------------ core
    @api.model
    def execute_run(self, run):
        """Run every selected rule. Returns total inspected records."""
        engine = self.sudo().with_company(run.company_id)
        total = 0
        rules = run.rule_ids
        for index, rule in enumerate(rules, start=1):
            run._update_progress(index - 1, len(rules), rule.code)
            meta = RULE_METHODS.get(rule.method_key)
            if not meta:
                run._add_message('error', rule, self.env._("No implementation registered for '%s'.", rule.method_key))
                continue
            missing = [m for m in meta['models'] if m not in self.env]
            if missing:
                run._add_message('warning', rule, self.env._("Skipped: required model(s) not installed: %s",
                                                              ', '.join(missing)))
                continue
            if not rule.config_ok:
                run._add_message('warning', rule, rule.config_message)
                continue
            try:
                with self.env.cr.savepoint():
                    total += getattr(engine, meta['fn'])(run, rule) or 0
            except Exception as exc:  # noqa: BLE001 - a failing rule must not stop the run
                _logger.exception("Audit rule %s failed", rule.code)
                run._add_message('error', rule, str(exc))
        run._update_progress(len(rules), len(rules), False)
        return total

    # --------------------------------------------------------------- helpers
    def _dt_range(self, run):
        return (datetime.combine(run.date_from, time.min), datetime.combine(run.date_to, time.max))

    def _base_domain(self, run, rule, extra=(), partner_field=None):
        dom = [('company_id', '=', run.company_id.id)] + list(extra)
        if partner_field and rule.exclude_partner_ids:
            dom.append((partner_field, 'not in', rule.exclude_partner_ids.ids))
        return dom

    def _to_company(self, amount, currency, run, date):
        company = run.company_id
        if not currency or currency == company.currency_id:
            return amount
        return currency._convert(amount, company.currency_id, company, date or fields.Date.today())

    def _add_finding(self, run, rule, record, title, description, expected, actual, amount=0.0,
                     partner=None, product=None, snapshot=None, key=None, severity=None, doc_date=False,
                     confidential=False):
        Finding = self.env['odoo.auditor.finding'].sudo()
        fingerprint = "%s|%s" % (rule.code, key or "%s,%s" % (record._name, record.id))
        if self.env['odoo.auditor.exclusion'].sudo().search_count(
                [('fingerprint', '=', fingerprint), ('company_id', '=', run.company_id.id)]):
            return Finding  # documented exclusion: ignore silently
        existing = Finding.with_context(active_test=False).search(
            [('fingerprint', '=', fingerprint), ('company_id', '=', run.company_id.id)], limit=1)
        if existing:
            if existing.state == 'closed':
                existing._reopen_recurrence(run)
            existing.last_run_id = run
            return existing
        finding = Finding.create({
            'title': title, 'description': description, 'company_id': run.company_id.id,
            'rule_id': rule.id, 'run_id': run.id, 'last_run_id': run.id, 'fingerprint': fingerprint,
            'source_model': record._name, 'source_res_id': record.id, 'source_name': record.display_name,
            'source_date': doc_date or False,
            'severity': severity or rule.severity, 'nature': rule.nature,
            'estimated_impact': amount, 'currency_id': run.company_id.currency_id.id,
            'expected_condition': expected, 'actual_condition': actual,
            'partner_id': partner.id if partner else False,
            'product_name': product.display_name if product else False,
            'product_res_id': product.id if product else 0,
            'recommendation': rule.recommendation, 'assigned_user_id': rule.owner_id.id or False,
            'is_confidential': confidential,
        })
        self.env['odoo.auditor.evidence'].sudo().create_snapshot(
            finding, snapshot or {}, self.env._("Values observed at detection time (historical snapshot)."))
        if finding.severity in ('high', 'critical') and finding.assigned_user_id:
            finding.activity_schedule('mail.mail_activity_data_todo', user_id=finding.assigned_user_id.id,
                                      summary=self.env._("Review %(s)s finding %(n)s", s=finding.severity,
                                                         n=finding.name))
        return finding

    # ------------------------------------------------------------ financial
    @audit_rule('FIN001', ['account.move'], 'Draft journal entries outstanding too long', needs=['days'])
    def _r_fin001(self, run, rule):
        limit = run.date_to - timedelta(days=rule.threshold_days)
        moves = self.env['account.move'].search(self._base_domain(
            run, rule, [('state', '=', 'draft'), ('date', '<', limit)], 'partner_id'))
        for m in moves:
            self._add_finding(
                run, rule, m, self.env._("Draft entry outstanding: %s", m.display_name),
                self.env._("The entry has been in draft since %s.", m.date),
                self.env._("Draft entries older than %s days are posted or cancelled.", rule.threshold_days),
                self.env._("Draft since %s", m.date), partner=m.partner_id,
                snapshot={'name': m.display_name, 'date': m.date, 'type': m.move_type, 'amount': m.amount_total},
                doc_date=m.date)
        return len(moves)

    @audit_rule('FIN002', ['account.move.line'], 'Large manual journal entries', needs=['amount'])
    def _r_fin002(self, run, rule):
        Line = self.env['account.move.line']
        Move = self.env['account.move']
        dom = self._base_domain(run, rule, [
            ('move_id.move_type', '=', 'entry'), ('move_id.state', '=', 'posted'),
            ('date', '>=', run.date_from), ('date', '<=', run.date_to)])
        # "manual" = not generated by payments, bank statements, stock valuation, etc.
        for fname in ('statement_line_id', 'origin_payment_id', 'stock_move_id', 'tax_cash_basis_origin_move_id',
                      'reversed_entry_id'):
            if fname in Move._fields:
                dom.append(('move_id.' + fname, '=', False))
        groups = Line._read_group(dom, ['move_id'], ['debit:sum'])
        for move, debit in groups:
            if debit >= rule.threshold_amount:
                self._add_finding(
                    run, rule, move, self.env._("Large manual entry: %s", move.display_name),
                    self.env._("Manual journal entry with total debit %(amt)s (threshold %(thr)s).",
                               amt=debit, thr=rule.threshold_amount),
                    self.env._("Manual entries above the threshold carry documented approval."),
                    self.env._("Total debit %s", debit), amount=debit,
                    snapshot={'name': move.display_name, 'date': move.date, 'debit_total': debit,
                              'created_by': move.create_uid.display_name, 'ref': move.ref},
                    doc_date=move.date)
        return len(groups)

    @audit_rule('FIN003', ['account.move'], 'Potential duplicate vendor bills')
    def _r_fin003(self, run, rule):
        Move = self.env['account.move']
        dom = self._base_domain(run, rule, [
            ('move_type', '=', 'in_invoice'), ('state', 'in', ('draft', 'posted')), ('ref', '!=', False),
            ('date', '>=', run.date_from), ('date', '<=', run.date_to)], 'partner_id')
        groups = Move._read_group(dom, ['partner_id', 'ref', 'amount_total', 'currency_id'], ['id:array_agg'],
                                  having=[('__count', '>', 1)])
        for partner, ref, amount, currency, ids in groups:
            moves = Move.browse(ids)
            self._add_finding(
                run, rule, moves[0], self.env._("Possible duplicate vendor bill (ref %s)", ref),
                self.env._("%(n)s vendor bills share partner, reference, amount and currency: %(names)s",
                           n=len(ids), names=', '.join(moves.mapped('display_name'))),
                self.env._("A vendor reference is registered once per partner."),
                self.env._("%s documents with identical partner/ref/amount/currency", len(ids)),
                amount=self._to_company(amount * (len(ids) - 1), currency, run, run.date_to), partner=partner,
                key="DUP|%s" % sorted(ids),
                snapshot={'bills': moves.mapped('display_name'), 'ref': ref, 'amount': amount,
                          'currency': currency.name},
                doc_date=moves[0].date)
        return len(groups)

    @audit_rule('FIN004', ['account.move'], 'Potential duplicate customer invoices')
    def _r_fin004(self, run, rule):
        Move = self.env['account.move']
        dom = self._base_domain(run, rule, [
            ('move_type', '=', 'out_invoice'), ('state', 'in', ('draft', 'posted')),
            ('invoice_date', '!=', False), ('invoice_date', '>=', run.date_from),
            ('invoice_date', '<=', run.date_to)], 'partner_id')
        groups = Move._read_group(dom, ['partner_id', 'amount_total', 'invoice_date:day', 'currency_id'],
                                  ['id:array_agg'], having=[('__count', '>', 1)])
        for partner, amount, inv_date, currency, ids in groups:
            moves = Move.browse(ids)
            self._add_finding(
                run, rule, moves[0], self.env._("Possible duplicate customer invoice for %s", partner.display_name),
                self.env._("%(n)s invoices share customer, date, amount and currency: %(names)s",
                           n=len(ids), names=', '.join(moves.mapped('display_name'))),
                self.env._("Invoices with identical customer/date/amount are intentional and documented."),
                self.env._("%s similar invoices", len(ids)),
                amount=self._to_company(amount * (len(ids) - 1), currency, run, inv_date), partner=partner,
                key="DUP|%s" % sorted(ids),
                snapshot={'invoices': moves.mapped('display_name'), 'amount': amount, 'date': inv_date},
                doc_date=inv_date)
        return len(groups)

    @audit_rule('FIN005', ['account.move'], 'Large credit notes / refunds', needs=['amount'])
    def _r_fin005(self, run, rule):
        moves = self.env['account.move'].search(self._base_domain(run, rule, [
            ('move_type', 'in', ('out_refund', 'in_refund')), ('state', '=', 'posted'),
            ('date', '>=', run.date_from), ('date', '<=', run.date_to)], 'partner_id'))
        hits = moves.filtered(lambda m: abs(m.amount_total_signed) >= rule.threshold_amount)
        for m in hits:
            amt = abs(m.amount_total_signed)
            self._add_finding(
                run, rule, m, self.env._("Large credit note: %s", m.display_name),
                self.env._("Credit note of %(amt)s in company currency (threshold %(thr)s).",
                           amt=amt, thr=rule.threshold_amount),
                self.env._("Credit notes above the threshold are approved and supported."),
                self.env._("Amount %s", amt), amount=amt, partner=m.partner_id,
                snapshot={'name': m.display_name, 'date': m.date, 'amount_company_currency': amt,
                          'reversed_entry': m.reversed_entry_id.display_name},
                doc_date=m.date)
        return len(moves)

    @audit_rule('FIN006', ['account.move'], 'Entries posted long after their accounting date', needs=['days'])
    def _r_fin006(self, run, rule):
        start, end = self._dt_range(run)
        moves = self.env['account.move'].search(self._base_domain(run, rule, [
            ('state', '=', 'posted'), ('create_date', '>=', start), ('create_date', '<=', end)], 'partner_id'))
        hits = moves.filtered(lambda m: (m.create_date.date() - m.date).days > rule.threshold_days)
        for m in hits:
            lag = (m.create_date.date() - m.date).days
            self._add_finding(
                run, rule, m, self.env._("Backdated entry: %s", m.display_name),
                self.env._("Entry dated %(d)s was created %(lag)s days later. Backdating can be legitimate "
                           "(late documents); verify the period was open and approved.", d=m.date, lag=lag),
                self.env._("Entries are dated within %s days of creation.", rule.threshold_days),
                self.env._("Created %s days after accounting date", lag), partner=m.partner_id,
                snapshot={'name': m.display_name, 'date': m.date, 'created': m.create_date,
                          'created_by': m.create_uid.display_name}, doc_date=m.date)
        return len(moves)

    # ------------------------------------------------------------ inventory
    @audit_rule('INV001', ['stock.quant'], 'Negative stock in internal locations')
    def _r_inv001(self, run, rule):
        quants = self.env['stock.quant'].search(self._base_domain(run, rule, [
            ('location_id.usage', '=', 'internal'), ('quantity', '<', 0)]))
        for q in quants:
            self._add_finding(
                run, rule, q, self.env._("Negative stock: %(p)s @ %(l)s", p=q.product_id.display_name,
                                         l=q.location_id.display_name),
                self.env._("On-hand quantity is %s. Check for unrecorded receipts before concluding a loss.",
                           q.quantity),
                self.env._("On-hand quantity is not negative in internal locations."),
                self.env._("Quantity %s", q.quantity), product=q.product_id,
                snapshot={'product': q.product_id.display_name, 'location': q.location_id.display_name,
                          'quantity': q.quantity, 'lot': q.lot_id.name})
        return len(quants)

    @audit_rule('INV002', ['stock.picking'], 'Transfers pending beyond threshold', needs=['days'])
    def _r_inv002(self, run, rule):
        limit = datetime.combine(run.date_to, time.max) - timedelta(days=rule.threshold_days)
        pickings = self.env['stock.picking'].search(self._base_domain(run, rule, [
            ('state', 'in', ('confirmed', 'waiting', 'assigned')), ('scheduled_date', '<', limit)],
            'partner_id'))
        for p in pickings:
            self._add_finding(
                run, rule, p, self.env._("Transfer pending too long: %s", p.name),
                self.env._("Transfer scheduled %(d)s is still in state %(s)s. In-transit stock is not a loss; "
                           "check the transfer workflow.", d=p.scheduled_date, s=p.state),
                self.env._("Transfers are completed within %s days of schedule.", rule.threshold_days),
                self.env._("Pending since %s", p.scheduled_date), partner=p.partner_id,
                snapshot={'name': p.name, 'state': p.state, 'scheduled': p.scheduled_date,
                          'type': p.picking_type_id.display_name}, doc_date=p.scheduled_date.date())
        return len(pickings)

    @audit_rule('INV003', ['stock.move'], 'Large inventory adjustments', needs=['amount'])
    def _r_inv003(self, run, rule):
        start, end = self._dt_range(run)
        moves = self.env['stock.move'].search(self._base_domain(run, rule, [
            ('is_inventory', '=', True), ('state', '=', 'done'), ('date', '>=', start), ('date', '<=', end)]))
        hits = moves.filtered(lambda m: abs(m.quantity) >= rule.threshold_amount)
        for m in hits:
            self._add_finding(
                run, rule, m, self.env._("Large inventory adjustment: %s", m.product_id.display_name),
                self.env._("Adjustment of %(q)s %(u)s (quantity threshold %(t)s). Valuation impact is not "
                           "computed by this rule.", q=m.quantity, u=m.product_uom.name, t=rule.threshold_amount),
                self.env._("Adjustments are within the approved tolerance."),
                self.env._("Quantity %s", m.quantity), product=m.product_id,
                snapshot={'product': m.product_id.display_name, 'qty': m.quantity, 'from': m.location_id.display_name,
                          'to': m.location_dest_id.display_name, 'date': m.date, 'user': m.write_uid.display_name},
                doc_date=m.date.date())
        return len(moves)

    # ---------------------------------------------------------------- sales
    def _sale_lines(self, run, rule, extra=()):
        start, end = self._dt_range(run)
        return self.env['sale.order.line'].search(self._base_domain(run, rule, [
            ('order_id.state', 'in', ('sale', 'done')), ('display_type', '=', False),
            ('order_id.date_order', '>=', start), ('order_id.date_order', '<=', end)] + list(extra),
            'order_partner_id'))

    @audit_rule('SAL001', ['sale.order.line'], 'High sales discounts', needs=['percent'])
    def _r_sal001(self, run, rule):
        lines = self._sale_lines(run, rule, [('discount', '>', rule.threshold_percent)])
        for l in lines:
            amount = l.price_unit * l.product_uom_qty * l.discount / 100.0
            self._add_finding(
                run, rule, l, self.env._("High discount on %(o)s: %(d)s%%", o=l.order_id.name, d=l.discount),
                self.env._("Line '%(p)s' has discount %(d)s%% (limit %(t)s%%).",
                           p=l.product_id.display_name or l.name, d=l.discount, t=rule.threshold_percent),
                self.env._("Discounts do not exceed %s%% without approval.", rule.threshold_percent),
                self.env._("Discount %s%%", l.discount),
                amount=self._to_company(amount, l.currency_id, run, l.order_id.date_order.date()),
                partner=l.order_partner_id, product=l.product_id,
                snapshot={'order': l.order_id.name, 'product': l.product_id.display_name, 'discount': l.discount,
                          'price_unit': l.price_unit, 'qty': l.product_uom_qty,
                          'salesperson': l.salesman_id.display_name},
                doc_date=l.order_id.date_order.date())
        return len(lines)

    @audit_rule('SAL002', ['sale.order.line'], 'Sales below cost / minimum margin')
    def _r_sal002(self, run, rule):
        lines = self._sale_lines(run, rule, [('product_id', '!=', False)])
        use_line_cost = 'purchase_price' in self.env['sale.order.line']._fields
        count = 0
        for l in lines:
            net = l.price_unit * (1 - l.discount / 100.0)
            if net <= 0:
                continue
            cost = l.purchase_price if use_line_cost and l.purchase_price else l.product_id.standard_price
            if not cost:
                continue
            order_date = l.order_id.date_order.date()
            net_c = self._to_company(net, l.currency_id, run, order_date)
            margin = (net_c - cost) / net_c * 100.0
            count += 1
            if margin < rule.threshold_percent:
                loss = max((cost - net_c) * l.product_uom_qty, 0.0)
                src = self.env._("line cost recorded on the order") if use_line_cost and l.purchase_price else \
                    self.env._("CURRENT product cost (historical cost at order time is not available - limitation)")
                self._add_finding(
                    run, rule, l, self.env._("Low/negative margin on %s", l.order_id.name),
                    self.env._("Margin %(m).1f%% below minimum %(t)s%%. Cost basis: %(s)s.",
                               m=margin, t=rule.threshold_percent, s=src),
                    self.env._("Margin is at least %s%%.", rule.threshold_percent),
                    self.env._("Margin %.1f%%", margin), amount=loss, partner=l.order_partner_id,
                    product=l.product_id,
                    snapshot={'order': l.order_id.name, 'net_price_company_ccy': net_c, 'cost_used': cost,
                              'cost_basis': src, 'margin_pct': round(margin, 2)}, doc_date=order_date)
        return count

    # ------------------------------------------------------------- purchase
    def _po_amount(self, po, run):
        return self._to_company(po.amount_total, po.currency_id, run, po.date_order.date())

    @audit_rule('PUR001', ['purchase.order'], 'Purchase orders above approval threshold', needs=['amount'])
    def _r_pur001(self, run, rule):
        start, end = self._dt_range(run)
        pos = self.env['purchase.order'].search(self._base_domain(run, rule, [
            ('state', 'in', ('purchase', 'done')), ('date_order', '>=', start), ('date_order', '<=', end)],
            'partner_id'))
        for po in pos:
            amt = self._po_amount(po, run)
            if amt >= rule.threshold_amount:
                self._add_finding(
                    run, rule, po, self.env._("High-value purchase order %s", po.name),
                    self.env._("PO value %(a)s (threshold %(t)s). Verify approval evidence.",
                               a=amt, t=rule.threshold_amount),
                    self.env._("Orders above the threshold are approved by an authorised person."),
                    self.env._("Value %s", amt), amount=amt, partner=po.partner_id,
                    snapshot={'po': po.name, 'amount_company_ccy': amt, 'buyer': po.user_id.display_name,
                              'confirmed_by_write_uid': po.write_uid.display_name},
                    doc_date=po.date_order.date())
        return len(pos)

    @audit_rule('PUR002', ['purchase.order'], 'Purchase orders split around approval limit', needs=['amount'])
    def _r_pur002(self, run, rule):
        start, end = self._dt_range(run)
        pos = self.env['purchase.order'].search(self._base_domain(run, rule, [
            ('state', 'in', ('purchase', 'done')), ('date_order', '>=', start), ('date_order', '<=', end)],
            'partner_id'))
        buckets = defaultdict(list)
        for po in pos:
            amt = self._po_amount(po, run)
            if amt < rule.threshold_amount:
                buckets[(po.partner_id.id, po.date_order.date())].append((po, amt))
        for (partner_id, day), items in buckets.items():
            total = sum(a for _po, a in items)
            if len(items) >= 2 and total >= rule.threshold_amount:
                orders = self.env['purchase.order'].concat(*[p for p, _a in items])
                self._add_finding(
                    run, rule, orders[0], self.env._("Possible split purchase on %s", day),
                    self.env._("%(n)s orders to the same vendor on the same day, each below %(t)s but totalling "
                               "%(tot)s: %(names)s", n=len(items), t=rule.threshold_amount, tot=total,
                               names=', '.join(orders.mapped('name'))),
                    self.env._("Purchases are not split to avoid approval limits."),
                    self.env._("Combined value %s", total), amount=total, partner=orders[0].partner_id,
                    key="SPLIT|%s" % sorted(orders.ids),
                    snapshot={'orders': orders.mapped('name'), 'combined': total, 'day': day}, doc_date=day)
        return len(pos)

    # ------------------------------------------------------- financial (2)
    @audit_rule('FIN007', ['account.move'], 'Overdue receivables and payables', needs=['days'])
    def _r_fin007(self, run, rule):
        limit = run.date_to - timedelta(days=rule.threshold_days)
        moves = self.env['account.move'].search(self._base_domain(run, rule, [
            ('move_type', 'in', ('out_invoice', 'in_invoice')), ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')), ('invoice_date_due', '<', limit)], 'partner_id'))
        for m in moves:
            residual = abs(m.amount_residual_signed)
            kind = self.env._("receivable") if m.move_type == 'out_invoice' else self.env._("payable")
            self._add_finding(
                run, rule, m, self.env._("Overdue %(k)s: %(n)s", k=kind, n=m.display_name),
                self.env._("Due %(d)s, residual %(r)s (company currency). Overdue status alone does not "
                           "imply error; check collection / payment agreements.", d=m.invoice_date_due, r=residual),
                self.env._("Items are settled within %s days after the due date.", rule.threshold_days),
                self.env._("Overdue since %s", m.invoice_date_due), amount=residual, partner=m.partner_id,
                snapshot={'name': m.display_name, 'due': m.invoice_date_due, 'residual': residual,
                          'payment_state': m.payment_state}, doc_date=m.invoice_date_due)
        return len(moves)

    # -------------------------------------------------------- manufacturing
    @audit_rule('MRP001', ['mrp.production'], 'Component consumption above BOM demand', needs=['percent'])
    def _r_mrp001(self, run, rule):
        start, end = self._dt_range(run)
        mos = self.env['mrp.production'].search(self._base_domain(run, rule, [
            ('state', '=', 'done'), ('date_finished', '>=', start), ('date_finished', '<=', end)]))
        for mo in mos:
            excess_lines, value = [], 0.0
            for mv in mo.move_raw_ids.filtered(lambda m: m.state == 'done'):
                planned = mv.product_uom_qty
                if planned > 0 and mv.quantity > planned * (1 + rule.threshold_percent / 100.0):
                    extra = mv.quantity - planned
                    value += extra * mv.product_id.standard_price
                    excess_lines.append({'product': mv.product_id.display_name, 'planned': planned,
                                         'consumed': mv.quantity})
            if excess_lines:
                self._add_finding(
                    run, rule, mo, self.env._("Excess consumption on %s", mo.name),
                    self.env._("%(n)s component(s) consumed more than %(p)s%% above demand. Demand may have been "
                               "edited after MO creation; value uses CURRENT product cost (limitation).",
                               n=len(excess_lines), p=rule.threshold_percent),
                    self.env._("Consumption stays within %s%% of demand.", rule.threshold_percent),
                    self.env._("%s component(s) over tolerance", len(excess_lines)), amount=value,
                    snapshot={'mo': mo.name, 'lines': excess_lines}, doc_date=mo.date_finished.date())
        return len(mos)

    @audit_rule('MRP002', ['mrp.production'], 'Manufacturing orders open too long', needs=['days'])
    def _r_mrp002(self, run, rule):
        limit = datetime.combine(run.date_to, time.max) - timedelta(days=rule.threshold_days)
        mos = self.env['mrp.production'].search(self._base_domain(run, rule, [
            ('state', 'in', ('confirmed', 'progress', 'to_close')), ('date_start', '<', limit)]))
        for mo in mos:
            self._add_finding(
                run, rule, mo, self.env._("Manufacturing order open too long: %s", mo.name),
                self.env._("Started %(d)s and still in state %(s)s.", d=mo.date_start, s=mo.state),
                self.env._("Orders are closed within %s days.", rule.threshold_days),
                self.env._("Open since %s", mo.date_start),
                snapshot={'mo': mo.name, 'state': mo.state, 'start': mo.date_start}, doc_date=mo.date_start.date())
        return len(mos)

    # ------------------------------------------------------------------- HR
    @audit_rule('HR001', ['hr.employee'], 'Potential duplicate employee records')
    def _r_hr001(self, run, rule):
        Emp = self.env['hr.employee']
        total = 0
        for fname in [f for f in ('identification_id', 'work_email') if f in Emp._fields]:
            groups = Emp._read_group(self._base_domain(run, rule, [(fname, '!=', False)]), [fname],
                                     ['id:array_agg'], having=[('__count', '>', 1)])
            total += len(groups)
            for value, ids in groups:
                emps = Emp.browse(ids)
                self._add_finding(
                    run, rule, emps[0], self.env._("Duplicate employees sharing %s", fname),
                    self.env._("%(n)s employee records share the same %(f)s: %(names)s",
                               n=len(ids), f=fname, names=', '.join(emps.mapped('name'))),
                    self.env._("Each person has a single employee record."),
                    self.env._("%s records", len(ids)), key="DUP|%s|%s" % (fname, sorted(ids)),
                    snapshot={'field': fname, 'employees': emps.mapped('name')}, confidential=True)
        return total

    @audit_rule('HR002', ['hr.employee'], 'Employees missing mandatory master data')
    def _r_hr002(self, run, rule):
        Emp = self.env['hr.employee']
        wanted = [f for f in (rule.get_params().get('fields') or ['identification_id', 'department_id'])
                  if f in Emp._fields]
        emps = Emp.search(self._base_domain(run, rule))
        for e in emps:
            missing = [f for f in wanted if not e[f]]
            if missing:
                self._add_finding(
                    run, rule, e, self.env._("Missing master data: %s", e.name),
                    self.env._("Missing fields: %s", ', '.join(missing)),
                    self.env._("Mandatory employee data is complete."), ', '.join(missing),
                    snapshot={'employee': e.name, 'missing': missing}, confidential=True)
        return len(emps)

    # ---------------------------------------------------------- access / SoD
    def _sod_conflicts(self, company, pairs):
        """Return ({user: [conflicting pairs]}, users_examined). Read-only analysis."""
        valid = {x for p in pairs for x in p if self.env.ref(x, raise_if_not_found=False)}
        users = self.env['res.users'].sudo().search([('share', '=', False), ('company_ids', 'in', company.id)])
        result = {}
        for user in users:
            hits = [p for p in pairs if len(p) == 2 and p[0] in valid and p[1] in valid
                    and user.has_group(p[0]) and user.has_group(p[1])]
            if hits:
                result[user] = hits
        return result, len(users)

    @audit_rule('SOD001', ['res.users'], 'Users holding conflicting access rights')
    def _r_sod001(self, run, rule):
        pairs = rule.get_params().get('pairs') or DEFAULT_SOD_PAIRS
        result, examined = self._sod_conflicts(run.company_id, pairs)
        for user, hits in result.items():
            for pair in hits:
                self._add_finding(
                    run, rule, user, self.env._("Conflicting access: %s", user.display_name),
                    self.env._("User holds both %(a)s and %(b)s. Compensating controls may justify this.",
                               a=pair[0], b=pair[1]),
                    self.env._("Incompatible duties are held by different people."),
                    ' + '.join(pair), key="SOD|%s|%s" % (user.id, '/'.join(pair)),
                    snapshot={'user': user.display_name, 'groups': pair})
        return examined

    # ================================================= PHASE 3 RULES ========
    # ---------------------------------------------------------- financial
    @audit_rule('FIN008', ['account.move'], 'Repeated round-number transactions', needs=['amount'])
    def _r_fin008(self, run, rule):
        step = rule.threshold_amount
        min_count = int(rule.get_params().get('min_count', 3))
        moves = self.env['account.move'].search(self._base_domain(run, rule, [
            ('state', '=', 'posted'), ('move_type', 'in', ('in_invoice', 'out_invoice', 'in_refund', 'out_refund')),
            ('date', '>=', run.date_from), ('date', '<=', run.date_to)], 'partner_id'))
        buckets = defaultdict(list)
        for m in moves:
            amt = abs(m.amount_total_signed)
            if amt and abs(amt / step - round(amt / step)) < 1e-6:
                buckets[m.partner_id.id].append(m)
        for pid, items in buckets.items():
            if len(items) >= min_count:
                recs = self.env['account.move'].concat(*items)
                self._add_finding(
                    run, rule, recs[0], self.env._("Repeated round amounts: %s", recs[0].partner_id.display_name),
                    self.env._("%(n)s documents with amounts that are multiples of %(s)s: %(names)s. "
                               "Round amounts are common (e.g. retainers); this is only a risk indicator.",
                               n=len(items), s=step, names=', '.join(recs.mapped('display_name'))),
                    self.env._("Amounts reflect actual quantities and prices."),
                    self.env._("%s round-number documents", len(items)),
                    amount=sum(abs(m.amount_total_signed) for m in items), partner=recs[0].partner_id,
                    key="ROUND|%s|%s" % (pid, sorted(recs.ids)),
                    snapshot={'documents': recs.mapped('display_name'), 'step': step})
        return len(moves)

    @audit_rule('FIN009', ['account.move.line', 'account.account'], 'Unusual balance in clearing / suspense accounts',
                needs=['amount'])
    def _r_fin009(self, run, rule):
        codes = rule.get_params().get('codes') or []
        if not codes:
            run._add_message('warning', rule, self.env._("Configure account codes in extra parameters: "
                                                         "{\"codes\": [\"101404\"]}"))
            return 0
        accounts = self.env['account.account'].search([('code', 'in', codes)])
        groups = self.env['account.move.line']._read_group(
            [('company_id', '=', run.company_id.id), ('parent_state', '=', 'posted'),
             ('account_id', 'in', accounts.ids), ('date', '<=', run.date_to)], ['account_id'], ['balance:sum'])
        for account, balance in groups:
            if abs(balance) >= rule.threshold_amount:
                self._add_finding(
                    run, rule, account, self.env._("Clearing/suspense balance: %s", account.display_name),
                    self.env._("Cumulative balance %(b)s at %(d)s exceeds %(t)s.", b=balance, d=run.date_to,
                               t=rule.threshold_amount),
                    self.env._("Clearing / suspense accounts are cleared regularly."),
                    self.env._("Balance %s", balance), amount=abs(balance),
                    key="SUSP|%s|%s" % (account.id, run.date_to),
                    snapshot={'account': account.display_name, 'balance': balance, 'as_of': run.date_to})
        return len(accounts)

    @audit_rule('FIN010', ['account.move.line', 'account.account'], 'Abnormal period-over-period account movements',
                needs=['amount', 'percent'])
    def _r_fin010(self, run, rule):
        Line = self.env['account.move.line']
        days = (run.date_to - run.date_from).days + 1
        prev_to = run.date_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=days - 1)

        def totals(d1, d2):
            return dict(Line._read_group(
                [('company_id', '=', run.company_id.id), ('parent_state', '=', 'posted'),
                 ('date', '>=', d1), ('date', '<=', d2)], ['account_id'], ['balance:sum']))
        cur, prev = totals(run.date_from, run.date_to), totals(prev_from, prev_to)
        for acc in set(cur) | set(prev):
            c, p = cur.get(acc, 0.0), prev.get(acc, 0.0)
            delta = c - p
            pct = abs(delta) / abs(p) * 100.0 if p else 100.0
            if abs(delta) >= rule.threshold_amount and pct >= rule.threshold_percent:
                self._add_finding(
                    run, rule, acc, self.env._("Abnormal movement: %s", acc.display_name),
                    self.env._("Movement %(c)s vs previous equal period %(p)s (change %(pct).0f%%). "
                               "Seasonality or one-off events can explain this.", c=c, p=p, pct=pct),
                    self.env._("Movements are consistent with the previous period."),
                    self.env._("Change %s", delta), amount=abs(delta),
                    key="POP|%s|%s|%s" % (acc.id, run.date_from, run.date_to),
                    snapshot={'account': acc.display_name, 'current': c, 'previous': p,
                              'periods': [str(run.date_from), str(run.date_to), str(prev_from), str(prev_to)]})
        return len(set(cur) | set(prev))

    @audit_rule('FIN011', ['account.bank.statement.line'], 'Bank statement lines unreconciled too long',
                needs=['days'])
    def _r_fin011(self, run, rule):
        limit = run.date_to - timedelta(days=rule.threshold_days)
        lines = self.env['account.bank.statement.line'].search(self._base_domain(run, rule, [
            ('is_reconciled', '=', False), ('date', '<', limit)]))
        for l in lines:
            self._add_finding(
                run, rule, l, self.env._("Unreconciled bank line: %s", l.display_name),
                self.env._("Dated %(d)s, amount %(a)s, still unreconciled. An outstanding item alone is not "
                           "an error; verify it is being followed up.", d=l.date, a=l.amount),
                self.env._("Statement lines are reconciled within %s days.", rule.threshold_days),
                self.env._("Unreconciled since %s", l.date), amount=abs(l.amount),
                snapshot={'line': l.display_name, 'date': l.date, 'amount': l.amount}, doc_date=l.date)
        return len(lines)

    # ------------------------------------------------------------ inventory
    @audit_rule('INV004', ['stock.picking'], 'Deliveries without a linked sales order')
    def _r_inv004(self, run, rule):
        Picking = self.env['stock.picking']
        if 'sale_id' not in Picking._fields:
            run._add_message('warning', rule, self.env._("Sales app not installed; link cannot be checked."))
            return 0
        start, end = self._dt_range(run)
        picks = Picking.search(self._base_domain(run, rule, [
            ('picking_type_code', '=', 'outgoing'), ('state', '=', 'done'), ('sale_id', '=', False),
            ('date_done', '>=', start), ('date_done', '<=', end)], 'partner_id'))
        for p in picks:
            self._add_finding(
                run, rule, p, self.env._("Delivery without sales order: %s", p.name),
                self.env._("Done delivery has no linked sales order. Returns, samples and manual deliveries may "
                           "be legitimate."),
                self.env._("Deliveries are linked to a sales order."), self.env._("No sales order"),
                partner=p.partner_id, snapshot={'picking': p.name, 'done': p.date_done, 'origin': p.origin},
                doc_date=p.date_done.date())
        return len(picks)

    # ---------------------------------------------------------------- sales
    @audit_rule('SAL003', ['sale.order'], 'Repeated sales orders just below approval threshold',
                needs=['amount', 'percent'])
    def _r_sal003(self, run, rule):
        start, end = self._dt_range(run)
        orders = self.env['sale.order'].search(self._base_domain(run, rule, [
            ('state', 'in', ('sale', 'done')), ('date_order', '>=', start), ('date_order', '<=', end)],
            'partner_id'))
        low = rule.threshold_amount * (1 - rule.threshold_percent / 100.0)
        buckets = defaultdict(list)
        for o in orders:
            amt = self._to_company(o.amount_total, o.currency_id, run, o.date_order.date())
            if low <= amt < rule.threshold_amount:
                buckets[o.partner_id.id].append((o, amt))
        for pid, items in buckets.items():
            if len(items) >= 2:
                recs = self.env['sale.order'].concat(*[o for o, _a in items])
                self._add_finding(
                    run, rule, recs[0], self.env._("Orders just below threshold: %s", recs[0].partner_id.display_name),
                    self.env._("%(n)s orders between %(l).0f and %(t)s: %(names)s", n=len(items), l=low,
                               t=rule.threshold_amount, names=', '.join(recs.mapped('name'))),
                    self.env._("Order values are not clustered just below approval limits."),
                    self.env._("%s orders", len(items)), amount=sum(a for _o, a in items),
                    partner=recs[0].partner_id, key="NEAR|%s|%s" % (pid, sorted(recs.ids)),
                    snapshot={'orders': recs.mapped('name'), 'threshold': rule.threshold_amount})
        return len(orders)

    @audit_rule('SAL004', ['sale.order'], 'Confirmed sales to archived customers')
    def _r_sal004(self, run, rule):
        start, end = self._dt_range(run)
        orders = self.env['sale.order'].with_context(active_test=False).search(self._base_domain(run, rule, [
            ('state', 'in', ('sale', 'done')), ('date_order', '>=', start), ('date_order', '<=', end),
            ('partner_id.active', '=', False)]))
        for o in orders:
            self._add_finding(
                run, rule, o, self.env._("Sale to archived customer: %s", o.name),
                self.env._("Customer %s is archived (an archive after the sale is also possible; check dates).",
                           o.partner_id.display_name),
                self.env._("Customers are active when orders are confirmed."), self.env._("Customer archived"),
                partner=o.partner_id, snapshot={'order': o.name, 'date': o.date_order}, doc_date=o.date_order.date())
        return len(orders)

    # ------------------------------------------------------------- purchase
    @audit_rule('PUR003', ['account.move', 'purchase.order'], 'Vendor bills without purchase order')
    def _r_pur003(self, run, rule):
        if 'purchase_line_id' not in self.env['account.move.line']._fields:
            return 0
        bills = self.env['account.move'].search(self._base_domain(run, rule, [
            ('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
            ('date', '>=', run.date_from), ('date', '<=', run.date_to)], 'partner_id'))
        hits = bills.filtered(lambda b: not any(b.invoice_line_ids.mapped('purchase_line_id')))
        for b in hits:
            self._add_finding(
                run, rule, b, self.env._("Vendor bill without PO: %s", b.display_name),
                self.env._("No bill line is linked to a purchase order. Allowed for some expense categories; "
                           "exclude those vendors in the rule if the process is permitted."),
                self.env._("Bills reference an approved purchase order."), self.env._("No purchase order link"),
                amount=abs(b.amount_total_signed), partner=b.partner_id,
                snapshot={'bill': b.display_name, 'ref': b.ref, 'amount': b.amount_total_signed}, doc_date=b.date)
        return len(bills)

    @audit_rule('PUR004', ['purchase.order.line'], 'Purchase price above vendor history', needs=['percent'])
    def _r_pur004(self, run, rule):
        PL = self.env['purchase.order.line']
        start, end = self._dt_range(run)
        lines = PL.search(self._base_domain(run, rule, [
            ('order_id.state', 'in', ('purchase', 'done')), ('display_type', '=', False),
            ('product_id', '!=', False), ('order_id.date_order', '>=', start), ('order_id.date_order', '<=', end)],
            'order_id.partner_id'))
        for l in lines:
            prev = PL.search([('company_id', '=', run.company_id.id), ('product_id', '=', l.product_id.id),
                              ('order_id.partner_id', '=', l.order_id.partner_id.id),
                              ('order_id.state', 'in', ('purchase', 'done')),
                              ('order_id.date_order', '<', l.order_id.date_order)], limit=20)
            if len(prev) < 2:
                continue
            avg = sum(prev.mapped('price_unit')) / len(prev)
            if avg and l.price_unit > avg * (1 + rule.threshold_percent / 100.0):
                self._add_finding(
                    run, rule, l, self.env._("Price above history: %s", l.order_id.name),
                    self.env._("Unit price %(p)s vs average %(a).2f of %(n)s earlier orders (+%(pct).0f%%).",
                               p=l.price_unit, a=avg, n=len(prev), pct=(l.price_unit / avg - 1) * 100),
                    self.env._("Prices stay within %s%% of history.", rule.threshold_percent),
                    self.env._("Unit price %s", l.price_unit),
                    amount=(l.price_unit - avg) * l.product_qty, partner=l.order_id.partner_id,
                    snapshot={'po': l.order_id.name, 'product': l.product_id.display_name,
                              'price': l.price_unit, 'avg_previous': avg, 'samples': len(prev)},
                    doc_date=l.order_id.date_order.date())
        return len(lines)

    # ---------------------------------------------- HR: expenses & payroll
    def _expense_amount_field(self):
        Exp = self.env['hr.expense']
        for f in ('total_amount', 'total_amount_currency'):
            if f in Exp._fields:
                return f
        return None

    @audit_rule('HR003', ['hr.expense'], 'Potential duplicate expense claims')
    def _r_hr003(self, run, rule):
        Exp = self.env['hr.expense']
        amt = self._expense_amount_field()
        if not amt:
            run._add_message('warning', rule, self.env._("Expense amount field not found."))
            return 0
        groups = Exp._read_group(self._base_domain(run, rule, [
            ('state', '!=', 'refused'), ('date', '>=', run.date_from), ('date', '<=', run.date_to)]),
            ['employee_id', 'date:day', amt, 'product_id'], ['id:array_agg'], having=[('__count', '>', 1)])
        for emp, day, amount, product, ids in groups:
            recs = Exp.browse(ids)
            self._add_finding(
                run, rule, recs[0], self.env._("Possible duplicate expense on %s", day),
                self.env._("%(n)s claims with the same employee, date, product and amount: %(names)s",
                           n=len(ids), names=', '.join(recs.mapped('name'))),
                self.env._("Each expense is claimed once."), self.env._("%s identical claims", len(ids)),
                amount=amount * (len(ids) - 1), key="DUP|%s" % sorted(ids), confidential=True,
                snapshot={'claims': recs.mapped('name'), 'date': day}, doc_date=day)
        return len(groups)

    @audit_rule('HR004', ['hr.expense'], 'Expenses above configured limit', needs=['amount'])
    def _r_hr004(self, run, rule):
        Exp = self.env['hr.expense']
        amt = self._expense_amount_field()
        if not amt:
            return 0
        exps = Exp.search(self._base_domain(run, rule, [
            ('date', '>=', run.date_from), ('date', '<=', run.date_to), (amt, '>=', rule.threshold_amount)]))
        for e in exps:
            self._add_finding(
                run, rule, e, self.env._("Expense above limit: %s", e.name),
                self.env._("Claim exceeds the limit of %s. Verify approval.", rule.threshold_amount),
                self.env._("Claims above the limit are specially approved."), self.env._("Above limit"),
                amount=e[amt], confidential=True, snapshot={'claim': e.name, 'date': e.date}, doc_date=e.date)
        return len(exps)

    @audit_rule('HR005', ['hr.expense'], 'Expenses missing receipts', needs=['amount'])
    def _r_hr005(self, run, rule):
        Exp = self.env['hr.expense']
        amt = self._expense_amount_field()
        if not amt:
            return 0
        exps = Exp.search(self._base_domain(run, rule, [
            ('date', '>=', run.date_from), ('date', '<=', run.date_to), (amt, '>=', rule.threshold_amount)]))
        with_att = set(self.env['ir.attachment'].search([
            ('res_model', '=', 'hr.expense'), ('res_id', 'in', exps.ids)]).mapped('res_id'))
        for e in exps.filtered(lambda x: x.id not in with_att):
            self._add_finding(
                run, rule, e, self.env._("Expense without receipt: %s", e.name),
                self.env._("No attachment found on a claim above %s.", rule.threshold_amount),
                self.env._("Receipts are attached to claims above the limit."), self.env._("No attachment"),
                amount=e[amt], confidential=True, snapshot={'claim': e.name, 'date': e.date}, doc_date=e.date)
        return len(exps)

    @audit_rule('HR006', ['hr.payslip'], 'Payroll deviation from previous period', needs=['percent'])
    def _r_hr006(self, run, rule):
        Slip = self.env['hr.payslip']
        if 'net_wage' not in Slip._fields:
            run._add_message('warning', rule, self.env._("Payslip net wage field not found."))
            return 0
        slips = Slip.search(self._base_domain(run, rule, [
            ('state', 'in', ('done', 'paid')), ('date_from', '>=', run.date_from), ('date_to', '<=', run.date_to)]))
        for s in slips:
            prev = Slip.search([('employee_id', '=', s.employee_id.id), ('state', 'in', ('done', 'paid')),
                                ('date_to', '<', s.date_from), ('company_id', '=', run.company_id.id)],
                               order='date_from desc', limit=1)
            if prev and prev.net_wage:
                pct = (s.net_wage - prev.net_wage) / abs(prev.net_wage) * 100.0
                if abs(pct) >= rule.threshold_percent:
                    # Salary values are deliberately NOT written to the finding: only the percentage.
                    self._add_finding(
                        run, rule, s, self.env._("Payroll deviation: %s", s.employee_id.display_name),
                        self.env._("Net pay changed by %(p).0f%% versus the previous payslip. Bonuses, unpaid "
                                   "leave or corrections can explain this.", p=pct),
                        self.env._("Net pay is stable within %s%%.", rule.threshold_percent),
                        self.env._("Change %.0f%%", pct), confidential=True,
                        snapshot={'payslip': s.display_name, 'change_pct': round(pct, 1)}, doc_date=s.date_to)
        return len(slips)

    # ================================================= PHASE 5 RULES ========
    @audit_rule('FIN012', ['account.tax'], 'Tax configuration modified in period')
    def _r_fin012(self, run, rule):
        start, end = self._dt_range(run)
        taxes = self.env['account.tax'].with_context(active_test=False).search(self._base_domain(run, rule, [
            ('write_date', '>=', start), ('write_date', '<=', end)]))
        hits = taxes.filtered(lambda t: (t.write_date - t.create_date).total_seconds() > 60)
        for t in hits:
            self._add_finding(
                run, rule, t, self.env._("Tax modified: %s", t.display_name),
                self.env._("Tax record last modified on %(d)s by %(u)s. Odoo does not keep field-level history "
                           "for taxes, so what changed must be verified manually.", d=t.write_date,
                           u=t.write_uid.display_name),
                self.env._("Tax configuration changes are approved and documented."),
                self.env._("Modified %s", t.write_date),
                snapshot={'tax': t.display_name, 'amount': t.amount, 'modified': t.write_date,
                          'modified_by': t.write_uid.display_name})
        return len(taxes)

    @audit_rule('PUR005', ['res.partner.bank', 'account.payment'], 'Vendor bank account changed shortly before payment',
                needs=['days'])
    def _r_pur005(self, run, rule):
        start, end = self._dt_range(run)
        banks = self.env['res.partner.bank'].with_context(active_test=False).search([
            ('write_date', '>=', start), ('write_date', '<=', end)])
        count = 0
        for bank in banks:
            changed = bank.write_date.date()
            payments = self.env['account.payment'].search(self._base_domain(run, rule, [
                ('partner_id', '=', bank.partner_id.id), ('payment_type', '=', 'outbound'),
                ('state', 'in', ('in_process', 'paid')), ('date', '>=', changed),
                ('date', '<=', changed + timedelta(days=rule.threshold_days))]))
            count += 1
            for pay in payments:
                self._add_finding(
                    run, rule, pay, self.env._("Payment soon after bank change: %s", pay.display_name),
                    self.env._("Bank account of %(p)s was created or edited on %(c)s and a payment followed on %(d)s. "
                               "Verify the change with the vendor through an independent channel.",
                               p=bank.partner_id.display_name, c=changed, d=pay.date),
                    self.env._("Bank detail changes are verified before payments are released."),
                    self.env._("Payment %s days after change", (pay.date - changed).days),
                    amount=abs(pay.amount_company_currency_signed) if 'amount_company_currency_signed' in pay._fields
                    else pay.amount, partner=bank.partner_id,
                    key="BANK|%s|%s" % (bank.id, pay.id),
                    snapshot={'partner': bank.partner_id.display_name, 'bank_changed': bank.write_date,
                              'payment': pay.display_name, 'payment_date': pay.date,
                              'changed_by': bank.write_uid.display_name}, doc_date=pay.date)
        return count

    @audit_rule('INV005', ['stock.lot'], 'Expired or near-expiry lots with stock on hand', needs=['days'])
    def _r_inv005(self, run, rule):
        Lot = self.env['stock.lot']
        if 'expiration_date' not in Lot._fields:
            run._add_message('warning', rule, self.env._("Expiration dates are not configured (product_expiry)."))
            return 0
        limit = datetime.combine(run.date_to, time.max) + timedelta(days=rule.threshold_days)
        lots = Lot.search(self._base_domain(run, rule, [
            ('expiration_date', '!=', False), ('expiration_date', '<=', limit), ('product_qty', '>', 0)]))
        for lot in lots:
            expired = lot.expiration_date < datetime.combine(run.date_to, time.max)
            self._add_finding(
                run, rule, lot, self.env._("Expiry risk: %(l)s (%(p)s)", l=lot.name, p=lot.product_id.display_name),
                self.env._("Lot expires %(d)s with %(q)s on hand.", d=lot.expiration_date, q=lot.product_qty),
                self.env._("Expired stock is quarantined or disposed of."),
                self.env._("Expired") if expired else self.env._("Expires within %s days", rule.threshold_days),
                severity='high' if expired else None, product=lot.product_id,
                snapshot={'lot': lot.name, 'product': lot.product_id.display_name, 'expires': lot.expiration_date,
                          'on_hand': lot.product_qty})
        return len(lots)

    @audit_rule('SAL005', ['sale.order', 'res.partner'], 'Sales to customers above their credit limit')
    def _r_sal005(self, run, rule):
        Partner = self.env['res.partner']
        if 'credit_limit' not in Partner._fields or 'credit' not in Partner._fields:
            run._add_message('warning', rule, self.env._("Accounting credit-limit fields not found."))
            return 0
        start, end = self._dt_range(run)
        orders = self.env['sale.order'].search(self._base_domain(run, rule, [
            ('state', 'in', ('sale', 'done')), ('date_order', '>=', start), ('date_order', '<=', end)],
            'partner_id'))
        seen = set()
        for o in orders:
            p = o.partner_id.commercial_partner_id
            if p.id in seen or not p.credit_limit:
                continue
            if 'use_partner_credit_limit' in Partner._fields and not p.use_partner_credit_limit:
                continue
            if p.credit > p.credit_limit:
                seen.add(p.id)
                self._add_finding(
                    run, rule, p, self.env._("Customer above credit limit: %s", p.display_name),
                    self.env._("Receivable balance %(c)s exceeds the credit limit %(l)s. The CURRENT balance is "
                               "compared (the balance at order time is not available - limitation).",
                               c=p.credit, l=p.credit_limit),
                    self.env._("Sales to customers stay within their credit limit."),
                    self.env._("Balance %s", p.credit), amount=p.credit - p.credit_limit, partner=p,
                    key="CREDIT|%s|%s" % (p.id, run.date_to),
                    snapshot={'customer': p.display_name, 'balance': p.credit, 'limit': p.credit_limit,
                              'example_order': o.name})
        return len(orders)

    @audit_rule('HR007', ['hr.salary.rule'], 'Payroll salary rules modified in period')
    def _r_hr007(self, run, rule):
        start, end = self._dt_range(run)
        rules = self.env['hr.salary.rule'].with_context(active_test=False).search([
            ('write_date', '>=', start), ('write_date', '<=', end)])
        hits = rules.filtered(lambda r: (r.write_date - r.create_date).total_seconds() > 60)
        for r in hits:
            self._add_finding(
                run, rule, r, self.env._("Salary rule modified: %s", r.display_name),
                self.env._("Salary rule last modified on %(d)s by %(u)s. Verify the change was authorised.",
                           d=r.write_date, u=r.write_uid.display_name),
                self.env._("Payroll configuration changes are approved and documented."),
                self.env._("Modified %s", r.write_date), confidential=True,
                snapshot={'rule': r.display_name, 'modified': r.write_date, 'modified_by': r.write_uid.display_name})
        return len(rules)
