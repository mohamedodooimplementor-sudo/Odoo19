from datetime import timedelta

from odoo import _, api, fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    rc_expiry_alert_days = fields.Integer(
        string='Near-Expiry Alert (days)', default=60,
        help='Stock whose lot expires within this number of days is listed in the Expiring Soon report.')


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    rc_expiration_date = fields.Datetime(
        string='Expiration Date', related='lot_id.expiration_date', store=True, index=True)
    rc_uom_id = fields.Many2one(
        'uom.uom', string='Unit of Measure', related='product_id.uom_id',
        help='Version-independent unit of measure of the product (core field name changed between releases).')
    rc_days_to_expiry = fields.Integer(
        string='Days to Expiry', compute='_compute_rc_expiry',
        help='Negative when the lot is already expired.')
    rc_expiry_state = fields.Selection([
        ('expired', 'Expired'), ('soon', 'Expiring Soon'), ('ok', 'Valid'), ('none', 'No Expiry'),
    ], string='Expiry Status', compute='_compute_rc_expiry')

    @api.depends('rc_expiration_date', 'company_id.rc_expiry_alert_days')
    def _compute_rc_expiry(self):
        now = fields.Datetime.now()
        for quant in self:
            exp = quant.rc_expiration_date
            if not exp:
                quant.rc_days_to_expiry = 0
                quant.rc_expiry_state = 'none'
                continue
            quant.rc_days_to_expiry = (exp.date() - now.date()).days
            if exp < now:
                quant.rc_expiry_state = 'expired'
            elif exp <= now + timedelta(days=quant.company_id.rc_expiry_alert_days or 0):
                quant.rc_expiry_state = 'soon'
            else:
                quant.rc_expiry_state = 'ok'

    @api.model
    def rc_open_expiry_report(self, mode='expired'):
        """Open the expired / expiring-soon stock list for the current companies."""
        now = fields.Datetime.now()
        days = self.env.company.rc_expiry_alert_days or 0
        domain = [
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0),
            ('lot_id', '!=', False),
            ('rc_expiration_date', '!=', False),
            ('company_id', 'in', self.env.companies.ids),
        ]
        if mode == 'expired':
            name = _('Expired Stock')
            domain.append(('rc_expiration_date', '<', now))
        else:
            name = _('Expiring Soon (%s days)', days)
            domain += [('rc_expiration_date', '>=', now),
                       ('rc_expiration_date', '<=', now + timedelta(days=days))]
        ref = self.env.ref
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': 'stock.quant',
            'view_mode': 'list,pivot',
            'views': [(ref('radiology_consumables.rc_expiry_view_list').id, 'list'),
                      (ref('radiology_consumables.rc_expiry_view_pivot').id, 'pivot')],
            'search_view_id': ref('radiology_consumables.rc_expiry_view_search').id,
            'domain': domain,
            'context': {'search_default_group_room': 1},
        }
