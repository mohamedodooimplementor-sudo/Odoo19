# -*- coding: utf-8 -*-
from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError

from ..models.utils import convert_uom, default_location, location_warehouse, pick_field


class ErProjectReplace(models.TransientModel):
    """Replace action on a project: pull stock for it from any location. Stock held by
    another project goes through the approval, with the purchase-order alert."""
    _name = 'er.project.replace'
    _description = 'Replace Stock for a Project'

    project_id = fields.Many2one('project.project', string='Project', required=True)
    location_id = fields.Many2one(
        'stock.location', string='Pull From Location', required=True,
        domain="[('usage', '=', 'internal')]",
        default=lambda self: default_location(self.env))
    reason = fields.Text(string='Reason', required=True)
    line_ids = fields.One2many('er.project.replace.line', 'wizard_id', string='Products')
    alert = fields.Text(string='Approval Alert', compute='_compute_alert')

    @api.depends('line_ids.product_id', 'line_ids.qty', 'location_id', 'project_id')
    def _compute_alert(self):
        Move = self.env['stock.move']
        for wiz in self:
            texts = []
            if wiz.location_id and wiz.project_id:
                for line in wiz.line_ids.filtered(lambda l: l.product_id and l.qty > 0):
                    wanted = convert_uom(line.qty, line.product_uom_id, line.product_id.uom_id)
                    found = Move._er_lock_check(line.product_id, wiz.project_id,
                                                wiz.location_id, wanted)
                    if found:
                        texts.append(Move._er_lock_alert(found))
            wiz.alert = "\n".join(texts)

    def action_confirm(self):
        self.ensure_one()
        lines = self.line_ids.filtered(lambda l: l.product_id and l.qty > 0)
        if not lines:
            raise UserError(_("Add at least one product."))
        dest = self.env.ref('mo_employee_request.location_employee_consumption',
                            raise_if_not_found=False)
        if not dest:
            raise UserError(_("The 'Employee Consumption' location is missing."))
        loc = self.location_id
        wh = location_warehouse(self.env, loc)
        Move = self.env['stock.move']
        uom_field = pick_field(Move, 'product_uom', 'product_uom_id')
        moves = []
        for line in lines:
            vals = {
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty,
                uom_field: line.product_uom_id.id,
                'location_id': loc.id,
                'location_dest_id': dest.id,
                'company_id': wh.company_id.id,
                'er_project_id': self.project_id.id,
            }
            if 'name' in Move._fields:
                vals['name'] = line.product_id.display_name
            moves.append(Command.create(vals))
        account = self.project_id.account_id
        picking = self.env['stock.picking'].sudo().create({
            'picking_type_id': wh.out_type_id.id,
            'location_id': loc.id,
            'location_dest_id': dest.id,
            'origin': _("Replace: %s", self.project_id.display_name),
            'company_id': wh.company_id.id,
            'er_project_id': self.project_id.id,
            'analytic_distribution': {str(account.id): 100.0} if account else False,
            'move_ids': moves,
        })
        picking.action_confirm()
        if picking.er_has_lock_excess:
            picking._er_lock_do_request(self.reason)   # needs the approval of the owners
        else:
            picking.action_assign()
        return {
            'type': 'ir.actions.act_window', 'res_model': 'stock.picking',
            'res_id': picking.id, 'view_mode': 'form', 'target': 'current',
        }


class ErProjectReplaceLine(models.TransientModel):
    _name = 'er.project.replace.line'
    _description = 'Replace Stock Line'

    wizard_id = fields.Many2one('er.project.replace', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product', required=True,
                                 domain="[('type', '=', 'consu')]")
    product_uom_id = fields.Many2one(related='product_id.uom_id', string='UoM')
    qty = fields.Float(string='Quantity', required=True, default=1.0, digits='Product Unit')
    free_qty = fields.Float(string='Free for the Project', compute='_compute_free_qty',
                            digits='Product Unit')

    @api.depends('product_id', 'wizard_id.location_id', 'wizard_id.project_id')
    def _compute_free_qty(self):
        Move = self.env['stock.move']
        for line in self:
            free = 0.0
            wh = line.wizard_id.location_id
            if line.product_id and wh:
                onhand = line.product_id.sudo().with_context(location=wh.id).qty_available
                others = Move._er_project_locked_qty(
                    line.product_id, wh, exclude_project=line.wizard_id.project_id)
                free = max(onhand - sum(others.values()), 0.0)
            line.free_qty = free
