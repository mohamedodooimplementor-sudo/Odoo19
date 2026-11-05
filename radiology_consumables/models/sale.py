import logging
import math

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    rc_ris_ref = fields.Char(
        string='RIS Reference', copy=False, index=True,
        help='Filled by the RIS connection. Exams created from this order are marked as coming from RIS.')
    rc_consumption_count = fields.Integer(compute='_compute_rc_consumption_count')

    def _compute_rc_consumption_count(self):
        groups = self.env['rc.exam.consumption'].sudo()._read_group(
            [('sale_order_id', 'in', self.ids)], ['sale_order_id'], ['__count'])
        counts = {order.id: count for order, count in groups}
        for rec in self:
            rec.rc_consumption_count = counts.get(rec.id, 0)

    rc_payment_pending = fields.Boolean(compute='_compute_rc_payment_pending')

    @api.depends('state', 'invoice_ids.state', 'invoice_ids.payment_state')
    def _compute_rc_payment_pending(self):
        for order in self:
            invoices = order.invoice_ids.filtered(
                lambda m: m.move_type == 'out_invoice' and m.state != 'cancel')
            order.rc_payment_pending = order.state == 'sale' and (
                not invoices or any(
                    inv.state == 'draft' or inv.payment_state in ('not_paid', 'partial')
                    for inv in invoices))

    def action_rc_register_payment(self):
        """Pay from the sales order: create and post the invoice when needed,
        then open Odoo's standard Register Payment wizard. The wizard
        reconciles the payment with the invoice automatically."""
        self.ensure_one()
        if self.state != 'sale':
            raise UserError(_('Confirm the sales order before registering a payment.'))
        invoices = self.invoice_ids.filtered(
            lambda m: m.move_type == 'out_invoice' and m.state != 'cancel')
        if not invoices:
            invoices = self._create_invoices()
        drafts = invoices.filtered(lambda m: m.state == 'draft')
        if drafts:
            drafts.action_post()
        to_pay = invoices.filtered(
            lambda m: m.state == 'posted' and m.payment_state in ('not_paid', 'partial'))
        if not to_pay:
            raise UserError(_('Nothing to pay: the invoices of this order are already paid.'))
        return to_pay.action_register_payment()

    def action_confirm(self):
        res = super().action_confirm()
        confirmed = self.filtered(lambda o: o.state == 'sale')
        confirmed.order_line._rc_create_consumptions()
        confirmed.filtered(lambda o: o.warehouse_id.rc_auto_fulfill_on_confirm)._rc_auto_fulfill()
        return res

    def _rc_auto_fulfill(self):
        """Warehouse option: validate the delivery transfers, then create and
        post the invoice. A failed step never blocks the confirmation: it is
        rolled back on its own and explained in the order's chatter."""
        for order in self.sudo():
            try:
                with self.env.cr.savepoint():
                    order._rc_validate_pickings()
            except Exception as exc:  # noqa: BLE001
                _logger.warning('Auto delivery failed for %s: %s', order.name, exc)
                order.message_post(body=_(
                    'Automatic delivery could not be completed: %s', str(exc)[:500]))
            try:
                with self.env.cr.savepoint():
                    invoices = order.invoice_ids.filtered(
                        lambda m: m.move_type == 'out_invoice' and m.state == 'draft')
                    if not invoices:
                        invoices = order._create_invoices()
                    invoices.action_post()
            except Exception as exc:  # noqa: BLE001
                _logger.warning('Auto invoice failed for %s: %s', order.name, exc)
                order.message_post(body=_(
                    'Automatic invoice could not be completed: %s', str(exc)[:500]))

    def _rc_validate_pickings(self):
        self.ensure_one()
        # up to 5 rounds so multi-step routes (pick, pack, ship) are completed too
        for _round in range(5):
            pending = self.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
            if not pending:
                return
            for picking in pending.sorted('id'):
                if picking.state in ('confirmed', 'waiting'):
                    picking.action_assign()
                result = picking.with_context(
                    skip_immediate=True, skip_backorder=True,
                    picking_ids_not_to_backorder=picking.ids).button_validate()
                if isinstance(result, dict) or picking.state != 'done':
                    raise UserError(_(
                        'Transfer %s could not be validated automatically (check stock availability).',
                        picking.display_name))

    def _action_cancel(self):
        res = super()._action_cancel()
        self.env['rc.exam.consumption'].sudo().search([
            ('sale_order_id', 'in', self.ids), ('state', '=', 'draft')]).action_cancel()
        return res

    def action_view_rc_consumptions(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('radiology_consumables.rc_consumption_action')
        action['domain'] = [('sale_order_id', '=', self.id)]
        action['context'] = {}
        return action


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        # a service added to an order that is already confirmed
        lines.filtered(lambda l: l.order_id.state == 'sale')._rc_create_consumptions()
        return lines

    def _rc_create_consumptions(self):
        """Create one draft Exam Consumption per unit of every exam service line.
        Safe to call twice: lines that already have their records are skipped."""
        Consumption = self.env['rc.exam.consumption'].sudo()
        Template = self.env['rc.consumption.template'].sudo()
        for line in self:
            tmpl = line.product_id.product_tmpl_id.sudo()
            if line.display_type or not tmpl.rc_is_exam or line.product_uom_qty <= 0:
                continue
            order = line.order_id
            units = max(int(math.ceil(line.product_uom_qty)), 1)
            existing = Consumption.with_context(active_test=False).search_count(
                [('sale_line_id', '=', line.id)])
            template = Template.search([
                ('service_tmpl_ids', 'in', tmpl.id),
                ('company_id', 'in', [False, order.company_id.id]),
            ], limit=1)
            for _i in range(units - existing):
                rec = Consumption.create({
                    'company_id': order.company_id.id,
                    'room_id': tmpl.rc_room_id.id or False,
                    'service_product_id': line.product_id.id,
                    'template_id': template.id,
                    'patient_id': order.partner_id.id,
                    'sale_order_id': order.id,
                    'sale_line_id': line.id,
                    'source': 'ris' if order.rc_ris_ref else 'manual',
                    'nurse_id': False,
                })
                rec._rc_fill_lines()
