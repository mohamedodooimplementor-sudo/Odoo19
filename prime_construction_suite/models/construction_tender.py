# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionTender(models.Model):
    _name = 'construction.tender'
    _description = 'Subcontractor Tender / Bid Package'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'submission_deadline'

    name        = fields.Char(string='Reference', required=True, copy=False, default='New')
    project_id  = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    trade       = fields.Char(string='Scope / Trade', required=True, help="e.g. 'Structural Steel Works'")
    description = fields.Text(string='Scope Description')
    boq_line_ids = fields.Many2many('construction.boq.line', string='Related BOQ Items',
                                     domain="[('contract_id.project_id','=',project_id)]")

    submission_deadline = fields.Date(string='Submission Deadline', required=True)
    state = fields.Selection([
        ('draft',    'Draft'),
        ('open',     'Open for Bids'),
        ('closed',   'Bidding Closed'),
        ('awarded',  'Awarded'),
        ('cancelled','Cancelled'),
    ], string='Status', default='draft', tracking=True, required=True)

    bid_ids       = fields.One2many('construction.tender.bid', 'tender_id', string='Bids')
    bid_count     = fields.Integer(compute='_compute_bid_count')
    lowest_bid    = fields.Monetary(string='Lowest Bid', currency_field='currency_id', compute='_compute_bid_count')
    currency_id   = fields.Many2one(related='project_id.currency_id', store=True)
    awarded_bid_id = fields.Many2one('construction.tender.bid', string='Awarded Bid', copy=False, readonly=True)

    @api.depends('bid_ids.bid_amount', 'bid_ids.state')
    def _compute_bid_count(self):
        for rec in self:
            valid = rec.bid_ids.filtered(lambda b: b.state != 'withdrawn')
            rec.bid_count = len(valid)
            rec.lowest_bid = min(valid.mapped('bid_amount')) if valid else 0.0

    def action_open_for_bids(self):
        self.write({'state': 'open'})

    def action_close_bidding(self):
        self.write({'state': 'closed'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.tender') or 'New'
        return super().create(vals_list)


class ConstructionTenderBid(models.Model):
    _name = 'construction.tender.bid'
    _description = 'Subcontractor Bid'
    _order = 'bid_amount'

    tender_id      = fields.Many2one('construction.tender', required=True, ondelete='cascade')
    partner_id     = fields.Many2one('res.partner', string='Bidder', required=True, domain=[('is_company', '=', True)])
    currency_id    = fields.Many2one(related='tender_id.currency_id', store=True)
    bid_amount     = fields.Monetary(string='Bid Amount', currency_field='currency_id', required=True)
    submission_date = fields.Date(string='Submission Date', default=fields.Date.today)
    proposed_duration_days = fields.Integer(string='Proposed Duration (Days)')
    notes          = fields.Text(string='Notes')

    state = fields.Selection([
        ('submitted',   'Submitted'),
        ('shortlisted', 'Shortlisted'),
        ('awarded',     'Awarded'),
        ('rejected',    'Rejected'),
        ('withdrawn',   'Withdrawn'),
    ], string='Status', default='submitted', required=True, tracking=True)

    def action_shortlist(self): self.write({'state': 'shortlisted'})
    def action_reject(self):    self.write({'state': 'rejected'})

    def action_award(self):
        self.ensure_one()
        if self.tender_id.state not in ('open', 'closed'):
            raise UserError(_('The tender must be open or closed before awarding a bid.'))
        other_bids = self.tender_id.bid_ids - self
        other_bids.filtered(lambda b: b.state not in ('withdrawn', 'rejected')).write({'state': 'rejected'})
        self.state = 'awarded'
        self.tender_id.write({'state': 'awarded', 'awarded_bid_id': self.id})

    def action_create_subcontractor(self):
        """Convert the awarded bid into an actual Subcontractor record."""
        self.ensure_one()
        if self.state != 'awarded':
            raise UserError(_('Only an awarded bid can be converted into a subcontractor.'))
        subcontractor = self.env['construction.subcontractor'].create({
            'project_id': self.tender_id.project_id.id,
            'partner_id': self.partner_id.id,
            'scope_of_work': self.tender_id.trade,
            'contract_value': self.bid_amount,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Subcontractor'),
            'res_model': 'construction.subcontractor',
            'view_mode': 'form',
            'res_id': subcontractor.id,
        }
