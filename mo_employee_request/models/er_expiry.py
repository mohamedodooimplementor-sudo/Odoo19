# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models, tools


class StockLot(models.Model):
    _inherit = 'stock.lot'

    er_expiry_notified = fields.Selection(
        [('soon', 'Expiring soon'), ('expired', 'Expired')], copy=False,
        help="Last expiry notice sent for this lot (each notice is sent once).")

    @api.model
    def _er_cron_expiry_notify(self):
        """Daily: notify the users about the lots that are about to expire or have expired."""
        now = fields.Datetime.now()
        for company in self.env['res.company'].sudo().search([]):
            days = company.er_expiry_days
            if days <= 0:
                continue
            quants = self.env['stock.quant'].sudo().search([
                ('company_id', '=', company.id), ('location_id.usage', '=', 'internal'),
                ('quantity', '>', 0), ('lot_id.expiration_date', '!=', False),
                ('lot_id.expiration_date', '<=', now + timedelta(days=days))])
            lots = quants.lot_id
            expired = lots.filtered(lambda l: l.expiration_date <= now
                                    and l.er_expiry_notified != 'expired')
            soon = (lots - expired).filtered(lambda l: l.expiration_date > now
                                             and not l.er_expiry_notified)
            if not (expired or soon):
                continue
            users = company.er_expiry_user_ids or self.env.ref(
                'stock.group_stock_manager').sudo().user_ids.filtered(
                lambda u: company in u.company_ids)
            if not users:
                continue

            def rows(recs):
                return "".join(
                    "<li>%s - %s: %s</li>" % (
                        l.product_id.display_name, l.name, fields.Date.to_string(l.expiration_date))
                    for l in recs.sorted('expiration_date')[:50])

            body = ""
            if expired:
                body += "<p><b>%s</b></p><ul>%s</ul>" % (_("Expired lots"), rows(expired))
            if soon:
                body += "<p><b>%s</b></p><ul>%s</ul>" % (
                    _("Lots expiring within %s days", days), rows(soon))
            self.env['mail.thread'].sudo().message_notify(
                partner_ids=users.partner_id.ids,
                subject=_("Expiry Date Notice"), body=body,
                subtype_xmlid='mail.mt_note')
            expired.write({'er_expiry_notified': 'expired'})
            soon.write({'er_expiry_notified': 'soon'})


class ErExpiryReport(models.Model):
    """Stock in the warehouses that has an expiry date, closest first."""
    _name = 'er.expiry.report'
    _description = 'Expiry Date Report'
    _auto = False
    _order = 'expiration_date, product_id'

    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    lot_id = fields.Many2one('stock.lot', string='Lot / Serial', readonly=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Warehouse', readonly=True)
    location_id = fields.Many2one('stock.location', string='Location', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    quantity = fields.Float(string='Quantity', readonly=True, digits='Product Unit')
    expiration_date = fields.Datetime(string='Expiry Date', readonly=True)
    days_left = fields.Integer(string='Days Left', readonly=True)
    state = fields.Selection(
        [('expired', 'Expired'), ('soon', 'Expiring Soon'), ('ok', 'Valid')],
        string='Status', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT row_number() OVER () AS id,
                       q.product_id, q.lot_id, q.location_id, sl.warehouse_id, q.company_id,
                       SUM(q.quantity) AS quantity,
                       l.expiration_date,
                       (l.expiration_date::date - CURRENT_DATE) AS days_left,
                       CASE WHEN l.expiration_date < NOW() THEN 'expired'
                            WHEN l.expiration_date < NOW() + INTERVAL '30 days' THEN 'soon'
                            ELSE 'ok' END AS state
                FROM stock_quant q
                JOIN stock_lot l ON l.id = q.lot_id
                JOIN stock_location sl ON sl.id = q.location_id
                WHERE sl.usage = 'internal' AND q.quantity > 0 AND l.expiration_date IS NOT NULL
                GROUP BY q.product_id, q.lot_id, q.location_id, sl.warehouse_id, q.company_id,
                         l.expiration_date
            )""" % self._table)
