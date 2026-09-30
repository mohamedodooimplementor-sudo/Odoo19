# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models


class EducationPublicAccessLog(models.Model):
    _name = 'education.public.access.log'
    _description = 'Public Token Access Log (certificate verification / student portal)'
    _order = 'create_date desc'

    endpoint = fields.Selection([
        ('certificate', 'Certificate Verification'),
        ('portal', 'Student Portal'),
        ('attendance', 'QR Self Check-in'),
    ], string='Endpoint', required=True)
    token = fields.Char(string='Token', index=True)
    ip_address = fields.Char(string='IP Address', index=True)
    found = fields.Boolean(string='Record Found')

    @api.model
    def check_rate_limit(self, ip_address, endpoint, max_requests=30, window_minutes=60):
        """Returns True if this IP is currently within the allowed request
        rate for the given endpoint, False if it should be throttled."""
        if not ip_address:
            return True
        since = fields.Datetime.now() - timedelta(minutes=window_minutes)
        count = self.sudo().search_count([
            ('ip_address', '=', ip_address),
            ('endpoint', '=', endpoint),
            ('create_date', '>=', since),
        ])
        return count < max_requests

    @api.model
    def log_access(self, ip_address, endpoint, token, found):
        self.sudo().create({
            'ip_address': ip_address, 'endpoint': endpoint, 'token': token, 'found': found,
        })

    def _cron_purge_old_logs(self, days=90):
        """Data-retention housekeeping: these logs exist only for rate
        limiting / abuse monitoring, not permanent audit, so they don't need
        to accumulate forever."""
        cutoff = fields.Datetime.now() - timedelta(days=days)
        old_logs = self.search([('create_date', '<', cutoff)])
        old_logs.unlink()
