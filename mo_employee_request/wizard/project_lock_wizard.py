# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class ErProjectLockReason(models.TransientModel):
    _name = 'er.project.lock.reason'
    _description = 'Reason to ask / reject a project stock approval'

    picking_id = fields.Many2one('stock.picking', required=True, ondelete='cascade')
    action = fields.Selection([('request', 'Request'), ('reject', 'Reject')], required=True)
    reason = fields.Text(string='Reason', required=True)
    line_ids = fields.One2many('er.project.lock.reason.line', 'wizard_id', string='Quantities')

    def action_confirm(self):
        self.ensure_one()
        if self.action == 'request':
            self.picking_id._er_lock_do_request(self.reason)
        else:
            self.picking_id._er_check_lock_approver()
            rejects = {}
            for line in self.line_ids:
                if line.reject_qty < 0 or line.reject_qty - line.demand > 1e-6:
                    raise UserError(_(
                        "%(product)s: the quantity to reject must be between 0 and %(max)s.",
                        product=line.product_id.display_name, max=line.demand))
                if line.reject_qty > 0:
                    rejects[line.move_id] = line.reject_qty
            if not rejects:
                raise UserError(_("Enter the quantity to reject."))
            self.picking_id._er_lock_do_reject(self.reason, rejects)
        return {'type': 'ir.actions.act_window_close'}


class ErProjectLockReasonLine(models.TransientModel):
    _name = 'er.project.lock.reason.line'
    _description = 'Quantity to reject (project stock approval)'

    wizard_id = fields.Many2one('er.project.lock.reason', required=True, ondelete='cascade')
    move_id = fields.Many2one('stock.move', required=True, readonly=True)
    product_id = fields.Many2one(related='move_id.product_id', string='Product')
    demand = fields.Float(related='move_id.product_uom_qty', string='Quantity')
    reject_qty = fields.Float(string='Reject', digits='Product Unit')
