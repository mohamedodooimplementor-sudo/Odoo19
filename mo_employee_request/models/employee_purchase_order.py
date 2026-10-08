# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .utils import pick_field

GROUP_PURCHASE_MANAGER = 'mo_employee_request.group_purchase_manager'
GROUP_PURCHASE_USER = 'mo_employee_request.group_purchase_user'
GROUP_REQ_MANAGER = 'mo_employee_request.group_employee_request_manager'
TODO = 'mail.mail_activity_data_todo'
APPROVAL_STAGES = ['manager', 'budget']
FLOW = ['draft', 'manager', 'budget', 'approved']

EPO_STATES = [
    ('draft', 'RFQ'),
    ('manager', 'Manager Approval'),
    ('budget', 'Budget Approval'),
    ('budget_rejected', 'Budget Rejected'),
    ('budget_control', 'Budget Control'),
    ('approved', 'Open'),
    ('done', 'Closed'),
    ('invoiced', 'Invoiced'),
    ('rejected', 'Rejected'),
    ('cancelled', 'Cancelled'),
]


class EmployeePurchaseOrderApproval(models.Model):
    _name = 'employee.purchase.order.approval'
    _description = 'Employee Purchase Order Approval History'
    _order = 'id desc'

    order_id = fields.Many2one('employee.purchase.order', required=True,
                               ondelete='cascade', index=True)
    stage = fields.Selection(EPO_STATES, string='Stage')
    user_id = fields.Many2one('res.users', required=True, default=lambda s: s.env.user)
    date = fields.Datetime(default=fields.Datetime.now)
    action = fields.Selection([
        ('confirm', 'Confirmed'), ('approve', 'Approved'), ('reject', 'Rejected'),
        ('to_control', 'Sent to Budget Control'), ('resubmit', 'Budget Resubmitted'),
        ('reset', 'Reset to Draft'), ('cancel', 'Cancelled'),
    ], required=True)
    comment = fields.Text()


class EmployeePurchaseOrder(models.Model):
    _name = 'employee.purchase.order'
    _description = 'Employee Purchase Order'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'er.required.mixin']
    _order = 'id desc'

    LOCKED_FIELDS = {'partner_id', 'date_order', 'warehouse_id', 'agreement_id',
                     'currency_id', 'payment_term_id', 'fiscal_position_id',
                     'incoterm_id', 'line_ids', 'project_id', 'analytic_account_id'}

    def _default_employee(self):
        return self.env.user.employee_id

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True, index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    partner_id = fields.Many2one('res.partner', string='Vendor', tracking=True,
                                 domain="[('supplier_rank', '>=', 0)]")
    date_order = fields.Datetime(string='Purchase Date', default=fields.Datetime.now,
                                 required=True)
    employee_id = fields.Many2one('hr.employee', string='Employee', default=_default_employee)
    user_id = fields.Many2one('res.users', related='employee_id.user_id', store=True)
    department_id = fields.Many2one('hr.department', string='Department',
                                    compute='_compute_department', store=True, readonly=False)
    project_id = fields.Many2one('project.project', string='Project')
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account')
    request_id = fields.Many2one('employee.request', string='Source Request',
                                 ondelete='restrict', index=True, copy=False)
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse',
                                   default=lambda s: s.env['stock.warehouse'].search(
                                       [('company_id', '=', s.env.company.id)], limit=1))
    agreement_id = fields.Many2one('purchase.requisition', string='Agreement', copy=False)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
                                  default=lambda s: s.env.company.currency_id)
    payment_term_id = fields.Many2one('account.payment.term', string='Payment Terms')
    fiscal_position_id = fields.Many2one('account.fiscal.position', string='Fiscal Position')
    incoterm_id = fields.Many2one('account.incoterms', string='Incoterm')
    notes = fields.Html(string='Notes')
    line_ids = fields.One2many('employee.purchase.order.line', 'order_id', string='Order Lines',
                               copy=True)
    approval_ids = fields.One2many('employee.purchase.order.approval', 'order_id',
                                   string='Approval History')
    pending_approver_ids = fields.Many2many(
        'res.users', 'employee_po_pending_user_rel', 'order_id', 'user_id',
        string='Waiting Action From', copy=False)
    can_approve = fields.Boolean(compute='_compute_can_approve')
    can_edit_budget = fields.Boolean(compute='_compute_can_approve')
    reject_reason = fields.Text(copy=False, readonly=True)
    state = fields.Selection(EPO_STATES, default='draft', required=True, copy=False,
                             tracking=True, index=True, group_expand=True)
    odoo_po_id = fields.Many2one('purchase.order', string='Odoo Purchase Order',
                                 copy=False, readonly=True)
    amount_untaxed = fields.Monetary(compute='_compute_amounts', store=True)
    amount_tax = fields.Monetary(compute='_compute_amounts', store=True)
    amount_total = fields.Monetary(compute='_compute_amounts', store=True)
    discount_total = fields.Monetary(string='Total Discount', compute='_compute_amounts',
                                     store=True)
    received_notified = fields.Boolean(copy=False, readonly=True)
    line_count = fields.Integer(compute='_compute_line_count')
    receipt_count = fields.Integer(compute='_compute_counts')
    bill_count = fields.Integer(compute='_compute_counts')

    # ------------------------------------------------------------------
    @api.depends('employee_id')
    def _compute_department(self):
        for rec in self:
            rec.department_id = rec.employee_id.department_id

    @api.depends('line_ids.price_subtotal', 'line_ids.price_tax', 'line_ids.discount_amount')
    def _compute_amounts(self):
        for rec in self:
            rec.amount_untaxed = sum(rec.line_ids.mapped('price_subtotal'))
            rec.amount_tax = sum(rec.line_ids.mapped('price_tax'))
            rec.amount_total = rec.amount_untaxed + rec.amount_tax
            rec.discount_total = sum(rec.line_ids.mapped('discount_amount'))

    @api.depends('state', 'pending_approver_ids')
    @api.depends_context('uid')
    def _compute_can_approve(self):
        user = self.env.user
        is_admin = user.has_group('base.group_system')
        for rec in self:
            rec.can_approve = rec.state in APPROVAL_STAGES and (
                user in rec.pending_approver_ids or is_admin)
            rec.can_edit_budget = rec.state == 'budget_control' and (
                user in rec.pending_approver_ids or is_admin
                or user in rec.company_id.er_budget_control_user_ids)

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.depends('odoo_po_id.picking_ids',
                 'odoo_po_id.invoice_ids')
    def _compute_counts(self):
        for rec in self:
            rec.receipt_count = len(rec.odoo_po_id.picking_ids)
            rec.bill_count = len(rec.odoo_po_id.invoice_ids)

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id:
            self.payment_term_id = self.partner_id.property_supplier_payment_term_id
            self.fiscal_position_id = self.fiscal_position_id or \
                self.env['account.fiscal.position']._get_fiscal_position(self.partner_id)
            currency = self.partner_id.property_purchase_currency_id
            if currency:
                self.currency_id = currency

    @api.onchange('agreement_id')
    def _onchange_agreement_id(self):
        agreement = self.agreement_id
        if not agreement:
            return
        vendor_field = pick_field(agreement, 'vendor_id')
        if vendor_field and agreement[vendor_field]:
            self.partner_id = agreement[vendor_field]
        if agreement.currency_id:
            self.currency_id = agreement.currency_id
        for line in self.line_ids:
            agreement_line = agreement.line_ids.filtered(
                lambda a: a.product_id == line.product_id)[:1]
            if agreement_line:
                line.price_unit = agreement_line.price_unit

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    def _is_controller(self):
        user = self.env.user
        return (user.has_group('base.group_system') or user.has_group(GROUP_REQ_MANAGER)
                or user.has_group(GROUP_PURCHASE_MANAGER)
                or user in self.company_id.er_budget_control_user_ids
                or user in self.pending_approver_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'employee.purchase.order') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and self.LOCKED_FIELDS & set(vals):
            for rec in self:
                if rec.state == 'draft':
                    continue
                if rec.state == 'budget_control' and rec._is_controller():
                    continue
                raise UserError(_("%s can only be edited in Draft (or by Budget Control "
                                  "after a budget rejection).", rec.name))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and any(rec.state != 'draft' for rec in self):
            raise UserError(_("Only draft purchase orders can be deleted."))
        return super().unlink()

    def copy_data(self, default=None):
        return super().copy_data(dict(default or {}, name='New'))

    @api.model
    def _prepare_line_from_request_line(self, line, qty, seller=None):
        product = line.product_id
        taxes = product.supplier_taxes_id.filtered(
            lambda t: t.company_id == line.company_id)
        price, discount = product.standard_price, 0.0
        if seller:
            # price / discount set on the product page for this vendor
            price = seller.price
            seller_uom = seller.product_uom_id if 'product_uom_id' in seller._fields else False
            if seller_uom and line.product_uom_id and seller_uom != line.product_uom_id:
                try:
                    price = seller_uom._compute_price(price, line.product_uom_id)
                except Exception:
                    pass
            discount = seller.discount if 'discount' in seller._fields else 0.0
        return {
            'request_line_id': line.id,
            'product_id': product.id,
            'name': line.name or product.display_name,
            'product_uom_id': line.product_uom_id.id,
            'product_uom_qty': qty,
            'price_unit': price,
            'discount': discount,
            'tax_ids': [(6, 0, taxes.ids)],
            'project_id': line.project_id.id,
            'analytic_account_id': line.analytic_account_id.id,
            'warehouse_id': line.warehouse_id.id,
        }

    # ------------------------------------------------------------------
    # Approval helpers
    # ------------------------------------------------------------------
    def _stage_label(self, state=None):
        return dict(self._fields['state'].selection).get(state or self.state)

    def _get_stage_approvers(self, stage):
        self.ensure_one()
        rec = self.sudo()
        company = rec.company_id
        if stage == 'manager':
            if company.er_purchase_manager_method == 'users':
                return company.er_purchase_manager_user_ids
            users = self.env['res.users']
            dept = rec.employee_id.department_id
            while dept and not users:
                manager_user = dept.manager_id.user_id
                if manager_user and manager_user != rec.user_id:
                    users = manager_user
                dept = dept.parent_id
            return users or company.er_purchase_manager_user_ids
        if stage == 'budget':
            return company.er_purchase_budget_user_ids
        if stage == 'budget_control':
            return company.er_budget_control_user_ids
        return self.env['res.users']

    def _log(self, action, comment=False):
        self.ensure_one()
        self.env['employee.purchase.order.approval'].sudo().create({
            'order_id': self.id, 'stage': self.state, 'user_id': self.env.user.id,
            'action': action, 'comment': comment or False})
        labels = {
            'confirm': _("confirmed the purchase order"),
            'approve': _("approved (%s)", self._stage_label()),
            'reject': _("rejected (%s)", self._stage_label()),
            'to_control': _("sent the order to Budget Control"),
            'resubmit': _("resubmitted the order to Budget Approval"),
            'reset': _("reset the order to draft"),
            'cancel': _("cancelled the order"),
        }
        body = "%s %s" % (self.env.user.name, labels[action])
        if comment:
            body += " - %s" % comment
        self.message_post(body=body, subtype_xmlid='mail.mt_note')

    def _enter_state(self, state):
        """Call on a sudo() record."""
        self.ensure_one()
        self.activity_unlink([TODO])
        if state in APPROVAL_STAGES or state == 'budget_control':
            approvers = self._get_stage_approvers(state)
            if not approvers:
                raise UserError(_("No users are configured for '%s'. Ask an administrator "
                                  "to set them in Settings > Employee Requests.",
                                  self._stage_label(state)))
            self.write({'state': state, 'pending_approver_ids': [(6, 0, approvers.ids)]})
            for user in approvers:
                self.activity_schedule(TODO, user_id=user.id,
                                       summary=_("Action required: %s", self.name))
            self.message_post(
                body=_("Waiting for %(stage)s: %(users)s", stage=self._stage_label(state),
                       users=", ".join(approvers.mapped('name'))),
                subtype_xmlid='mail.mt_note')
        else:
            self.write({'state': state, 'pending_approver_ids': [(5,)]})
            if state == 'approved':
                self.message_post(body=_("All approvals completed."),
                                  subtype_xmlid='mail.mt_note')
                if self.company_id.er_auto_odoo_po:
                    self._create_odoo_po()

    def _check_can_approve(self):
        self.ensure_one()
        if self.state not in APPROVAL_STAGES:
            raise UserError(_("This order is not waiting for approval."))
        if not self.can_approve:
            raise AccessError(_("You are not an approver for the current step (%s).",
                                self._stage_label()))

    def _check_ready(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_("Please choose a vendor first."))
        if not self.line_ids:
            raise UserError(_("Please add at least one line."))
        for line in self.line_ids:
            if line.product_uom_qty <= 0:
                raise UserError(_("Quantity must be positive (%s).", line.product_id.display_name))
            if (line.price_unit < 0 and not line._is_discount_line()) \
                    or not 0 <= line.discount <= 100:
                raise UserError(_("Check price and discount on %s.", line.product_id.display_name))
        self._er_check_required()

    def _check_user_rights(self):
        user = self.env.user
        if not (user.has_group(GROUP_PURCHASE_USER) or user.has_group(GROUP_PURCHASE_MANAGER)
                or user.has_group(GROUP_REQ_MANAGER)):
            raise AccessError(_("Only purchase users can do this."))

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_confirm(self):
        for rec in self:
            rec._check_user_rights()
            if rec.state != 'draft':
                raise UserError(_("Only draft orders can be confirmed."))
            rec._check_ready()
            rec._log('confirm')
            rec.sudo()._enter_state('manager')
        return True

    def action_approve(self):
        for rec in self:
            rec._check_can_approve()
            user = self.env.user
            srec = rec.sudo()
            is_override = user not in rec.pending_approver_ids
            rec._log('approve')
            if not is_override:
                srec.write({'pending_approver_ids': [(3, user.id)]})
                srec.activity_feedback([TODO], user_id=user.id)
            if (is_override or not srec.pending_approver_ids
                    or rec.company_id.er_approval_mode == 'any'):
                srec._enter_state(FLOW[FLOW.index(srec.state) + 1])
            else:
                srec.message_post(
                    body=_("Waiting for the remaining approvers: %s",
                           ", ".join(srec.pending_approver_ids.mapped('name'))),
                    subtype_xmlid='mail.mt_note')
        return True

    def action_reject(self):
        self.ensure_one()
        self._check_can_approve()
        return {'type': 'ir.actions.act_window', 'name': _("Reject"),
                'res_model': 'employee.request.reject.wizard', 'view_mode': 'form',
                'target': 'new',
                'context': {'default_res_model': self._name, 'default_res_id': self.id}}

    def _do_reject(self, reason):
        for rec in self:
            rec._check_can_approve()
            budget_stage = rec.state == 'budget'
            rec._log('reject', reason)
            srec = rec.sudo()
            srec.activity_unlink([TODO])
            srec.write({'state': 'budget_rejected' if budget_stage else 'rejected',
                        'pending_approver_ids': [(5,)], 'reject_reason': reason})

    def action_send_budget_control(self):
        for rec in self:
            if rec.state != 'budget_rejected':
                raise UserError(_("Only budget-rejected orders can be sent to Budget Control."))
            rec._check_user_rights()
            rec._log('to_control')
            rec.sudo()._enter_state('budget_control')
        return True

    def action_resubmit_budget(self):
        for rec in self:
            if rec.state != 'budget_control':
                raise UserError(_("This order is not in Budget Control."))
            if not rec.can_edit_budget:
                raise AccessError(_("Only Budget Control users can resubmit."))
            rec._check_ready()
            rec._log('resubmit')
            rec.sudo()._enter_state('budget')  # back to Budget Approval, not to the start
        return True

    def action_reset_draft(self):
        for rec in self:
            if rec.state not in ('rejected', 'cancelled', 'budget_rejected'):
                raise UserError(_("This order cannot be reset to draft."))
            rec._check_user_rights()
            rec._log('reset')
            rec.sudo().write({'state': 'draft', 'pending_approver_ids': [(5,)],
                              'reject_reason': False})
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state in ('cancelled', 'done', 'invoiced'):
                continue
            if rec.odoo_po_id:
                raise UserError(_("%s already has an Odoo purchase order; cancel that one "
                                  "from Purchase instead.", rec.name))
            if not self.env.su:
                rec._check_user_rights()
            rec._log('cancel')
            srec = rec.sudo()
            srec.activity_unlink([TODO])
            srec.write({'state': 'cancelled', 'pending_approver_ids': [(5,)]})
        self.request_id._refresh_execution_state()
        return True

    # ------------------------------------------------------------------
    # Standard Odoo purchase order
    # ------------------------------------------------------------------
    def action_create_odoo_po(self):
        for rec in self:
            rec._check_user_rights()
            rec.sudo()._create_odoo_po()
        return True

    def _create_odoo_po(self):
        self.ensure_one()
        if self.odoo_po_id:
            return self.odoo_po_id  # never create it twice
        if self.state != 'approved':
            raise UserError(_("The order must be fully approved first."))
        env = self.sudo().env
        PO, POL = env['purchase.order'], env['purchase.order.line']
        uom_f = pick_field(POL, 'product_uom_id', 'product_uom')
        tax_f = pick_field(POL, 'tax_ids', 'taxes_id')
        has_discount = 'discount' in POL._fields
        lines = []
        for line in self.line_ids:
            vals = {
                'product_id': line.product_id.id,
                'name': line.name or line.product_id.display_name,
                'product_qty': line.product_uom_qty,
                uom_f: line.product_uom_id.id,
                tax_f: [(6, 0, line.tax_ids.ids)],
                'date_planned': self.date_order,
                'er_po_line_id': line.id,
            }
            if has_discount:
                vals['price_unit'] = line.price_unit
                vals['discount'] = line.discount
            else:
                vals['price_unit'] = line.price_unit * (1 - line.discount / 100.0)
            if line.analytic_account_id:
                vals['analytic_distribution'] = {str(line.analytic_account_id.id): 100.0}
            lines.append((0, 0, vals))
        po_vals = {
            'partner_id': self.partner_id.id,
            'date_order': self.date_order,
            'currency_id': self.currency_id.id,
            'payment_term_id': self.payment_term_id.id,
            'fiscal_position_id': self.fiscal_position_id.id,
            'incoterm_id': self.incoterm_id.id,
            'origin': self.name,
            'company_id': self.company_id.id,
            'er_epo_id': self.id,
            'order_line': lines,
        }
        note_f = pick_field(PO, 'note', 'notes')  # `notes` was renamed `note` in Odoo 19
        if note_f and self.notes:
            po_vals[note_f] = self.notes
        if self.warehouse_id:
            po_vals['picking_type_id'] = self.warehouse_id.in_type_id.id
        if self.agreement_id and 'requisition_id' in PO._fields:
            po_vals['requisition_id'] = self.agreement_id.id
        po = PO.create(po_vals)
        po.button_confirm()
        for po_line in po.order_line:
            if po_line.er_po_line_id:
                po_line.er_po_line_id.purchase_line_id = po_line.id
        self.write({'odoo_po_id': po.id})
        self.message_post(body=_("Odoo purchase order %s created.", po.name),
                          subtype_xmlid='mail.mt_note')
        if self.company_id.er_auto_bill:
            try:
                po.action_create_invoice()
                self.message_post(body=_("Vendor bill created automatically."),
                                  subtype_xmlid='mail.mt_note')
            except UserError as err:
                self.message_post(body=_("Automatic bill skipped: %s", err.args[0]),
                                  subtype_xmlid='mail.mt_note')
        self.request_id._refresh_execution_state()
        return po

    def action_create_bill(self):
        self.ensure_one()
        if not self.odoo_po_id:
            raise UserError(_("Create the Odoo purchase order first."))
        po = self.odoo_po_id
        try:
            res = po.action_create_invoice()
        except UserError as err:
            raise UserError(_(
                "No bill could be created yet: %s\nBills follow each product's control "
                "policy (on ordered or on received quantities).", err.args[0]))
        self.message_post(body=_("Vendor bill created from %s.", po.name),
                          subtype_xmlid='mail.mt_note')
        self.sudo()._refresh_state()
        return res

    def _notify_received(self):
        """Tell the user who confirmed the order that everything has been received."""
        self.ensure_one()
        self.received_notified = True
        confirmed = self.approval_ids.filtered(lambda a: a.action == 'confirm').sorted('id')
        user = confirmed[-1:].user_id or self.create_uid
        if not user.partner_id:
            return
        self.message_notify(
            partner_ids=user.partner_id.ids,
            author_id=self.env.ref('base.partner_root').id,
            subject=_("Purchase order %s received", self.name),
            body=_("The purchase order <a href=\"#\" data-oe-model=\"employee.purchase.order\" "
                   "data-oe-id=\"%(id)s\">%(name)s</a> that you confirmed has been received.",
                   id=self.id, name=self.name),
            subtype_xmlid='mail.mt_note')

    def _refresh_state(self):
        """Open -> Closed (everything received) -> Invoiced (a vendor bill was made)."""
        for rec in self.sudo().filtered(
                lambda r: r.state in ('approved', 'done', 'invoiced') and r.odoo_po_id):
            goods = rec.line_ids.filtered(lambda l: not l._is_discount_line())
            fully = goods and all(
                l.received_qty >= l.product_uom_qty - 1e-6 for l in goods)
            if fully and not rec.received_notified:
                rec._notify_received()
            has_bill = bool(rec.odoo_po_id.invoice_ids.filtered(lambda m: m.state != 'cancel'))
            if has_bill:
                new_state = 'invoiced'
            elif fully:
                new_state = 'done'
            else:
                new_state = 'approved'
            if new_state != rec.state:
                rec.write({'state': new_state})
                rec.message_post(body=_("Order is now: %s", rec._stage_label(new_state)),
                                 subtype_xmlid='mail.mt_note')

    # ------------------------------------------------------------------
    # Email / smart buttons
    # ------------------------------------------------------------------
    def action_print_rfq(self):
        self.ensure_one()
        return self.env.ref('mo_employee_request.report_employee_purchase_order').report_action(self)

    def action_send_email(self):
        self.ensure_one()
        template = self.env.ref('mo_employee_request.mail_template_employee_po')
        return {
            'type': 'ir.actions.act_window', 'res_model': 'mail.compose.message',
            'views': [(False, 'form')], 'target': 'new',
            'context': {'default_model': self._name, 'default_res_ids': self.ids,
                        'default_template_id': template.id,
                        'default_composition_mode': 'comment', 'force_email': True},
        }

    def _open(self, model, domain, name):
        return {'type': 'ir.actions.act_window', 'name': name, 'res_model': model,
                'view_mode': 'list,form', 'domain': domain}

    def action_view_odoo_po(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'purchase.order',
                'view_mode': 'form', 'res_id': self.odoo_po_id.id}

    def action_view_receipts(self):
        self.ensure_one()
        return self._open('stock.picking', [('id', 'in', self.odoo_po_id.picking_ids.ids)],
                          _("Receipts"))

    def action_view_bills(self):
        self.ensure_one()
        return self._open('account.move', [('id', 'in', self.odoo_po_id.invoice_ids.ids)],
                          _("Vendor Bills"))

    def action_view_request(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'employee.request',
                'view_mode': 'form', 'res_id': self.request_id.id}

    def action_view_agreement(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'purchase.requisition',
                'view_mode': 'form', 'res_id': self.agreement_id.id}


class EmployeePurchaseOrderLine(models.Model):
    _name = 'employee.purchase.order.line'
    _description = 'Employee Purchase Order Line'
    _order = 'sequence, id'

    order_id = fields.Many2one('employee.purchase.order', required=True,
                               ondelete='cascade', index=True)
    request_line_id = fields.Many2one('employee.request.line', string='Source Request Line',
                                      ondelete='set null', index=True, copy=False)
    sequence = fields.Integer(default=10)
    currency_id = fields.Many2one(related='order_id.currency_id', store=True)
    partner_id = fields.Many2one(related='order_id.partner_id', store=True, string='Vendor')
    employee_id = fields.Many2one(related='order_id.employee_id', store=True)
    request_id = fields.Many2one(related='order_id.request_id', store=True)
    date_order = fields.Datetime(related='order_id.date_order', store=True)
    order_state = fields.Selection(related='order_id.state', store=True, string='Order Status')
    product_id = fields.Many2one('product.product', string='Product', required=True,
                                 domain="[('purchase_ok', '=', True)]")
    name = fields.Text(string='Description', compute='_compute_name', store=True,
                       readonly=False)
    product_uom_qty = fields.Float(string='Quantity', default=1.0, digits='Product Unit',
                                   required=True)
    product_uom_id = fields.Many2one('uom.uom', string='UoM', compute='_compute_uom',
                                     store=True, readonly=False, required=True)
    price_unit = fields.Float(string='Unit Price', digits='Product Price')
    discount = fields.Float(string='Discount %', digits='Discount')
    tax_ids = fields.Many2many('account.tax', 'employee_po_line_tax_rel', 'line_id', 'tax_id',
                               string='Taxes', domain="[('type_tax_use', '=', 'purchase')]")
    discount_amount = fields.Monetary(compute='_compute_amount', store=True)
    price_subtotal = fields.Monetary(string='Subtotal', compute='_compute_amount', store=True)
    price_tax = fields.Monetary(compute='_compute_amount', store=True)
    price_total = fields.Monetary(string='Total', compute='_compute_amount', store=True)
    project_id = fields.Many2one('project.project', string='Project')
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account')
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse')
    purchase_line_id = fields.Many2one('purchase.order.line', string='Odoo PO Line',
                                       copy=False, readonly=True)
    received_qty = fields.Float(string='Received', digits='Product Unit',
                                compute='_compute_received_qty', store=True)
    planned_qty = fields.Float(compute='_compute_planned_qty', store=True,
                               digits='Product Unit')

    @api.depends('product_id')
    def _compute_name(self):
        for line in self:
            line.name = line.name or line.product_id.display_name or ''

    @api.depends('product_id')
    def _compute_uom(self):
        for line in self:
            line.product_uom_id = line.product_id.uom_id

    @api.depends('product_uom_qty', 'price_unit', 'discount', 'tax_ids',
                 'order_id.partner_id', 'order_id.currency_id')
    def _compute_amount(self):
        for line in self:
            order = line.order_id
            price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
            gross = line.price_unit * line.product_uom_qty
            taxes = line.tax_ids.compute_all(
                price, order.currency_id, line.product_uom_qty,
                product=line.product_id, partner=order.partner_id)
            line.discount_amount = gross - price * line.product_uom_qty
            line.price_subtotal = taxes['total_excluded']
            line.price_total = taxes['total_included']
            line.price_tax = taxes['total_included'] - taxes['total_excluded']

    def _is_discount_line(self):
        """True for the negative lines added by the Discount button."""
        self.ensure_one()
        product = self.order_id.company_id.sudo().er_discount_product_id
        return bool(product) and self.product_id == product

    @api.depends('purchase_line_id.qty_received')
    def _compute_received_qty(self):
        for line in self:
            line.received_qty = line.purchase_line_id.qty_received if line.purchase_line_id else 0.0

    @api.depends('product_uom_qty', 'order_id.state')
    def _compute_planned_qty(self):
        for line in self:
            line.planned_qty = 0.0 if line.order_id.state in ('cancelled', 'rejected') \
                else line.product_uom_qty

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id and not self.price_unit:
            self.price_unit = self.product_id.standard_price
            self.tax_ids = self.product_id.supplier_taxes_id.filtered(
                lambda t: t.company_id == self.order_id.company_id)

    @api.constrains('discount')
    def _check_discount(self):
        for line in self:
            if not 0 <= line.discount <= 100:
                raise ValidationError(_("Discount must be between 0 and 100."))

    # Editable in draft, or by Budget Control after a budget rejection
    def _check_editable(self):
        if self.env.su:
            return
        for line in self:
            order = line.order_id
            if order.state == 'draft' or (order.state == 'budget_control'
                                          and order._is_controller()):
                continue
            raise UserError(_("Lines of %s cannot be changed in its current state.", order.name))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            orders = self.env['employee.purchase.order'].browse(
                {v['order_id'] for v in vals_list if v.get('order_id')})
            for order in orders:
                if order.state != 'draft' and not (
                        order.state == 'budget_control' and order._is_controller()):
                    raise UserError(_("Lines cannot be added to %s now.", order.name))
        return super().create(vals_list)

    def write(self, vals):
        self._check_editable()
        return super().write(vals)

    def unlink(self):
        self._check_editable()
        return super().unlink()
