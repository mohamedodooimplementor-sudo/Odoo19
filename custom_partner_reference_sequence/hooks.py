SEQUENCES = (
    ('partner.customer.seq', 'Customer Reference', 'C'),
    ('partner.supplier.seq', 'Supplier Reference', 'S'),
    ('partner.contact.seq', 'Contact Reference', 'P'),
)


def _create_company_sequences(env):
    """Give every existing company its own independent numbering.

    The module ships with one global sequence per code (company_id=False)
    so it works out of the box on single-company databases. On install,
    this hook additionally creates a company-specific sequence for each
    existing company; ir.sequence.next_by_code() will then automatically
    prefer the company-specific sequence over the global one, so each
    company counts its own references starting from 1.
    """
    ir_sequence = env['ir.sequence']
    for company in env['res.company'].search([]):
        for code, name, prefix in SEQUENCES:
            existing = ir_sequence.search([
                ('code', '=', code),
                ('company_id', '=', company.id),
            ], limit=1)
            if not existing:
                ir_sequence.create({
                    'name': f'{name} ({company.name})',
                    'code': code,
                    'prefix': prefix,
                    'padding': 4,
                    'implementation': 'no_gap',
                    'company_id': company.id,
                })
