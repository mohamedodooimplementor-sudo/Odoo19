# -*- coding: utf-8 -*-
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

INSPECTION_SUMMARY = 'Receipt inspection approval'


class StockMove(models.Model):
    _name = 'stock.move'
    _inherit = ['stock.move', 'analytic.mixin']

    er_request_line_id = fields.Many2one(
        'employee.request.line', string='Employee Request Line',
        index=True, copy=False, ondelete='set null')
    # stored shortcuts used by the Stock Consumption report
    er_request_id = fields.Many2one(related='er_request_line_id.request_id', store=True,
                                    string='Employee Request')
    er_employee_id = fields.Many2one(related='er_request_line_id.employee_id', store=True,
                                     string='Employee')
    er_department_id = fields.Many2one(related='er_request_line_id.department_id', store=True,
                                       string='Department')
    er_warehouse_id = fields.Many2one(related='er_request_line_id.warehouse_id', store=True,
                                      string='Request Warehouse')
    er_project_id = fields.Many2one(related='er_request_line_id.project_id', store=True,
                                    string='Project')
    # --- Analytic distribution (same widget / logic as sales and purchases) ----------------
    # `analytic_distribution` comes from analytic.mixin. Value: the one chosen on the transfer
    # header, otherwise the analytic account of the employee request line. Editable per line.
    # When the transfer is validated, Odoo (stock_account) books it as analytic lines.
    er_analytic_id = fields.Many2one(
        'account.analytic.account', string='Analytic Account',
        compute='_compute_er_analytic', store=True)

    @api.depends('picking_id.analytic_distribution', 'er_request_line_id.analytic_account_id')
    def _compute_analytic_distribution(self):
        for move in self:
            distribution = move.picking_id.analytic_distribution
            if not distribution:
                account = move.er_request_line_id.analytic_account_id
                distribution = {str(account.id): 100.0} if account else False
            # nothing to inherit: keep whatever was chosen on the line
            move.analytic_distribution = distribution or move.analytic_distribution

    @api.depends('analytic_distribution')
    def _compute_er_analytic(self):
        # first account of the distribution: used for the reports (group by analytic account)
        for move in self:
            key = next(iter(move.analytic_distribution or {}), False)
            ids = [int(i) for i in key.split(',') if i.isdigit()] if key else []
            move.er_analytic_id = ids[0] if ids else False

    def _get_analytic_distribution(self):
        # hook of stock_account: used to create the analytic lines of the move
        res = super()._get_analytic_distribution()
        return self.analytic_distribution or res

    def _get_account_move_line_vals(self):
        # Put the analytic distribution on the journal entry of the move, on the line of the
        # location account (expense / consumption), not on the product's stock valuation line.
        vals_list = super()._get_account_move_line_vals()
        distribution = self._get_analytic_distribution()
        if distribution:
            stock_account = self.product_id._get_product_accounts()['stock_valuation']
            for vals in vals_list:
                if vals.get('account_id') != stock_account.id:
                    vals['analytic_distribution'] = distribution
        return vals_list

    def _create_analytic_move(self):
        # When the distribution is already on the journal entry, posting it creates the analytic
        # lines: do not create (or keep the estimated) ones from the stock move as well.
        booked = self.filtered(lambda m: m.account_move_id and m._get_analytic_distribution())
        booked.sudo().analytic_account_line_ids.unlink()
        return super(StockMove, self - booked)._create_analytic_move()


class StockPicking(models.Model):
    _name = 'stock.picking'
    _inherit = ['stock.picking', 'analytic.mixin']

    er_request_id = fields.Many2one(
        'employee.request', string='Employee Request', index=True, copy=False,
        ondelete='set null')

    # `analytic_distribution` (analytic.mixin) on the header: taken from the request, applied
    # to every line when changed (each line can still be changed).
    @api.depends('er_request_id.analytic_account_id')
    def _compute_analytic_distribution(self):
        for picking in self:
            account = picking.er_request_id.analytic_account_id
            picking.analytic_distribution = (
                {str(account.id): 100.0} if account else picking.analytic_distribution)

    @api.onchange('analytic_distribution')
    def _onchange_er_analytic_distribution(self):
        if self.analytic_distribution:
            for move in self.move_ids:
                move.analytic_distribution = self.analytic_distribution

    # --- Receipt inspection approval -----------------------------------------
    er_needs_inspection = fields.Boolean(
        string='Needs Inspection', compute='_compute_er_needs_inspection', store=True)
    er_inspection_state = fields.Selection(
        [('pending', 'Waiting Inspection'), ('approved', 'Inspection Approved'),
         ('rejected', 'Inspection Rejected')],
        string='Inspection', default='pending', copy=False, tracking=True)
    er_inspector_ids = fields.Many2many(
        'res.users', 'er_picking_inspector_rel', 'picking_id', 'user_id',
        string='Inspection Approvers', copy=False)
    er_inspected_by = fields.Many2one('res.users', string='Inspected By', copy=False,
                                      readonly=True)
    er_inspection_date = fields.Datetime(string='Inspection Date', copy=False, readonly=True)
    er_can_inspect = fields.Boolean(compute='_compute_er_can_inspect')

    @api.depends('picking_type_code', 'company_id', 'company_id.er_inspection_enabled',
                 'move_ids.purchase_line_id')
    def _compute_er_needs_inspection(self):
        for picking in self:
            picking.er_needs_inspection = bool(
                picking.picking_type_code == 'incoming'
                and picking.company_id.sudo().er_inspection_enabled
                and picking.sudo().move_ids.purchase_line_id.er_po_line_id)

    @api.depends_context('uid')
    @api.depends('er_needs_inspection', 'er_inspection_state', 'er_inspector_ids')
    def _compute_er_can_inspect(self):
        for picking in self:
            picking.er_can_inspect = bool(
                picking.er_needs_inspection and picking.er_inspection_state == 'pending'
                and picking._er_user_is_inspector())

    def _er_user_is_inspector(self):
        self.ensure_one()
        user = self.env.user
        inspectors = self.sudo().er_inspector_ids or self._er_get_inspectors()
        return user in inspectors or user.has_group('base.group_system')

    def _er_get_requests(self):
        return self.sudo().move_ids.purchase_line_id.er_po_line_id.order_id.request_id

    def _er_get_inspectors(self):
        """The employee who made the request (its user), or the users chosen in the settings.

        Always taken from the REQUEST, never from the purchase order.
        """
        self.ensure_one()
        company = self.company_id.sudo()
        users = self.env['res.users']
        if company.er_inspection_mode == 'requester':
            for request in self._er_get_requests():
                users |= request.user_id
        return users or company.er_inspection_user_ids

    def _er_close_inspection_activities(self, feedback=None):
        for picking in self.sudo():
            picking._er_get_requests().activity_ids.filtered(
                lambda a: a.summary == INSPECTION_SUMMARY and picking.name in (a.note or '')
            )._action_done(feedback=feedback)

    def action_confirm(self):
        res = super().action_confirm()
        for picking in self.sudo().filtered(
                lambda p: p.er_needs_inspection and not p.er_inspector_ids
                and p.er_inspection_state == 'pending'):
            inspectors = picking._er_get_inspectors()
            picking.er_inspector_ids = [Command.set(inspectors.ids)]
            for request in picking._er_get_requests():
                for user in inspectors:
                    request.activity_schedule(
                        'mail.mail_activity_data_todo', user_id=user.id,
                        summary=INSPECTION_SUMMARY,
                        note=_("Receipt %s is waiting for your inspection approval.",
                               picking.name))
            picking.message_post(
                body=_("Inspection approval required from: %s",
                       ", ".join(inspectors.mapped('name')) or _("(no approver configured)")),
                subtype_xmlid='mail.mt_note')
        return res

    def _er_check_inspector(self):
        for picking in self.sudo():
            if not picking._er_user_is_inspector():
                raise UserError(_("You are not allowed to approve the inspection of %s.",
                                  picking.name))

    def _er_pending_for_user(self):
        return self.sudo().filtered(
            lambda p: p.er_needs_inspection and p.er_inspection_state == 'pending'
            and p._er_user_is_inspector())

    def action_er_inspection_approve(self):
        self._er_check_inspector()
        for picking in self.sudo():
            picking.write({'er_inspection_state': 'approved',
                           'er_inspected_by': self.env.user.id,
                           'er_inspection_date': fields.Datetime.now()})
            picking._er_close_inspection_activities(feedback=_("Inspection approved"))
            picking.message_post(body=_("Inspection approved by %s.", self.env.user.name),
                                 subtype_xmlid='mail.mt_note')
        return True

    def action_er_inspection_reject(self):
        self._er_check_inspector()
        for picking in self.sudo():
            picking.write({'er_inspection_state': 'rejected',
                           'er_inspected_by': self.env.user.id,
                           'er_inspection_date': fields.Datetime.now()})
            picking._er_close_inspection_activities(feedback=_("Inspection rejected"))
            picking.message_post(body=_("Inspection rejected by %s.", self.env.user.name),
                                 subtype_xmlid='mail.mt_note')
        return True

    def action_er_inspection_reset(self):
        """Ask for a new inspection (e.g. after a rejection was fixed)."""
        for picking in self.sudo().filtered(lambda p: p.er_inspection_state == 'rejected'):
            picking.er_inspection_state = 'pending'
            for request in picking._er_get_requests():
                for user in picking.er_inspector_ids:
                    request.activity_schedule(
                        'mail.mail_activity_data_todo', user_id=user.id,
                        summary=INSPECTION_SUMMARY,
                        note=_("Receipt %s is waiting for your inspection approval.",
                               picking.name))
        return True

    def _er_check_inspection(self):
        for picking in self.sudo():
            if (picking.er_needs_inspection and picking.picking_type_code == 'incoming'
                    and picking.state not in ('done', 'cancel')
                    and picking.er_inspection_state != 'approved'):
                raise UserError(_(
                    "Receipt %s needs an inspection approval before it can be validated.",
                    picking.name))

    def button_validate(self):
        self._er_check_inspection()
        return super().button_validate()

    @api.model_create_multi
    def create(self, vals_list):
        pickings = super().create(vals_list)
        for picking in pickings.filtered('backorder_id'):
            inspectors = picking.backorder_id.sudo().er_inspector_ids
            if inspectors:
                picking.sudo().er_inspector_ids = [Command.set(inspectors.ids)]
        return pickings

    def _er_refresh_requests(self):
        requests = self.env['employee.request']
        epos = self.env['employee.purchase.order']
        for picking in self.sudo():
            requests |= picking.er_request_id
            requests |= picking.move_ids.er_request_line_id.request_id
            po_lines = picking.move_ids.purchase_line_id
            if po_lines:
                po_ep_lines = po_lines.er_po_line_id
                requests |= po_ep_lines.order_id.request_id
                epos |= po_ep_lines.order_id
        epos._refresh_state()
        requests._refresh_execution_state()

    def _action_done(self):
        self._er_check_inspection()
        res = super()._action_done()
        self._er_refresh_requests()
        return res

    def action_cancel(self):
        res = super().action_cancel()
        self._er_refresh_requests()
        return res
