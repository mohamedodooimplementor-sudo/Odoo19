# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionSubcontractor(models.Model):
    _name = 'construction.subcontractor'
    _description = 'Subcontractor'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'date_start desc'

    name        = fields.Char(string='Subcontract No.', required=True, copy=False, readonly=True, default='New')
    project_id  = fields.Many2one('construction.project',  string='Project',  required=True)
    contract_id = fields.Many2one('construction.contract', string='Main Contract', domain="[('project_id','=',project_id)]")
    partner_id  = fields.Many2one('res.partner', string='Subcontractor', required=True)
    currency_id = fields.Many2one(related='project_id.currency_id', store=True)
    company_id  = fields.Many2one(related='project_id.company_id',  store=True)

    scope_of_work  = fields.Text(string='Scope of Work', required=True)
    specialization = fields.Selection([
        ('civil',      'Civil Works'),
        ('electrical', 'Electrical'),
        ('mechanical', 'Mechanical'),
        ('finishing',  'Finishing'),
        ('plumbing',   'Plumbing'),
        ('hvac',       'HVAC'),
        ('it',         'IT & Telecom'),
        ('other',      'Other'),
    ], string='Specialization', required=True, default='civil')

    date_start = fields.Date(string='Start Date', required=True)
    date_end   = fields.Date(string='End Date')

    contract_value    = fields.Monetary(string='Subcontract Value', currency_field='currency_id', required=True)
    retention_percent = fields.Float(string='Retention %', default=10.0)
    paid_amount       = fields.Monetary(string='Amount Paid',      currency_field='currency_id', compute='_compute_paid', store=True)
    remaining_amount  = fields.Monetary(string='Remaining Balance', currency_field='currency_id', compute='_compute_paid', store=True)
    retention_held         = fields.Monetary(string='Retention Held', currency_field='currency_id', compute='_compute_paid', store=True)
    retention_released_amt = fields.Monetary(string='Retention Released', currency_field='currency_id', compute='_compute_paid', store=True)
    retention_outstanding  = fields.Monetary(string='Retention Outstanding', currency_field='currency_id', compute='_compute_paid', store=True)

    performance_rating = fields.Selection([
        ('5', 'Excellent'),
        ('4', 'Good'),
        ('3', 'Average'),
        ('2', 'Below Average'),
        ('1', 'Poor'),
    ], string='Performance Rating')
    rating_notes = fields.Text(string='Rating Notes')

    daily_penalty_rate = fields.Monetary(
        string='Daily Delay Penalty Rate', currency_field='currency_id',
        help='Penalty (Liquidated Damages) charged per day of delay beyond the subcontract end date. '
             'Used to auto-suggest a penalty amount when logging a delay.')

    evaluation_ids  = fields.One2many('construction.subcontractor.evaluation', 'subcontractor_id', string='Evaluations')
    evaluation_count = fields.Integer(compute='_compute_performance')
    average_evaluation_score = fields.Float(
        string='Average Evaluation (1-5)', compute='_compute_performance', store=True)

    completion_percent = fields.Float(
        string='Completion %', compute='_compute_performance', store=True,
        help='Weighted average physical completion of the BOQ items assigned to this subcontractor, '
             'based on approved Measurement Sheets.')

    penalty_ids     = fields.One2many('construction.subcontractor.penalty', 'subcontractor_id', string='Penalties')
    total_penalties = fields.Monetary(
        string='Total Applied Penalties', currency_field='currency_id', compute='_compute_performance', store=True)

    delay_days = fields.Integer(
        string='Current Delay (Days)', compute='_compute_performance', store=True,
        help='Days past the subcontract end date, for subcontracts still Active.')

    performance_score = fields.Float(
        string='Performance Score (0-100)', compute='_compute_performance', store=True,
        help='Blended score: 50% average evaluation, 30% schedule adherence, 20% penalty impact. '
             'A simple heuristic meant as a starting point — adjust the weighting to fit your operation.')

    @api.depends('evaluation_ids.overall_score', 'boq_line_ids.physical_completion_percent',
                 'boq_line_ids.total_price', 'penalty_ids.amount', 'penalty_ids.state',
                 'date_end', 'state', 'contract_value')
    def _compute_performance(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.evaluation_count = len(rec.evaluation_ids)
            rec.average_evaluation_score = (
                sum(rec.evaluation_ids.mapped('overall_score')) / len(rec.evaluation_ids)
                if rec.evaluation_ids else 0.0)

            boq_val = sum(rec.boq_line_ids.mapped('total_price'))
            rec.completion_percent = (
                sum(l.total_price * l.physical_completion_percent for l in rec.boq_line_ids) / boq_val
                if boq_val else 0.0)

            applied = rec.penalty_ids.filtered(lambda p: p.state == 'applied')
            rec.total_penalties = sum(applied.mapped('amount'))

            rec.delay_days = (
                (today - rec.date_end).days
                if rec.state == 'active' and rec.date_end and rec.date_end < today else 0)

            eval_component = (rec.average_evaluation_score / 5.0 * 100) if rec.average_evaluation_score else 70.0
            schedule_component = max(0.0, 100 - rec.delay_days * 2)
            penalty_ratio = (rec.total_penalties / rec.contract_value * 100) if rec.contract_value else 0.0
            penalty_component = max(0.0, 100 - penalty_ratio * 5)
            rec.performance_score = round(
                eval_component * 0.5 + schedule_component * 0.3 + penalty_component * 0.2, 1)

    state = fields.Selection([
        ('draft',     'Draft'),
        ('active',    'Active'),
        ('completed', 'Completed'),
        ('terminated','Terminated'),
    ], default='draft', tracking=True)

    purchase_order_ids = fields.Many2many('purchase.order', string='Purchase Orders',
                                           domain="[('partner_id','=',partner_id)]")
    payment_ids        = fields.One2many('construction.subcontractor.payment', 'subcontractor_id', string='Payments')
    boq_line_ids       = fields.Many2many('construction.boq.line', string='Assigned BOQ Items',
                                           domain="[('contract_id','=',contract_id)]")

    purchase_count = fields.Integer(compute='_compute_counts')
    payment_count  = fields.Integer(compute='_compute_counts')

    @api.depends('payment_ids.amount', 'payment_ids.net_amount', 'payment_ids.state',
                 'payment_ids.retention_amount', 'payment_ids.retention_released')
    def _compute_paid(self):
        for rec in self:
            paid = rec.payment_ids.filtered(lambda p: p.state == 'paid')
            rec.paid_amount      = sum(paid.mapped('net_amount'))
            rec.remaining_amount = rec.contract_value - rec.paid_amount
            rec.retention_held         = sum(paid.mapped('retention_amount'))
            released = paid.filtered('retention_released')
            rec.retention_released_amt = sum(released.mapped('retention_amount'))
            rec.retention_outstanding  = rec.retention_held - rec.retention_released_amt

    @api.depends('purchase_order_ids', 'payment_ids')
    def _compute_counts(self):
        for rec in self:
            rec.purchase_count = len(rec.purchase_order_ids)
            rec.payment_count  = len(rec.payment_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.subcontractor') or 'New'
        return super().create(vals_list)

    def action_activate(self):  self.write({'state': 'active'})
    def action_complete(self):  self.write({'state': 'completed'})
    def action_terminate(self): self.write({'state': 'terminated'})

    def action_create_purchase_order(self):
        self.ensure_one()
        po = self.env['purchase.order'].create({
            'partner_id': self.partner_id.id,
            'company_id': self.company_id.id,
            'notes': _('Subcontract: %s - Project: %s') % (self.name, self.project_id.name),
        })
        self.purchase_order_ids = [(4, po.id)]
        return {'type':'ir.actions.act_window','res_model':'purchase.order','res_id':po.id,'view_mode':'form'}

    def action_view_purchases(self):
        return {'type':'ir.actions.act_window','res_model':'purchase.order',
                'view_mode':'list,form','domain':[('id','in',self.purchase_order_ids.ids)]}

    def action_view_evaluations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Evaluations'),
            'res_model': 'construction.subcontractor.evaluation',
            'view_mode': 'list,form',
            'domain': [('subcontractor_id', '=', self.id)],
            'context': {'default_subcontractor_id': self.id},
        }

    def action_new_evaluation(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Evaluation'),
            'res_model': 'construction.subcontractor.evaluation',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_subcontractor_id': self.id},
        }


class ConstructionSubcontractorEvaluation(models.Model):
    _name = 'construction.subcontractor.evaluation'
    _description = 'Subcontractor Performance Evaluation'
    _order = 'date desc'

    _RATING = [
        ('5', 'Excellent'),
        ('4', 'Good'),
        ('3', 'Average'),
        ('2', 'Below Average'),
        ('1', 'Poor'),
    ]

    subcontractor_id = fields.Many2one('construction.subcontractor', required=True, ondelete='cascade')
    project_id  = fields.Many2one(related='subcontractor_id.project_id', store=True)
    date        = fields.Date(string='Evaluation Date', default=fields.Date.today, required=True)
    evaluator_id = fields.Many2one('res.users', string='Evaluated By', default=lambda s: s.env.user)

    quality_score       = fields.Selection(_RATING, string='Quality of Work', required=True)
    schedule_score      = fields.Selection(_RATING, string='Schedule Adherence', required=True)
    safety_score        = fields.Selection(_RATING, string='Safety Compliance', required=True)
    cooperation_score   = fields.Selection(_RATING, string='Cooperation & Responsiveness', required=True)
    documentation_score = fields.Selection(_RATING, string='Documentation Quality', required=True)
    overall_score       = fields.Float(string='Overall Score (1-5)', compute='_compute_overall', store=True)
    notes = fields.Text(string='Notes')

    @api.depends('quality_score', 'schedule_score', 'safety_score', 'cooperation_score', 'documentation_score')
    def _compute_overall(self):
        for rec in self:
            values = [int(v) for v in (
                rec.quality_score, rec.schedule_score, rec.safety_score,
                rec.cooperation_score, rec.documentation_score) if v]
            rec.overall_score = round(sum(values) / len(values), 2) if values else 0.0


class ConstructionSubcontractorPenalty(models.Model):
    _name = 'construction.subcontractor.penalty'
    _description = 'Subcontractor Delay Penalty (Liquidated Damages)'
    _inherit = ['mail.thread']
    _order = 'date desc'

    subcontractor_id = fields.Many2one('construction.subcontractor', required=True, ondelete='cascade')
    currency_id = fields.Many2one(related='subcontractor_id.currency_id', store=True)
    project_id  = fields.Many2one(related='subcontractor_id.project_id', store=True)
    date        = fields.Date(string='Date', default=fields.Date.today, required=True)
    reason      = fields.Char(string='Reason', required=True)
    delay_days  = fields.Integer(string='Delay Days')
    amount      = fields.Monetary(string='Penalty Amount', currency_field='currency_id', required=True)
    state = fields.Selection([
        ('draft',   'Draft'),
        ('applied', 'Applied'),
        ('waived',  'Waived'),
    ], default='draft', required=True, tracking=True)
    notes = fields.Text(string='Notes')

    @api.onchange('delay_days')
    def _onchange_delay_days(self):
        if self.delay_days and self.subcontractor_id.daily_penalty_rate:
            self.amount = self.delay_days * self.subcontractor_id.daily_penalty_rate

    def action_apply(self):
        self.write({'state': 'applied'})

    def action_waive(self):
        self.write({'state': 'waived'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})


class ConstructionSubcontractorPayment(models.Model):
    _name = 'construction.subcontractor.payment'
    _description = 'Subcontractor Payment'
    _inherit = ['mail.thread']
    _order = 'date desc'

    subcontractor_id = fields.Many2one('construction.subcontractor', ondelete='cascade')
    currency_id      = fields.Many2one(related='subcontractor_id.currency_id', store=True)
    name           = fields.Char(string='Description', required=True)
    date           = fields.Date(string='Date', required=True, default=fields.Date.today)
    due_date       = fields.Date(string='Due Date', compute='_compute_due_date', store=True, readonly=False,
                                  help='Defaults to 30 days after the payment date; editable per payment term.')
    amount         = fields.Monetary(string='Gross Amount', currency_field='currency_id', required=True)
    wht_percent    = fields.Float(string='WHT %', default=1.0, help='Withholding tax percentage deducted from the subcontractor payment.')
    wht_amount     = fields.Monetary(string='WHT Amount', currency_field='currency_id', compute='_compute_wht', store=True)
    retention_percent = fields.Float(string='Retention %', compute='_compute_retention_percent', store=True, readonly=False,
                                      help='Defaults to the subcontract\'s retention %; deducted from this payment and held until released.')
    retention_amount  = fields.Monetary(string='Retention Withheld', currency_field='currency_id', compute='_compute_wht', store=True)
    net_amount     = fields.Monetary(string='Net Payable', currency_field='currency_id', compute='_compute_wht', store=True,
                                      help='Gross Amount - WHT - Retention Withheld = actual cash paid to the subcontractor.')
    retention_released     = fields.Boolean(string='Retention Released', copy=False, tracking=True)
    retention_release_date = fields.Date(string='Retention Release Date', copy=False, tracking=True)
    retention_released_by  = fields.Many2one('res.users', string='Released By', copy=False, readonly=True)
    state          = fields.Selection([('draft','Draft'),('paid','Paid')], default='draft', tracking=True)
    payment_method = fields.Selection([('bank','Bank Transfer'),('check','Check'),('cash','Cash')],
                                       string='Payment Method', default='bank')
    notes = fields.Text(string='Notes')

    aging_days   = fields.Integer(string='Days Overdue', compute='_compute_aging')
    aging_bucket = fields.Selection([
        ('current', 'Not Due Yet'),
        ('b1_30',   '1-30 Days'),
        ('b31_60',  '31-60 Days'),
        ('b61_90',  '61-90 Days'),
        ('b90_plus','Over 90 Days'),
    ], string='Aging Bucket', compute='_compute_aging', store=True)

    @api.depends('date')
    def _compute_due_date(self):
        from datetime import timedelta
        for rec in self:
            if not rec.due_date and rec.date:
                rec.due_date = rec.date + timedelta(days=30)

    @api.depends('due_date', 'state')
    def _compute_aging(self):
        from datetime import date
        today = date.today()
        for rec in self:
            if rec.state == 'paid' or not rec.due_date:
                rec.aging_days = 0
                rec.aging_bucket = 'current'
                continue
            days = (today - rec.due_date).days
            rec.aging_days = max(days, 0)
            if days <= 0:
                rec.aging_bucket = 'current'
            elif days <= 30:
                rec.aging_bucket = 'b1_30'
            elif days <= 60:
                rec.aging_bucket = 'b31_60'
            elif days <= 90:
                rec.aging_bucket = 'b61_90'
            else:
                rec.aging_bucket = 'b90_plus'

    @api.depends('subcontractor_id.retention_percent')
    def _compute_retention_percent(self):
        for rec in self:
            if not rec.retention_percent:
                rec.retention_percent = rec.subcontractor_id.retention_percent

    @api.depends('amount', 'wht_percent', 'retention_percent')
    def _compute_wht(self):
        for rec in self:
            rec.wht_amount = rec.amount * rec.wht_percent / 100
            rec.retention_amount = rec.amount * rec.retention_percent / 100
            rec.net_amount = rec.amount - rec.wht_amount - rec.retention_amount

    def action_mark_paid(self): self.write({'state': 'paid'})

    def action_release_retention(self):
        for rec in self:
            if rec.state != 'paid':
                raise UserError(_('Retention can only be released for payments already marked Paid.'))
            if not rec.retention_amount:
                raise UserError(_('There is no retention amount to release for this payment.'))
            rec.write({
                'retention_released': True,
                'retention_release_date': fields.Date.today(),
                'retention_released_by': self.env.user.id,
            })
