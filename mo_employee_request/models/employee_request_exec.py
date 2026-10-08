# -*- coding: utf-8 -*-
from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.fields import Domain

from .utils import convert_uom, pick_field

GROUP_MANAGER = 'mo_employee_request.group_employee_request_manager'
GROUP_WAREHOUSE = 'mo_employee_request.group_warehouse_approver'
GROUP_PURCHASE = 'mo_employee_request.group_purchase_user'
PROCESSABLE = ('approved', 'processing', 'partial')
APPROVAL_STATES = ['department', 'warehouse', 'budget']


class EmployeeRequestExec(models.Model):
    _name = 'employee.request'
    _inherit = ['employee.request', 'product.catalog.mixin']

    picking_ids = fields.One2many('stock.picking', 'er_request_id', string='Stock Transfers')
    epo_ids = fields.One2many('employee.purchase.order', 'request_id',
                              string='Purchase Orders')
    stock_order_count = fields.Integer(compute='_compute_doc_counts')
    has_inspection_pending = fields.Boolean(compute='_compute_has_inspection_pending')
    epo_count = fields.Integer(compute='_compute_doc_counts')
    has_stock_to_create = fields.Boolean(compute='_compute_to_create')
    has_purchase_to_create = fields.Boolean(compute='_compute_to_create')
    total_requested = fields.Float(compute='_compute_totals')
    total_issued = fields.Float(compute='_compute_totals')
    total_purchased = fields.Float(compute='_compute_totals')
    total_received = fields.Float(compute='_compute_totals')
    total_remaining = fields.Float(compute='_compute_totals')

    # ------------------------------------------------------------------
    def _er_receipts(self):
        """Receipts of the Odoo purchase orders created from this request."""
        return self.sudo().epo_ids.odoo_po_id.picking_ids

    @api.depends_context('uid')
    @api.depends('epo_ids.odoo_po_id.picking_ids.er_inspection_state')
    def _compute_has_inspection_pending(self):
        for rec in self:
            rec.has_inspection_pending = bool(rec._er_receipts()._er_pending_for_user())

    def action_er_inspection_approve(self):
        for rec in self:
            pending = rec._er_receipts()._er_pending_for_user()
            if not pending:
                raise UserError(_("Nothing is waiting for your inspection approval."))
            pending.action_er_inspection_approve()
        return True

    def action_er_inspection_reject(self):
        for rec in self:
            pending = rec._er_receipts()._er_pending_for_user()
            if not pending:
                raise UserError(_("Nothing is waiting for your inspection approval."))
            pending.action_er_inspection_reject()
        return True

    @api.depends('picking_ids', 'epo_ids')
    def _compute_doc_counts(self):
        for rec in self:
            rec.stock_order_count = len(rec.picking_ids)
            rec.epo_count = len(rec.epo_ids)

    @api.depends('line_ids.qty_issued', 'line_ids.qty_received', 'line_ids.qty_remaining',
                 'line_ids.qty_purchase_planned', 'line_ids.product_uom_qty')
    def _compute_totals(self):
        for rec in self:
            lines = rec.line_ids
            rec.total_requested = sum(lines.mapped('product_uom_qty'))
            rec.total_issued = sum(lines.mapped('qty_issued'))
            rec.total_purchased = sum(lines.mapped('qty_purchase_planned'))
            rec.total_received = sum(lines.mapped('qty_received'))
            rec.total_remaining = sum(lines.mapped('qty_remaining'))

    @api.depends('state', 'line_ids.qty_unprocessed', 'line_ids.available_qty')
    def _compute_to_create(self):
        for rec in self:
            stock = purchase = False
            if rec.state in PROCESSABLE:
                for _line, issue, buy in rec._get_split_plan():
                    stock = stock or issue > 0
                    purchase = purchase or buy > 0
            rec.has_stock_to_create = stock
            rec.has_purchase_to_create = purchase

    # ------------------------------------------------------------------
    # Split logic
    # ------------------------------------------------------------------
    def _get_split_plan(self):
        """[(line, qty_from_stock, qty_to_purchase)] for what is not processed yet."""
        self.ensure_one()
        plan = []
        for line in self.line_ids:
            unprocessed = line.qty_unprocessed
            if unprocessed <= 0:
                continue
            # Free stock already promised to a draft transfer (not reserved yet)
            # (so not reserved) must not be counted again: the purchase quantity is
            # always what the warehouse cannot cover.
            earmarked = sum(
                convert_uom(m.product_uom_qty,
                            m[pick_field(m, 'product_uom', 'product_uom_id')],
                            line.product_uom_id)
                for m in line.move_ids if m.state == 'draft')
            available = max(line.available_qty - earmarked, 0.0)
            issue = min(unprocessed, available)
            plan.append((line, issue, unprocessed - issue))
        return plan

    def _lock_for_processing(self):
        """Serialise concurrent clicks and refresh the numbers we decide on."""
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM employee_request WHERE id = %s FOR UPDATE", (self.id,))
        self.invalidate_recordset()
        self.line_ids.invalidate_recordset()

    def _check_can_process(self, kind):
        self.ensure_one()
        if self.state not in PROCESSABLE:
            raise UserError(_("Documents can only be created for approved requests."))
        if self.env.su:
            return
        user = self.env.user
        allowed = user.has_group(GROUP_MANAGER) or (
            user.has_group(GROUP_WAREHOUSE) if kind == 'stock'
            else user.has_group(GROUP_PURCHASE))
        if not allowed:
            raise UserError(_("You are not allowed to create these documents."))

    def _create_stock_orders(self, confirm=False):
        """Create the stock transfers (Odoo pickings) of the request directly."""
        self.ensure_one()
        rec = self.sudo()
        rec._lock_for_processing()
        groups = {}
        for line, issue, _buy in rec._get_split_plan():
            if issue > 0:
                groups.setdefault(line.warehouse_id, []).append((line, issue))
        if not groups:
            return self.env['stock.picking']
        dest = self.env.ref('mo_employee_request.location_employee_consumption',
                            raise_if_not_found=False)
        if not dest:
            raise UserError(_("The 'Employee Consumption' location is missing."))
        Picking = self.env['stock.picking'].sudo()
        Move = self.env['stock.move']
        uom_field = pick_field(Move, 'product_uom', 'product_uom_id')
        partner = (rec.employee_id.work_contact_id
                   if 'work_contact_id' in rec.employee_id._fields else False)
        pickings = Picking
        for warehouse, items in groups.items():
            moves = []
            for line, qty in items:
                move_vals = {
                    'product_id': line.product_id.id,
                    'product_uom_qty': qty,
                    uom_field: line.product_uom_id.id,
                    'location_id': warehouse.lot_stock_id.id,
                    'location_dest_id': dest.id,
                    'company_id': rec.company_id.id,
                    'er_request_line_id': line.id,
                }
                if line.analytic_account_id:
                    move_vals['analytic_distribution'] = {
                        str(line.analytic_account_id.id): 100.0}
                if 'name' in Move._fields:  # removed in Odoo 19
                    move_vals['name'] = line.product_id.display_name
                moves.append((0, 0, move_vals))
            pickings |= Picking.create({
                'picking_type_id': warehouse.out_type_id.id,
                'location_id': warehouse.lot_stock_id.id,
                'location_dest_id': dest.id,
                'partner_id': partner.id if partner else False,
                'origin': rec.name,
                'company_id': rec.company_id.id,
                'er_request_id': rec.id,
                'analytic_distribution': ({str(rec.analytic_account_id.id): 100.0}
                                          if rec.analytic_account_id else False),
                'move_ids': moves,
            })
        rec.message_post(
            body=_("Stock transfer(s) created: %s", ", ".join(pickings.mapped('name'))),
            subtype_xmlid='mail.mt_note')
        if confirm:
            pickings.action_confirm()
            pickings.action_assign()
        rec._refresh_execution_state()
        return pickings

    def _er_select_seller(self, line, qty):
        """Best vendor line (product.supplierinfo) of the product for this quantity."""
        try:
            return line.product_id.sudo()._select_seller(
                quantity=qty, date=fields.Date.context_today(self),
                uom_id=line.product_uom_id)
        except Exception:
            return self.env['product.supplierinfo']

    def _create_purchase_orders(self):
        self.ensure_one()
        rec = self.sudo()
        rec._lock_for_processing()
        groups = {}
        for line, _issue, buy in rec._get_split_plan():
            if buy > 0:
                # vendor and price come from the product page (Purchase tab)
                seller = rec._er_select_seller(line, buy)
                key = (line.warehouse_id, seller.partner_id, seller.currency_id)
                groups.setdefault(key, []).append((line, buy, seller))
        EPO = self.env['employee.purchase.order'].sudo()
        epos = EPO
        for (warehouse, vendor, currency), items in groups.items():
            epos |= EPO.create({
                'request_id': rec.id,
                'employee_id': rec.employee_id.id,
                'department_id': rec.department_id.id,
                'project_id': rec.project_id.id,
                'analytic_account_id': rec.analytic_account_id.id,
                'warehouse_id': warehouse.id,
                'company_id': rec.company_id.id,
                'partner_id': vendor.id or False,
                'currency_id': (currency or rec.company_id.currency_id).id,
                'payment_term_id': (vendor.property_supplier_payment_term_id.id
                                    if vendor else False),
                'line_ids': [(0, 0, EPO._prepare_line_from_request_line(line, qty, seller))
                             for line, qty, seller in items],
            })
        if epos:
            rec.message_post(
                body=_("Purchase order(s) created: %s", ", ".join(epos.mapped('name'))),
                subtype_xmlid='mail.mt_note')
            rec._refresh_execution_state()
        return epos

    def action_create_stock_orders(self):
        for rec in self:
            rec._check_can_process('stock')
            if not rec._create_stock_orders(confirm=rec.company_id.er_auto_stock_order):
                raise UserError(_("Nothing is left to issue from stock for %s.", rec.name))
        return True

    def action_create_purchase_orders(self):
        for rec in self:
            rec._check_can_process('purchase')
            if not rec._create_purchase_orders():
                raise UserError(_("Nothing is left to purchase for %s.", rec.name))
        return True

    def _on_fully_approved(self):
        res = super()._on_fully_approved()
        for rec in self:
            company = rec.company_id
            if company.er_auto_stock_order:
                rec._create_stock_orders(confirm=True)
            if company.er_auto_purchase_order:
                rec._create_purchase_orders()
        return res

    # ------------------------------------------------------------------
    # Status calculation
    # ------------------------------------------------------------------
    def _refresh_execution_state(self):
        for rec in self.sudo().filtered(
                lambda r: r.state in ('approved', 'processing', 'partial', 'closed')):
            lines = rec.line_ids
            has_docs = bool(
                rec.picking_ids.filtered(lambda p: p.state != 'cancel')
                or rec.epo_ids.filtered(lambda e: e.state not in ('cancelled', 'rejected')))
            done = sum(l.product_uom_qty - l.qty_remaining for l in lines)
            if lines and all(l.qty_remaining <= 1e-6 for l in lines):
                new_state = 'closed'
            elif done > 0:
                new_state = 'partial'
            elif has_docs:
                new_state = 'processing'
            else:
                new_state = 'approved'
            if new_state != rec.state:
                rec.write({'state': new_state})
                rec.message_post(
                    body=_("Request is now: %s", rec._stage_label(new_state)),
                    subtype_xmlid='mail.mt_note')
                if new_state == 'closed':
                    rec._er_notify_closed()

    def _er_notify_closed(self):
        """Tell the requester that the request is fully done and closed."""
        self.ensure_one()
        partner = self.user_id.partner_id
        if not partner:
            return
        self.message_notify(
            partner_ids=partner.ids,
            author_id=self.env.ref('base.partner_root').id,
            subject=_("Request %s is closed", self.name),
            body=_("Your request <a href=\"#\" data-oe-model=\"employee.request\" "
                   "data-oe-id=\"%(id)s\">%(name)s</a> is completed and closed.",
                   id=self.id, name=self.name),
            subtype_xmlid='mail.mt_note')

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------
    def _check_cancellable(self):
        super()._check_cancellable()
        rec = self.sudo()
        if any(l.qty_issued or l.qty_received for l in rec.line_ids) or \
                rec.epo_ids.filtered(lambda e: e.odoo_po_id):
            raise UserError(_(
                "%s already has executed stock or purchase documents. They are kept "
                "for history, so the request cannot be cancelled.", rec.name))

    def action_cancel(self):
        res = super().action_cancel()
        for rec in self.sudo():
            rec.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')).action_cancel()
            rec.epo_ids.filtered(
                lambda e: e.state not in ('cancelled', 'rejected')).action_cancel()
        return res

    # ------------------------------------------------------------------
    # Smart buttons / catalog / dashboard
    # ------------------------------------------------------------------
    def action_view_stock_orders(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _("Stock Transfers"),
                'res_model': 'stock.picking', 'view_mode': 'list,form',
                'domain': [('er_request_id', '=', self.id)]}

    def action_view_epos(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _("Purchase Orders"),
                'res_model': 'employee.purchase.order', 'view_mode': 'list,kanban,form',
                'domain': [('request_id', '=', self.id)]}

    # ------------------------------------------------------------------
    # Standard Odoo product catalog (same behaviour as Sales / Purchase)
    # ------------------------------------------------------------------
    def _is_readonly(self):
        return self.state != 'draft'

    def _get_product_catalog_domain(self):
        return super()._get_product_catalog_domain() & Domain('type', '=', 'consu')

    def _get_product_catalog_order_data(self, products, **kwargs):
        res = super()._get_product_catalog_order_data(products, **kwargs)
        for product in products:
            res[product.id]['price'] = 0.0
        return res

    def _default_order_line_values(self, child_field=False):
        default_data = super()._default_order_line_values(child_field)
        new_default_data = self.env['employee.request.line']._get_product_catalog_lines_data()
        return {**default_data, **new_default_data}

    def _get_product_catalog_record_lines(self, product_ids, **kwargs):
        grouped = defaultdict(lambda: self.env['employee.request.line'])
        for line in self.line_ids:
            if line.product_id.id in product_ids:
                grouped[line.product_id] |= line
        return grouped

    def _update_order_line_info(self, product_id, quantity, **kwargs):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Products can only be changed on a draft request."))
        lines = self.line_ids.filtered(lambda l: l.product_id.id == product_id)
        if lines:
            if quantity > 0:
                lines[0].product_uom_qty = quantity
            else:
                lines.unlink()
        elif quantity > 0:
            Line = self.env['employee.request.line']
            warehouse = self.line_ids[:1].warehouse_id or Line.with_company(
                self.company_id)._default_warehouse()
            Line.create({
                'request_id': self.id,
                'product_id': product_id,
                'product_uom_qty': quantity,
                'warehouse_id': warehouse.id,
            })
        return 0.0

    @api.model
    def _er_dashboard_range(self, filters, today):
        """Return (date_from, date_to) for the selected period (either may be None)."""
        from datetime import timedelta
        period = filters.get('period') or 'all'
        if period == 'today':
            return today, today
        if period == 'week':
            start = today - timedelta(days=today.weekday())
            return start, start + timedelta(days=6)
        if period == 'month':
            start = today.replace(day=1)
            nxt = (start + timedelta(days=32)).replace(day=1)
            return start, nxt - timedelta(days=1)
        if period == 'quarter':
            q_month = 3 * ((today.month - 1) // 3) + 1
            start = today.replace(month=q_month, day=1)
            nxt = (start + timedelta(days=95)).replace(day=1)
            return start, nxt - timedelta(days=1)
        if period == 'year':
            return today.replace(month=1, day=1), today.replace(month=12, day=31)
        if period == 'custom':
            return (fields.Date.to_date(filters.get('date_from') or False),
                    fields.Date.to_date(filters.get('date_to') or False))
        return None, None

    @api.model
    def get_dashboard_data(self, filters=None):
        if not (self.env.su or self.env.user.has_group('mo_employee_request.group_er_dashboard')):
            raise AccessError(_("You are not allowed to open the dashboard."))
        filters = filters or {}
        uid = self.env.uid
        today = fields.Date.context_today(self)
        date_from, date_to = self._er_dashboard_range(filters, today)
        department = filters.get('department_id') or False
        only_mine = bool(filters.get('only_mine'))

        def base_domain(model):
            """Filters shared by every tile, adapted to each model's columns."""
            cols = {
                'employee.request': ('request_date', 'user_id', False, 'department_id'),
                'employee.purchase.order': ('date_order', 'user_id', True, 'department_id'),
                'stock.picking': ('er_request_id.request_date', 'er_request_id.user_id',
                                  False, 'er_request_id.department_id'),
            }[model]
            date_col, user_col, is_dt, dept_col = cols
            dom = []
            if date_from:
                dom.append((date_col, '>=', '%s 00:00:00' % date_from if is_dt else date_from))
            if date_to:
                dom.append((date_col, '<=', '%s 23:59:59' % date_to if is_dt else date_to))
            if department:
                dom.append((dept_col, '=', department))
            if only_mine:
                dom.append((user_col, '=', uid))
            return dom

        user = self.env.user
        is_all = user.has_group('mo_employee_request.group_employee_request_all_documents')
        is_warehouse = user.has_group('mo_employee_request.group_warehouse_approver')
        is_budget = user.has_group('mo_employee_request.group_budget_approver')
        is_purchase = user.has_group('mo_employee_request.group_purchase_user')
        is_budget_control = user.has_group('mo_employee_request.group_budget_control')
        company = self.env.company.sudo()
        is_dept_manager = bool(self.env['hr.department'].sudo().search_count(
            [('manager_id.user_id', '=', uid)])) or user in company.er_department_user_ids
        is_approver = (is_warehouse or is_budget or is_dept_manager
                       or user in company.er_warehouse_user_ids
                       or user in company.er_budget_user_ids)
        see_pipeline = is_all or is_approver
        see_stock = is_all or is_warehouse
        see_epo = is_all or is_purchase
        see_budget_rej = is_all or is_purchase or is_budget_control

        R, P, S = ('employee.request', 'employee.purchase.order', 'stock.picking')
        # key, label, hint, model, extra domain, color, icon, section, visible
        tiles = [
            ('all', _("All Requests"), _("Every request in the selected period"),
             R, [], 'primary', 'fa-inbox', 'requests', is_all),
            ('my', _("My Requests"), _("Requests you created"),
             R, [('user_id', '=', uid)], 'primary', 'fa-user', 'requests', True),
            ('open', _("Open Requests"), _("Approved and being processed"),
             R, [('state', 'in', PROCESSABLE)], 'info', 'fa-folder-open', 'requests', True),
            ('partial', _("Partially Done"), _("Some lines are still pending"),
             R, [('state', '=', 'partial')], 'warning', 'fa-adjust', 'requests', True),
            ('closed', _("Closed"), _("Fully processed requests"),
             R, [('state', '=', 'closed')], 'success', 'fa-check-circle', 'requests', True),
            ('to_approve', _("Waiting for My Approval"), _("Requests you have to approve"),
             R, [('pending_approver_ids', 'in', [uid])], 'danger', 'fa-bell',
             'approvals', is_approver or is_all),
            ('waiting', _("Waiting for Approval"), _("Any approval stage"),
             R, [('state', 'in', APPROVAL_STATES)], 'info', 'fa-hourglass-half',
             'approvals', True),
            ('department', _("Waiting Department"), _("Department manager approval"),
             R, [('state', '=', 'department')], 'info', 'fa-sitemap', 'approvals',
             see_pipeline),
            ('warehouse', _("Waiting Warehouse"), _("Warehouse approval"),
             R, [('state', '=', 'warehouse')], 'info', 'fa-cubes', 'approvals',
             see_pipeline),
            ('budget', _("Waiting Budget"), _("Budget approval"),
             R, [('state', '=', 'budget')], 'warning', 'fa-money', 'approvals',
             see_pipeline),
            ('approved', _("Approved"), _("Ready to be processed"),
             R, [('state', '=', 'approved')], 'success', 'fa-thumbs-up', 'approvals', True),
            ('rejected', _("Rejected"), _("Rejected requests"),
             R, [('state', '=', 'rejected')], 'danger', 'fa-ban', 'approvals', True),
            ('stock', _("Stock Transfers"), _("Transfers created from requests"),
             S, [('er_request_id', '!=', False)], 'primary', 'fa-exchange', 'orders',
             see_stock),
            ('epo', _("Purchase Orders"), _("Employee purchase orders"),
             P, [], 'primary', 'fa-shopping-cart', 'orders', see_epo),
            ('budget_rejected', _("Budget Rejected"),
             _("Purchase orders to fix and resubmit"),
             P, [('state', '=', 'budget_rejected')], 'danger', 'fa-exclamation-triangle',
             'orders', see_budget_rej),
        ]
        Request = self.env[R]
        try:
            total_requests = Request.search_count(base_domain(R))
        except Exception:
            total_requests = 0
        data = []
        for key, label, hint, model, extra, color, icon, section, visible in tiles:
            if not visible:
                continue
            domain = base_domain(model) + extra
            try:
                count = self.env[model].search_count(domain)
            except Exception:
                continue
            percent = 0
            if model == R and total_requests:
                percent = round(100.0 * count / total_requests)
            data.append({'key': key, 'label': label, 'hint': hint, 'model': model,
                         'domain': domain, 'count': count, 'color': color, 'icon': icon,
                         'section': section, 'percent': percent,
                         'show_percent': model == R and key != 'all'})

        # Status distribution (requests)
        state_labels = dict(Request._fields['state'].selection)
        by_state = []
        try:
            for state, count in Request._read_group(base_domain(R), ['state'], ['__count']):
                by_state.append({'state': state, 'label': state_labels.get(state, state),
                                 'count': count,
                                 'domain': base_domain(R) + [('state', '=', state)]})
        except Exception:
            pass
        order = list(state_labels)
        by_state.sort(key=lambda r: order.index(r['state']) if r['state'] in order else 99)

        # Latest requests
        recent = []
        try:
            for rec in Request.search(base_domain(R), limit=6):
                recent.append({
                    'id': rec.id, 'name': rec.display_name,
                    'employee': rec.employee_id.name or '',
                    'department': rec.department_id.name or '',
                    'date': fields.Date.to_string(rec.request_date) if rec.request_date else '',
                    'state': rec.state, 'state_label': state_labels.get(rec.state, rec.state),
                })
        except Exception:
            pass

        # "Needs my action": always about the current user, never filtered by period/department
        action_cats = [
            ('req_approve', _("Requests to approve"), 'fa-bell', 'danger', R,
             [('pending_approver_ids', 'in', [uid])], True),
            ('epo_approve', _("Purchase orders to approve"), 'fa-shopping-cart', 'danger', P,
             [('pending_approver_ids', 'in', [uid])], True),
            ('budget_fix', _("Budget rejected: fix and resubmit"), 'fa-exclamation-triangle',
             'danger', P, [('state', '=', 'budget_rejected')], see_budget_rej),
            ('to_process', _("Approved, ready to process"), 'fa-play-circle', 'success', R,
             [('state', '=', 'approved')], is_all or is_warehouse or is_purchase),
            ('my_rfq', _("My RFQs to send for approval"), 'fa-file-text-o', 'info', P,
             [('state', '=', 'draft'), ('user_id', '=', uid)], is_purchase or is_all),
            ('my_rejected', _("My rejected requests"), 'fa-ban', 'warning', R,
             [('state', '=', 'rejected'), ('user_id', '=', uid)], True),
        ]
        chips, items = [], []
        for key, label, icon, color, model, domain, visible in action_cats:
            if not visible:
                continue
            try:
                count = self.env[model].search_count(domain)
                if not count:
                    continue
                recs = self.env[model].search(domain, order='write_date asc, id asc',
                                              limit=4) if len(items) < 8 else self.env[model]
            except Exception:
                continue
            chips.append({'key': key, 'label': label, 'icon': icon, 'color': color,
                          'count': count, 'model': model, 'domain': domain})
            for rec in recs:
                if len(items) >= 8:
                    break
                if model == R:
                    sub = ' - '.join(x for x in (rec.employee_id.name, rec.department_id.name) if x)
                else:
                    sub = ' - '.join(x for x in (
                        rec.partner_id.name,
                        '%s %s' % (rec.currency_id.symbol or '', '{:,.2f}'.format(rec.amount_total))
                        if rec.currency_id else '') if x)
                items.append({'model': model, 'id': rec.id, 'name': rec.display_name,
                              'sub': sub, 'tag': label, 'color': color, 'icon': icon})
        actions = {'chips': chips, 'items': items, 'total': sum(c['count'] for c in chips)}

        departments = []
        if is_all:
            departments = [{'id': d.id, 'name': d.display_name}
                           for d in self.env['hr.department'].search([])]
        return {
            'actions': actions,
            'tiles': data,
            'by_state': by_state,
            'recent': recent,
            'departments': departments,
            'scope': {'can_filter_all': bool(is_all)},
            'total': total_requests,
            'sections': [
                {'key': 'requests', 'label': _("Requests"), 'icon': 'fa-inbox'},
                {'key': 'approvals', 'label': _("Approvals Pipeline"), 'icon': 'fa-tasks'},
                {'key': 'orders', 'label': _("Orders"), 'icon': 'fa-truck'},
            ],
            'periods': [
                {'key': 'all', 'label': _("All time")},
                {'key': 'today', 'label': _("Today")},
                {'key': 'week', 'label': _("This week")},
                {'key': 'month', 'label': _("This month")},
                {'key': 'quarter', 'label': _("This quarter")},
                {'key': 'year', 'label': _("This year")},
                {'key': 'custom', 'label': _("Custom range")},
            ],
        }
