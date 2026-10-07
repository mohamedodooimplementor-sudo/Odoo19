import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class PortalSourceMixin(models.AbstractModel):
    _name = 'mo.portal.source.mixin'
    _description = 'Sales Rep Portal Audit Fields'

    mo_source = fields.Selection([('backend', 'Backend'), ('portal', 'Sales Representative Portal')],
                                 string='Created From', default='backend', copy=False)
    # Set explicitly by the portal; when missing it falls back to the rep who created the record
    # (portal documents are created under the representative's own user).
    mo_rep_id = fields.Many2one('mo.sales.rep', 'Sales Representative', copy=False, index=True,
                                compute='_compute_mo_rep_id', store=True, readonly=False)
    mo_visit_id = fields.Many2one('mo.sales.visit', 'Visit', copy=False, index=True)
    mo_client_uid = fields.Char('Device Reference', copy=False, index=True,
                                help='Set by the portal so an action replayed after an offline period is never created twice.')


    @api.depends('create_uid')
    def _compute_mo_rep_id(self):
        users = self.mapped('create_uid')
        reps = self.env['mo.sales.rep'].sudo().with_context(active_test=False).search([('user_id', 'in', users.ids)])
        by_user = {r.user_id.id: r for r in reps}
        for rec in self:
            if not rec.mo_rep_id:
                rec.mo_rep_id = by_user.get(rec.create_uid.id) or False


class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'mo.portal.source.mixin']

    def action_confirm(self):
        res = super().action_confirm()
        settings = self.env['mo.sales.rep.settings'].get_settings()
        for order in self.filtered('mo_rep_id'):
            order.mo_rep_id._notify(_('Order confirmed'), order.name, '/rep/order/%s' % order.id)
            if order.mo_rep_id.can_auto_validate(settings):
                order._mo_auto_validate_deliveries()
            order.mo_rep_id._check_targets()
        return res

    def _mo_auto_validate_deliveries(self):
        """Validate the order's stock transfers (all steps) when the rep holds the auto-validate permission.

        Only fully reserved transfers are validated (no backorders, no negative stock). Anything that
        cannot be validated stays as it is and the rep is notified; the order confirmation is never blocked.
        """
        self.ensure_one()
        order = self.sudo()
        rep = self.mo_rep_id
        for _pass in range(3):            # a later step (pack / ship) becomes ready once the previous one is done
            progressed = False
            for picking in order.picking_ids.sorted('id').filtered(lambda p: p.state not in ('done', 'cancel')):
                try:
                    with self.env.cr.savepoint():
                        if picking.state in ('confirmed', 'waiting'):
                            picking.action_assign()
                        moves = picking.move_ids.filtered(lambda m: m.state != 'cancel')
                        if picking.state != 'assigned' or any(m.state != 'assigned' for m in moves):
                            continue
                        res = picking.with_context(skip_backorder=True, skip_sms=True, skip_expired=True).button_validate()
                        if isinstance(res, dict):
                            raise UserError(_('This transfer needs manual processing.'))
                    if picking.state == 'done':
                        progressed = True
                except (UserError, ValidationError) as e:
                    _logger.info('Auto-validation of %s skipped: %s', picking.name, e)
            if not progressed:
                break
        pending = order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
        if pending:
            rep._notify(_('Delivery not validated'),
                        _('%s is waiting: not enough stock or it needs manual processing.', pending[:1].name),
                        '/rep/order/%s' % order.id)
        elif order.picking_ids:
            rep._notify(_('Delivery validated'), order.name, '/rep/order/%s' % order.id)

    def _action_cancel(self):
        res = super()._action_cancel()
        for order in self.filtered('mo_rep_id'):
            order.mo_rep_id._notify(_('Order cancelled'), order.name, '/rep/order/%s' % order.id)
        return res

    def _prepare_invoice(self):
        vals = super()._prepare_invoice()
        if self.mo_rep_id:
            vals.update({'mo_rep_id': self.mo_rep_id.id, 'mo_visit_id': self.mo_visit_id.id})
        return vals


class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'mo.portal.source.mixin']

    def _post(self, soft=True):
        posted = super()._post(soft=soft)
        for move in posted.filtered(lambda m: m.mo_rep_id and m.move_type == 'out_invoice'):
            move.mo_rep_id._notify(_('Invoice issued'), move.name, '/rep/invoice/%s' % move.id)
        return posted


class AccountPayment(models.Model):
    _name = 'account.payment'
    _inherit = ['account.payment', 'mo.portal.source.mixin']

    mo_method_id = fields.Many2one('mo.sales.rep.payment.method', 'Rep Payment Method', copy=False)

    def action_post(self):
        res = super().action_post()
        for pay in self.filtered('mo_rep_id'):
            pay.mo_rep_id._notify(_('Payment registered'), pay.name or '', '/rep/payment/%s' % pay.id)
            pay.mo_rep_id._check_targets()
        return res


class StockPicking(models.Model):
    _name = 'stock.picking'
    _inherit = ['stock.picking', 'mo.portal.source.mixin']

    mo_operation = fields.Selection([('receive', 'Receive Stock'), ('return', 'Return Stock'),
                                     ('transfer', 'Internal Transfer'), ('customer_return', 'Customer Return')],
                                    string='Rep Operation', copy=False)
    mo_return_reason_id = fields.Many2one('mo.return.reason', 'Return Reason', copy=False)

    def _action_done(self):
        res = super()._action_done()
        for picking in self.filtered(lambda p: p.state == 'done' and p.mo_rep_id):
            picking.mo_rep_id._notify(_('Stock operation completed'), picking.name, '/rep/picking/%s' % picking.id,
                                      key='picking-done:%s' % picking.id)
        return res

    @api.depends('create_uid', 'sale_id.mo_rep_id')
    def _compute_mo_rep_id(self):
        # a delivery belongs to the representative of its sale order
        super()._compute_mo_rep_id()
        for rec in self:
            if not rec.mo_rep_id and rec.sale_id.mo_rep_id:
                rec.mo_rep_id = rec.sale_id.mo_rep_id


class ResUsers(models.Model):
    _inherit = 'res.users'

    mo_rep_ids = fields.One2many('mo.sales.rep', 'user_id', string='Sales Representative Profiles')


class ResPartner(models.Model):
    _inherit = 'res.partner'

    mo_rep_ids = fields.Many2many('mo.sales.rep', 'mo_sales_rep_partner_rel', 'partner_id', 'rep_id',
                                  string='Sales Representatives')
