# -*- coding: utf-8 -*-
from collections import defaultdict
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Domain

OPEN_STATES = ('submitted', 'approved', 'quotation')
WON_STATES = ('won', 'delivered', 'invoiced', 'paid')
ACT_APPROVAL = 'tender_management.mail_activity_type_tender_approval'
ACT_QUOTATION = 'tender_management.mail_activity_type_tender_quotation'


class TmTenderStage(models.Model):
    """Fixed kanban columns. One stage per workflow state, so every column always shows."""
    _name = 'tm.tender.stage'
    _description = 'Tender Stage'
    _order = 'sequence, id'
    _fold_name = 'fold'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    fold = fields.Boolean('Folded in Kanban', default=False,
                          help='Folded stages are collapsed in the kanban view.')


class TmTender(models.Model):
    _name = 'tm.tender'
    _description = 'Tender'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'product.catalog.mixin']
    _order = 'tender_date desc, id desc'

    name = fields.Char('Tender Number', default=lambda self: _('New'), copy=False,
                       readonly=True, tracking=True)
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, tracking=True)
    tender_date = fields.Date('Tender Date', required=True, tracking=True,
                              default=fields.Date.context_today)
    deadline = fields.Date('Deadline', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('quotation', 'Quotation'),
        ('won', 'Won'),
        ('delivered', 'Delivered'),
        ('invoiced', 'Invoiced'),
        ('paid', 'Paid'),
        ('lost', 'Lost'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, copy=False, tracking=True, index=True)
    stage_id = fields.Many2one(
        'tm.tender.stage', string='Stage', compute='_compute_stage_id', store=True,
        index=True, group_expand='_read_group_stage_ids')
    user_id = fields.Many2one('res.users', string='Responsible', tracking=True,
                              default=lambda self: self.env.user)
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id', store=True)
    note = fields.Html('Notes')
    lost_reason = fields.Text('Lost Notes')
    lost_reason_id = fields.Many2one('tm.tender.lost.reason', string='Lost Reason', tracking=True, copy=False)
    priority = fields.Selection([
        ('0', 'Normal'),
        ('1', 'Low'),
        ('2', 'High'),
        ('3', 'Very High'),
    ], string='Priority', default='0')
    tag_ids = fields.Many2many('tm.tender.tag', string='Tags')
    document_ids = fields.Many2many(
        'ir.attachment', 'tm_tender_attachment_rel', 'tender_id', 'attachment_id',
        string='Attachments', copy=False)
    payment_term_id = fields.Many2one('account.payment.term', string='Payment Terms')
    validity_days = fields.Integer('Quotation Validity (days)', default=30)
    costs_outdated = fields.Boolean(compute='_compute_costs_outdated')
    min_margin = fields.Float(
        'Target Margin %',
        help='Profit percentage on cost. Type it to set the sale price of all the lines, including '
             'the lines you add later: price = BOM cost x (1 + percentage). It is also a threshold: '
             'an alert is shown when the tender profit percentage, after the tender additional '
             'costs, is below it.')
    approved_by = fields.Many2one('res.users', string='Approved By', readonly=True, copy=False)
    approved_date = fields.Datetime('Approved On', readonly=True, copy=False)

    revision_of_id = fields.Many2one('tm.tender', string='Revision Of', copy=False, readonly=True,
                                     index=True, ondelete='set null')
    revision_ids = fields.One2many('tm.tender', 'revision_of_id', string='Revisions')
    revision_no = fields.Integer('Revision', default=0, copy=False, readonly=True)
    revision_count = fields.Integer(compute='_compute_revision_count')

    actual_cost = fields.Monetary('Actual Manufacturing Cost', compute='_compute_actual_cost',
                                  help='Cost of the finished products of the completed manufacturing orders.')
    estimated_produced_cost = fields.Monetary('Estimated Cost (produced quantity)',
                                              compute='_compute_actual_cost')
    cost_variance = fields.Monetary('Cost Variance', compute='_compute_actual_cost',
                                    help='Actual minus estimated. Positive means the production cost more than estimated.')
    cost_variance_percent = fields.Float('Variance %', compute='_compute_actual_cost')

    line_ids = fields.One2many('tm.tender.line', 'tender_id', string='Products', copy=True)
    cost_ids = fields.One2many('tm.tender.cost', 'tender_id', string='Additional Costs', copy=True)
    sale_order_ids = fields.One2many('sale.order', 'tender_id', string='Sales Orders')

    quotation_count = fields.Integer(compute='_compute_quotation_count')
    bom_count = fields.Integer('BOMs', compute='_compute_counts')
    sale_order_count = fields.Integer('Sales Orders', compute='_compute_counts')
    production_count = fields.Integer('Manufacturing Orders', compute='_compute_counts')
    picking_count = fields.Integer('Deliveries', compute='_compute_counts')
    invoice_count = fields.Integer('Invoices', compute='_compute_counts')
    payment_count = fields.Integer('Payments', compute='_compute_counts')
    purchase_order_ids = fields.One2many('purchase.order', 'tender_id', string='Purchase Orders')
    purchase_order_count = fields.Integer('Purchase Orders', compute='_compute_counts')
    landed_cost_ids = fields.One2many('stock.landed.cost', 'tender_id', string='Landed Costs')
    landed_cost_count = fields.Integer('Landed Costs', compute='_compute_counts')
    delivery_status = fields.Selection([
        ('none', 'Nothing to Deliver'),
        ('pending', 'To Deliver'),
        ('partial', 'Partially Delivered'),
        ('delivered', 'Delivered'),
    ], string='Delivery Status', compute='_compute_fulfillment')
    invoicing_status = fields.Selection([
        ('none', 'Nothing to Invoice'),
        ('to_invoice', 'To Invoice'),
        ('invoiced', 'Fully Invoiced'),
        ('paid', 'Paid'),
    ], string='Invoicing Status', compute='_compute_fulfillment')

    amount_sale = fields.Monetary('Total Sale', compute='_compute_totals', store=True)
    amount_bom_cost = fields.Monetary('BOM Costs', compute='_compute_totals', store=True)
    amount_extra_cost = fields.Monetary('Tender Additional Costs', compute='_compute_totals', store=True)
    amount_total_cost = fields.Monetary('Tender Total Cost', compute='_compute_totals', store=True)
    profit = fields.Monetary('Profit', compute='_compute_totals', store=True)
    margin_percent = fields.Float('Margin %', compute='_compute_totals', store=True)
    low_margin = fields.Boolean(compute='_compute_flags')
    is_overdue = fields.Boolean(compute='_compute_flags', search='_search_is_overdue')

    # ------------------------------------------------------------------
    # Computes / constraints
    # ------------------------------------------------------------------
    @api.depends('state')
    def _compute_stage_id(self):
        stages = {s.code: s for s in self.env['tm.tender.stage'].sudo().search([])}
        for tender in self:
            tender.stage_id = stages.get(tender.state)

    @api.model
    def _read_group_stage_ids(self, stages, domain, order=None):
        # every stage is always displayed as a kanban column
        return self.env['tm.tender.stage'].search([], order='sequence, id')

    @api.depends('line_ids.total_price', 'line_ids.total_bom_cost', 'cost_ids.amount')
    def _compute_totals(self):
        for tender in self:
            sale = sum(tender.line_ids.mapped('total_price'))
            bom_cost = sum(tender.line_ids.mapped('total_bom_cost'))
            extra = sum(tender.cost_ids.mapped('amount'))
            total = bom_cost + extra
            tender.amount_sale = sale
            tender.amount_bom_cost = bom_cost
            tender.amount_extra_cost = extra
            tender.amount_total_cost = total
            tender.profit = sale - total
            tender.margin_percent = ((sale - total) / total * 100.0) if total else 0.0

    @api.depends('margin_percent', 'min_margin', 'deadline', 'state')
    def _compute_flags(self):
        for tender in self:
            tender.low_margin = bool(tender.min_margin and tender.line_ids
                                     and tender.margin_percent < tender.min_margin)
            today = fields.Date.context_today(tender)
            tender.is_overdue = bool(tender.deadline and tender.deadline < today
                                     and tender.state in ('draft', 'submitted'))

    def _search_is_overdue(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_('Unsupported search on "Overdue".'))
        today = fields.Date.context_today(self)
        domain = ['&', ('state', 'in', ('draft', 'submitted')), ('deadline', '<', today)]
        return domain if (operator == '=') == value else ['!'] + domain

    @api.depends('sale_order_ids.state')
    def _compute_quotation_count(self):
        for tender in self:
            tender.quotation_count = len(tender.sale_order_ids.filtered(lambda o: o.state != 'cancel'))

    @api.depends('line_ids.bom_id', 'sale_order_ids.state', 'sale_order_ids.picking_ids',
                 'sale_order_ids.invoice_ids', 'sale_order_ids.invoice_ids.payment_state')
    def _compute_counts(self):
        for tender in self:
            orders = tender.sudo().sale_order_ids
            tender.bom_count = len(tender.line_ids.bom_id)
            tender.sale_order_count = len(orders)
            tender.picking_count = len(orders.picking_ids)
            tender.invoice_count = len(orders.invoice_ids)
            tender.payment_count = len(tender._tm_payments())
            tender.purchase_order_count = len(tender.purchase_order_ids)
            tender.landed_cost_count = len(tender.landed_cost_ids.filtered(lambda l: l.state != 'cancel'))
            tender.production_count = len(tender._tm_productions())

    def _tm_payments(self):
        """Payments reconciled with the posted customer invoices of the tender's sales orders."""
        self.ensure_one()
        invoices = self.sudo().sale_order_ids.invoice_ids.filtered(
            lambda m: m.move_type == 'out_invoice' and m.state == 'posted')
        return invoices._get_reconciled_payments()

    def _tm_confirmed_orders(self):
        self.ensure_one()
        return self.sudo().sale_order_ids.filtered(lambda o: o.state in ('sale', 'done'))

    def _tm_productions(self):
        """All Manufacturing Orders linked to this tender's own confirmed sales orders
        (matched on MO origin = SO name, the same link Odoo's Sales/MRP flow uses)."""
        self.ensure_one()
        names = self._tm_confirmed_orders().mapped('name')
        return self.env['mrp.production'].sudo().search([('origin', 'in', names)]) if names \
            else self.env['mrp.production']

    @staticmethod
    def _tm_outgoing_pickings(orders):
        return orders.picking_ids.filtered(
            lambda p: p.state != 'cancel' and p.picking_type_code == 'outgoing')

    @staticmethod
    def _tm_is_paid(orders):
        invoices = orders.invoice_ids.filtered(
            lambda m: m.move_type == 'out_invoice' and m.state == 'posted')
        return bool(invoices) and all(m.payment_state in ('paid', 'in_payment') for m in invoices)

    @api.depends('sale_order_ids.state', 'sale_order_ids.invoice_status',
                 'sale_order_ids.picking_ids.state', 'sale_order_ids.invoice_ids.payment_state')
    def _compute_fulfillment(self):
        for tender in self:
            orders = tender._tm_confirmed_orders()
            pickings = self._tm_outgoing_pickings(orders)
            if not pickings:
                tender.delivery_status = 'none'
            elif all(p.state == 'done' for p in pickings):
                tender.delivery_status = 'delivered'
            elif any(p.state == 'done' for p in pickings):
                tender.delivery_status = 'partial'
            else:
                tender.delivery_status = 'pending'
            if not orders:
                tender.invoicing_status = 'none'
            elif all(o.invoice_status in ('invoiced', 'upselling') for o in orders):
                tender.invoicing_status = 'paid' if self._tm_is_paid(orders) else 'invoiced'
            elif any(o.invoice_status == 'to invoice' for o in orders):
                tender.invoicing_status = 'to_invoice'
            else:
                tender.invoicing_status = 'none'

    def _tm_sync_fulfillment(self):
        """Won -> Delivered -> Invoiced -> Paid, driven by deliveries, invoices and payments."""
        labels = dict(self._fields['state'].selection)
        for tender in self.filtered(lambda t: t.state in ('won', 'delivered', 'invoiced')):
            orders = tender._tm_confirmed_orders()
            if not orders:
                continue
            pickings = self._tm_outgoing_pickings(orders)
            delivered = all(p.state == 'done' for p in pickings)
            invoiced = all(o.invoice_status in ('invoiced', 'upselling') for o in orders)
            new_state = tender.state
            if delivered and invoiced and self._tm_is_paid(orders):
                new_state = 'paid'
            elif delivered and invoiced:
                new_state = 'invoiced'
            elif delivered and pickings and tender.state == 'won':
                new_state = 'delivered'
            if new_state != tender.state:
                tender.sudo().write({'state': new_state})
                tender.sudo().message_post(
                    body=_('Tender moved to %s automatically.') % labels[new_state])

    @api.model
    def _cron_sync_fulfillment(self):
        self.search([('state', 'in', ('won', 'delivered', 'invoiced'))])._tm_sync_fulfillment()

    # ------------------------------------------------------------------
    # Actual vs estimated cost
    # ------------------------------------------------------------------
    @staticmethod
    def _tm_finished_value(production):
        total = 0.0
        for move in production.move_finished_ids.filtered(
                lambda m: m.state == 'done' and m.product_id == production.product_id):
            if 'value' in move._fields and move.value:
                total += abs(move.value)
            else:
                total += move.price_unit * move.product_qty
        return total

    def _tm_actual_vs_estimated(self):
        """One row per tender product that already has completed manufacturing orders."""
        self.ensure_one()
        productions = self._tm_productions().filtered(lambda p: p.state == 'done')
        rows = []
        for line in self.line_ids.sorted('sequence'):
            prods = productions.filtered(lambda p: p.product_id == line.product_id)
            if not prods:
                continue
            produced = sum(p.product_uom_id._compute_quantity(p.qty_produced, line.uom_id, round=False)
                           for p in prods)
            actual = sum(self._tm_finished_value(p) for p in prods)
            estimated = produced * line.bom_cost_unit
            variance = actual - estimated
            rows.append({
                'product': line.product_id.display_name,
                'uom': line.uom_id.name,
                'qty_ordered': line.quantity,
                'qty_produced': produced,
                'orders': ', '.join(prods.mapped('name')),
                'estimated': estimated,
                'actual': actual,
                'variance': variance,
                'variance_percent': (variance / estimated * 100.0) if estimated else 0.0,
            })
        return rows

    @api.depends('sale_order_ids.state')
    def _compute_actual_cost(self):
        for tender in self:
            rows = tender._tm_actual_vs_estimated() if tender.id else []
            actual = sum(r['actual'] for r in rows)
            estimated = sum(r['estimated'] for r in rows)
            tender.actual_cost = actual
            tender.estimated_produced_cost = estimated
            tender.cost_variance = actual - estimated
            tender.cost_variance_percent = ((actual - estimated) / estimated * 100.0) if estimated else 0.0

    # ------------------------------------------------------------------
    # Revisions
    # ------------------------------------------------------------------
    @api.depends('revision_ids')
    def _compute_revision_count(self):
        for tender in self:
            tender.revision_count = len(tender.revision_ids)

    def action_new_revision(self):
        self.ensure_one()
        if self.state in ('draft', 'won', 'delivered', 'invoiced', 'paid'):
            raise UserError(_('A revision can only be created from a submitted, approved, '
                              'quotation, lost or cancelled tender.'))
        if self.quotation_count:
            raise UserError(_('Cancel the quotation of this tender before creating a revision.'))
        base = self.name.split('-R')[0]
        number = self.revision_no + 1
        new = self.copy({
            'name': '%s-R%d' % (base, number),
            'revision_of_id': self.id,
            'revision_no': number,
        })
        self.write({'state': 'cancelled'})
        self.message_post(body=_('Superseded by revision %s.') % new.name)
        new.message_post(body=_('Revision of %s.') % self.name)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'tm.tender',
            'res_id': new.id,
            'view_mode': 'form',
        }

    def action_view_revisions(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Revisions'),
            'res_model': 'tm.tender',
            'domain': [('revision_of_id', '=', self.id)],
        }
        if len(self.revision_ids) == 1:
            action.update(view_mode='form', res_id=self.revision_ids.id)
        else:
            action.update(view_mode='list,form')
        return action

    @api.depends('line_ids.cost_outdated', 'state')
    def _compute_costs_outdated(self):
        for tender in self:
            tender.costs_outdated = bool(
                tender.state in ('draft', 'submitted') and any(tender.line_ids.mapped('cost_outdated')))

    @api.constrains('tender_date', 'deadline')
    def _check_dates(self):
        for tender in self:
            if tender.deadline and tender.tender_date and tender.deadline < tender.tender_date:
                raise ValidationError(_('The deadline cannot be before the tender date.'))

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('tm.tender') or _('New')
        return super().create(vals_list)

    def unlink(self):
        if any(t.state not in ('draft', 'cancelled') for t in self):
            raise UserError(_('Only draft or cancelled tenders can be deleted.'))
        return super().unlink()

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def _check_manager(self):
        if not self.env.user.has_group('tender_management.group_tender_manager'):
            raise AccessError(_('Only Tender Managers can perform this action.'))

    def action_submit(self):
        for tender in self:
            if not tender.line_ids:
                raise UserError(_('Add at least one product before submitting the tender.'))
        self.write({'state': 'submitted'})
        self._tm_notify_managers()

    def _tm_notify_managers(self):
        """Activity for the managers: a tender is waiting for approval."""
        managers = self.env['res.users'].sudo().search([('share', '=', False)]).filtered(
            lambda u: u.has_group('tender_management.group_tender_manager'))
        targets = (managers - self.env.user) or managers
        for tender in self.sudo():
            for user in targets:
                tender.activity_schedule(
                    ACT_APPROVAL,
                    summary=_('Tender %s is waiting for approval') % tender.name,
                    user_id=user.id)

    def _tm_close_activities(self, xmlid, unlink=False):
        atype = self.env.ref(xmlid, raise_if_not_found=False)
        if not atype:
            return
        for tender in self.sudo():
            activities = tender.activity_ids.filtered(lambda a: a.activity_type_id == atype)
            if unlink:
                activities.unlink()
            else:
                activities._action_done()

    def action_approve(self):
        self._check_manager()
        self.write({
            'state': 'approved',
            'approved_by': self.env.user.id,
            'approved_date': fields.Datetime.now(),
        })
        self._tm_close_activities(ACT_APPROVAL)
        for tender in self.sudo():
            tender.activity_schedule(
                ACT_QUOTATION,
                summary=_('Tender %s is approved: create the quotation') % tender.name,
                user_id=(tender.user_id or self.env.user).id)

    def _tm_apply_target_margin(self):
        """Sale price of every line = (BOM cost + its share of the tender additional costs)
        x (1 + target %), so the target margin is on the tender's full cost, not the BOM
        cost alone. Additional costs are allocated across lines in proportion to their total
        BOM cost. Returns lines without cost (no BOM cost and no share to allocate)."""
        self.ensure_one()
        without_cost = self.env['tm.tender.line']
        extra = sum(self.cost_ids.mapped('amount'))
        bom_total = sum(self.line_ids.mapped('total_bom_cost'))
        for line in self.line_ids:
            share = (line.total_bom_cost / bom_total * extra) if bom_total else 0.0
            effective_unit_cost = line.bom_cost_unit + (share / line.quantity if line.quantity else 0.0)
            if effective_unit_cost:
                line.price_unit = effective_unit_cost * (1.0 + self.min_margin / 100.0)
            else:
                without_cost |= line
        return without_cost

    @api.onchange('min_margin', 'cost_ids.amount')
    def _onchange_min_margin(self):
        if self.state not in ('draft', 'submitted') or not self.line_ids:
            return
        if self.min_margin <= -100.0:
            return {'warning': {
                'title': _('Invalid margin'),
                'message': _('The percentage must be greater than -100%.'),
            }}
        without_cost = self._tm_apply_target_margin()
        if without_cost:
            return {'warning': {
                'title': _('No cost'),
                'message': _('These products have no BOM cost, so their price was not changed: %s') % ', '.join(
                    without_cost.mapped('product_id.display_name')),
            }}

    def action_refresh_costs(self):
        """Re-read the BOM costs into the tender lines (only before approval)."""
        for tender in self:
            if tender.state not in ('draft', 'submitted'):
                raise UserError(_('Costs are frozen once the tender is approved.'))
        self.mapped('line_ids').modified(['bom_id'])
        for tender in self:
            if tender.min_margin > 0.0:
                tender._tm_apply_target_margin()
        return True

    def action_create_quotation(self):
        self.ensure_one()
        if self.state not in ('approved', 'quotation'):
            raise UserError(_('The tender must be approved before creating a quotation.'))
        if self.quotation_count:
            raise UserError(_('An active quotation already exists for this tender.'))
        sale_line = self.env['sale.order.line']
        uom_field = 'product_uom_id' if 'product_uom_id' in sale_line._fields else 'product_uom'
        order_lines = [(0, 0, {
            'sequence': line.sequence,
            'product_id': line.product_id.id,
            'product_uom_qty': line.quantity,
            uom_field: line.uom_id.id,
            'price_unit': line.price_unit,
            'discount': 0.0,
        }) for line in self.line_ids.sorted('sequence')]
        order_vals = {
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'user_id': self.user_id.id,
            'origin': self.name,
            'tender_id': self.id,
            'order_line': order_lines,
        }
        if self.payment_term_id:
            order_vals['payment_term_id'] = self.payment_term_id.id
        if self.validity_days:
            order_vals['validity_date'] = fields.Date.context_today(self) + timedelta(days=self.validity_days)
        order = self.env['sale.order'].create(order_vals)
        self._tm_close_activities(ACT_QUOTATION)
        self.state = 'quotation'
        self.message_post(body=_('Quotation %s created.') % order.name)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
        }

    def action_won(self):
        self._check_manager()
        self.write({'state': 'won'})

    def action_delivered(self):
        self._check_manager()
        self.write({'state': 'delivered'})

    def action_invoiced(self):
        self._check_manager()
        self.write({'state': 'invoiced'})

    def action_paid(self):
        self._check_manager()
        self.write({'state': 'paid'})

    def action_lost(self):
        self.ensure_one()
        self._check_manager()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Mark as Lost'),
            'res_model': 'tm.tender.lost.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_tender_id': self.id},
        }

    def action_cancel(self):
        self._check_manager()
        self.write({'state': 'cancelled'})
        self._tm_close_activities(ACT_APPROVAL, unlink=True)
        self._tm_close_activities(ACT_QUOTATION, unlink=True)

    def action_draft(self):
        self._check_manager()
        self.write({'state': 'draft', 'approved_by': False, 'approved_date': False})
        self._tm_close_activities(ACT_APPROVAL, unlink=True)
        self._tm_close_activities(ACT_QUOTATION, unlink=True)

    def action_add_products(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Add Products'),
            'res_model': 'tm.tender.add.products.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_tender_id': self.id},
        }

    # ------------------------------------------------------------------
    # Product catalog (same "Catalog" picker used on Sales Orders)
    #
    # This mirrors, hook for hook, how `sale.order` implements
    # `product.catalog.mixin` in core Odoo:
    #   - action_add_from_catalog / _get_action_add_from_catalog_extra_context
    #   - _get_product_catalog_domain
    #   - _get_product_catalog_order_data
    #   - _get_product_catalog_record_lines
    #   - _is_readonly
    #   - _update_order_line_info
    # plus the `_get_product_catalog_lines_data` method that the mixin
    # requires on the *line* model (tm.tender.line, below).
    # ------------------------------------------------------------------
    def action_add_from_catalog(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Products can only be added to a draft tender.'))
        return super().action_add_from_catalog()

    def _get_action_add_from_catalog_extra_context(self):
        return {
            **super()._get_action_add_from_catalog_extra_context(),
            # `sale.order`/`purchase.order` have their own dedicated JS
            # catalog renderer that reads `product_catalog_order_id`
            # (set by super() above). `tm.tender` has no such renderer, so
            # it falls back to the generic catalog kanban widget, which
            # reads the order id from a plain `order_id` context key
            # instead. Without it, the client calls
            # `/product/catalog/order_lines_info` with no `order_id` at
            # all, causing "missing 1 required positional argument:
            # 'order_id'".
            'order_id': self.id,
            'product_catalog_currency_id': self.currency_id.id,
            'product_catalog_digits': self.currency_id.decimal_places,
        }

    def _get_product_catalog_domain(self):
        return super()._get_product_catalog_domain() & Domain('sale_ok', '=', True)

    def _get_product_catalog_order_data(self, products, **kwargs):
        res = super()._get_product_catalog_order_data(products, **kwargs)
        for product in products:
            res[product.id]['price'] = product.lst_price
        return res

    def _get_product_catalog_record_lines(self, product_ids, **kwargs):
        self.ensure_one()
        grouped_lines = defaultdict(lambda: self.env['tm.tender.line'])
        for line in self.line_ids.filtered(lambda l: l.product_id.id in product_ids):
            grouped_lines[line.product_id] |= line
        return grouped_lines

    def _is_readonly(self):
        return self.state != 'draft'

    def _update_order_line_info(self, product_id, quantity, **kwargs):
        self.ensure_one()
        lines = self._get_product_catalog_record_lines([product_id], **kwargs)
        line = lines.get(self.env['product.product'].browse(product_id))
        if line:
            line = line[0]
            if quantity > 0:
                line.quantity = quantity
            elif self.state == 'draft':
                line.unlink()
                return 0
        else:
            line = self.env['tm.tender.line'].create({
                'tender_id': self.id,
                'product_id': product_id,
                'quantity': quantity or 1.0,
            })
        return line.price_unit

    def action_send_email(self):
        self.ensure_one()
        template = self.env.ref('tender_management.mail_template_tender_proposal')
        report = self.env.ref('tender_management.action_report_tender_proposal')
        ctx = {
            'default_model': 'tm.tender',
            'default_res_ids': self.ids,
            'default_template_id': template.id,
            'default_composition_mode': 'comment',
            'force_email': True,
        }
        if 'report_template_ids' in template._fields:
            if report not in template.report_template_ids:
                template.sudo().write({'report_template_ids': [(4, report.id)]})
        else:
            pdf, _report_type = self.env['ir.actions.report']._render_qweb_pdf(report, self.ids)
            attachment = self.env['ir.attachment'].create({
                'name': '%s.pdf' % self.name,
                'raw': pdf,
                'res_model': 'tm.tender',
                'res_id': self.id,
                'mimetype': 'application/pdf',
            })
            ctx['default_attachment_ids'] = [(6, 0, attachment.ids)]
        form = self.env.ref('mail.email_compose_message_wizard_form')
        return {
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'views': [(form.id, 'form')],
            'view_id': form.id,
            'target': 'new',
            'context': ctx,
        }

    # ------------------------------------------------------------------
    # Smart buttons
    # ------------------------------------------------------------------
    def action_view_boms(self):
        self.ensure_one()
        boms = self.line_ids.bom_id
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Bills of Materials'),
            'res_model': 'mrp.bom',
            'domain': [('id', 'in', boms.ids)],
        }
        if len(boms) == 1:
            action.update(view_mode='form', res_id=boms.id)
        else:
            action.update(view_mode='list,form')
        return action

    def action_view_sale_orders(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Sales Orders'),
            'res_model': 'sale.order',
            'domain': [('tender_id', '=', self.id)],
        }
        if len(self.sale_order_ids) == 1:
            action.update(view_mode='form', res_id=self.sale_order_ids.id)
        else:
            action.update(view_mode='list,form')
        return action

    def action_view_productions(self):
        self.ensure_one()
        names = self.sale_order_ids.filtered(lambda o: o.state != 'cancel').mapped('name')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Manufacturing Orders'),
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('origin', 'in', names)],
        }

    def action_view_pickings(self):
        self.ensure_one()
        pickings = self.sudo().sale_order_ids.picking_ids
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Delivery Orders'),
            'res_model': 'stock.picking',
            'domain': [('id', 'in', pickings.ids)],
        }
        if len(pickings) == 1:
            action.update(view_mode='form', res_id=pickings.id)
        else:
            action.update(view_mode='list,form')
        return action

    def action_view_payments(self):
        self.ensure_one()
        payments = self._tm_payments()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Payments'),
            'res_model': 'account.payment',
            'domain': [('id', 'in', payments.ids)],
        }
        if len(payments) == 1:
            action.update(view_mode='form', res_id=payments.id)
        else:
            action.update(view_mode='list,form')
        return action

    def action_view_purchase_orders(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Purchase Orders'),
            'res_model': 'purchase.order',
            'domain': [('id', 'in', self.purchase_order_ids.ids)],
        }
        if len(self.purchase_order_ids) == 1:
            action.update(view_mode='form', res_id=self.purchase_order_ids.id)
        else:
            action.update(view_mode='list,form')
        return action

    def action_view_landed_costs(self):
        self.ensure_one()
        costs = self.landed_cost_ids.filtered(lambda l: l.state != 'cancel')
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Landed Costs'),
            'res_model': 'stock.landed.cost',
            'domain': [('id', 'in', costs.ids)],
        }
        if len(costs) == 1:
            action.update(view_mode='form', res_id=costs.id)
        else:
            action.update(view_mode='list,form')
        return action

    def action_create_landed_cost(self):
        """Turn this tender's Additional Costs into a real Odoo Landed Cost, applied directly
        to this tender's Manufacturing Orders (Landed Cost's "Apply On: Manufacturing Orders"
        mode), once manufacturing is done. Nothing is validated automatically: the user still
        presses Compute then Validate on the created record, exactly like any other Landed
        Cost in Odoo."""
        self.ensure_one()
        self._check_manager()

        # 1. Additional Cost lines
        if not self.cost_ids:
            raise UserError(_('Add at least one Additional Cost line before creating a Landed Cost.'))

        # 2. Manufacturing Orders exist and are all confirmed (not still in draft) —
        # they no longer need to be fully "Done", just confirmed.
        productions = self._tm_productions()
        if not productions:
            raise UserError(_('No Manufacturing Orders were found for this tender yet.'))
        draft = productions.filtered(lambda p: p.state == 'draft')
        if draft:
            raise UserError(_(
                'These Manufacturing Orders are still in Draft and must be confirmed first: %s'
            ) % ', '.join(draft.mapped('name')))

        # 3. This Odoo installation must support Landed Cost "Apply On: Manufacturing Orders"
        # (added to stock.landed.cost by the mrp_account bridge module, already a dependency
        # of this module). Fail clearly instead of silently falling back to something else.
        LandedCost = self.env['stock.landed.cost']
        if 'mrp_production_ids' not in LandedCost._fields or 'target_model' not in LandedCost._fields:
            raise UserError(_(
                'This Odoo installation\'s Landed Cost does not support applying costs '
                'directly to Manufacturing Orders (the "mrp_production_ids" / "target_model" '
                'fields were not found on stock.landed.cost). Check that the "mrp_account" '
                'module is installed, or ask your administrator.'))

        # 4. Invoice (optional now — only used to label the Landed Cost's origin if one exists)
        invoices = self.sudo().sale_order_ids.invoice_ids.filtered(
            lambda m: m.move_type == 'out_invoice' and m.state == 'posted')

        # 5. Not already created for the same costs and transfers
        existing = self.landed_cost_ids.filtered(lambda l: l.state != 'cancel')
        if existing:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Landed Cost Already Created'),
                    'message': _('A Landed Cost already exists for this tender.'),
                    'type': 'warning',
                    'sticky': False,
                    'next': {
                        'type': 'ir.actions.act_window',
                        'res_model': 'stock.landed.cost',
                        'res_id': existing[0].id,
                        'view_mode': 'form',
                    },
                },
            }

        template = self.env.ref('tender_management.product_tm_landed_cost', raise_if_not_found=False)
        product = template.product_variant_id if template else False
        if not product:
            raise UserError(_('The generic Landed Cost product is missing; reinstall the module.'))
        cost_lines = [(0, 0, {
            'product_id': product.id,
            'name': cost.name,
            'price_unit': cost.amount,
            'split_method': cost.split_method,
            'account_id': cost.account_id.id,
        }) for cost in self.cost_ids]
        landed_cost_vals = {
            'mrp_production_ids': [(6, 0, productions.ids)],
            'target_model': 'manufacturing',
            'cost_lines': cost_lines,
            'tender_id': self.id,
            'company_id': self.company_id.id,
        }
        invoice_names = ', '.join(invoices.mapped('name'))
        if 'origin' in LandedCost._fields and invoice_names:
            landed_cost_vals['origin'] = invoice_names
        landed_cost = LandedCost.sudo().create(landed_cost_vals)
        if invoice_names:
            self.message_post(body=_('Landed Cost %s created for Manufacturing Orders %s (invoices: %s).') % (
                landed_cost.display_name, ', '.join(productions.mapped('name')), invoice_names))
        else:
            self.message_post(body=_('Landed Cost %s created for Manufacturing Orders %s.') % (
                landed_cost.display_name, ', '.join(productions.mapped('name'))))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.landed.cost',
            'res_id': landed_cost.id,
            'view_mode': 'form',
        }

    def _tm_component_needs(self):
        """{product: quantity} needed to build the tender's products, from the direct
        components of each line's BOM (one level, not exploded through sub-BOMs)."""
        self.ensure_one()
        needs = {}
        for line in self.line_ids.filtered('bom_id'):
            bom = line.bom_id.sudo()
            if not bom.product_qty:
                continue
            qty_in_bom_uom = line.uom_id._compute_quantity(
                line.quantity, bom.product_uom_id, round=False)
            factor = qty_in_bom_uom / bom.product_qty
            for comp in bom.bom_line_ids:
                product = comp.product_id
                needed = comp.product_qty * factor
                current_qty, current_uom = needs.get(product, (0.0, comp.product_uom_id))
                if current_uom != comp.product_uom_id:
                    needed = comp.product_uom_id._compute_quantity(needed, current_uom, round=False)
                needs[product] = (current_qty + needed, current_uom)
        return needs

    def action_create_purchase_orders(self):
        self.ensure_one()
        self._check_manager()
        if self.state == 'draft':
            raise UserError(_('Approve the tender before creating purchase orders.'))
        needs = self._tm_component_needs()
        if not needs:
            raise UserError(_('None of the tender products have a BOM with components.'))
        by_vendor = {}
        no_vendor = []
        for product, (qty, uom) in needs.items():
            if qty <= 0:
                continue
            seller = product.sudo()._select_seller(quantity=qty, uom_id=uom)
            if not seller:
                no_vendor.append(product.display_name)
                continue
            by_vendor.setdefault(seller.partner_id, []).append((product, qty, uom, seller))
        if not by_vendor:
            raise UserError(_('No vendor is configured for any of the needed components: %s') % ', '.join(no_vendor))
        Purchase = self.env['purchase.order'].sudo()
        po_uom_field = 'product_uom_id' if 'product_uom_id' in self.env['purchase.order.line']._fields else 'product_uom'
        orders = Purchase
        for vendor, items in by_vendor.items():
            order_lines = [(0, 0, {
                'product_id': product.id,
                'name': product.display_name,
                'product_qty': qty,
                po_uom_field: uom.id,
                'price_unit': seller.price,
                'date_planned': fields.Datetime.now(),
            }) for product, qty, uom, seller in items]
            orders |= Purchase.create({
                'partner_id': vendor.id,
                'company_id': self.company_id.id,
                'origin': self.name,
                'tender_id': self.id,
                'order_line': order_lines,
            })
        message = _('%s purchase order(s) created.') % len(orders)
        if no_vendor:
            message += ' ' + _('No vendor configured for: %s') % ', '.join(no_vendor)
        self.message_post(body=message)
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Purchase Orders'),
            'res_model': 'purchase.order',
            'domain': [('id', 'in', orders.ids)],
        }
        if len(orders) == 1:
            action.update(view_mode='form', res_id=orders.id)
        else:
            action.update(view_mode='list,form')
        return action

    def action_view_invoices(self):
        self.ensure_one()
        invoices = self.sudo().sale_order_ids.invoice_ids
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Invoices'),
            'res_model': 'account.move',
            'domain': [('id', 'in', invoices.ids)],
        }
        if len(invoices) == 1:
            action.update(view_mode='form', res_id=invoices.id)
        else:
            action.update(view_mode='list,form')
        return action

    # ------------------------------------------------------------------
    # Printing
    # ------------------------------------------------------------------
    def action_print_proposal(self):
        return self.env.ref('tender_management.action_report_tender_proposal').report_action(self)

    def action_print_variance(self):
        return self.env.ref('tender_management.action_report_tender_variance').report_action(self)

    def action_print_costing(self):
        return self.env.ref('tender_management.action_report_tender_costing').report_action(self)

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_deadline_reminder(self):
        tomorrow = fields.Date.context_today(self) + timedelta(days=1)
        for tender in self.search([('state', 'in', ('draft', 'submitted')),
                                   ('deadline', '=', tomorrow)]):
            tender.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=tender.deadline,
                summary=_('Tender deadline is tomorrow'),
                user_id=(tender.user_id or self.env.user).id)

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, period='year'):
        today = fields.Date.context_today(self)
        date_from = False
        if period == 'month':
            date_from = today.replace(day=1)
        elif period == 'quarter':
            date_from = today.replace(month=(today.month - 1) // 3 * 3 + 1, day=1)
        elif period == 'year':
            date_from = today.replace(month=1, day=1)
        domain = [('tender_date', '>=', fields.Date.to_string(date_from))] if date_from else []

        labels = dict(self._fields['state']._description_selection(self.env))
        by_state = {key: {'key': key, 'label': labels[key], 'count': 0, 'sale': 0.0, 'profit': 0.0}
                    for key in labels}
        for state, count, sale, profit in self._read_group(
                domain, ['state'], ['__count', 'amount_sale:sum', 'profit:sum']):
            by_state[state].update(count=count, sale=sale or 0.0, profit=profit or 0.0)

        def total(keys, field):
            return sum(by_state[k][field] for k in keys)

        active_keys = [k for k in labels if k != 'cancelled']
        won, lost = total(WON_STATES, 'count'), by_state['lost']['count']
        sale_all = total(active_keys, 'sale')
        profit_all = total(active_keys, 'profit')
        overdue_domain = [('state', 'in', ('draft', 'submitted')), ('deadline', '<', fields.Date.to_string(today))]

        kpis = [
            {'key': 'total', 'label': _('Total Tenders'), 'value': sum(v['count'] for v in by_state.values()),
             'type': 'count', 'color': 'primary', 'domain': domain},
            {'key': 'open', 'label': _('In Progress'), 'value': total(OPEN_STATES, 'count'),
             'type': 'count', 'color': 'warning', 'sub_value': total(OPEN_STATES, 'sale'),
             'sub_label': _('pipeline value'), 'domain': domain + [('state', 'in', list(OPEN_STATES))]},
            {'key': 'won', 'label': _('Won'), 'value': won, 'type': 'count', 'color': 'success',
             'sub_value': total(WON_STATES, 'sale'), 'sub_label': _('won value'),
             'domain': domain + [('state', 'in', list(WON_STATES))]},
            {'key': 'to_deliver', 'label': _('To Deliver'), 'value': by_state['won']['count'],
             'type': 'count', 'color': 'info', 'sub_value': by_state['won']['sale'],
             'sub_label': _('waiting delivery'), 'domain': domain + [('state', '=', 'won')]},
            {'key': 'to_invoice', 'label': _('To Invoice'), 'value': by_state['delivered']['count'],
             'type': 'count', 'color': 'warning', 'sub_value': by_state['delivered']['sale'],
             'sub_label': _('delivered, not invoiced'), 'domain': domain + [('state', '=', 'delivered')]},
            {'key': 'invoiced', 'label': _('Invoiced, Unpaid'), 'value': by_state['invoiced']['count'],
             'type': 'count', 'color': 'success', 'sub_value': by_state['invoiced']['sale'],
             'sub_label': _('invoiced value'), 'domain': domain + [('state', '=', 'invoiced')]},
            {'key': 'paid', 'label': _('Paid'), 'value': by_state['paid']['count'],
             'type': 'count', 'color': 'success', 'sub_value': by_state['paid']['sale'],
             'sub_label': _('collected value'), 'domain': domain + [('state', '=', 'paid')]},
            {'key': 'lost', 'label': _('Lost'), 'value': lost, 'type': 'count', 'color': 'danger',
             'sub_value': by_state['lost']['sale'], 'sub_label': _('lost value'),
             'domain': domain + [('state', '=', 'lost')]},
            {'key': 'win_rate', 'label': _('Win Rate'), 'value': (won / (won + lost) * 100.0) if (won + lost) else 0.0,
             'type': 'percent', 'color': 'info', 'domain': domain + [('state', 'in', list(WON_STATES) + ['lost'])]},
            {'key': 'profit', 'label': _('Expected Profit'), 'value': profit_all, 'type': 'money',
             'color': 'success', 'sub_value': (profit_all / (sale_all - profit_all) * 100.0) if sale_all != profit_all else 0.0,
             'sub_type': 'percent', 'sub_label': _('avg margin'),
             'domain': domain + [('state', '!=', 'cancelled')]},
            {'key': 'overdue', 'label': _('Overdue'), 'value': self.search_count(overdue_domain),
             'type': 'count', 'color': 'danger', 'domain': overdue_domain},
        ]

        # last 12 months: sale vs cost
        start = today.replace(day=1) - relativedelta(months=11)
        month_rows = {}
        for month, sale, cost in self._read_group(
                [('tender_date', '>=', fields.Date.to_string(start)), ('state', '!=', 'cancelled')],
                ['tender_date:month'], ['amount_sale:sum', 'amount_total_cost:sum']):
            month = fields.Date.to_date(month)
            month_rows[(month.year, month.month)] = (sale or 0.0, cost or 0.0)
        months = []
        for i in range(12):
            month = start + relativedelta(months=i)
            sale, cost = month_rows.get((month.year, month.month), (0.0, 0.0))
            months.append({'label': month.strftime('%b %y'), 'sale': sale, 'cost': cost})

        customers = [
            {'label': partner.display_name, 'value': amount or 0.0}
            for partner, amount in self._read_group(
                domain + [('state', '!=', 'cancelled')], ['partner_id'], ['amount_sale:sum'],
                order='amount_sale:sum desc', limit=6)
        ]

        lost_reasons = [
            {'label': reason.display_name if reason else _('Not specified'), 'value': count,
             'amount': amount or 0.0}
            for reason, count, amount in self._read_group(
                domain + [('state', '=', 'lost')], ['lost_reason_id'],
                ['__count', 'amount_sale:sum'], order='__count desc')
        ]

        upcoming = self.search_read(
            [('state', 'in', ('draft',) + OPEN_STATES), ('deadline', '!=', False)],
            ['name', 'partner_id', 'deadline', 'amount_sale', 'state', 'is_overdue'],
            order='deadline asc', limit=6)
        for row in upcoming:
            row['state_label'] = labels[row['state']]

        currency = self.env.company.currency_id
        return {
            'kpis': kpis,
            'states': list(by_state.values()),
            'months': months,
            'customers': customers,
            'lost_reasons': lost_reasons,
            'upcoming': upcoming,
            'currency': {'symbol': currency.symbol, 'position': currency.position,
                         'decimals': currency.decimal_places},
        }


class TmTenderLine(models.Model):
    _name = 'tm.tender.line'
    _description = 'Tender Product'
    _order = 'sequence, id'

    tender_id = fields.Many2one('tm.tender', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related='tender_id.company_id', store=True)
    currency_id = fields.Many2one(related='tender_id.currency_id', store=True)
    partner_id = fields.Many2one(related='tender_id.partner_id', string='Customer', store=True)
    tender_date = fields.Date(related='tender_id.tender_date', string='Tender Date', store=True)
    tender_state = fields.Selection(related='tender_id.state', string='Tender Status', store=True)
    product_categ_id = fields.Many2one(related='product_id.categ_id', string='Product Category', store=True)
    product_id = fields.Many2one('product.product', string='Product', required=True,
                                 domain=[('sale_ok', '=', True)])
    product_tmpl_id = fields.Many2one(related='product_id.product_tmpl_id')
    quantity = fields.Float('Quantity', default=1.0, required=True, digits='Product Unit')
    uom_id = fields.Many2one('uom.uom', string='UoM', compute='_compute_uom_id',
                             store=True, readonly=False, precompute=True, copy=True)
    bom_id = fields.Many2one(
        'mrp.bom', string='BOM', compute='_compute_bom_id', store=True, readonly=False,
        precompute=True, ondelete='restrict', copy=True,
        domain="[('type', '=', 'normal'), ('product_tmpl_id', '=', product_tmpl_id), "
               "'|', ('product_id', '=', False), ('product_id', '=', product_id)]")
    material_cost_unit = fields.Monetary('Materials / Unit', compute='_compute_bom_cost_unit', store=True, precompute=True)
    labour_cost_unit = fields.Monetary('Labour / Unit', compute='_compute_bom_cost_unit', store=True, precompute=True)
    overhead_cost_unit = fields.Monetary('Overhead / Unit', compute='_compute_bom_cost_unit', store=True, precompute=True)
    other_cost_unit = fields.Monetary('Other / Unit', compute='_compute_bom_cost_unit', store=True, precompute=True)
    bom_cost_unit = fields.Monetary(
        'BOM Cost / Unit', compute='_compute_bom_cost_unit', store=True, precompute=True,
        help='Total BOM Cost (Materials + Labour + Overhead + Other) per unit. '
             'Products without a BOM use their standard cost. Frozen once approved; '
             'use "Refresh Costs" before approval to re-read it.')
    cost_outdated = fields.Boolean(compute='_compute_cost_outdated')
    material_cost_total = fields.Monetary('Materials', compute='_compute_amounts', store=True)
    labour_cost_total = fields.Monetary('Labour', compute='_compute_amounts', store=True)
    overhead_cost_total = fields.Monetary('Overhead', compute='_compute_amounts', store=True)
    other_cost_total = fields.Monetary('Other', compute='_compute_amounts', store=True)
    total_bom_cost = fields.Monetary('Total BOM Cost', compute='_compute_amounts', store=True)
    price_unit = fields.Monetary('Sale Price', compute='_compute_price_unit',
                                 store=True, readonly=False, precompute=True, copy=True)
    last_price_sold = fields.Monetary(
        'Last Price Sold', compute='_compute_last_price_sold',
        help='Unit price on the most recent confirmed sales order for this customer and product.')
    last_price_sold_info = fields.Char(compute='_compute_last_price_sold')
    total_price = fields.Monetary('Total Sale', compute='_compute_amounts', store=True)
    extra_cost_share = fields.Monetary(
        'Additional Cost Share', compute='_compute_profit_margin', store=True,
        help="This line's share of the tender's Additional Costs, allocated in proportion "
             "to total BOM cost across the tender's lines.")
    profit = fields.Monetary('Profit', compute='_compute_profit_margin', store=True)
    margin_percent = fields.Float(
        'Margin %', compute='_compute_profit_margin', store=True, readonly=False,
        help='Profit as a percentage of the full cost: (Sale Price - BOM Cost - Additional '
             'Cost Share) / (BOM Cost + Additional Cost Share). '
             'Type a percentage to set the sale price; changing the sale price updates the percentage.')

    @api.depends('product_id')
    def _compute_uom_id(self):
        for line in self:
            line.uom_id = line.product_id.uom_id

    @api.depends('product_id')
    def _compute_bom_id(self):
        Bom = self.env['mrp.bom'].sudo()
        for line in self:
            bom = Bom
            if line.product_id:
                company = line.tender_id.company_id or self.env.company
                bom = Bom.search([
                    ('type', '=', 'normal'),
                    ('product_tmpl_id', '=', line.product_id.product_tmpl_id.id),
                    '|', ('product_id', '=', False), ('product_id', '=', line.product_id.id),
                    '|', ('company_id', '=', False), ('company_id', '=', company.id),
                ], order='sequence, id', limit=1)
            line.bom_id = bom

    def _uom_factor(self):
        """How many product-UoM units are in one unit of the line UoM."""
        self.ensure_one()
        if not self.uom_id or not self.product_id:
            return 1.0
        return self.uom_id._compute_quantity(1.0, self.product_id.uom_id, round=False)

    def _tm_cost_parts(self):
        """Materials / Labour / Overhead / Other per unit (line UoM), from the BOM as it is now."""
        self.ensure_one()
        parts = {'material': 0.0, 'labour': 0.0, 'overhead': 0.0, 'other': 0.0}
        if self.product_id:
            factor = self._uom_factor()
            if self.bom_id:
                for key, value in self.bom_id._tm_unit_breakdown().items():
                    parts[key] = value * factor
            else:
                company = self.tender_id.company_id or self.env.company
                parts['material'] = self.product_id.with_company(company).standard_price * factor
        return parts

    @api.depends('product_id', 'bom_id', 'uom_id',
                 'bom_id.product_qty', 'bom_id.product_uom_id', 'bom_id.product_tmpl_id',
                 'bom_id.bom_line_ids.product_id', 'bom_id.bom_line_ids.product_qty',
                 'bom_id.bom_line_ids.product_uom_id', 'bom_id.bom_line_ids.product_id.standard_price',
                 'bom_id.mfg_cost_line_ids.amount', 'bom_id.mfg_cost_line_ids.cost_type',
                 'product_id.standard_price')
    def _compute_bom_cost_unit(self):
        for line in self:
            parts = line._tm_cost_parts()
            line.material_cost_unit = parts['material']
            line.labour_cost_unit = parts['labour']
            line.overhead_cost_unit = parts['overhead']
            line.other_cost_unit = parts['other']
            line.bom_cost_unit = sum(parts.values())

    @api.depends('bom_cost_unit', 'bom_id', 'uom_id', 'product_id', 'tender_id.state')
    def _compute_cost_outdated(self):
        for line in self:
            if not line.id or line.tender_id.state not in ('draft', 'submitted'):
                line.cost_outdated = False
                continue
            current = sum(line._tm_cost_parts().values())
            line.cost_outdated = abs(current - line.bom_cost_unit) > 0.005

    def action_show_cost_breakdown(self):
        self.ensure_one()
        view = self.env.ref('tender_management.tm_tender_line_view_form_breakdown')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cost Breakdown'),
            'res_model': 'tm.tender.line',
            'res_id': self.id,
            'views': [(view.id, 'form')],
            'target': 'new',
        }

    @api.depends('product_id', 'uom_id', 'tender_id.min_margin')
    def _compute_price_unit(self):
        """Default sale price of a line: from the tender target margin when it is set
        (price = full cost x (1 + margin), full cost includes a share of the tender's
        additional costs), otherwise the product list price. Depending on
        tender_id.min_margin means changing the header Target Margin % re-applies the
        price to every line automatically (new or existing)."""
        for line in self:
            if not line.product_id:
                line.price_unit = 0.0
                continue
            margin = line.tender_id.min_margin
            cost = line._tm_effective_unit_cost()
            if cost and margin > 0.0:
                line.price_unit = cost * (1.0 + margin / 100.0)
            else:
                line.price_unit = line.product_id.lst_price * line._uom_factor()

    @api.depends('product_id', 'tender_id.partner_id')
    def _compute_last_price_sold(self):
        SaleLine = self.env['sale.order.line'].sudo()
        for line in self:
            price = 0.0
            info = False
            partner = line.tender_id.partner_id
            if line.product_id and partner:
                # Odoo 19 does not allow ordering a sale.order.line search by
                # a related property such as order_id.date_order. Fetch the
                # matching lines first, then determine the latest quotation/order
                # in Python using the parent sale.order date.
                sale_lines = SaleLine.search([
                    ('order_id.partner_id', '=', partner.id),
                    ('product_id', '=', line.product_id.id),
                    ('order_id.state', 'in', ('sale', 'done')),
                ])
                last = max(
                    sale_lines,
                    key=lambda x: (x.order_id.date_order or x.order_id.create_date or x.create_date, x.id),
                    default=False,
                )
                if last:
                    uom_field = 'product_uom_id' if 'product_uom_id' in last._fields else 'product_uom'
                    last_uom = last[uom_field]
                    uom_factor = last_uom._compute_quantity(
                        1.0, line.uom_id or line.product_id.uom_id, round=False) if last_uom else 1.0
                    price = last.price_unit * uom_factor
                    info = _('%s on %s') % (last.order_id.name, last.order_id.date_order.date()
                                            if last.order_id.date_order else last.order_id.name)
            line.last_price_sold = price
            line.last_price_sold_info = info

    @api.depends('quantity', 'bom_cost_unit', 'price_unit',
                 'material_cost_unit', 'labour_cost_unit', 'overhead_cost_unit', 'other_cost_unit')
    def _compute_amounts(self):
        for line in self:
            line.material_cost_total = line.quantity * line.material_cost_unit
            line.labour_cost_total = line.quantity * line.labour_cost_unit
            line.overhead_cost_total = line.quantity * line.overhead_cost_unit
            line.other_cost_total = line.quantity * line.other_cost_unit
            line.total_bom_cost = line.quantity * line.bom_cost_unit
            line.total_price = line.quantity * line.price_unit

    @api.depends('total_price', 'total_bom_cost', 'tender_id.cost_ids.amount',
                 'tender_id.line_ids.total_bom_cost')
    def _compute_profit_margin(self):
        """Profit and margin on the line's full cost: its BOM cost plus its share of the
        tender's additional costs (allocated in proportion to total BOM cost across the
        tender's lines), so a line's displayed margin isn't overstated by ignoring them."""
        for line in self:
            share = line._tm_extra_cost_share()
            total_cost = line.total_bom_cost + share
            line.extra_cost_share = share
            line.profit = line.total_price - total_cost
            line.margin_percent = (line.profit / total_cost * 100.0) if total_cost else 0.0

    def _tm_extra_cost_share(self):
        """This line's share of the tender's additional costs, allocated in proportion to
        total BOM cost across the tender's lines."""
        self.ensure_one()
        tender = self.tender_id
        extra = sum(tender.cost_ids.mapped('amount'))
        bom_total = sum(tender.line_ids.mapped('total_bom_cost'))
        return (self.total_bom_cost / bom_total * extra) if bom_total else 0.0

    def _tm_effective_unit_cost(self):
        """BOM cost per unit plus this line's share of the tender's additional costs, per unit."""
        self.ensure_one()
        share = self._tm_extra_cost_share()
        return self.bom_cost_unit + (share / self.quantity if self.quantity else 0.0)

    @api.onchange('margin_percent')
    def _onchange_margin_percent(self):
        """Typing a profit percentage sets the sale price: price = full cost x (1 + percentage),
        where full cost includes this line's share of the tender's additional costs."""
        for line in self:
            if not line.product_id:
                continue  # new empty line: nothing to price yet (Odoo also fires this onchange on creation)
            if line.margin_percent <= -100.0:
                return {'warning': {
                    'title': _('Invalid margin'),
                    'message': _('The percentage must be greater than -100%.'),
                }}
            cost = line._tm_effective_unit_cost()
            if not cost:
                if line.margin_percent:
                    return {'warning': {
                        'title': _('No cost'),
                        'message': _('This product has no cost yet, so a sale price cannot be calculated from a margin.'),
                    }}
                continue
            line.price_unit = cost * (1.0 + line.margin_percent / 100.0)

    @api.constrains('quantity')
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(_('The quantity must be greater than zero.'))

    # ------------------------------------------------------------------
    # Product catalog
    #
    # `product.catalog.mixin` (on tm.tender, above) requires the model
    # holding the order lines to expose this method: it's how the catalog
    # kanban knows the quantity/price already on the tender for a product,
    # and whether that line can still be edited from the catalog.
    # ------------------------------------------------------------------
    def _get_product_catalog_lines_data(self, **kwargs):
        if len(self) == 1:
            return {
                'quantity': self.quantity,
                'price': self.price_unit,
                'readOnly': self.tender_state != 'draft',
            }
        if not self:
            return {'quantity': 0, 'price': 0, 'readOnly': False}
        # Several lines for the same product on the same tender: aggregate
        # the quantity and treat it as read-only from the catalog since
        # there's no single line to update unambiguously.
        return {
            'quantity': sum(self.mapped('quantity')),
            'price': self[0].price_unit,
            'readOnly': True,
        }


class TmTenderCost(models.Model):
    """Costs of the tender itself (transportation, installation, site expenses...). Kept
    apart from BOM manufacturing costs on purpose. These are real company costs: once the
    tender is invoiced, they are turned into an actual Odoo Landed Cost that lands on the
    valuation of the delivered products (see TmTender.action_create_landed_cost)."""
    _name = 'tm.tender.cost'
    _description = 'Tender Additional Cost'
    _order = 'sequence, id'

    tender_id = fields.Many2one('tm.tender', required=True, ondelete='cascade', index=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one(related='tender_id.company_id', store=True)
    currency_id = fields.Many2one(related='tender_id.currency_id', store=True)
    cost_type = fields.Selection([
        ('overhead', 'Tender Overhead'),
        ('other', 'Other Tender Cost'),
    ], string='Cost Type', required=True, default='overhead')
    name = fields.Char('Description', required=True)
    amount = fields.Monetary('Amount', required=True)
    account_id = fields.Many2one(
        'account.account', string='Account', compute='_compute_account_id',
        store=True, readonly=False, precompute=True,
        domain="[('account_type', 'not in', ('asset_receivable', 'liability_payable'))]",
        help='Account credited by the Landed Cost when this cost is validated.')
    split_method = fields.Selection([
        ('equal', 'Equal'),
        ('by_quantity', 'By Quantity'),
        ('by_current_cost', 'By Current Cost'),
        ('by_weight', 'By Weight'),
        ('by_volume', 'By Volume'),
    ], string='Split Method', required=True, default='equal',
        help='How the Landed Cost distributes this amount across the delivered products.')

    @api.depends('cost_type', 'tender_id.company_id')
    def _compute_account_id(self):
        for cost in self:
            company = cost.tender_id.company_id or self.env.company
            mapping = {'overhead': company.tm_overhead_account_id, 'other': company.tm_other_account_id}
            cost.account_id = mapping.get(cost.cost_type) or False

    @api.constrains('amount', 'account_id')
    def _check_amount(self):
        for cost in self:
            if cost.amount < 0:
                raise ValidationError(_('Tender additional costs cannot be negative.'))
            if not cost.account_id:
                raise ValidationError(_(
                    'Please choose an account for the "%s" additional cost (or set default '
                    'accounts in Tenders > Configuration > Settings).') % cost.name)
