# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ConstructionRisk(models.Model):
    _name = 'construction.risk'
    _description = 'Project Risk'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'risk_score desc'

    name       = fields.Char(string='Risk Description', required=True)
    project_id = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')

    category = fields.Selection([
        ('schedule',  'Schedule'),
        ('cost',      'Cost'),
        ('quality',   'Quality'),
        ('safety',    'Safety'),
        ('technical', 'Technical'),
        ('external',  'External (Weather, Regulatory, Market)'),
        ('other',     'Other'),
    ], string='Category', default='other', required=True)

    probability = fields.Selection([
        ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'),
    ], string='Probability', default='medium', required=True)

    impact = fields.Selection([
        ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'),
    ], string='Impact', default='medium', required=True)

    risk_score = fields.Integer(string='Risk Score', compute='_compute_risk_score', store=True,
                                 help='Probability x Impact, on a 1-9 scale. 6+ is high risk.')
    risk_level = fields.Selection([
        ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'),
    ], string='Risk Level', compute='_compute_risk_score', store=True)

    mitigation_plan = fields.Text(string='Mitigation Plan')
    owner_id        = fields.Many2one('res.users', string='Risk Owner')
    date_identified = fields.Date(string='Date Identified', default=fields.Date.today)

    status = fields.Selection([
        ('open',      'Open'),
        ('mitigated', 'Mitigated'),
        ('closed',    'Closed / No Longer Relevant'),
    ], string='Status', default='open', tracking=True, required=True)

    review_ids = fields.One2many('construction.risk.review', 'risk_id', string='Review History')
    review_count = fields.Integer(compute='_compute_review_info')
    last_reviewed_date = fields.Date(string='Last Reviewed', compute='_compute_review_info', store=True)
    next_review_date = fields.Date(string='Next Review Due')
    is_review_overdue = fields.Boolean(compute='_compute_review_info', store=True)

    _SCORE_MAP = {'low': 1, 'medium': 2, 'high': 3}

    @api.depends('review_ids.date', 'next_review_date', 'status')
    def _compute_review_info(self):
        today = fields.Date.today()
        for rec in self:
            rec.review_count = len(rec.review_ids)
            rec.last_reviewed_date = max(rec.review_ids.mapped('date')) if rec.review_ids else False
            rec.is_review_overdue = bool(
                rec.next_review_date and rec.status == 'open' and rec.next_review_date < today)

    @api.depends('probability', 'impact')
    def _compute_risk_score(self):
        for rec in self:
            score = self._SCORE_MAP.get(rec.probability, 1) * self._SCORE_MAP.get(rec.impact, 1)
            rec.risk_score = score
            rec.risk_level = 'high' if score >= 6 else ('medium' if score >= 3 else 'low')

    def action_mitigate(self): self.write({'status': 'mitigated'})
    def action_close(self):    self.write({'status': 'closed'})
    def action_reopen(self):   self.write({'status': 'open'})

    def action_new_review(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'New Risk Review',
            'res_model': 'construction.risk.review',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_risk_id': self.id,
                'default_probability': self.probability,
                'default_impact': self.impact,
            },
        }

    def action_view_reviews(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Review History',
            'res_model': 'construction.risk.review',
            'view_mode': 'list,form',
            'domain': [('risk_id', '=', self.id)],
        }

    def _cron_remind_overdue_reviews(self):
        overdue = self.search([('is_review_overdue', '=', True)])
        for rec in overdue:
            already = rec.activity_ids.filtered(lambda a: a.summary == 'Risk Review Overdue')
            if already:
                continue
            rec.activity_schedule(
                'mail.mail_activity_data_todo', summary='Risk Review Overdue',
                note='Risk "%s" is due for its periodic review (was due %s).' % (rec.name, rec.next_review_date),
                user_id=rec.owner_id.id or self.env.user.id,
            )


class ConstructionRiskReview(models.Model):
    _name = 'construction.risk.review'
    _description = 'Periodic Risk Review'
    _order = 'date desc, id desc'

    risk_id = fields.Many2one('construction.risk', required=True, ondelete='cascade')
    project_id = fields.Many2one(related='risk_id.project_id', store=True)
    date = fields.Date(string='Review Date', default=fields.Date.today, required=True)
    reviewer_id = fields.Many2one('res.users', string='Reviewed By', default=lambda s: s.env.user)

    probability = fields.Selection([
        ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'),
    ], string='Probability (at review time)')
    impact = fields.Selection([
        ('low', 'Low'), ('medium', 'Medium'), ('high', 'High'),
    ], string='Impact (at review time)')

    notes = fields.Text(string='Review Notes')
    next_review_date = fields.Date(string='Next Review Due')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            updates = {}
            if rec.probability:
                updates['probability'] = rec.probability
            if rec.impact:
                updates['impact'] = rec.impact
            if rec.next_review_date:
                updates['next_review_date'] = rec.next_review_date
            if updates:
                rec.risk_id.write(updates)
        return records
