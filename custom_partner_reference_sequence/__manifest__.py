{
    'name': 'Partner Reference Sequence',
    'version': '19.0.2.0.0',
    'summary': 'Auto-generate reference codes for customers, suppliers and contacts',
    'category': 'Contacts',
    'author': 'Eng. M.Aboelmagde',
    'license': 'LGPL-3',
    'depends': ['base'],
    'data': [
        'data/sequence_data.xml',
        'views/res_partner_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'post_init_hook': '_create_company_sequences',
}
