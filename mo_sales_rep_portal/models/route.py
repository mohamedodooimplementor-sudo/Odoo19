from odoo import api, fields, models, _
from odoo.exceptions import UserError
from .geo import nearest_neighbour_order
from .sales_rep import WEEKDAYS


class SalesRoute(models.Model):
    _name = 'mo.sales.route'
    _description = 'Sales Route'
    _inherit = ['mail.thread']
    _order = 'weekday, name'

    name = fields.Char('Route Name', required=True)
    rep_id = fields.Many2one('mo.sales.rep', 'Salesperson', required=True, tracking=True, ondelete='cascade')
    weekday = fields.Selection(WEEKDAYS, 'Day', required=True, default='6', tracking=True)
    area = fields.Char('Area')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company)
    line_ids = fields.One2many('mo.sales.route.line', 'route_id', 'Customers', copy=True)

    def write(self, vals):
        res = super().write(vals)
        if {'line_ids', 'weekday', 'rep_id', 'active'} & set(vals):
            for route in self:
                route.rep_id._notify(_('Route changed'), _('Route "%s" was updated.', route.name), '/rep/route')
        return res

    def action_optimize(self):
        """Re-sequence the stops by nearest neighbour using customer coordinates.

        The first stop with coordinates stays the origin; stops without coordinates keep their
        relative order at the end.
        """
        for route in self:
            lines = route.line_ids.sorted('sequence')
            located = lines.filtered(lambda l: l.partner_id.partner_latitude or l.partner_id.partner_longitude)
            if len(located) < 2:
                raise UserError(_('At least two customers with a saved location are needed to optimize "%s".', route.name))
            order = nearest_neighbour_order(
                [(l.id, l.partner_id.partner_latitude, l.partner_id.partner_longitude) for l in located])
            order += (lines - located).ids
            for idx, line_id in enumerate(order, start=1):
                self.env['mo.sales.route.line'].browse(line_id).sequence = idx * 10
            route.rep_id._notify(_('Route changed'), _('Route "%s" was re-ordered by distance.', route.name), '/rep/route')
        return True

    @api.model_create_multi
    def create(self, vals_list):
        routes = super().create(vals_list)
        for route in routes:
            route.rep_id._notify(_('New route'), _('Route "%s" was assigned to you.', route.name), '/rep/route')
        return routes


class SalesRouteLine(models.Model):
    _name = 'mo.sales.route.line'
    _description = 'Sales Route Customer'
    _order = 'sequence, id'

    route_id = fields.Many2one('mo.sales.route', required=True, ondelete='cascade')
    rep_id = fields.Many2one(related='route_id.rep_id', store=True)
    sequence = fields.Integer(default=10)
    partner_id = fields.Many2one('res.partner', 'Customer', required=True)
    expected_time = fields.Float('Expected Visit Time')
    priority = fields.Selection([('0', 'Normal'), ('1', 'High'), ('2', 'Urgent')], default='0')
    note = fields.Char('Visit Purpose / Note')
    frequency = fields.Selection([('daily', 'Daily'), ('weekly', 'Weekly'), ('biweekly', 'Every 2 Weeks'),
                                  ('monthly', 'Monthly'), ('custom', 'Custom (every N days)')],
                                 'Frequency', default='weekly', required=True)
    start_date = fields.Date('Starts On', help='Anchor date for every-2-weeks, monthly and custom frequencies.')
    interval_days = fields.Integer('Every (days)', default=7, help='Used by the custom frequency.')
