# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class IntercompanyPayment(models.Model):
    _name = 'intercompany.payment'
    _description = 'Intercompany Payment Distribution'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(
        string='Operation No.',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Partner',
        required=True,
        tracking=True,
    )
    payment_type = fields.Selection([
        ('inbound', 'Receive (Inbound)'),
        ('outbound', 'Send (Outbound)'),
    ], string='Payment Type', required=True, default='inbound')

    # journal_id removed from header - each line has its own journal per company
    payment_date = fields.Date(
        string='Payment Date',
        required=True,
        default=fields.Date.today,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
        ('to_approve', 'To Approve'),
        ('approved', 'Approved'),
        ('posted', 'Posted'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    line_ids = fields.One2many(
        'intercompany.payment.line',
        'payment_id',
        string='Payment Lines',
    )
    payment_ids = fields.One2many(
        'account.payment',
        'intercompany_payment_id',
        string='Payments',
    )
    amount_total = fields.Monetary(
        string='Total',
        compute='_compute_total',
        currency_field='currency_id',
        store=True,
    )
    payment_count = fields.Integer(compute='_compute_payment_count')

    submitted_by = fields.Many2one(
        'res.users',
        string='Submitted By',
        readonly=True,
        copy=False,
        help='User who submitted this distribution for approval.',
    )
    reject_reason = fields.Text(
        string='Rejection Reason',
        readonly=True,
        copy=False,
    )

    # ── APPROVAL NOTIFICATIONS ──────────────────────────────────────────────

    def _get_manager_users(self):
        return self.env['res.users'].search([
            ('groups_id', 'in', self.env.ref('intercompany_operation_modified.group_intercompany_manager').id),
        ])

    def _notify_managers_for_approval(self):
        for rec in self:
            managers = rec._get_manager_users()
            if not managers:
                continue
            rec.message_post(
                body=_('%s submitted this payment distribution for approval.') % (rec.env.user.name),
                partner_ids=managers.mapped('partner_id').ids,
            )
            activity_type = rec.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
            for manager in managers:
                rec.activity_schedule(
                    activity_type_id=activity_type.id if activity_type else False,
                    summary=_('Approval Required'),
                    note=_('%s is waiting for your approval.') % rec.display_name,
                    user_id=manager.id,
                )

    def _notify_submitter(self, message):
        for rec in self:
            if rec.submitted_by:
                rec.message_post(body=message, partner_ids=rec.submitted_by.partner_id.ids)
                rec.activity_feedback(['mail.mail_activity_data_todo'], user_id=self.env.user.id)

    def action_open_reject_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject with Reason'),
            'res_model': 'intercompany.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_res_model': 'intercompany.payment',
                'default_res_id': self.id,
            },
        }

    def _do_refuse(self, reason):
        """Manager-only: reject the distribution back to draft, with a reason."""
        self.ensure_one()
        if self.state not in ('to_approve', 'approved'):
            raise UserError(_('Only submitted or approved distributions can be rejected.'))
        self.reject_reason = reason
        self.state = 'draft'
        self.message_post(body=_('Rejected by %s: %s') % (self.env.user.name, reason))
        self._notify_submitter(_('Your payment distribution %s was rejected.\nReason: %s') % (self.display_name, reason))

    @api.model
    def _cron_remind_pending_approvals(self):
        """Daily reminder: re-notify managers about distributions still
        waiting for approval (state = to_approve)."""
        pending = self.search([('state', '=', 'to_approve')])
        for rec in pending:
            managers = rec._get_manager_users()
            if not managers:
                continue
            rec.message_post(
                body=_('Reminder: this payment distribution has been waiting for approval since %s.')
                % (rec.write_date.strftime('%Y-%m-%d') if rec.write_date else ''),
                partner_ids=managers.mapped('partner_id').ids,
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('intercompany.payment') or _('New')
        return super().create(vals_list)

    @api.depends('line_ids.amount')
    def _compute_total(self):
        for rec in self:
            rec.amount_total = sum(rec.line_ids.mapped('amount'))

    def _compute_payment_count(self):
        for rec in self:
            rec.payment_count = len(rec.payment_ids)

    def action_submit(self):
        """Submit payment distribution for manager approval"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only draft distributions can be submitted for approval.'))
        self.submitted_by = self.env.user
        self.reject_reason = False
        self.state = 'to_approve'
        self._notify_managers_for_approval()

    def action_approve(self):
        """Approve the payment distribution before posting"""
        self.ensure_one()
        if self.state != 'to_approve':
            raise UserError(_('Only submitted distributions can be approved. Please submit it first.'))
        self.state = 'approved'
        self._notify_submitter(_('Your payment distribution %s was approved.') % self.display_name)

    def action_refuse(self):
        """Manager-only: opens the reject wizard to capture a reason."""
        return self.action_open_reject_wizard()

    def action_post_payment(self):
        """Create one payment per company line, and reconcile against any
        selected open invoices for that company/partner."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Please add payment lines first.'))

        Payment = self.env['account.payment']
        for line in self.line_ids:
            # Find a valid bank/cash journal for each company
            journal = line.journal_id if line.journal_id else self.env['account.journal'].search([
                ('type', 'in', ['bank', 'cash']),
                ('company_id', '=', line.company_id.id),
            ], limit=1)
            if not journal:
                raise UserError(_('No bank/cash journal found for company: %s') % line.company_id.name)

            partner_type = 'customer' if self.payment_type == 'inbound' else 'supplier'

            payment = Payment.with_company(line.company_id).create({
                'partner_id': self.partner_id.id,
                'partner_type': partner_type,
                'amount': line.amount,
                'payment_type': self.payment_type,
                'journal_id': journal.id,
                'date': self.payment_date,
                'currency_id': self.currency_id.id,
                'intercompany_payment_id': self.id,
                'company_id': line.company_id.id,
                'memo': self.name,
            })
            payment.action_post()

            # ── Reconcile against the selected open invoices, if any ──────
            if line.invoice_ids:
                # NOTE: Odoo 17+ uses account_type values like
                # 'asset_receivable' / 'liability_payable' (NOT the old
                # 'receivable' / 'payable' strings) — using the wrong value
                # made the filter always return an empty recordset, so
                # reconcile() was silently never being called.
                account_type = 'asset_receivable' if partner_type == 'customer' else 'liability_payable'
                reconciled_invoices = []
                try:
                    for inv in line.invoice_ids:
                        # Re-fetch fresh, not-yet-fully-reconciled lines on
                        # every iteration: after a partial reconciliation
                        # the payment's open balance shrinks, so a stale
                        # snapshot from before the loop would be wrong.
                        payment_lines = payment.move_id.line_ids.filtered(
                            lambda l: not l.reconciled and l.account_id.account_type == account_type
                        )
                        if not payment_lines:
                            break  # payment fully allocated already
                        inv_lines = inv.line_ids.filtered(
                            lambda l: not l.reconciled and l.account_id.account_type == account_type
                        )
                        to_reconcile = payment_lines + inv_lines
                        if to_reconcile:
                            to_reconcile.reconcile()
                            reconciled_invoices.append(inv.name)
                    if reconciled_invoices:
                        self.message_post(
                            body=_('Payment %s was reconciled with: %s')
                            % (payment.name, ', '.join(reconciled_invoices))
                        )
                except Exception as e:
                    self.message_post(
                        body=_('Could not auto-reconcile payment %s with the selected invoice(s): %s')
                        % (payment.name, str(e))
                    )

        self.state = 'posted'

    def action_reset_to_draft(self):
        """Reset to draft: move all linked account.payments back to draft"""
        self.ensure_one()
        for payment in self.payment_ids.filtered(lambda p: p.state != 'draft'):
            try:
                payment.action_draft()
            except Exception as e:
                raise UserError(_('Could not reset payment %s to draft:\n%s') % (payment.name, str(e)))
        self.state = 'draft'

    def action_cancel(self):
        """Cancel: reset payments to draft first, then cancel them"""
        self.ensure_one()
        if self.state == 'to_approve':
            self.state = 'cancelled'
            return
        for payment in self.payment_ids:
            try:
                if payment.state == 'posted':
                    payment.action_draft()
                if payment.state == 'draft':
                    payment.action_cancel()
            except Exception as e:
                raise UserError(_('Could not cancel payment %s:\n%s') % (payment.name, str(e)))
        self.state = 'cancelled'

    def action_view_payments(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Payments'),
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': [('intercompany_payment_id', '=', self.id)],
        }


class IntercompanyPaymentLine(models.Model):
    _name = 'intercompany.payment.line'
    _description = 'Intercompany Payment Line'

    payment_id = fields.Many2one(
        'intercompany.payment',
        string='Payment',
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
    )
    journal_id = fields.Many2one(
        'account.journal',
        string='Journal',
        domain="[('type', 'in', ['bank', 'cash']), ('company_id', '=', company_id)]",
        help="Leave empty to use the first available bank/cash journal for this company",
    )
    amount = fields.Monetary(
        string='Amount',
        currency_field='currency_id',
    )
    move_type_filter = fields.Selection([
        ('out_invoice', 'Customer Invoice'),
        ('in_invoice', 'Vendor Bill'),
    ], string='Invoice Type', compute='_compute_move_type_filter', store=True)
    invoice_ids = fields.Many2many(
        'account.move',
        string='Invoices to Reconcile',
        help='Optional: select open invoices/bills for this company & partner. '
             'On posting, the payment will be automatically reconciled against them. '
             'The oldest open invoice is pre-selected automatically when you pick a company; '
             'you can change it.',
        domain="[('company_id', '=', company_id), ('partner_id', '=', parent.partner_id),"
               " ('state', '=', 'posted'), ('payment_state', 'in', ['not_paid', 'partial']),"
               " ('move_type', '=', move_type_filter)]",
    )
    percentage = fields.Float(
        string='Percentage (%)',
        compute='_compute_percentage',
        store=True,
    )
    currency_id = fields.Many2one(
        related='payment_id.currency_id',
        string='Currency',
    )

    # Related fields used by the Payments Report (manager only)
    partner_id = fields.Many2one(
        related='payment_id.partner_id', string='Partner', store=True)
    payment_type = fields.Selection(
        related='payment_id.payment_type', string='Direction', store=True)
    state = fields.Selection(
        related='payment_id.state', string='Status', store=True)
    payment_date = fields.Date(
        related='payment_id.payment_date', string='Payment Date', store=True)

    @api.depends('payment_id.payment_type')
    def _compute_move_type_filter(self):
        # Receiving money (inbound) → we are owed by the partner → look at
        #   the Sales invoices we issued to them (out_invoice).
        # Sending money (outbound) → we owe the partner → look at the
        #   Purchase bills they issued to us (in_invoice).
        for rec in self:
            rec.move_type_filter = (
                'out_invoice' if rec.payment_id.payment_type == 'inbound' else 'in_invoice'
            )

    @api.onchange('company_id', 'payment_id')
    def _onchange_company_auto_select_invoice(self):
        """Automatically pre-select the oldest open invoice/bill for this
        company & partner (user can still change or clear it manually)."""
        for rec in self:
            if rec.invoice_ids:
                continue  # don't override a manual choice
            if not rec.company_id or not rec.payment_id or not rec.payment_id.partner_id:
                continue
            move_type = 'out_invoice' if rec.payment_id.payment_type == 'inbound' else 'in_invoice'
            oldest_invoice = rec.env['account.move'].search([
                ('company_id', '=', rec.company_id.id),
                ('partner_id', '=', rec.payment_id.partner_id.id),
                ('state', '=', 'posted'),
                ('payment_state', 'in', ['not_paid', 'partial']),
                ('move_type', '=', move_type),
            ], order='invoice_date_due asc, invoice_date asc, id asc', limit=1)
            if oldest_invoice:
                rec.invoice_ids = [(6, 0, [oldest_invoice.id])]

    @api.depends('amount', 'payment_id.amount_total')
    def _compute_percentage(self):
        for rec in self:
            total = rec.payment_id.amount_total
            rec.percentage = (rec.amount / total * 100) if total else 0.0
