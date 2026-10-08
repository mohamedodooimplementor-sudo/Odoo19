# -*- coding: utf-8 -*-
from odoo import Command, api, fields, models

# settings user list -> group that gives the menus / access rights those users need
ER_COMPANY_GROUPS = {
    'er_warehouse_user_ids': 'mo_employee_request.group_warehouse_approver',
    'er_budget_user_ids': 'mo_employee_request.group_budget_approver',
    'er_budget_control_user_ids': 'mo_employee_request.group_budget_control',
}


class ResCompany(models.Model):
    _inherit = 'res.company'

    # --- Request approval -------------------------------------------------
    er_department_method = fields.Selection(
        [('manager', 'Department Manager'), ('users', 'Specific Users')],
        string='Department Approval Method', default='manager')
    er_department_user_ids = fields.Many2many(
        'res.users', 'er_company_department_user_rel', 'company_id', 'user_id',
        string='Department Approval Users')
    er_warehouse_user_ids = fields.Many2many(
        'res.users', 'er_company_warehouse_user_rel', 'company_id', 'user_id',
        string='Warehouse Approval Users')
    er_budget_user_ids = fields.Many2many(
        'res.users', 'er_company_budget_user_rel', 'company_id', 'user_id',
        string='Budget Approval Users')
    er_approval_mode = fields.Selection(
        [('any', 'Any Approver'), ('all', 'All Approvers')],
        string='Approval Mode', default='any', required=True)

    # --- Automation (used by the next phases) -------------------------------
    er_auto_stock_order = fields.Boolean(string='Automatically Create Stock Transfers')
    er_auto_purchase_order = fields.Boolean(string='Automatically Create Purchase Orders')
    er_auto_odoo_po = fields.Boolean(string='Automatically Create Odoo Purchase Orders')
    er_auto_bill = fields.Boolean(string='Automatically Create Bills')
    er_discount_product_id = fields.Many2one(
        'product.product', string='Purchase Discount Product', copy=False,
        help="Service product used on the discount lines added by the Discount button of "
             "purchase orders. Created automatically the first time it is needed.")

    # --- Receipt inspection approval -------------------------------------------
    er_inspection_enabled = fields.Boolean(string='Receipt Inspection Approval')
    er_inspection_mode = fields.Selection(
        [('requester', 'Requester of the Request'), ('users', 'Specific Users')],
        string='Inspection Approver', default='requester', required=True)
    er_inspection_user_ids = fields.Many2many(
        'res.users', 'er_company_inspection_user_rel', 'company_id', 'user_id',
        string='Inspection Approval Users')

    # --- Purchase approval ---------------------------------------------------
    er_purchase_manager_method = fields.Selection(
        [('manager', 'Direct Manager'), ('users', 'Specific Users')],
        string='Purchase Manager Approval', default='manager')
    er_purchase_manager_user_ids = fields.Many2many(
        'res.users', 'er_company_purchase_manager_rel', 'company_id', 'user_id',
        string='Purchase Manager Users')
    er_purchase_budget_user_ids = fields.Many2many(
        'res.users', 'er_company_purchase_budget_rel', 'company_id', 'user_id',
        string='Purchase Budget Approval Users')
    er_budget_control_user_ids = fields.Many2many(
        'res.users', 'er_company_budget_control_rel', 'company_id', 'user_id',
        string='Budget Control Users')

    # ------------------------------------------------------------------
    # Keep the module groups in sync with the users chosen in the settings,
    # so approvers no longer need to be ticked on the user form.
    # ------------------------------------------------------------------
    def _er_sync_groups(self, fnames, old):
        for fname in fnames:
            group = self.env.ref(ER_COMPANY_GROUPS[fname], raise_if_not_found=False)
            if not group:
                continue
            new = self.mapped(fname)
            added = new - old[fname]
            removed = old[fname] - new
            if removed:
                # keep the group when the user is still chosen in another company
                still = self.sudo().search([]).mapped(fname)
                removed -= still
            if added:
                added.sudo().write({'group_ids': [Command.link(group.id)]})
            if removed:
                removed.sudo().write({'group_ids': [Command.unlink(group.id)]})

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        empty = {f: self.env['res.users'] for f in ER_COMPANY_GROUPS}
        for company in companies:
            company._er_sync_groups(
                [f for f in ER_COMPANY_GROUPS if company[f]], empty)
        return companies

    def write(self, vals):
        fnames = [f for f in ER_COMPANY_GROUPS if f in vals]
        old = {f: self.mapped(f) for f in fnames}
        res = super().write(vals)
        if fnames:
            self._er_sync_groups(fnames, old)
        return res
