from odoo import models, api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('ref'):
                customer_rank = vals.get('customer_rank', 0)
                supplier_rank = vals.get('supplier_rank', 0)

                if customer_rank and not supplier_rank:
                    seq = self.env['ir.sequence'].next_by_code('partner.customer.seq')
                    vals['ref'] = seq or False

                elif supplier_rank and not customer_rank:
                    seq = self.env['ir.sequence'].next_by_code('partner.supplier.seq')
                    vals['ref'] = seq or False

                elif customer_rank and supplier_rank:
                    seq = self.env['ir.sequence'].next_by_code('partner.customer.seq')
                    vals['ref'] = seq or False
        return super().create(vals_list)
