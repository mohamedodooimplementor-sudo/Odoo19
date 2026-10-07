import logging
from datetime import datetime, time, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .perm import discount_cap, resolve

_logger = logging.getLogger(__name__)

WEEKDAYS = [('6', 'Sunday'), ('0', 'Monday'), ('1', 'Tuesday'), ('2', 'Wednesday'),
            ('3', 'Thursday'), ('4', 'Friday'), ('5', 'Saturday')]


PERM_SELECTION = [('default', 'Use global setting'), ('yes', 'Allowed'), ('no', 'Not allowed')]
PERMISSION_KEYS = (
    'allow_quotation', 'allow_sales_order', 'allow_discount', 'allow_price_change',
    'allow_invoice_creation', 'allow_direct_invoice', 'allow_payment',
    'allow_stock_view', 'allow_internal_transfer', 'allow_return',
    'allow_delivery_validation', 'allow_auto_validate',
    'allow_new_customer', 'allow_expense', 'allow_customer_return', 'allow_ranking',
)


class RepSettings:
    """The global portal settings as seen by ONE representative (his own overrides win)."""

    def __init__(self, settings, rep):
        self._settings = settings
        self._rep = rep

    def __getattr__(self, name):
        if name in PERMISSION_KEYS:
            return resolve(self._rep['perm_' + name], getattr(self._settings, name))
        if name == 'max_discount':
            return self._rep.effective_discount_cap()
        return getattr(self._settings, name)


class SalesRepPaymentMethod(models.Model):
    _name = 'mo.sales.rep.payment.method'
    _description = 'Sales Representative Payment Method'

    name = fields.Char(required=True)
    method_type = fields.Selection([('cash', 'Cash'), ('bank', 'Bank'), ('cheque', 'Cheque'), ('other', 'Other')],
                                   required=True, default='cash')
    journal_id = fields.Many2one('account.journal', required=True, domain=[('type', 'in', ('cash', 'bank'))])
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company)


class SalesRep(models.Model):
    _name = 'mo.sales.rep'
    _description = 'Sales Representative'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    user_id = fields.Many2one('res.users', 'Portal User', required=True, ondelete='restrict', tracking=True,
                              domain=[('share', '=', True)])
    partner_id = fields.Many2one('res.partner', related='user_id.partner_id', store=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company, required=True)
    customer_ids = fields.Many2many('res.partner', 'mo_sales_rep_partner_rel', 'rep_id', 'partner_id',
                                    string='Assigned Customers')
    can_view_all_customers = fields.Boolean('Can See All Customers',
                                            help='Supervisor mode: sees every customer, not only assigned ones.')
    warehouse_id = fields.Many2one('stock.warehouse', 'Sales Representative Warehouse (Van)', tracking=True)
    payment_method_ids = fields.Many2many('mo.sales.rep.payment.method', string='Allowed Payment Methods')
    max_discount = fields.Float('Max Discount % (0 = use the global maximum)', default=0.0,
                                help='When above zero this replaces the global maximum for this representative only '
                                     '(it can be higher or lower than the global value).')
    # Per-representative permissions: follow the global setting or override it for this rep only
    perm_allow_quotation = fields.Selection(PERM_SELECTION, 'Allow Quotation', default='default', required=True)
    perm_allow_sales_order = fields.Selection(PERM_SELECTION, 'Allow Sales Order', default='default', required=True)
    perm_allow_discount = fields.Selection(PERM_SELECTION, 'Allow Discount', default='default', required=True)
    perm_allow_price_change = fields.Selection(PERM_SELECTION, 'Allow Price Change', default='default', required=True)
    perm_allow_invoice_creation = fields.Selection(PERM_SELECTION, 'Allow Invoice Creation', default='default', required=True)
    perm_allow_direct_invoice = fields.Selection(PERM_SELECTION, 'Allow Invoice without Sales Order', default='default', required=True)
    perm_allow_payment = fields.Selection(PERM_SELECTION, 'Allow Payment Registration', default='default', required=True)
    perm_allow_stock_view = fields.Selection(PERM_SELECTION, 'Allow Stock View', default='default', required=True)
    perm_allow_internal_transfer = fields.Selection(PERM_SELECTION, 'Allow Internal Transfer', default='default', required=True)
    perm_allow_return = fields.Selection(PERM_SELECTION, 'Allow Return', default='default', required=True)
    perm_allow_delivery_validation = fields.Selection(PERM_SELECTION, 'Allow Delivery Validation', default='default', required=True)
    perm_allow_auto_validate = fields.Selection(PERM_SELECTION, 'Auto-validate Stock Operations', default='default', required=True,
                                                help='Validate stock operations and sale-order deliveries automatically when the stock is available.')
    perm_allow_new_customer = fields.Selection(PERM_SELECTION, 'Allow Creating Customers', default='default', required=True)
    perm_allow_expense = fields.Selection(PERM_SELECTION, 'Allow Expenses', default='default', required=True)
    perm_allow_customer_return = fields.Selection(PERM_SELECTION, 'Allow Customer Returns', default='default', required=True)
    perm_allow_ranking = fields.Selection(PERM_SELECTION, 'Can See the Ranking', default='default', required=True)
    team_id = fields.Many2one('crm.team', 'Sales Team')
    target_ids = fields.One2many('mo.sales.target', 'rep_id', 'Targets')
    route_ids = fields.One2many('mo.sales.route', 'rep_id')
    visit_count = fields.Integer(compute='_compute_counts')
    route_count = fields.Integer(compute='_compute_counts')

    @api.depends('route_ids')
    def _compute_counts(self):
        Visit = self.env['mo.sales.visit']
        for rep in self:
            rep.visit_count = Visit.search_count([('rep_id', '=', rep.id)])
            rep.route_count = len(rep.route_ids)

    @api.constrains('user_id')
    def _check_user(self):
        for rep in self:
            if not rep.user_id.share:
                raise ValidationError(_('The user of a sales representative must be a Portal user.'))
            if self.with_context(active_test=False).search_count([('user_id', '=', rep.user_id.id)]) > 1:
                raise ValidationError(_('This user is already linked to another sales representative.'))

    @api.model_create_multi
    def create(self, vals_list):
        reps = super().create(vals_list)
        reps._grant_group()
        return reps

    def write(self, vals):
        before = {rep.id: set(rep.customer_ids.ids) for rep in self} if 'customer_ids' in vals else {}
        res = super().write(vals)
        if 'user_id' in vals:
            self._grant_group()
        for rep in self:
            if rep.id in before:
                for partner in rep.customer_ids.filtered(lambda p: p.id not in before[rep.id]):
                    rep._notify(_('New customer assigned'), partner.display_name, '/rep/customer/%s' % partner.id,
                                key='assigned:%s' % partner.id)
        return res

    def _grant_group(self):
        group = self.env.ref('mo_sales_rep_portal.group_sales_rep_portal')
        for rep in self:
            field = 'group_ids' if 'group_ids' in rep.user_id._fields else 'groups_id'
            rep.user_id.sudo().write({field: [(4, group.id)]})

    # ------------------------------------------------------------------
    def customers_domain(self):
        self.ensure_one()
        if self.can_view_all_customers:
            return [('active', '=', True), ('parent_id', '=', False)]
        return ['|', ('id', 'in', self.customer_ids.ids), ('user_id', '=', self.user_id.id)]

    def get_customers(self):
        self.ensure_one()
        return self.env['res.partner'].sudo().search(self.customers_domain())

    def can_access_partner(self, partner_id):
        self.ensure_one()
        return bool(self.env['res.partner'].sudo().search_count(
            self.customers_domain() + [('id', '=', int(partner_id))]))

    # ---- permissions (global setting unless this representative overrides it) -------------
    def permission(self, key):
        self.ensure_one()
        return resolve(self['perm_' + key], self.env['mo.sales.rep.settings'].get_settings()[key])

    def portal_settings(self):
        """Global settings resolved for this representative (what the portal must use)."""
        self.ensure_one()
        return RepSettings(self.env['mo.sales.rep.settings'].get_settings(), self)

    def effective_discount_cap(self, settings=None):
        self.ensure_one()
        glob = self.env['mo.sales.rep.settings'].get_settings()
        return discount_cap(self.permission('allow_discount'), self.max_discount, glob.max_discount)

    def can_auto_validate(self, settings=None):
        return self.permission('allow_auto_validate')

    def can_change_price(self, settings=None):
        return self.permission('allow_price_change')

    def _notify(self, title, body='', url=False, key=False):
        """Create a portal notification (and an optional queued email). `key` makes it fire only once."""
        send_mail = self.env['mo.sales.rep.settings'].get_settings().notify_by_email
        Notification = self.env['mo.sales.rep.notification'].sudo()
        for rep in self:
            if key and Notification.search_count([('rep_id', '=', rep.id), ('key', '=', key)]):
                continue
            Notification.create({'rep_id': rep.id, 'name': title, 'body': body, 'url': url or False, 'key': key or False})
            email = rep.partner_id.email
            if send_mail and email:
                # queued only: the standard mail cron sends it, so a mail problem never blocks the business flow
                self.env['mail.mail'].sudo().create({
                    'subject': title, 'body_html': '<p>%s</p>' % (body or title),
                    'email_to': email, 'auto_delete': True,
                })

    def _audit(self, record, text):
        """Write who/what/when into the record's chatter (audit trail)."""
        for rep in self:
            try:
                if record and hasattr(record, 'message_post'):
                    record.sudo().message_post(
                        body=_('%(who)s (sales representative portal): %(what)s', who=rep.name, what=text),
                        message_type='comment', subtype_xmlid='mail.mt_note')
            except Exception as e:  # the audit trail must never block the operation
                _logger.info('Audit message skipped: %s', e)

    # ---- performance / targets -----------------------------------------------------------------
    def performance(self, d_from, d_to):
        """Actual figures of this representative between two dates."""
        self.ensure_one()
        env = self.env
        start, end = datetime.combine(d_from, time.min), datetime.combine(d_to, time.max)
        orders = env['sale.order'].sudo().search([
            ('state', 'in', ('sale', 'done')), '|', ('mo_rep_id', '=', self.id), ('user_id', '=', self.user_id.id),
            ('date_order', '>=', start), ('date_order', '<=', end)])
        pays = env['account.payment'].sudo().search([
            ('payment_type', '=', 'inbound'), ('state', 'not in', ('draft', 'canceled', 'rejected')),
            '|', ('mo_rep_id', '=', self.id), ('create_uid', '=', self.user_id.id),
            ('date', '>=', d_from), ('date', '<=', d_to)])
        return {
            'sales': sum(orders.mapped('amount_total')),
            'orders': len(orders),
            'collection': sum(pays.mapped('amount')),
            'visits': env['mo.sales.visit'].sudo().search_count([
                ('rep_id', '=', self.id), ('state', '=', 'completed'),
                ('visit_date', '>=', d_from), ('visit_date', '<=', d_to)]),
            'new_customers': env['res.partner'].sudo().search_count([
                ('mo_created_by_rep_id', '=', self.id), ('mo_approval_state', '!=', 'refused'),
                ('create_date', '>=', start), ('create_date', '<=', end)]),
        }

    def current_target(self, day=None):
        self.ensure_one()
        day = day or fields.Date.context_today(self)
        return self.env['mo.sales.target'].sudo().search([
            ('rep_id', '=', self.id), ('date_from', '<=', day), ('date_to', '>=', day)], order='date_from desc', limit=1)

    def _check_targets(self):
        """Notify (once) when a target is reached."""
        for rep in self:
            target = rep.current_target()
            if target:
                target._notify_if_achieved()

    # ---- visits generation (frequencies) -----------------------------------------------------------
    @staticmethod
    def _line_due(line, route, day):
        freq = line.frequency or 'weekly'
        anchor = line.start_date or (line.create_date.date() if line.create_date else day)
        if freq == 'daily':
            return True
        if freq == 'custom':
            step = max(line.interval_days or 7, 1)
            delta = (day - anchor).days
            return delta >= 0 and delta % step == 0
        if route.weekday != str(day.weekday()):
            return False
        if freq == 'weekly':
            return True
        if freq == 'biweekly':
            return ((day - anchor).days // 7) % 2 == 0
        if freq == 'monthly':      # same "nth weekday of the month" as the anchor (first one when no start date)
            nth = (anchor.day - 1) // 7 if line.start_date else 0
            return (day.day - 1) // 7 == nth
        return False

    def _generate_visits(self, day):
        """Create planned visits from the routes for the given date (idempotent)."""
        Visit = self.env['mo.sales.visit'].sudo().with_context(no_rep_notify=True)
        for rep in self:
            routes = self.env['mo.sales.route'].sudo().search([('rep_id', '=', rep.id), ('active', '=', True)])
            for route in routes:
                for line in route.line_ids:
                    if not self._line_due(line, route, day):
                        continue
                    if Visit.search_count([('rep_id', '=', rep.id), ('visit_date', '=', day),
                                           ('route_line_id', '=', line.id)]):
                        continue
                    Visit.create({
                        'rep_id': rep.id, 'partner_id': line.partner_id.id, 'route_line_id': line.id,
                        'visit_date': day, 'visit_type': 'sales', 'state': 'planned', 'purpose': line.note or False,
                    })

    @api.model
    def cron_notifications(self):
        """Daily reminders: follow-ups due, overdue invoices."""
        today = fields.Date.context_today(self)
        Followup = self.env['mo.sales.followup'].sudo()
        Move = self.env['account.move'].sudo()
        for rep in self.search([]):
            due = Followup.search([('rep_id', '=', rep.id), ('state', '=', 'open'), ('due_date', '<=', today)])
            for f in due:
                late = f.due_date < today
                rep._notify(_('Follow-up overdue') if late else _('Follow-up due'),
                            '%s - %s' % (f.partner_id.display_name, f.name), '/rep/followups',
                            key='followup:%s:%s' % (f.id, 'late' if late else 'due'))
            customers = rep.get_customers()
            invoices = Move.search([
                ('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('amount_residual', '>', 0),
                ('invoice_date_due', '<', today),
                '|', ('mo_rep_id', '=', rep.id), ('partner_id', 'in', customers.ids)], limit=200)
            for inv in invoices:
                rep._notify(_('Invoice overdue'), '%s - %s' % (inv.name, inv.partner_id.display_name),
                            '/rep/invoice/%s' % inv.id, key='overdue:%s' % inv.id)

    def action_open_visits(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Visits'), 'res_model': 'mo.sales.visit',
                'view_mode': 'list,form', 'domain': [('rep_id', '=', self.id)],
                'context': {'default_rep_id': self.id}}

    def action_open_routes(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Routes'), 'res_model': 'mo.sales.route',
                'view_mode': 'list,form', 'domain': [('rep_id', '=', self.id)],
                'context': {'default_rep_id': self.id}}
