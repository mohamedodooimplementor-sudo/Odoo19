# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

GROUP_MANAGER = 'mo_employee_request.group_employee_request_manager'
GROUP_USER = 'mo_employee_request.group_employee_request_user'
GROUP_ON_BEHALF = 'mo_employee_request.group_request_on_behalf'
APPROVAL_STATES = ['department', 'warehouse', 'budget']
FLOW = ['draft', 'department', 'warehouse', 'budget', 'approved']
TODO = 'mail.mail_activity_data_todo'


class EmployeeRequest(models.Model):
    _name = 'employee.request'
    _description = 'Employee Request'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'er.required.mixin']
    _order = 'id desc'

    # Fields that only a manager may touch once the request left Draft
    LOCKED_FIELDS = {'employee_id', 'project_id', 'analytic_account_id',
                     'request_date', 'line_ids'}

    def _default_employee(self):
        return self.env.user.employee_id

    name = fields.Char(string='Request Number', default='New', copy=False,
                       readonly=True, index=True)
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.company)
    employee_id = fields.Many2one(
        'hr.employee', string='Employee', required=True, tracking=True,
        default=_default_employee)
    user_id = fields.Many2one('res.users', string='User',
                              related='employee_id.user_id', store=True)
    department_id = fields.Many2one(
        'hr.department', string='Department', compute='_compute_department',
        store=True, tracking=True)
    project_id = fields.Many2one('project.project', string='Project', tracking=True)
    # taken from the project's analytic account when it has one (can still be changed)
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Analytic Account', tracking=True,
        compute='_compute_analytic_account', store=True, readonly=False)
    request_date = fields.Date(string='Request Date', default=fields.Date.context_today,
                               required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('department', 'Department Approval'),
        ('warehouse', 'Warehouse Approval'),
        ('budget', 'Budget Approval'),
        ('approved', 'Approved'),
        ('processing', 'Processing'),
        ('partial', 'Partially Done'),
        ('closed', 'Closed'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, copy=False,
        tracking=True, index=True, group_expand=True)
    line_ids = fields.One2many('employee.request.line', 'request_id',
                               string='Request Lines', copy=True)
    approval_ids = fields.One2many('employee.request.approval', 'request_id',
                                   string='Approval History')
    pending_approver_ids = fields.Many2many(
        'res.users', 'employee_request_pending_user_rel', 'request_id', 'user_id',
        string='Waiting Approval From', copy=False)
    approval_round = fields.Integer(copy=False, default=0)
    can_approve = fields.Boolean(compute='_compute_can_approve')
    note = fields.Html(string='Notes')
    reject_reason = fields.Text(string='Rejection Reason', copy=False, readonly=True)
    line_count = fields.Integer(compute='_compute_line_count')

    # ------------------------------------------------------------------
    # Computes / constraints
    # ------------------------------------------------------------------
    @api.depends('employee_id')
    def _compute_department(self):
        for rec in self:
            rec.department_id = rec.employee_id.department_id

    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.depends('state', 'pending_approver_ids')
    @api.depends_context('uid')
    def _compute_can_approve(self):
        user = self.env.user
        is_admin = user.has_group('base.group_system')
        for rec in self:
            rec.can_approve = rec.state in APPROVAL_STATES and (
                user in rec.pending_approver_ids or is_admin)

    @api.depends('project_id.account_id')
    def _compute_analytic_account(self):
        for rec in self:
            rec.analytic_account_id = rec.project_id.account_id or rec.analytic_account_id

    @api.constrains('employee_id')
    def _check_employee_permission(self):
        # Only users with "Create Requests for Employees" may use another employee.
        if self.env.su or self.env.user.has_group(GROUP_ON_BEHALF):
            return
        for rec in self:
            if rec.employee_id.user_id != self.env.user:
                raise ValidationError(
                    _("You can only create requests for your own employee record."))

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'employee.request') or 'New'
        return super().create(vals_list)

    def write(self, vals):
        if (not self.env.su and self.LOCKED_FIELDS & set(vals)
                and not self.env.user.has_group(GROUP_MANAGER)):
            if any(rec.state != 'draft' for rec in self):
                raise UserError(_("Only draft requests can be modified."))
        return super().write(vals)

    def unlink(self):
        if not self.env.su and any(rec.state != 'draft' for rec in self):
            raise UserError(_("Only draft requests can be deleted. "
                              "Cancel the request instead to keep its history."))
        return super().unlink()

    def copy_data(self, default=None):
        default = dict(default or {}, name='New')
        return super().copy_data(default)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _stage_label(self, state=None):
        state = state or self.state
        return dict(self._fields['state'].selection).get(state, state)

    def _check_owner_or_manager(self):
        self.ensure_one()
        user = self.env.user
        if not (self.user_id == user or self.create_uid == user
                or user.has_group(GROUP_MANAGER)):
            raise AccessError(_("Only the requester or a request manager can do this."))

    def _check_can_approve(self):
        self.ensure_one()
        if self.state not in APPROVAL_STATES:
            raise UserError(_("This request is not waiting for approval."))
        if not self.can_approve:
            raise AccessError(_("You are not an approver for the current step (%s).",
                                self._stage_label()))

    def _check_lines(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Please add at least one request line."))
        for line in self.line_ids:
            if not line.product_id or not line.warehouse_id:
                raise UserError(_("Every line needs a product and a warehouse."))
            if line.product_uom_qty <= 0:
                raise UserError(_("Requested quantity must be positive (%s).",
                                  line.product_id.display_name))

    def _get_stage_approvers(self, stage):
        """Return the res.users that must approve `stage` (sudo, no rights needed)."""
        self.ensure_one()
        rec = self.sudo()
        company = rec.company_id
        if stage == 'department':
            if company.er_department_method == 'users':
                return company.er_department_user_ids
            users = self.env['res.users']
            requester = rec.user_id
            dept = rec.department_id
            while dept and not users:
                manager_user = dept.manager_id.user_id
                if manager_user and manager_user != requester:
                    users = manager_user
                dept = dept.parent_id
            if not users:
                # fall back to the employee's own direct manager
                direct = rec.employee_id.parent_id.user_id
                if direct and direct != requester:
                    users = direct
            return users or company.er_department_user_ids
        if stage == 'warehouse':
            return company.er_warehouse_user_ids
        if stage == 'budget':
            return company.er_budget_user_ids
        return self.env['res.users']

    def _log_approval(self, action, comment=False):
        """Create a history line and post it in the chatter."""
        self.ensure_one()
        self.env['employee.request.approval'].sudo().create({
            'request_id': self.id,
            'round': self.approval_round,
            'stage': self.state,
            'user_id': self.env.user.id,
            'action': action,
            'comment': comment or False,
        })
        labels = {
            'submit': _("submitted the request"),
            'approve': _("approved (%s)", self._stage_label()),
            'reject': _("rejected the request (%s)", self._stage_label()),
            'reset': _("reset the request to draft"),
            'cancel': _("cancelled the request"),
        }
        body = "%s %s" % (self.env.user.name, labels[action])
        if comment:
            body += " - %s" % comment
        self.message_post(body=body, subtype_xmlid='mail.mt_note')

    def _enter_state(self, state):
        """Move to `state`. Call on a sudo() record."""
        self.ensure_one()
        self.activity_unlink([TODO])
        if state in APPROVAL_STATES:
            approvers = self._get_stage_approvers(state)
            if not approvers:
                if state == 'department' and self.company_id.er_department_method == 'manager':
                    dept = self.department_id
                    if not dept:
                        reason = _("The employee '%s' has no department.",
                                   self.employee_id.name)
                    elif not dept.manager_id:
                        reason = _("The department '%s' has no manager.", dept.complete_name)
                    elif not dept.manager_id.user_id:
                        reason = _("The manager '%s' of department '%s' is not linked to a "
                                   "user (set the Related User on the employee).",
                                   dept.manager_id.name, dept.complete_name)
                    else:
                        reason = _("The only manager found is the requester himself.")
                    raise UserError(_(
                        "No department approver found. %s\nSet the department manager, or "
                        "configure fallback users in Settings > Employee Requests.", reason))
                raise UserError(_(
                    "No approver is configured for '%s'. Ask an administrator to set "
                    "it in Settings > Employee Requests.", self._stage_label(state)))
            self.write({'state': state, 'pending_approver_ids': [(6, 0, approvers.ids)]})
            for user in approvers:
                self.activity_schedule(
                    TODO, user_id=user.id,
                    summary=_("Approval required: %s", self.name))
            self.message_post(
                body=_("Waiting for %(stage)s from: %(users)s",
                       stage=self._stage_label(state),
                       users=", ".join(approvers.mapped('name'))),
                subtype_xmlid='mail.mt_note')
        else:
            self.write({'state': state, 'pending_approver_ids': [(5,)]})
            if state == 'approved':
                self.message_post(body=_("All approvals completed."),
                                  subtype_xmlid='mail.mt_note')
                self._on_fully_approved()

    def _advance(self):
        self.ensure_one()
        self._enter_state(FLOW[FLOW.index(self.state) + 1])

    def _on_fully_approved(self):
        """Hook for the next phases (automatic Stock / Purchase creation)."""
        return True

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_submit(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_("Only draft requests can be submitted."))
            rec._check_owner_or_manager()
            rec._check_lines()
            rec._er_check_required()
            srec = rec.sudo()
            srec.approval_round += 1
            rec._log_approval('submit')
            srec._enter_state('department')
        return True

    def action_approve(self):
        for rec in self:
            rec._check_can_approve()
            user = self.env.user
            srec = rec.sudo()
            is_override = user not in rec.pending_approver_ids
            rec._log_approval('approve')
            if not is_override:
                srec.write({'pending_approver_ids': [(3, user.id)]})
                srec.activity_feedback([TODO], user_id=user.id)
            if (is_override or not srec.pending_approver_ids
                    or rec.company_id.er_approval_mode == 'any'):
                srec._advance()
            else:
                srec.message_post(
                    body=_("Waiting for the remaining approvers: %s",
                           ", ".join(srec.pending_approver_ids.mapped('name'))),
                    subtype_xmlid='mail.mt_note')
        return True

    def action_reject(self):
        self.ensure_one()
        self._check_can_approve()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Reject Request"),
            'res_model': 'employee.request.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_res_model': self._name, 'default_res_id': self.id},
        }

    def _do_reject(self, reason):
        for rec in self:
            rec._check_can_approve()
            rec._log_approval('reject', reason)
            srec = rec.sudo()
            srec.activity_unlink([TODO])
            srec.write({'state': 'rejected', 'pending_approver_ids': [(5,)],
                        'reject_reason': reason})

    def action_reset_draft(self):
        for rec in self:
            is_manager = self.env.user.has_group(GROUP_MANAGER)
            if rec.state in ('rejected', 'cancelled'):
                rec._check_owner_or_manager()
            elif rec.state in APPROVAL_STATES or rec.state == 'approved':
                if not is_manager:
                    raise AccessError(_("Only a request manager can reset a request "
                                        "that is already in the approval flow."))
            else:
                raise UserError(_("This request cannot be reset to draft."))
            rec._log_approval('reset')
            srec = rec.sudo()
            srec.activity_unlink([TODO])
            srec.write({'state': 'draft', 'pending_approver_ids': [(5,)],
                        'reject_reason': False})
        return True

    def _check_cancellable(self):
        """Hook: next phases block cancelling when documents were already executed."""
        self.ensure_one()

    def action_cancel(self):
        for rec in self:
            if rec.state in ('closed', 'rejected', 'cancelled'):
                raise UserError(_("This request cannot be cancelled."))
            rec._check_owner_or_manager()
            rec._check_cancellable()
            rec._log_approval('cancel')
            srec = rec.sudo()
            srec.activity_unlink([TODO])
            srec.write({'state': 'cancelled', 'pending_approver_ids': [(5,)]})
        return True
