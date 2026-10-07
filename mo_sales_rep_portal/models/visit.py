from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

VISIT_TYPES = [('sales', 'Sales Visit'), ('collection', 'Collection Visit'), ('delivery', 'Delivery Visit'),
               ('follow_up', 'Follow Up'), ('complaint', 'Complaint'), ('other', 'Other')]
VISIT_RESULTS = [('order', 'Order Created'), ('collected', 'Payment Collected'),
                 ('not_available', 'Customer Not Available'), ('no_order', 'No Order'),
                 ('follow_up', 'Follow-up Required'), ('opportunity', 'New Customer Opportunity'),
                 ('complaint', 'Complaint'), ('other', 'Other')]


class SalesVisit(models.Model):
    _name = 'mo.sales.visit'
    _description = 'Customer Visit'
    _inherit = ['mail.thread']
    _order = 'visit_date desc, id desc'

    name = fields.Char(default='New', readonly=True, copy=False)
    rep_id = fields.Many2one('mo.sales.rep', 'Sales Representative', required=True, tracking=True)
    partner_id = fields.Many2one('res.partner', 'Customer', required=True, tracking=True)
    route_line_id = fields.Many2one('mo.sales.route.line', 'Route Stop', ondelete='set null')
    route_id = fields.Many2one(related='route_line_id.route_id', store=True)
    day_sequence = fields.Integer('Optimized Order', default=0, copy=False,
                                  help='Set by the portal route optimizer for the remaining visits of the day.')
    visit_date = fields.Date(default=fields.Date.context_today, required=True)
    visit_type = fields.Selection(VISIT_TYPES, default='sales', required=True)
    state = fields.Selection([('planned', 'Planned'), ('started', 'Started'), ('completed', 'Completed'),
                              ('cancelled', 'Cancelled'), ('missed', 'Missed')],
                             default='planned', required=True, tracking=True)
    start_time = fields.Datetime(readonly=True)
    end_time = fields.Datetime(readonly=True)
    start_latitude = fields.Float(digits=(10, 7), readonly=True)
    start_longitude = fields.Float(digits=(10, 7), readonly=True)
    end_latitude = fields.Float(digits=(10, 7), readonly=True)
    end_longitude = fields.Float(digits=(10, 7), readonly=True)
    result = fields.Selection(VISIT_RESULTS, 'Visit Result')
    notes = fields.Text()
    next_visit_date = fields.Date()
    next_followup_date = fields.Date('Next Follow-up Date')
    purpose = fields.Char('Planned Purpose')
    followup_ids = fields.One2many('mo.sales.followup', 'visit_id')
    expense_ids = fields.One2many('mo.sales.expense', 'visit_id')
    duration = fields.Float('Duration (h)', compute='_compute_duration', store=True)
    source = fields.Selection([('backend', 'Backend'), ('portal', 'Portal')], default='backend')
    company_id = fields.Many2one('res.company', related='rep_id.company_id', store=True)
    sale_order_ids = fields.One2many('sale.order', 'mo_visit_id')
    invoice_ids = fields.One2many('account.move', 'mo_visit_id')
    payment_ids = fields.One2many('account.payment', 'mo_visit_id')
    attachment_count = fields.Integer(compute='_compute_attachment_count')
    start_map_url = fields.Char(compute='_compute_map_url')

    @api.depends('start_time', 'end_time')
    def _compute_duration(self):
        for rec in self:
            if rec.start_time and rec.end_time:
                rec.duration = (rec.end_time - rec.start_time).total_seconds() / 3600.0
            else:
                rec.duration = 0.0

    def _compute_attachment_count(self):
        Att = self.env['ir.attachment'].sudo()
        for rec in self:
            rec.attachment_count = Att.search_count([('res_model', '=', self._name), ('res_id', '=', rec.id)])

    @api.depends('start_latitude', 'start_longitude')
    def _compute_map_url(self):
        for rec in self:
            rec.start_map_url = ('https://www.google.com/maps?q=%s,%s' % (rec.start_latitude, rec.start_longitude)
                                 if rec.start_latitude or rec.start_longitude else False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('mo.sales.visit') or 'New'
        visits = super().create(vals_list)
        if not self.env.context.get('no_rep_notify'):
            for v in visits:
                if self.env.uid != v.rep_id.user_id.id:
                    v.rep_id._notify(_('New visit'), _('Visit to %s on %s', v.partner_id.display_name, v.visit_date),
                                     '/rep/visit/%s' % v.id)
        return visits

    # ------------------------------------------------------------------
    @api.model
    def _sane_time(self, when):
        """A device timestamp (offline queue) is accepted only when it is plausible."""
        now = fields.Datetime.now()
        if when and now - timedelta(days=3) <= when <= now + timedelta(minutes=5):
            return when
        return now

    @staticmethod
    def _gps_text(lat, lng):
        if lat or lng:
            return _('GPS %(lat).6f, %(lng).6f', lat=lat, lng=lng)
        return _('no GPS')

    def action_start(self, lat=0.0, lng=0.0, when=None):
        for v in self:
            if v.state not in ('planned', 'missed'):
                raise UserError(_('Only a planned visit can be started.'))
            v.write({'state': 'started', 'start_time': self._sane_time(when),
                     'start_latitude': lat or 0.0, 'start_longitude': lng or 0.0})
            v.message_post(body=_('Visit started - %s', self._gps_text(lat, lng)), subtype_xmlid='mail.mt_note')

    def action_end(self, lat=0.0, lng=0.0, result=False, notes=False, next_visit_date=False,
                   next_followup_date=False, when=None):
        for v in self:
            if v.state != 'started':
                raise UserError(_('Only a started visit can be ended.'))
            vals = {'state': 'completed', 'end_time': self._sane_time(when),
                    'end_latitude': lat or 0.0, 'end_longitude': lng or 0.0,
                    'result': result or False, 'next_visit_date': next_visit_date or False,
                    'next_followup_date': next_followup_date or False}
            if notes:
                vals['notes'] = ((v.notes + '\n') if v.notes else '') + notes
            v.write(vals)
            v.message_post(body=_('Visit finished - %s', self._gps_text(lat, lng)), subtype_xmlid='mail.mt_note')
            if next_followup_date:
                self.env['mo.sales.followup'].sudo().create({
                    'name': _('Follow-up after visit %s', v.name), 'rep_id': v.rep_id.id, 'partner_id': v.partner_id.id,
                    'due_date': next_followup_date, 'visit_id': v.id, 'notes': notes or False})

    def add_note(self, text):
        for v in self:
            stamp = fields.Datetime.context_timestamp(v, fields.Datetime.now()).strftime('%H:%M')
            v.notes = ((v.notes + '\n') if v.notes else '') + '[%s] %s' % (stamp, text)

    def action_cancel(self):
        for v in self:
            if v.state in ('completed',):
                raise UserError(_('A completed visit cannot be cancelled.'))
        self.write({'state': 'cancelled'})

    def action_reset(self):
        self.filtered(lambda v: v.state in ('cancelled', 'missed')).write({'state': 'planned'})

    def action_open_attachments(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Attachments'), 'res_model': 'ir.attachment',
                'view_mode': 'list,form', 'domain': [('res_model', '=', self._name), ('res_id', '=', self.id)],
                'context': {'default_res_model': self._name, 'default_res_id': self.id}}

    @api.model
    def cron_daily(self):
        today = fields.Date.context_today(self)
        late = self.search([('state', '=', 'planned'), ('visit_date', '<', today)])
        late.write({'state': 'missed'})
        for v in late:
            v.rep_id._notify(_('Visit overdue'), '%s - %s' % (v.partner_id.display_name, v.visit_date),
                             '/rep/visit/%s' % v.id, key='missed:%s' % v.id)
        reps = self.env['mo.sales.rep'].search([])
        for offset in range(0, 7):          # plan a week ahead
            reps._generate_visits(today + timedelta(days=offset))
        reps.cron_notifications()


class SalesRepLocation(models.Model):
    _name = 'mo.sales.rep.location'
    _description = 'Sales Representative Location Log'
    _order = 'timestamp desc'

    rep_id = fields.Many2one('mo.sales.rep', required=True, ondelete='cascade')
    visit_id = fields.Many2one('mo.sales.visit', ondelete='cascade')
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    timestamp = fields.Datetime(default=fields.Datetime.now)
