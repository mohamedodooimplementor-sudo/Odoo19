# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .utils import convert_uom


class ErRequestSource(models.Model):
    """Stock the warehouse takes from the project that holds it, to cover a request line
    instead of purchasing it. The holders approve it (one approval) before the budget."""
    _name = 'er.request.source'
    _description = 'Request Stock Taken from Another Project'

    request_id = fields.Many2one('employee.request', required=True, ondelete='cascade',
                                 index=True)
    line_id = fields.Many2one('employee.request.line', string='Request Line', required=True,
                              ondelete='cascade')
    product_id = fields.Many2one(related='line_id.product_id', string='Product')
    location_id = fields.Many2one(related='line_id.location_id', string='Location')
    product_uom_id = fields.Many2one(related='line_id.product_uom_id', string='UoM')
    project_id = fields.Many2one('project.project', string='Take From Project', required=True)
    held_qty = fields.Float(string='Held by the Project', compute='_compute_held_qty',
                            digits='Product Unit')
    qty = fields.Float(string='Quantity', digits='Product Unit', required=True)
    released = fields.Boolean(readonly=True, copy=False)

    @api.depends('line_id', 'project_id', 'released')
    def _compute_held_qty(self):
        for rec in self:
            line = rec.line_id
            held = 0.0
            if line and rec.project_id and line.product_id and line.location_id:
                data = self.env['stock.move']._er_project_locked_qty(
                    line.product_id, line.location_id)
                held = line._to_line_uom(data.get(rec.project_id.id, 0.0))
            rec.held_qty = held

    @api.onchange('line_id', 'project_id')
    def _onchange_default_qty(self):
        """Propose the most this project can give for the line."""
        for rec in self:
            if rec.line_id and rec.project_id and not rec.qty:
                others = sum((rec.line_id.source_ids - rec).mapped('qty'))
                rec.qty = max(min(rec.held_qty, rec.line_id.product_uom_qty - others), 0.0)

    @api.constrains('qty', 'project_id', 'line_id')
    def _check_values(self):
        for rec in self:
            name = rec.line_id.product_id.display_name
            if rec.qty < 0:
                raise ValidationError(_("%s: the quantity cannot be negative.", name))
            if rec.project_id == rec.line_id.project_id:
                raise ValidationError(_(
                    "%s: choose a project other than the one of the request line.", name))
            if not rec.released and rec.qty - rec.held_qty > 1e-6:
                raise ValidationError(_(
                    "%(project)s holds only %(held)s of %(product)s.",
                    project=rec.project_id.display_name, held=rec.held_qty, product=name))
            total = sum(rec.line_id.source_ids.mapped('qty'))
            if total - rec.line_id.product_uom_qty > 1e-6:
                raise ValidationError(_(
                    "%(product)s: more than the requested quantity is taken from other "
                    "projects.", product=name))

    # --- who may change what -------------------------------------------------------------
    def _er_check_edit(self, request, vals=None, record=None):
        """Warehouse approvers choose the projects; the project approvers can only lower
        the quantities (0 refuses)."""
        if self.env.su:
            return
        if request.state == 'warehouse' and request.can_approve:
            return
        if (request.state == 'project' and request.can_approve and record is not None
                and vals is not None and set(vals) <= {'qty'}
                and vals.get('qty', record.qty) <= record.qty + 1e-6):
            return
        raise UserError(_("These quantities cannot be changed now."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._er_check_edit(self.env['employee.request'].browse(vals.get('request_id')))
        return super().create(vals_list)

    def write(self, vals):
        for rec in self:
            self._er_check_edit(rec.request_id, vals, rec)
        return super().write(vals)

    def unlink(self):
        for rec in self:
            self._er_check_edit(rec.request_id)
        return super().unlink()


class EmployeeRequestLineSource(models.Model):
    _inherit = 'employee.request.line'

    source_ids = fields.One2many('er.request.source', 'line_id', string='Taken from Projects')


class EmployeeRequestSource(models.Model):
    _inherit = 'employee.request'

    source_ids = fields.One2many('er.request.source', 'request_id',
                                 string='Stock from Other Projects')
    check_stock = fields.Boolean(
        string='Check Stock Availability', default=True, copy=True,
        help="Checked (default): the request is covered from the location stock first and "
             "only the rest is purchased. Unchecked: no stock transfer is made and the whole "
             "quantity goes to a purchase order, created after the budget approval "
             "(automatically if the setting is on, else with the button).")
    check_project_stock = fields.Boolean(
        string='Check Stock Held by Other Projects', default=True, copy=True,
        help="Checked: the stock can be taken from the projects that hold it "
             "(their managers approve it before the budget). Unchecked: stock held for other "
             "projects is left alone; the request issues what is free (or held for its own "
             "project) and purchases the rest.")
    er_lock_enabled = fields.Boolean(related='company_id.er_project_lock_enabled')

    def _get_stage_approvers(self, stage):
        """Project approval: the manager of every project the stock is taken from."""
        if stage == 'project':
            rec = self.sudo()
            users = rec.source_ids.filtered(lambda s: s.qty > 0).project_id.user_id
            return users or rec.company_id.er_project_lock_user_ids
        return super()._get_stage_approvers(stage)

    def _enter_state(self, state):
        res = super()._enter_state(state)
        if state == 'warehouse':
            self._er_suggest_sources()
        return res

    def _er_suggest_sources(self):
        """The warehouse approver finds, on the Other Projects tab, the stock other projects
        hold for the lines the free stock cannot cover (biggest holder first). He keeps,
        changes or deletes the rows; with no row the quantity is purchased."""
        Source = self.env['er.request.source'].sudo()
        for rec in self.sudo().filtered(lambda r: r.check_stock and r.check_project_stock):
            for line in rec.line_ids:
                if line.source_ids or not (line.product_id and line.location_id):
                    continue
                locked = line._er_locked_for_others()
                if locked <= 0:
                    continue
                own_free = max(line.available_qty - locked, 0.0)
                need = min(max(line.product_uom_qty - own_free, 0.0), locked)
                if need <= 0:
                    continue
                held = self.env['stock.move']._er_project_locked_qty(
                    line.product_id, line.location_id, exclude_project=line.project_id)
                for project_id, qty in sorted(held.items(), key=lambda kv: -kv[1]):
                    take = min(need, line._to_line_uom(qty))
                    if take <= 0:
                        continue
                    Source.create({'request_id': rec.id, 'line_id': line.id,
                                   'project_id': project_id, 'qty': take})
                    need -= take
                    if need <= 1e-6:
                        break

    def _advance(self):
        self.ensure_one()
        if self.state == 'warehouse' and (
                not self.check_stock
                or not self.check_project_stock
                or not self.source_ids.filtered(lambda s: s.qty > 0)):
            return self._enter_state('budget')      # nothing is taken from other projects
        return super()._advance()

    def _er_release_sources(self):
        """The approved quantities stop being held by the projects they come from: they
        become free stock, which the request then issues like any other."""
        Allocation = self.env['er.project.allocation'].sudo()
        for rec in self.sudo().filtered(lambda r: r.check_stock and r.check_project_stock):
            released = []
            for src in rec.source_ids.filtered(lambda s: s.qty > 0 and not s.released):
                product = src.product_id
                alloc = Allocation.create({
                    'kind': 'release', 'project_id': src.project_id.id,
                    'product_id': product.id, 'location_id': src.location_id.id,
                    'qty': convert_uom(src.qty, src.product_uom_id, product.uom_id),
                    'company_id': rec.company_id.id,
                    'note': _("Released for request %s", rec.name)})
                alloc.action_confirm()
                src.released = True
                released.append("%s: %s %s" % (
                    src.project_id.display_name, src.qty, product.display_name))
            if released:
                rec.message_post(
                    body=_("Stock released from other projects: %s", "; ".join(released)),
                    subtype_xmlid='mail.mt_note')
