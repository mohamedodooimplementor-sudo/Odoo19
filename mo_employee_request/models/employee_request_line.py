# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

GROUP_MANAGER = 'mo_employee_request.group_employee_request_manager'


class EmployeeRequestLine(models.Model):
    _name = 'employee.request.line'
    _description = 'Employee Request Line'
    _order = 'sequence, id'

    def _default_warehouse(self):
        return self.env['stock.warehouse'].search(
            [('company_id', '=', self.env.company.id)], limit=1)

    request_id = fields.Many2one('employee.request', string='Request',
                                 required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='request_id.company_id', store=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        domain="[('type', '=', 'consu')]")
    product_category_id = fields.Many2one(
        'product.category', string='Product Category',
        related='product_id.categ_id', store=True)
    name = fields.Text(string='Description', compute='_compute_name',
                       store=True, readonly=False)
    product_uom_id = fields.Many2one(
        'uom.uom', string='UoM', compute='_compute_uom', store=True,
        readonly=False, required=True)
    product_uom_qty = fields.Float(string='Requested Quantity', default=1.0,
                                   digits='Product Unit', required=True)
    warehouse_id = fields.Many2one(
        'stock.warehouse', string='Warehouse', required=True,
        default=_default_warehouse)
    project_id = fields.Many2one('project.project', string='Project',
                                 compute='_compute_project', store=True,
                                 readonly=False)
    analytic_account_id = fields.Many2one(
        'account.analytic.account', string='Analytic Account',
        compute='_compute_analytic', store=True, readonly=False)

    # Stock availability for the line's warehouse (expressed in the line UoM)
    onhand_qty = fields.Float(string='On Hand', compute='_compute_stock_info',
                              digits='Product Unit')
    reserved_qty = fields.Float(string='Reserved', compute='_compute_stock_info',
                                digits='Product Unit')
    available_qty = fields.Float(string='Available', compute='_compute_stock_info',
                                 digits='Product Unit')
    incoming_qty = fields.Float(string='Incoming', compute='_compute_stock_info',
                                digits='Product Unit')
    outgoing_qty = fields.Float(string='Outgoing', compute='_compute_stock_info',
                                digits='Product Unit')
    forecast_qty = fields.Float(string='Forecast', compute='_compute_stock_info',
                                digits='Product Unit')
    stock_status = fields.Selection([
        ('available', '🟢 Available'),
        ('partial', '🟠 Partially Available'),
        ('unavailable', '🔴 Not Available'),
    ], string='Stock Status', compute='_compute_stock_info')
    issue_qty = fields.Float(string='Issue Quantity', compute='_compute_stock_info',
                             digits='Product Unit')
    purchase_qty = fields.Float(string='Purchase Quantity',
                                compute='_compute_stock_info', digits='Product Unit')

    # ------------------------------------------------------------------
    @api.depends('product_id')
    def _compute_name(self):
        for line in self:
            line.name = line.product_id.display_name or ''

    @api.depends('product_id')
    def _compute_uom(self):
        for line in self:
            line.product_uom_id = line.product_id.uom_id

    @api.depends('request_id.project_id')
    def _compute_project(self):
        for line in self:
            line.project_id = line.project_id or line.request_id.project_id

    @api.depends('request_id.analytic_account_id', 'project_id.account_id')
    def _compute_analytic(self):
        for line in self:
            # the line's project account first, then the request's account
            line.analytic_account_id = (
                line.project_id.account_id or line.analytic_account_id
                or line.request_id.analytic_account_id)

    @api.depends('product_id', 'warehouse_id', 'product_uom_id', 'product_uom_qty')
    def _compute_stock_info(self):
        for line in self:
            vals = dict.fromkeys(
                ('onhand_qty', 'reserved_qty', 'available_qty', 'incoming_qty',
                 'outgoing_qty', 'forecast_qty', 'issue_qty', 'purchase_qty'), 0.0)
            status = False
            product, warehouse = line.product_id, line.warehouse_id
            if product and warehouse:
                prod = product.sudo().with_context(warehouse_id=warehouse.id)
                onhand = prod.qty_available
                free = prod.free_qty
                vals.update(
                    onhand_qty=line._to_line_uom(onhand),
                    reserved_qty=line._to_line_uom(onhand - free),
                    available_qty=line._to_line_uom(free),
                    incoming_qty=line._to_line_uom(prod.incoming_qty),
                    outgoing_qty=line._to_line_uom(prod.outgoing_qty),
                    forecast_qty=line._to_line_uom(prod.virtual_available),
                )
                available = max(vals['available_qty'], 0.0)
                issue = min(line.product_uom_qty, available)
                vals['issue_qty'] = issue
                vals['purchase_qty'] = line.product_uom_qty - issue
                if available >= line.product_uom_qty and line.product_uom_qty > 0:
                    status = 'available'
                elif available > 0:
                    status = 'partial'
                else:
                    status = 'unavailable'
            vals['stock_status'] = status
            line.update(vals)

    def _to_line_uom(self, qty):
        """Convert a quantity from the product UoM to the line UoM."""
        self.ensure_one()
        product_uom = self.product_id.uom_id
        if not self.product_uom_id or self.product_uom_id == product_uom:
            return qty
        try:
            return product_uom._compute_quantity(qty, self.product_uom_id, round=False)
        except UserError:
            return qty

    @api.constrains('product_uom_qty')
    def _check_qty(self):
        for line in self:
            if line.product_uom_qty <= 0:
                raise ValidationError(_("Requested quantity must be greater than zero."))

    # ------------------------------------------------------------------
    # Lines are only editable while the request is a draft
    # ------------------------------------------------------------------
    def _is_locked_for_user(self):
        return not (self.env.su or self.env.user.has_group(GROUP_MANAGER))

    @api.model_create_multi
    def create(self, vals_list):
        if self._is_locked_for_user():
            req_ids = {v['request_id'] for v in vals_list if v.get('request_id')}
            if any(r.state != 'draft' for r in self.env['employee.request'].browse(req_ids)):
                raise UserError(_("Lines can only be added while the request is a draft."))
        return super().create(vals_list)

    def write(self, vals):
        if self._is_locked_for_user() and any(
                line.request_id.state != 'draft' for line in self):
            raise UserError(_("Lines can only be edited while the request is a draft."))
        return super().write(vals)

    def unlink(self):
        if self._is_locked_for_user() and any(
                line.request_id.state != 'draft' for line in self):
            raise UserError(_("Lines can only be removed while the request is a draft."))
        return super().unlink()
