from odoo import models, api, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    _sql_constraints = [
        (
            'partner_ref_unique',
            'unique(ref, company_id)',
            'The Reference must be unique per company! '
            'If you are upgrading this module on a database that already '
            'has duplicate or blank references, clean up the data first, '
            'otherwise the module update will fail.',
        ),
    ]

    def _get_reference_sequence_code(self, customer_rank=0, supplier_rank=0):
        """Return the ir.sequence code to use based on customer/supplier rank."""
        if customer_rank and supplier_rank:
            return 'partner.customer.seq'
        if customer_rank:
            return 'partner.customer.seq'
        if supplier_rank:
            return 'partner.supplier.seq'
        # Plain contact: neither a customer nor a supplier
        return 'partner.contact.seq'

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('ref'):
                code = self._get_reference_sequence_code(
                    customer_rank=vals.get('customer_rank', 0),
                    supplier_rank=vals.get('supplier_rank', 0),
                )
                seq = self.env['ir.sequence'].next_by_code(code)
                vals['ref'] = seq or False
        return super().create(vals_list)

    def write(self, vals):
        res = super().write(vals)
        # If the reference was explicitly cleared out, regenerate it so a
        # partner never ends up permanently without one.
        if 'ref' in vals and not vals.get('ref'):
            for partner in self:
                if not partner.ref:
                    code = partner._get_reference_sequence_code(
                        customer_rank=partner.customer_rank,
                        supplier_rank=partner.supplier_rank,
                    )
                    seq = self.env['ir.sequence'].next_by_code(code)
                    if seq:
                        partner.ref = seq
        return res
