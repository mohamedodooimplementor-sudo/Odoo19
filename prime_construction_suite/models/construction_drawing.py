# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionDrawing(models.Model):
    _name = 'construction.drawing'
    _description = 'Drawing / Shop Drawing Register'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'display_name'
    _order = 'drawing_number'

    project_id      = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    company_id      = fields.Many2one(related='project_id.company_id', store=True)
    drawing_number  = fields.Char(string='Drawing No.', required=True)
    name            = fields.Char(string='Title', required=True)
    display_name    = fields.Char(compute='_compute_display_name', store=True)

    discipline = fields.Selection([
        ('architectural', 'Architectural'),
        ('structural',    'Structural'),
        ('mep',           'MEP'),
        ('civil',         'Civil'),
        ('landscape',     'Landscape'),
        ('other',         'Other'),
    ], string='Discipline', default='architectural', required=True)

    status = fields.Selection([
        ('for_review',  'For Review'),
        ('approved',    'Approved'),
        ('approved_as_noted', 'Approved as Noted'),
        ('rejected',    'Rejected / Revise & Resubmit'),
    ], string='Status', default='for_review', tracking=True, required=True)

    ball_in_court = fields.Selection([
        ('contractor', 'Contractor'),
        ('consultant', 'Consultant'),
        ('client',     'Client'),
    ], string='Ball in Court', default='contractor', tracking=True, required=True,
       help='Who currently owns the next action on this drawing.')

    revision_ids     = fields.One2many('construction.drawing.revision', 'drawing_id', string='Revisions')
    current_revision_id = fields.Many2one('construction.drawing.revision', string='Current Revision',
                                           compute='_compute_current_revision', store=True)
    revision_count   = fields.Integer(compute='_compute_current_revision', store=True)

    @api.depends('drawing_number', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.drawing_number} - {rec.name}" if rec.drawing_number else rec.name

    @api.depends('revision_ids.date', 'revision_ids.sequence')
    def _compute_current_revision(self):
        for rec in self:
            revs = rec.revision_ids.sorted(key=lambda r: (r.sequence, r.date or fields.Date.today()))
            rec.current_revision_id = revs[-1].id if revs else False
            rec.revision_count = len(revs)

    def action_new_revision(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Revision'),
            'res_model': 'construction.drawing.revision',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_drawing_id': self.id, 'default_sequence': self.revision_count + 1},
        }

    def _sync_status_from_revision(self, revision):
        """Roll up the latest revision's approval state onto the drawing's overall status,
        only when that revision is indeed the current one."""
        self.ensure_one()
        if not (self.current_revision_id and self.current_revision_id.id == revision.id):
            return
        status_map = {
            'submitted': 'for_review',
            'approved': 'approved',
            'approved_as_noted': 'approved_as_noted',
            'rejected': 'rejected',
        }
        new_status = status_map.get(revision.state)
        if new_status:
            self.status = new_status


class ConstructionDrawingRevision(models.Model):
    _name = 'construction.drawing.revision'
    _description = 'Drawing Revision'
    _order = 'sequence desc'

    drawing_id   = fields.Many2one('construction.drawing', required=True, ondelete='cascade')
    sequence     = fields.Integer(string='Revision #', default=1)
    revision_code = fields.Char(string='Revision Code', help="e.g. Rev A, Rev 1, Rev 2")
    date         = fields.Date(string='Date', default=fields.Date.today)
    file         = fields.Binary(string='File', attachment=True)
    file_name    = fields.Char(string='File Name')
    uploaded_by  = fields.Many2one('res.users', string='Uploaded By', default=lambda self: self.env.user)
    notes        = fields.Text(string='Revision Notes')
    markup_ids   = fields.One2many('construction.drawing.markup', 'revision_id', string='Markup Comments')
    markup_count = fields.Integer(compute='_compute_markup_count')

    # ── Approval workflow (per-revision, since each revision goes through its own review cycle) ──
    state = fields.Selection([
        ('draft',     'Draft'),
        ('submitted', 'Submitted for Review'),
        ('approved',  'Approved'),
        ('approved_as_noted', 'Approved as Noted'),
        ('rejected',  'Rejected / Revise & Resubmit'),
    ], string='Review Status', default='draft', required=True, tracking=True)
    submitted_by    = fields.Many2one('res.users', string='Submitted By', readonly=True, copy=False)
    date_submitted  = fields.Date(string='Date Submitted', readonly=True, copy=False)
    reviewed_by     = fields.Many2one('res.users', string='Reviewed By', readonly=True, copy=False)
    date_reviewed   = fields.Date(string='Date Reviewed', readonly=True, copy=False)
    review_comments = fields.Text(string='Review Comments')

    def _compute_markup_count(self):
        for rec in self:
            rec.markup_count = len(rec.markup_ids)

    def action_submit_for_review(self):
        for rec in self:
            rec.write({
                'state': 'submitted',
                'submitted_by': self.env.user.id,
                'date_submitted': fields.Date.today(),
            })
            rec.drawing_id._sync_status_from_revision(rec)

    def action_approve(self):
        for rec in self:
            rec.write({
                'state': 'approved',
                'reviewed_by': self.env.user.id,
                'date_reviewed': fields.Date.today(),
            })
            rec.drawing_id.write({'ball_in_court': 'contractor'})
            rec.drawing_id._sync_status_from_revision(rec)

    def action_approve_as_noted(self):
        for rec in self:
            rec.write({
                'state': 'approved_as_noted',
                'reviewed_by': self.env.user.id,
                'date_reviewed': fields.Date.today(),
            })
            rec.drawing_id.write({'ball_in_court': 'contractor'})
            rec.drawing_id._sync_status_from_revision(rec)

    def action_reject(self):
        for rec in self:
            rec.write({
                'state': 'rejected',
                'reviewed_by': self.env.user.id,
                'date_reviewed': fields.Date.today(),
            })
            rec.drawing_id.write({'ball_in_court': 'contractor'})
            rec.drawing_id._sync_status_from_revision(rec)

    def action_reset_draft(self):
        self.write({'state': 'draft', 'submitted_by': False, 'date_submitted': False,
                    'reviewed_by': False, 'date_reviewed': False})


class ConstructionDrawingMarkup(models.Model):
    _name = 'construction.drawing.markup'
    _description = 'Drawing Markup Comment (pinned to a point on the drawing image)'
    _order = 'create_date desc'

    revision_id = fields.Many2one('construction.drawing.revision', required=True, ondelete='cascade')
    pos_x       = fields.Float(string='X Position (%)', help='0-100, percentage from left edge of the image.')
    pos_y       = fields.Float(string='Y Position (%)', help='0-100, percentage from top edge of the image.')
    comment     = fields.Char(string='Comment', required=True)
    author_id   = fields.Many2one('res.users', string='Author', default=lambda self: self.env.user)
    resolved    = fields.Boolean(string='Resolved', default=False)
