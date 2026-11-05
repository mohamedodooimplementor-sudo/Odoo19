from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    rc_auto_validate_exam_transfers = fields.Boolean(
        string='Automatically Validate Exam Stock Transfers', default=False,
        help='When enabled, internal transfers created by exam phases are validated automatically. When disabled, transfers remain waiting for manual validation in Inventory.'
    )

    rc_consumption_location_id = fields.Many2one(
        'stock.location', string='Consumption Location',
        domain="[('usage', '=', 'inventory')]")
    rc_loss_location_id = fields.Many2one(
        'stock.location', string='Loss / Scrap Location',
        domain="[('usage', '=', 'inventory')]")
    rc_transit_location_id = fields.Many2one(
        'stock.location', string='In Transit Location',
        domain="[('usage', '=', 'transit')]")

    def _rc_ensure_locations(self):
        """Create the virtual locations used by the module when missing."""
        parent = self.env.ref('stock.stock_location_locations_virtual', raise_if_not_found=False)
        spec = [
            ('rc_consumption_location_id', 'RC Consumption', 'inventory'),
            ('rc_loss_location_id', 'RC Loss', 'inventory'),
            ('rc_transit_location_id', 'RC In Transit', 'transit'),
        ]
        for company in self.sudo():
            for fname, name, usage in spec:
                if not company[fname]:
                    vals = {'name': name, 'usage': usage, 'company_id': company.id}
                    if parent:
                        vals['location_id'] = parent.id
                    company[fname] = self.env['stock.location'].sudo().create(vals).id
