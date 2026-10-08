# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    er_department_method = fields.Selection(
        related='company_id.er_department_method', readonly=False)
    er_department_user_ids = fields.Many2many(
        related='company_id.er_department_user_ids', readonly=False)
    er_warehouse_user_ids = fields.Many2many(
        related='company_id.er_warehouse_user_ids', readonly=False)
    er_budget_user_ids = fields.Many2many(
        related='company_id.er_budget_user_ids', readonly=False)
    er_approval_mode = fields.Selection(
        related='company_id.er_approval_mode', readonly=False)
    er_auto_stock_order = fields.Boolean(
        related='company_id.er_auto_stock_order', readonly=False)
    er_auto_purchase_order = fields.Boolean(
        related='company_id.er_auto_purchase_order', readonly=False)
    er_auto_odoo_po = fields.Boolean(
        related='company_id.er_auto_odoo_po', readonly=False)
    er_auto_bill = fields.Boolean(
        related='company_id.er_auto_bill', readonly=False)

    er_inspection_enabled = fields.Boolean(
        related='company_id.er_inspection_enabled', readonly=False)
    er_inspection_mode = fields.Selection(
        related='company_id.er_inspection_mode', readonly=False)
    er_inspection_user_ids = fields.Many2many(
        related='company_id.er_inspection_user_ids', readonly=False)

    er_purchase_manager_method = fields.Selection(
        related='company_id.er_purchase_manager_method', readonly=False)
    er_purchase_manager_user_ids = fields.Many2many(
        related='company_id.er_purchase_manager_user_ids', readonly=False)
    er_purchase_budget_user_ids = fields.Many2many(
        related='company_id.er_purchase_budget_user_ids', readonly=False)
    er_budget_control_user_ids = fields.Many2many(
        related='company_id.er_budget_control_user_ids', readonly=False)
