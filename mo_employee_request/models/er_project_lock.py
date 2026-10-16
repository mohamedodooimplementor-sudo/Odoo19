# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .utils import default_location


class ErProjectAllocation(models.Model):
    """Stock that already sits in a location, set aside for a project by hand."""
    _name = 'er.project.allocation'
    _description = 'Project Stock Allocation'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True)
    project_id = fields.Many2one('project.project', string='Project', required=True,
                                 tracking=True, index=True)
    product_id = fields.Many2one('product.product', string='Product', required=True,
                                 domain="[('type', '=', 'consu')]", tracking=True)
    location_id = fields.Many2one(
        'stock.location', string='Location', required=True, tracking=True,
        domain="[('usage', '=', 'internal')]",
        default=lambda self: default_location(self.env))
    kind = fields.Selection(
        [('reserve', 'Reserve'), ('release', 'Release Back')], default='reserve',
        required=True, tracking=True,
        help="Reserve: set stock aside for the project. Release Back: the project no longer "
             "needs it, the quantity returns to general stock.")
    source = fields.Selection(
        [('general', 'General Projects Location'), ('other', 'Other Location')],
        compute='_compute_source', string='Taken From')
    project_held_qty = fields.Float(string='Held by the Project', compute='_compute_free_qty',
                                    digits='Product Unit')
    qty = fields.Float(string='Quantity', required=True, digits='Product Unit', tracking=True)
    product_uom_id = fields.Many2one(related='product_id.uom_id', string='UoM')
    free_qty = fields.Float(string='Not Held by Any Project', compute='_compute_free_qty',
                            digits='Product Unit',
                            help="On hand in the location minus what is already held for projects.")
    state = fields.Selection(
        [('draft', 'Draft'), ('confirmed', 'Allocated'), ('released', 'Released')],
        default='draft', tracking=True, copy=False)
    user_id = fields.Many2one('res.users', string='Responsible', default=lambda s: s.env.user)
    date = fields.Datetime(default=fields.Datetime.now, copy=False)
    note = fields.Text()
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company, required=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('er.project.allocation') or 'New'
        return super().create(vals_list)

    @api.constrains('qty')
    def _check_qty(self):
        for rec in self:
            if rec.qty <= 0:
                raise ValidationError(_("The quantity must be greater than zero."))

    @api.depends('location_id', 'company_id.er_general_location_ids')
    def _compute_source(self):
        for rec in self:
            general = rec.company_id.er_general_location_ids
            rec.source = 'general' if (general and rec.location_id in general) else 'other'

    @api.depends('product_id', 'location_id', 'project_id', 'state', 'kind', 'qty')
    def _compute_free_qty(self):
        for rec in self:
            free = held_project = 0.0
            if rec.product_id and rec.location_id:
                onhand = rec.product_id.sudo().with_context(
                    location=rec.location_id.id).qty_available
                held = self.env['stock.move']._er_project_locked_qty(
                    rec.product_id, rec.location_id)
                total = sum(held.values())
                held_project = held.get(rec.project_id.id, 0.0)
                # this record is already inside `held` once confirmed: take it back
                if rec.state == 'confirmed':
                    sign = -1.0 if rec.kind == 'release' else 1.0
                    total -= sign * rec.qty
                    held_project -= sign * rec.qty
                free = onhand - total
            rec.free_qty = free
            rec.project_held_qty = max(held_project, 0.0)

    def action_confirm(self):
        for rec in self.filtered(lambda r: r.state == 'draft'):
            if rec.kind == 'release':
                if rec.qty - rec.project_held_qty > 1e-6:
                    raise UserError(_(
                        "%(project)s holds only %(held)s of %(product)s in %(wh)s.",
                        project=rec.project_id.display_name, held=rec.project_held_qty,
                        product=rec.product_id.display_name, wh=rec.location_id.display_name))
            elif rec.qty - rec.free_qty > 1e-6:
                raise UserError(_(
                    "Only %(free)s of %(product)s is not held by a project in %(wh)s.",
                    free=rec.free_qty, product=rec.product_id.display_name,
                    wh=rec.location_id.display_name))
            rec.state = 'confirmed'
        return True

    def action_release(self):
        self.filtered(lambda r: r.state == 'confirmed').write({'state': 'released'})
        return True

    def action_draft(self):
        self.filtered(lambda r: r.state == 'released').write({'state': 'draft'})
        return True

    def unlink(self):
        if any(rec.state == 'confirmed' for rec in self):
            raise UserError(_("Release the allocation before deleting it."))
        return super().unlink()


class ErProjectLockLog(models.Model):
    """History of the approvals asked / given to issue stock held for another project."""
    _name = 'er.project.lock.log'
    _description = 'Project Stock Approval History'
    _order = 'id desc'

    picking_id = fields.Many2one('stock.picking', string='Transfer', index=True,
                                 ondelete='cascade')
    project_id = fields.Many2one('project.project', string='Issued to Project')
    action = fields.Selection([('request', 'Requested'), ('approve', 'Approved'),
                               ('reject', 'Rejected')], required=True)
    details = fields.Text(string='Details')
    reason = fields.Text(string='Reason')
    user_id = fields.Many2one('res.users', string='By', readonly=True)
    date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    company_id = fields.Many2one('res.company')
