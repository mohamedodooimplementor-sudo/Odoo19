# -*- coding: utf-8 -*-
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from .utils import convert_uom, pick_field

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
    er_location_id = fields.Many2one(related='er_request_line_id.location_id', store=True,
                                     string='Request Location')
    # Project of the move: the request line's project, else the purchase order line's project
    # (receipts), else the one chosen on the transfer header. Kept editable on draft transfers.
    er_project_id = fields.Many2one(
        'project.project', string='Project', index=True,
        compute='_compute_er_project', store=True, readonly=False)

    @api.depends('er_request_line_id.project_id',
                 'purchase_line_id.er_po_line_id.project_id',
                 'purchase_line_id.er_po_line_id.order_id.project_id',
                 'picking_id.er_project_id')
    def _compute_er_project(self):
        for move in self:
            po_line = move.sudo().purchase_line_id.er_po_line_id
            move.er_project_id = (
                move.er_request_line_id.project_id
                or po_line.project_id
                or po_line.order_id.project_id
                or move.picking_id.er_project_id
                or move.er_project_id)
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

    # --- Project stock lock ---------------------------------------------------
    @api.model
    def _er_project_locked_qty(self, product, location, exclude_project=None):
        """{project_id: quantity} still held for each project in this location (children included).

        Held = received for the project (receipt of a project purchase order)
               - already issued to that project.  Expressed in the product UoM.
        """
        product, location = product.sudo(), location.sudo()
        if not (product and location):
            return {}
        view = location
        base = [('product_id', '=', product.id), ('state', '=', 'done'),
                ('er_project_id', '!=', False)]
        if exclude_project:
            base.append(('er_project_id', '!=', exclude_project.id))
        Move = self.sudo()
        received = Move.search(base + [
            ('picking_type_id.code', '=', 'incoming'),
            ('location_dest_id', 'child_of', view.id)])
        issued = Move.search(base + [
            ('picking_type_id.code', '=', 'outgoing'),
            ('location_id', 'child_of', view.id)])
        held = {}
        alloc_domain = [('state', '=', 'confirmed'), ('product_id', '=', product.id),
                        ('location_id', 'child_of', location.id)]
        if exclude_project:
            alloc_domain.append(('project_id', '!=', exclude_project.id))
        for alloc in self.env['er.project.allocation'].sudo().search(alloc_domain):
            sign = -1.0 if alloc.kind == 'release' else 1.0
            held[alloc.project_id.id] = held.get(alloc.project_id.id, 0.0) + sign * alloc.qty
        for sign, moves in ((1, received), (-1, issued)):
            for move in moves:
                uom = move[pick_field(move, 'product_uom', 'product_uom_id')]
                qty = convert_uom(move.quantity, uom, product.uom_id)
                held[move.er_project_id.id] = held.get(move.er_project_id.id, 0.0) + sign * qty
        return {pid: qty for pid, qty in held.items() if qty > 1e-6}

    def _er_lock_scope(self):
        """Moves of an outgoing transfer the project lock applies to."""
        return self.filtered(
            lambda m: m.picking_id and m.picking_id.picking_type_code == 'outgoing'
            and m.state not in ('done', 'cancel')
            and m.picking_id.picking_type_id.warehouse_id
            and m.picking_id.company_id.sudo().er_project_lock_enabled)

    @api.model
    def _er_lock_check(self, product, project, location, wanted):
        """None when `wanted` (product UoM) can be issued to `project` without touching stock
        held for other projects, else (product, project, wanted, free, holder_ids, locked)."""
        others = self._er_project_locked_qty(product, location, exclude_project=project)
        locked = sum(others.values())
        if not locked:
            return None
        onhand = product.sudo().with_context(location=location.id).qty_available
        free = max(onhand - locked, 0.0)
        if wanted - free > 1e-6:
            return (product, project, wanted, free, set(others), locked)
        return None

    def _er_project_lock_excess(self):
        """[(product, project, wanted, free, holder_ids, locked)] for the moves asking more
        than what is free once the stock held by other projects is left alone."""
        res = []
        groups = {}
        for move in self._er_lock_scope():
            key = (move.product_id, move.er_project_id, move.location_id)
            groups[key] = groups.get(key, 0.0) + convert_uom(
                move.product_uom_qty, move[pick_field(move, 'product_uom', 'product_uom_id')],
                move.product_id.uom_id)
        for (product, project, location), wanted in groups.items():
            found = self._er_lock_check(product, project, location, wanted)
            if found:
                res.append(found)
        return res

    @api.model
    def _er_lock_alert(self, found):
        """Text of one excess: what is taken from whom, and whether the owners need a PO."""
        product, project, wanted, free, holder_ids, locked = found
        holders = self.env['project.project'].sudo().browse(holder_ids)
        taken = wanted - free
        keep = max(locked - taken, 0.0)
        return _(
            "%(product)s: %(wanted)s requested for %(project)s but only %(free)s is free. "
            "%(taken)s would be taken from stock held for %(holders)s, which would keep only "
            "%(keep)s: a purchase order may be needed for them.",
            product=product.display_name, wanted=wanted,
            project=project.display_name or _("(no project)"), free=free, taken=taken,
            holders=", ".join(holders.mapped('display_name')), keep=keep)

    def _action_assign(self, *args, **kwargs):
        # stock held for another project must not be reserved before it is approved
        blocked = self.filtered(
            lambda m: m.picking_id.er_lock_state != 'approved' and m._er_project_lock_excess())
        return super(StockMove, self - blocked)._action_assign(*args, **kwargs)

    def write(self, vals):
        if 'er_project_id' in vals and not self.env.su and any(
                m.state == 'done' and m.er_project_id.id != vals['er_project_id']
                for m in self):
            raise UserError(_("The project of a validated stock move cannot be changed: "
                              "it would change the stock held for the projects."))
        res = super().write(vals)
        if {'product_id', 'product_uom_qty', 'er_project_id'} & set(vals):
            # the approval was given for other quantities / another project
            self.picking_id.filtered(
                lambda p: p.er_lock_state in ('approved', 'rejected')
                and p.state not in ('done', 'cancel')).sudo().write(
                {'er_lock_state': 'none', 'er_lock_approved_by': False})
        return res

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

    # Project: from the request (stock order) or from the purchase order (receipt). A request
    # with several projects gives one stock order per project, so it is a single value here.
    er_project_id = fields.Many2one(
        'project.project', string='Project', index=True, tracking=True,
        compute='_compute_er_project', store=True, readonly=False)

    @api.depends('er_request_id.project_id', 'move_ids.er_request_line_id.project_id',
                 'move_ids.purchase_line_id.er_po_line_id.project_id',
                 'move_ids.purchase_line_id.er_po_line_id.order_id.project_id')
    def _compute_er_project(self):
        for picking in self.sudo():
            moves = picking.move_ids
            projects = moves.er_request_line_id.project_id
            for po_line in moves.purchase_line_id.er_po_line_id:
                projects |= po_line.project_id or po_line.order_id.project_id
            if not projects and picking.er_request_id:
                projects = picking.er_request_id.project_id
            if len(projects) == 1:
                picking.er_project_id = projects
            elif not projects:
                picking.er_project_id = picking.er_project_id  # keep the manual choice
            else:
                picking.er_project_id = False  # several projects: shown per line

    @api.onchange('er_project_id')
    def _onchange_er_project_id(self):
        for move in self.move_ids:
            move.er_project_id = self.er_project_id

    # --- Project stock lock (approval to issue stock held for another project) ----------
    er_lock_state = fields.Selection(
        [('none', 'No Approval'), ('pending', 'Waiting Project Approval'),
         ('approved', 'Project Issue Approved'), ('rejected', 'Project Issue Rejected')],
        string='Project Lock', default='none', copy=False, tracking=True)
    er_lock_approved_by = fields.Many2one('res.users', string='Project Lock Approved By',
                                          copy=False, readonly=True)
    er_lock_message = fields.Text(compute='_compute_er_lock', string='Project Lock Details')
    er_has_lock_excess = fields.Boolean(compute='_compute_er_lock')
    er_can_approve_lock = fields.Boolean(compute='_compute_er_can_approve_lock')
    er_lock_approver_ids = fields.Many2many(
        'res.users', 'er_picking_lock_approver_rel', 'picking_id', 'user_id',
        string='Project Lock Approvers', copy=False)

    @api.depends('move_ids.product_id', 'move_ids.product_uom_qty', 'move_ids.er_project_id',
                 'move_ids.state', 'state', 'er_lock_state')
    def _compute_er_lock(self):
        for picking in self:
            lines = []
            if picking.state not in ('done', 'cancel') and picking.id:
                for found in picking.move_ids._er_project_lock_excess():
                    lines.append(self.env['stock.move']._er_lock_alert(found))
            picking.er_has_lock_excess = bool(lines)
            picking.er_lock_message = "\n".join(lines)

    @api.depends_context('uid')
    @api.depends('er_lock_state', 'er_lock_approver_ids')
    def _compute_er_can_approve_lock(self):
        for picking in self:
            picking.er_can_approve_lock = bool(
                picking.er_lock_state == 'pending' and picking._er_user_is_lock_approver())

    def _er_user_is_lock_approver(self):
        """Approvers chosen when the approval was asked (manager of the project that holds
        the stock), the users of the settings, or an administrator."""
        self.ensure_one()
        user = self.env.user
        return (user in self.sudo().er_lock_approver_ids
                or user.has_group('mo_employee_request.group_project_lock_approver')
                or user.has_group('base.group_system'))

    def _er_get_lock_approvers(self):
        """Project manager of every project that holds the stock; the users of the settings
        when the company prefers them or when a project has no manager."""
        self.ensure_one()
        company = self.company_id.sudo()
        users = self.env['res.users']
        if company.er_project_lock_mode == 'project_manager':
            holder_ids = set()
            for found in self.sudo().move_ids._er_project_lock_excess():
                holder_ids |= found[4]
            users = self.env['project.project'].sudo().browse(holder_ids).user_id
        return users or company.er_project_lock_user_ids

    def _er_lock_log(self, action, reason=False):
        Log = self.env['er.project.lock.log'].sudo()
        for picking in self.sudo():
            Log.create({
                'picking_id': picking.id,
                'project_id': picking.er_project_id.id,
                'action': action,
                'details': picking.er_lock_message,
                'reason': reason,
                'user_id': self.env.user.id,
                'company_id': picking.company_id.id,
            })

    def _er_lock_wizard(self, action):
        self.ensure_one()
        vals = {'picking_id': self.id, 'action': action}
        if action == 'reject':
            vals['line_ids'] = [(0, 0, {'move_id': move.id, 'reject_qty': qty})
                                for move, qty in self._er_lock_reject_defaults()]
        wizard = self.env['er.project.lock.reason'].create(vals)
        return {
            'type': 'ir.actions.act_window', 'res_model': 'er.project.lock.reason',
            'res_id': wizard.id, 'view_mode': 'form', 'target': 'new',
            'name': _("Request Project Approval") if action == 'request'
            else _("Reject Project Issue"),
        }

    def _er_lock_reject_defaults(self):
        """[(move, quantity)]: the part of each move that would take stock held for other
        projects (move UoM), which is what the project owners are asked to refuse."""
        self.ensure_one()
        res = {}
        for product, project, wanted, free, _holders, _locked in \
                self.move_ids._er_project_lock_excess():
            taken = wanted - free
            moves = self.move_ids._er_lock_scope().filtered(
                lambda m: m.product_id == product and m.er_project_id == project)
            for move in moves.sorted('id', reverse=True):
                move_uom = move[pick_field(move, 'product_uom', 'product_uom_id')]
                demand = convert_uom(move.product_uom_qty, move_uom, product.uom_id)
                part = min(demand, taken)
                if part > 0:
                    res[move] = convert_uom(part, product.uom_id, move_uom)
                    taken -= part
        return list(res.items())

    def action_er_lock_request(self):
        # a reason is mandatory: asked in a small wizard
        self.ensure_one()
        return self._er_lock_wizard('request')

    def action_er_lock_reject(self):
        self.ensure_one()
        self._er_check_lock_approver()
        return self._er_lock_wizard('reject')

    def _er_lock_do_request(self, reason):
        for picking in self.sudo().filtered(lambda p: p.er_has_lock_excess):
            approvers = picking._er_get_lock_approvers()
            picking.write({'er_lock_state': 'pending',
                           'er_lock_approver_ids': [Command.set(approvers.ids)]})
            for user in approvers:
                picking.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=user.id,
                    summary=_("Project stock approval"),
                    note=_("%s issues stock that is held for other projects.", picking.name))
            details = (picking.er_lock_message or '').replace("\n", "<br/>")
            if approvers:
                picking.message_notify(
                    partner_ids=approvers.partner_id.ids,
                    subject=_("Project stock approval: %s", picking.name),
                    body=_("%(user)s asks to issue stock held for your project(s):<br/>"
                           "%(d)s<br/><b>Reason:</b> %(r)s",
                           user=self.env.user.name, d=details, r=reason),
                    subtype_xmlid='mail.mt_note')
            picking.message_post(
                body=_("Approval requested from %(who)s:<br/>%(d)s<br/><b>Reason:</b> %(r)s",
                       who=", ".join(approvers.mapped('name')) or _("(no approver configured)"),
                       d=details, r=reason),
                subtype_xmlid='mail.mt_note')
            picking._er_lock_log('request', reason)
        return True

    def _er_check_lock_approver(self):
        for picking in self:
            if not picking._er_user_is_lock_approver():
                raise UserError(_("You are not allowed to approve issuing project stock."))

    def action_er_lock_approve(self):
        self._er_check_lock_approver()
        for picking in self.sudo():
            picking._er_lock_log('approve')
            picking.write({'er_lock_state': 'approved',
                           'er_lock_approved_by': self.env.user.id})
            picking.activity_ids.filtered(
                lambda a: a.summary == _("Project stock approval"))._action_done(
                feedback=_("Approved"))
            picking.message_post(
                body=_("Issuing stock of other projects approved by %s.", self.env.user.name),
                subtype_xmlid='mail.mt_note')
            picking.move_ids.filtered(lambda m: m.state == 'confirmed')._action_assign()
        return True

    def _er_lock_do_reject(self, reason, rejects=None):
        """Refuse part of the stock held for other projects: `rejects` = {move: quantity}.
        The quantity leaves the transfer and is purchased for the request automatically."""
        rejects = rejects or {}
        for picking in self.sudo():
            lines = []
            for move, qty in rejects.items():
                move = move.sudo()
                if move.picking_id != picking or qty <= 0:
                    continue
                lines.append("%s: %s" % (move.product_id.display_name, qty))
                if qty >= move.product_uom_qty - 1e-6:
                    move._action_cancel()
                else:
                    move.product_uom_qty -= qty
            picking._er_lock_log('reject', reason)
            picking.write({'er_lock_state': 'rejected',
                           'er_lock_approved_by': self.env.user.id})
            picking.activity_ids.filtered(
                lambda a: a.summary == _("Project stock approval"))._action_done(
                feedback=_("Rejected"))
            picking.message_post(
                body=_("Issuing stock of other projects rejected by %(u)s.<br/>%(q)s"
                       "<b>Reason:</b> %(r)s", u=self.env.user.name, r=reason,
                       q=("<b>Rejected:</b> %s<br/>" % ", ".join(lines)) if lines else ""),
                subtype_xmlid='mail.mt_note')
            # what stays can be issued (nothing of it touches the held stock any more)
            picking.move_ids.filtered(lambda m: m.state == 'confirmed')._action_assign()
            # the rejected quantity is purchased for the request
            if lines and picking.er_request_id:
                picking.er_request_id._create_purchase_orders()
        return True

    def _er_check_project_lock(self):
        for picking in self.sudo():
            if (picking.state in ('done', 'cancel') or picking.er_lock_state == 'approved'
                    or not picking.move_ids._er_project_lock_excess()):
                continue
            raise UserError(_(
                "%(name)s issues stock that is held for other projects. Ask for the project "
                "approval first.\n\n%(details)s",
                name=picking.name, details=picking.er_lock_message))

    # `analytic_distribution` (analytic.mixin) on the header: taken from the project / request,
    # applied to every line when changed (each line can still be changed).
    @api.depends('er_request_id.analytic_account_id', 'er_project_id.account_id',
                 'move_ids.purchase_line_id.analytic_distribution')
    def _compute_analytic_distribution(self):
        for picking in self:
            account = (picking.er_project_id.account_id
                       or picking.er_request_id.analytic_account_id)
            if account:
                picking.analytic_distribution = {str(account.id): 100.0}
                continue
            # receipt of a purchase order: when every PO line has the same distribution,
            # show it on the header too (otherwise keep what is there)
            dists = [d for d in picking.sudo().move_ids.purchase_line_id.mapped(
                'analytic_distribution') if d]
            if dists and all(d == dists[0] for d in dists):
                picking.analytic_distribution = dists[0]

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
        self._er_check_project_lock()
        return super().button_validate()

    def write(self, vals):
        if 'er_project_id' in vals and not self.env.su and any(
                p.state == 'done' and p.er_project_id.id != vals['er_project_id']
                for p in self):
            raise UserError(_("The project of a validated transfer cannot be changed."))
        return super().write(vals)

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
        self._er_check_project_lock()
        res = super()._action_done()
        self._er_refresh_requests()
        return res

    def action_cancel(self):
        res = super().action_cancel()
        self._er_refresh_requests()
        return res
