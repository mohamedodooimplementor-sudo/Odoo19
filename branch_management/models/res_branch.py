# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResBranch(models.Model):
    _name = 'res.branch'
    _description = 'Branch'
    _order = 'name'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Branch Name', required=True, tracking=True)
    code = fields.Char(
        string='Branch Code', required=True, tracking=True, copy=False,
        default='New',
        help='Filled in automatically when the branch is created. '
             'You can still edit it afterwards if needed.')
    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company, tracking=True)

    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Warehouse',
        domain="[('company_id', '=', company_id), "
               "'|', ('branch_id', '=', False), ('branch_id', '=', id)]",
        tracking=True)
    sale_journal_id = fields.Many2one(
        'account.journal', string='Sales Journal',
        domain="[('type', '=', 'sale'), ('company_id', '=', company_id), "
               "'|', ('branch_id', '=', False), ('branch_id', '=', id)]",
        tracking=True)
    purchase_journal_id = fields.Many2one(
        'account.journal', string='Purchase Journal',
        domain="[('type', '=', 'purchase'), ('company_id', '=', company_id), "
               "'|', ('branch_id', '=', False), ('branch_id', '=', id)]",
        tracking=True)
    payment_journal_ids = fields.Many2many(
        'account.journal', 'res_branch_payment_journal_rel',
        'branch_id', 'journal_id', string='Payment Journals',
        domain="[('type', 'in', ('cash', 'bank')), ('company_id', '=', company_id), "
               "'|', ('branch_id', '=', False), ('branch_id', '=', id)]",
        help='Cash/Bank Journals this branch can register payments with. '
             'Only unassigned Journals, or Journals already assigned to '
             "this same branch (see the Journal's own Branch field), can "
             'be picked here.')
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Analytic Account',
        domain="[('company_id', 'in', (company_id, False))]", tracking=True)

    manager_id = fields.Many2one('res.users', string='Branch Manager', tracking=True)
    phone = fields.Char(string='Phone')
    email = fields.Char(string='Email')
    image_1920 = fields.Image(string='Image', max_width=1920, max_height=1920)

    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')

    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', string='Currency', readonly=True)
    no_credit_limit = fields.Boolean(
        string='Unlimited Credit', tracking=True,
        help='If checked, this branch has no credit limit: the Credit '
             'Limit field is hidden and the credit limit check is never '
             'triggered for this branch.')
    credit_limit = fields.Monetary(
        string='Credit Limit', currency_field='currency_id', tracking=True,
        help='Maximum total outstanding (unpaid) customer invoices allowed '
             'for this branch. Leave at 0 to disable the check.')
    branch_exposure = fields.Monetary(
        string='Current Exposure', currency_field='currency_id',
        compute='_compute_branch_exposure',
        help='Sum of residual amounts of posted, unpaid customer invoices '
             'linked to this branch.')

    def _compute_branch_exposure(self):
        for branch in self:
            moves = self.env['account.move'].search([
                ('branch_id', '=', branch.id),
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('payment_state', 'not in', ('paid', 'reversed')),
            ])
            branch.branch_exposure = sum(moves.mapped('amount_residual'))

    user_ids = fields.Many2many(
        'res.users', 'res_branch_res_users_rel', 'branch_id', 'user_id',
        string='Allowed Users',
        domain="[('company_ids', 'in', company_id)]")

    _sql_constraints = [
        ('code_company_uniq', 'unique(code, company_id)',
         'Branch Code must be unique per Company.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code') or vals.get('code') == 'New':
                vals['code'] = self.env['ir.sequence'].next_by_code(
                    'res.branch.code') or 'New'
        branches = super().create(vals_list)
        warehouses = branches.mapped('warehouse_id')
        if warehouses:
            # See write() below for why this is needed.
            warehouses.invalidate_recordset(['branch_id'])
        return branches

    def write(self, vals):
        old_warehouses = self.mapped('warehouse_id')
        res = super().write(vals)
        if 'warehouse_id' in vals:
            # stock.warehouse.branch_id is a stored computed field with no
            # @api.depends (it's a reverse-lookup search on this very
            # 'warehouse_id' field, which Odoo can't express as a normal
            # dependency). That means it is only computed once and is not
            # automatically refreshed when the link is changed from THIS
            # side (the Branch's Warehouse field) rather than from the
            # Warehouse's own Branch field. Without this, a warehouse can
            # keep showing a stale/previous Branch, which would then feed
            # a wrong default branch onto any picking created against it.
            (old_warehouses | self.mapped('warehouse_id')).invalidate_recordset(['branch_id'])
        return res

    @api.constrains('warehouse_id', 'company_id')
    def _check_warehouse_company(self):
        for branch in self:
            if branch.warehouse_id and branch.warehouse_id.company_id != branch.company_id:
                raise ValidationError(
                    "The Warehouse of branch '%s' must belong to the same Company." % branch.name)

    @api.depends('name', 'code')
    def _compute_display_name(self):
        for branch in self:
            branch.display_name = '[%s] %s' % (branch.code, branch.name) if branch.code else branch.name

    def _search(self, domain, offset=0, limit=None, order=None, **kwargs):
        """Scoped bypass of the row-level "Allowed Branches" restriction.

        Only active when the 'branch_selection_unrestricted' context key is
        set (done by the Inter-Branch Transfer action/views only), so a
        user can pick ANY branch as the Destination Branch of a transfer,
        without opening up branch visibility anywhere else in the system.
        """
        if self.env.context.get('branch_selection_unrestricted'):
            return super(ResBranch, self.sudo())._search(
                domain, offset=offset, limit=limit, order=order, **kwargs)
        return super()._search(domain, offset=offset, limit=limit, order=order, **kwargs)
