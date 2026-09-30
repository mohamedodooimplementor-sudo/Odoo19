# -*- coding: utf-8 -*-
from odoo import fields, models


class EducationCertificateTemplate(models.Model):
    _name = 'education.certificate.template'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Certificate Template'
    _order = 'name'

    name = fields.Char(string='Template Name', required=True)
    header_text = fields.Char(string='Header Text', default='CERTIFICATE',
                               help='Main heading printed at the top of the certificate.')
    intro_text = fields.Char(string='Intro Text', default='This is to certify that')
    border_color = fields.Char(string='Border Color (hex)', default='#2c3e50')
    accent_color = fields.Char(string='Accent Color (hex)', default='#2c3e50')
    show_qr_code = fields.Boolean(string='Show QR Verification Code', default=True)
    show_signature_line = fields.Boolean(string='Show Signature Line', default=True)
    footer_text = fields.Char(string='Footer Text')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
