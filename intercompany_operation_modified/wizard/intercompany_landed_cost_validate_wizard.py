# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IntercompanyLandedCostValidateWizard(models.TransientModel):
    """Wizard to assign transfers to each landed cost and validate them."""
    _name = 'intercompany.landed.cost.validate.wizard'
    _description = 'Landed Cost Validate Wizard'

    operation_id = fields.Many2one(
        'intercompany.operation', string='Operation', required=True, readonly=True,
    )
    line_ids = fields.One2many(
        'intercompany.landed.cost.validate.wizard.line', 'wizard_id', string='Landed Costs',
    )

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        Line = self.env['intercompany.landed.cost.validate.wizard.line']

        for wizard in wizards:
            if wizard.line_ids:
                continue
            operation = wizard.operation_id
            if not operation:
                continue

            # فقط العمليات المخزنية (incoming/outgoing) مش internal
            done_pickings = operation.picking_ids.filtered(
                lambda p: p.state == 'done'
                and p.picking_type_id.code in ('incoming', 'outgoing')
            )

            for lc in operation.landed_cost_ids:
                company = lc.company_id

                if lc.picking_ids:
                    auto_pickings = lc.picking_ids
                elif company:
                    auto_pickings = done_pickings.filtered(
                        lambda p: p.company_id == company
                    ) or done_pickings
                else:
                    auto_pickings = done_pickings

                amount = sum(lc.cost_lines.mapped('price_unit')) if lc.cost_lines else 0.0

                # جيب الحساب من أول cost_line
                account_id = False
                if lc.cost_lines and lc.cost_lines[0].account_id:
                    account_id = lc.cost_lines[0].account_id.id

                # جيب المنتج من أول cost_line
                product_id = False
                if lc.cost_lines and lc.cost_lines[0].product_id:
                    product_id = lc.cost_lines[0].product_id.id

                Line.create({
                    'wizard_id': wizard.id,
                    'landed_cost_id': lc.id,
                    'vendor_bill_id': lc.vendor_bill_id.id if lc.vendor_bill_id else False,
                    'picking_ids': [(6, 0, auto_pickings.ids)],
                    'amount_total': amount,
                    'account_id': account_id,
                    'product_id': product_id,
                })

        return wizards

    def action_confirm(self):
        """Add transfers to each landed cost and validate them all."""
        self.ensure_one()
        if self.operation_id.state != 'landed_cost_created':
            raise UserError(_('Operation must be in "Landed Cost Created" state.'))

        for line in self.line_ids:
            lc = line.landed_cost_id
            if not lc:
                continue

            # اكتب الـ transfers
            if line.picking_ids:
                lc.write({'picking_ids': [(6, 0, line.picking_ids.ids)]})

            # اكتب vendor bill لو اتغير
            if line.vendor_bill_id and line.vendor_bill_id != lc.vendor_bill_id:
                lc.vendor_bill_id = line.vendor_bill_id

            # اكتب التكلفة والضرائب والحساب والمنتج على cost_lines
            if lc.cost_lines:
                for cl in lc.cost_lines:
                    if line.amount_total:
                        amount = line.amount_total if len(lc.cost_lines) == 1 else line.amount_total / len(lc.cost_lines)
                        cl.price_unit = amount
                    if line.account_id:
                        cl.account_id = line.account_id
                    if line.product_id:
                        cl.product_id = line.product_id

            if lc.state == 'draft':
                lc.button_validate()

        self.operation_id.state = 'done'
        return {'type': 'ir.actions.act_window_close'}


class IntercompanyLandedCostValidateWizardLine(models.TransientModel):
    _name = 'intercompany.landed.cost.validate.wizard.line'
    _description = 'Landed Cost Validate Wizard Line'

    wizard_id = fields.Many2one(
        'intercompany.landed.cost.validate.wizard', string='Wizard',
        required=True, ondelete='cascade',
    )
    landed_cost_id = fields.Many2one(
        'stock.landed.cost', string='Landed Cost', required=True, readonly=True,
    )
    # الفاتورة - قابلة للتعديل
    vendor_bill_id = fields.Many2one(
        'account.move', string='Vendor Bill',
        domain="[('move_type', '=', 'in_invoice'), ('state', '=', 'posted'), ('company_id', '=', company_id)]",
    )
    company_id = fields.Many2one(
        related='landed_cost_id.company_id', string='Company', readonly=True,
    )
    lc_state = fields.Selection(
        related='landed_cost_id.state', string='Status', readonly=True,
    )
    # المنتج - قابل للتعديل
    product_id = fields.Many2one(
        'product.product', string='Product',
        domain="[('landed_cost_ok', '=', True)]",
    )
    amount_total = fields.Float(
        string='Cost Amount',
        digits='Account',
    )
    # الحساب - قابل للتعديل
    account_id = fields.Many2one(
        'account.account', string='Account',
        domain="[('deprecated', '=', False)]",
    )
    # Transfers - فقط incoming/outgoing مش internal
    picking_ids = fields.Many2many(
        'stock.picking',
        'lc_wizard_line_picking_rel',
        'wizard_line_id', 'picking_id',
        string='Transfers',
        domain="[('state', '=', 'done'), ('company_id', '=', company_id), ('picking_type_id.code', 'in', ('incoming', 'outgoing'))]",
    )
    # mrp_production_ids is added by intercompany_operation_mrp bridge when mrp is installed
