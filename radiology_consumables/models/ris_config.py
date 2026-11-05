import ipaddress
import json
import socket
from datetime import timedelta
from urllib.parse import urlparse

import requests
from requests.auth import HTTPBasicAuth

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

MGR = 'radiology_consumables.group_rc_manager'

# Keys whose values are patient data: masked before a sample is stored.
SENSITIVE_KEYS = ('patient', 'phone', 'mobile', 'email', 'national', 'birth', 'dob',
                  'address', 'passport', 'ssn', 'id_number')


def rc_mask(data, masked=False):
    """Keep the structure of an API response but hide patient values."""
    if isinstance(data, dict):
        return {k: rc_mask(v, masked or any(s in str(k).lower() for s in SENSITIVE_KEYS))
                for k, v in data.items()}
    if isinstance(data, list):
        return [rc_mask(v, masked) for v in data]
    if masked and data is not None and not isinstance(data, bool):
        return '***'
    return data


def rc_check_url(url):
    """Allow only http(s) endpoints and refuse loopback, link-local (cloud metadata),
    unspecified, multicast and reserved addresses. Private LAN ranges stay allowed
    because a RIS normally lives on the clinic network."""
    parsed = urlparse(url or '')
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise UserError(_('The RIS URL must start with http:// or https://'))
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80))
    except socket.gaierror:
        raise UserError(_('The RIS host name cannot be resolved.'))
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_loopback or ip.is_link_local or ip.is_unspecified
                or ip.is_multicast or ip.is_reserved):
            raise UserError(_('This RIS address is not allowed (loopback, link-local or reserved).'))


class RcRisConfig(models.Model):
    _name = 'rc.ris.config'
    _description = 'RIS Connection'
    _rec_name = 'company_id'

    company_id = fields.Many2one('res.company', required=True, index=True,
                                 default=lambda s: s.env.company)
    active = fields.Boolean(default=True)
    base_url = fields.Char(string='Base URL', required=True,
                           help='Example: https://ris.example.com/api')
    verify_ssl = fields.Boolean(string='Verify SSL Certificate', default=True)
    timeout = fields.Integer(string='Timeout (seconds)', default=30)

    auth_type = fields.Selection([
        ('none', 'No Authentication'),
        ('api_key', 'API Key (custom header)'),
        ('bearer', 'Bearer Token'),
        ('basic', 'Username / Password (Basic)'),
    ], string='Authentication', default='bearer', required=True)
    api_key_header = fields.Char(string='API Key Header', default='X-API-Key', groups=MGR)
    api_token = fields.Char(string='API Key / Token', groups=MGR)
    username = fields.Char(groups=MGR)
    password = fields.Char(groups=MGR)

    test_endpoint = fields.Char(string='Test Path', help='Optional path used by Test Connection. Empty = Base URL.')
    endpoint_sales_order = fields.Char(string='Sales Orders Path', default='/sales-orders')
    endpoint_invoice = fields.Char(string='Invoices Path', default='/invoices')
    endpoint_payment = fields.Char(string='Payments Path', default='/payments')

    last_test_date = fields.Datetime(readonly=True)
    last_test_status = fields.Selection([('ok', 'Connected'), ('failed', 'Failed')], readonly=True)
    last_test_message = fields.Text(readonly=True)

    sample_sales_order = fields.Text(string='Sales Order Sample', readonly=True)
    sample_invoice = fields.Text(string='Invoice Sample', readonly=True)
    sample_payment = fields.Text(string='Payment Sample', readonly=True)
    sample_date = fields.Datetime(readonly=True)

    @api.constrains('base_url')
    def _check_base_url_scheme(self):
        for rec in self:
            if urlparse((rec.base_url or '').strip()).scheme not in ('http', 'https'):
                raise ValidationError(_('The RIS URL must start with http:// or https://'))

    @api.constrains('timeout')
    def _check_timeout(self):
        for rec in self:
            if not 1 <= (rec.timeout or 0) <= 60:
                raise ValidationError(_('The timeout must be between 1 and 60 seconds.'))

    @api.constrains('company_id', 'active')
    def _check_one_per_company(self):
        for rec in self.filtered('active'):
            if self.with_context(active_test=True).search_count([
                    ('id', '!=', rec.id), ('company_id', '=', rec.company_id.id)]):
                raise ValidationError(_('There is already a RIS connection for this company.'))

    # --- helpers reused later by the sync layer -------------------------
    def _rc_url(self, path=''):
        self.ensure_one()
        base = (self.base_url or '').strip().rstrip('/')
        path = (path or '').strip()
        return f"{base}/{path.lstrip('/')}" if path else base

    def _rc_headers(self):
        self.ensure_one()
        headers = {'Accept': 'application/json'}
        if self.auth_type == 'api_key':
            headers[self.api_key_header or 'X-API-Key'] = self.api_token or ''
        elif self.auth_type == 'bearer':
            headers['Authorization'] = 'Bearer %s' % (self.api_token or '')
        return headers

    def _rc_auth(self):
        self.ensure_one()
        if self.auth_type == 'basic':
            return HTTPBasicAuth(self.username or '', self.password or '')
        return None

    def _rc_request(self, path='', params=None, method='GET'):
        self.ensure_one()
        url = self._rc_url(path)
        rc_check_url(url)
        try:
            # redirects are not followed: a redirect could point to a blocked address
            return requests.request(
                method, url, headers=self._rc_headers(), auth=self._rc_auth(),
                params=params, timeout=min(self.timeout or 30, 60), verify=self.verify_ssl,
                allow_redirects=False)
        except requests.exceptions.RequestException as exc:
            # no raw error text: it would reveal what is reachable inside the network
            raise UserError(_('Connection failed (%s).', type(exc).__name__))

    def _notify(self, title, message, ok=True):
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': title, 'message': message,
                       'type': 'success' if ok else 'danger', 'sticky': not ok},
        }

    # --- buttons --------------------------------------------------------
    def action_test_connection(self):
        self.ensure_one()
        try:
            resp = self._rc_request(self.test_endpoint)
            ok = resp.status_code < 400
            msg = 'HTTP %s %s' % (resp.status_code, resp.reason or '')
        except UserError as exc:
            ok, msg = False, exc.args[0]
        self.write({
            'last_test_date': fields.Datetime.now(),
            'last_test_status': 'ok' if ok else 'failed',
            'last_test_message': msg,
        })
        return self._notify(_('RIS connection'), msg, ok)

    def action_fetch_samples(self):
        self.ensure_one()
        vals = {}
        for fname, path in (('sample_sales_order', self.endpoint_sales_order),
                            ('sample_invoice', self.endpoint_invoice),
                            ('sample_payment', self.endpoint_payment)):
            if not path:
                continue
            try:
                resp = self._rc_request(path)
                try:
                    data = resp.json()
                    if isinstance(data, list):
                        data = data[:2]
                    text = json.dumps(rc_mask(data), indent=2, ensure_ascii=False)
                except ValueError:
                    # unknown format: nothing from the body is stored
                    text = '(not JSON, %s bytes, body not stored)' % len(resp.content or b'')
                vals[fname] = 'HTTP %s\n%s' % (resp.status_code, text[:6000])
            except UserError as exc:
                vals[fname] = exc.args[0]
        vals['sample_date'] = fields.Datetime.now()
        self.write(vals)
        return self._notify(
            _('RIS samples'),
            _('Samples saved with patient values masked. They are cleared automatically after 24 hours.'))

    def action_clear_samples(self):
        self.write({'sample_sales_order': False, 'sample_invoice': False,
                    'sample_payment': False, 'sample_date': False})

    @api.model
    def _cron_clear_old_samples(self):
        limit = fields.Datetime.now() - timedelta(hours=24)
        self.search([('sample_date', '<', limit)]).action_clear_samples()
