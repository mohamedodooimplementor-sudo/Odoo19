from odoo import fields, models


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    seeds_receipt_id = fields.Many2one('seeds.receipt', string='Seed Receipt', readonly=True, copy=False)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    seeds_receipt_id = fields.Many2one('seeds.receipt', string='Seed Receipt',
                                       compute='_compute_seeds_receipt_id')
    seeds_weight_per_unit = fields.Float(related='seeds_receipt_id.weight_per_unit', string='Weight Per Unit')
    seeds_total_weight = fields.Float(related='seeds_receipt_id.total_weight', string='Total Weight')
    seeds_ardab_wg = fields.Float(related='seeds_receipt_id.ardab_wg', string='Ardab WG')

    def _compute_seeds_receipt_id(self):
        for rec in self:
            rec.seeds_receipt_id = rec.purchase_id.seeds_receipt_id
