# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..models.utils import default_location


class ErProjectTransfer(models.TransientModel):
    """Move stock held for one project to another project: a Release Back on the source
    project and a Reserve on the destination project, in one step."""
    _name = 'er.project.transfer'
    _description = 'Transfer Held Stock to Another Project'

    allocation_id = fields.Many2one('er.project.allocation', string='Allocation', readonly=True)
    project_id = fields.Many2one('project.project', string='From Project', required=True)
    product_id = fields.Many2one('product.product', string='Product', required=True,
                                 domain="[('type', '=', 'consu')]")
    location_id = fields.Many2one(
        'stock.location', string='Location', required=True,
        domain="[('usage', '=', 'internal')]",
        default=lambda self: default_location(self.env))
    product_uom_id = fields.Many2one(related='product_id.uom_id', string='UoM')
    held_qty = fields.Float(string='Held by the Project', compute='_compute_held_qty',
                            digits='Product Unit')
    dest_project_id = fields.Many2one('project.project', string='To Project', required=True)
    qty = fields.Float(string='Quantity', required=True, digits='Product Unit')
    note = fields.Text(string='Reason')

    @api.depends('project_id', 'product_id', 'location_id')
    def _compute_held_qty(self):
        for wiz in self:
            held = {}
            if wiz.product_id and wiz.location_id:
                held = self.env['stock.move']._er_project_locked_qty(
                    wiz.product_id, wiz.location_id)
            wiz.held_qty = held.get(wiz.project_id.id, 0.0)

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group('mo_employee_request.group_er_project_transfer'):
            raise AccessError(_("You are not allowed to transfer stock between projects."))
        alloc = self.allocation_id
        company = alloc.company_id or self.env.company
        if self.dest_project_id == self.project_id:
            raise UserError(_("Choose a project different from %s.", self.project_id.display_name))
        if self.qty <= 0:
            raise UserError(_("The quantity must be greater than zero."))
        if self.qty - self.held_qty > 1e-6:
            raise UserError(_(
                "%(project)s holds only %(held)s of %(product)s in %(wh)s.",
                project=self.project_id.display_name, held=self.held_qty,
                product=self.product_id.display_name, wh=self.location_id.display_name))
        Allocation = self.env['er.project.allocation'].sudo()
        common = {
            'product_id': self.product_id.id,
            'location_id': self.location_id.id,
            'qty': self.qty,
            'company_id': company.id,
            'user_id': self.env.user.id,
        }
        reason = self.note or ""
        release = Allocation.create(dict(
            common, kind='release', project_id=self.project_id.id,
            note=_("Transferred to %(project)s. %(reason)s",
                   project=self.dest_project_id.display_name, reason=reason).strip()))
        release.action_confirm()                 # frees the quantity first
        reserve = Allocation.create(dict(
            common, kind='reserve', project_id=self.dest_project_id.id,
            note=_("Transferred from %(project)s. %(reason)s",
                   project=self.project_id.display_name, reason=reason).strip()))
        reserve.action_confirm()
        if alloc:
            alloc.sudo().message_post(body=_(
                "%(qty)s of %(product)s transferred to %(project)s (%(release)s / %(reserve)s).",
                qty=self.qty, product=self.product_id.display_name,
                project=self.dest_project_id.display_name,
                release=release.name, reserve=reserve.name))
        return {
            'type': 'ir.actions.act_window', 'res_model': 'er.project.allocation',
            'view_mode': 'list,form', 'domain': [('id', 'in', (release | reserve).ids)],
            'name': _("Project Transfer"),
        }


class ErProjectAllocation(models.Model):
    _inherit = 'er.project.allocation'

    def action_er_transfer(self):
        self.ensure_one()
        if self.kind != 'reserve' or self.state != 'confirmed':
            raise UserError(_("Only an allocated reservation can be transferred."))
        return {
            'type': 'ir.actions.act_window', 'res_model': 'er.project.transfer',
            'view_mode': 'form', 'target': 'new',
            'context': {'default_allocation_id': self.id, 'default_qty': self.qty,
                        'default_project_id': self.project_id.id,
                        'default_product_id': self.product_id.id,
                        'default_location_id': self.location_id.id},
        }
