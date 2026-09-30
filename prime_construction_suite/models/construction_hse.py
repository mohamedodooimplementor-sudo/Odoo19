# -*- coding: utf-8 -*-
from odoo import models, fields, api


class ConstructionHseIncident(models.Model):
    _name = 'construction.hse.incident'
    _description = 'Site Incident / Injury Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'date desc'

    name       = fields.Char(string='Reference', copy=False, readonly=True, default='New')
    project_id = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    date       = fields.Date(string='Date', required=True, default=fields.Date.today)

    incident_type = fields.Selection([
        ('near_miss',        'Near Miss'),
        ('injury',           'Injury'),
        ('property_damage',  'Property Damage'),
        ('fire',             'Fire'),
        ('environmental',    'Environmental'),
        ('other',            'Other'),
    ], string='Incident Type', required=True, default='near_miss')

    severity = fields.Selection([
        ('minor',    'Minor'),
        ('moderate', 'Moderate'),
        ('severe',   'Severe'),
        ('fatal',    'Fatal'),
    ], string='Severity', default='minor', required=True)

    description     = fields.Text(string='Description', required=True)
    location        = fields.Char(string='Location on Site')
    injured_person  = fields.Char(string='Injured Person (if any)')
    action_taken     = fields.Text(string='Immediate Action Taken')
    corrective_action = fields.Text(string='Corrective / Preventive Action')

    reported_by = fields.Many2one('res.users', string='Reported By', default=lambda self: self.env.user)
    status = fields.Selection([
        ('open',   'Open'),
        ('closed', 'Closed'),
    ], string='Status', default='open', tracking=True, required=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.hse.incident') or 'New'
        return super().create(vals_list)

    def action_close(self): self.write({'status': 'closed'})
    def action_reopen(self): self.write({'status': 'open'})


class ConstructionHsePermit(models.Model):
    _name = 'construction.hse.permit'
    _description = 'Work Permit'
    _inherit = ['mail.thread']
    _rec_name = 'name'
    _order = 'date_issued desc'

    name       = fields.Char(string='Permit No.', copy=False, readonly=True, default='New')
    project_id = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')

    permit_type = fields.Selection([
        ('hot_work',        'Hot Work'),
        ('confined_space',  'Confined Space'),
        ('working_at_height','Working at Height'),
        ('excavation',      'Excavation'),
        ('electrical',      'Electrical'),
        ('lifting',         'Lifting Operation'),
        ('other',           'Other'),
    ], string='Permit Type', required=True, default='hot_work')

    issued_to    = fields.Char(string='Issued To (Contractor/Worker)')
    date_issued  = fields.Date(string='Date Issued', required=True, default=fields.Date.today)
    valid_until  = fields.Date(string='Valid Until', required=True)
    approved_by  = fields.Many2one('res.users', string='Approved By')

    status = fields.Selection([
        ('active',  'Active'),
        ('expired', 'Expired'),
        ('closed',  'Closed'),
    ], string='Status', default='active', tracking=True, required=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.hse.permit') or 'New'
        return super().create(vals_list)

    def action_close(self): self.write({'status': 'closed'})

    def _cron_expire_permits(self):
        from datetime import date
        expired = self.search([('status', '=', 'active'), ('valid_until', '<', date.today())])
        expired.write({'status': 'expired'})


class ConstructionHseInspection(models.Model):
    _name = 'construction.hse.inspection'
    _description = 'Safety Equipment Inspection'
    _inherit = ['mail.thread']
    _rec_name = 'name'
    _order = 'date desc'

    name       = fields.Char(string='Reference', copy=False, readonly=True, default='New')
    project_id = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    equipment_id = fields.Many2one('construction.equipment', string='Equipment Inspected')
    item_description = fields.Char(string='Item Description (if not equipment)')

    date       = fields.Date(string='Inspection Date', required=True, default=fields.Date.today)
    inspector_id = fields.Many2one('res.users', string='Inspector', default=lambda self: self.env.user)

    result = fields.Selection([('pass', 'Pass'), ('fail', 'Fail')], string='Result', default='pass', required=True)
    notes  = fields.Text(string='Notes')
    next_inspection_date = fields.Date(string='Next Inspection Due')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.hse.inspection') or 'New'
        return super().create(vals_list)


class ConstructionHsePpe(models.Model):
    _name = 'construction.hse.ppe'
    _description = 'PPE Issuance & Tracking'
    _inherit = ['mail.thread']
    _rec_name = 'name'
    _order = 'date_issued desc'

    name = fields.Char(string='Reference', copy=False, readonly=True, default='New')
    project_id = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='project_id.company_id', store=True)

    employee_id = fields.Many2one('hr.employee', string='Employee')
    subcontractor_id = fields.Many2one('construction.subcontractor', string='Subcontractor')
    worker_name = fields.Char(string='Worker Name', help='Use when the worker is not registered as an Employee '
                                                          '(e.g. a subcontractor crew member).')

    ppe_type = fields.Selection([
        ('helmet',        'Safety Helmet'),
        ('safety_boots',  'Safety Boots'),
        ('gloves',        'Gloves'),
        ('safety_glasses','Safety Glasses'),
        ('ear_protection','Ear Protection'),
        ('harness',       'Safety Harness'),
        ('hi_vis_vest',   'Hi-Vis Vest'),
        ('respirator',    'Respirator / Mask'),
        ('other',         'Other'),
    ], string='PPE Type', required=True, default='helmet')

    quantity = fields.Integer(string='Quantity', default=1)
    date_issued = fields.Date(string='Date Issued', default=fields.Date.today, required=True)
    expiry_date = fields.Date(string='Expiry / Replacement Due')

    condition = fields.Selection([
        ('good',              'Good'),
        ('needs_replacement', 'Needs Replacement'),
        ('damaged',           'Damaged'),
    ], string='Condition', default='good', required=True)
    issued_by = fields.Many2one('res.users', string='Issued By', default=lambda s: s.env.user)
    notes = fields.Char(string='Notes')

    state = fields.Selection([
        ('draft',   'Draft'),
        ('issued',  'Issued'),
        ('expired', 'Expired'),
    ], default='draft', required=True, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.hse.ppe') or 'New'
        return super().create(vals_list)

    def action_issue(self):
        self.write({'state': 'issued'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    def _cron_expire_ppe(self):
        from datetime import date
        expired = self.search([('state', '=', 'issued'), ('expiry_date', '!=', False),
                                ('expiry_date', '<', date.today())])
        expired.write({'state': 'expired'})


class ConstructionHseTraining(models.Model):
    _name = 'construction.hse.training'
    _description = 'HSE Training / Toolbox Talk'
    _inherit = ['mail.thread']
    _rec_name = 'name'
    _order = 'date desc'

    name = fields.Char(string='Reference', copy=False, readonly=True, default='New')
    project_id = fields.Many2one('construction.project', string='Project', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='project_id.company_id', store=True)

    training_type = fields.Selection([
        ('induction',         'Site Induction'),
        ('toolbox_talk',      'Toolbox Talk'),
        ('first_aid',         'First Aid'),
        ('fire_safety',       'Fire Safety'),
        ('working_at_height', 'Working at Height'),
        ('confined_space',    'Confined Space'),
        ('other',             'Other'),
    ], string='Training Type', required=True, default='toolbox_talk')

    topic = fields.Char(string='Topic', required=True)
    date = fields.Date(string='Date', default=fields.Date.today, required=True)
    duration_hours = fields.Float(string='Duration (Hours)', default=1.0)
    trainer_id = fields.Many2one('res.users', string='Trainer', default=lambda s: s.env.user)

    attendee_ids = fields.One2many('construction.hse.training.attendee', 'training_id', string='Attendees')
    attendee_count = fields.Integer(compute='_compute_attendee_count')

    materials = fields.Binary(string='Training Materials / Handout')
    materials_filename = fields.Char(string='Filename')
    notes = fields.Text(string='Notes')

    state = fields.Selection([
        ('draft',     'Draft'),
        ('completed', 'Completed'),
    ], default='draft', required=True, tracking=True)

    @api.depends('attendee_ids')
    def _compute_attendee_count(self):
        for rec in self:
            rec.attendee_count = len(rec.attendee_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('construction.hse.training') or 'New'
        return super().create(vals_list)

    def action_complete(self):
        self.write({'state': 'completed'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})


class ConstructionHseTrainingAttendee(models.Model):
    _name = 'construction.hse.training.attendee'
    _description = 'HSE Training Attendee'

    training_id = fields.Many2one('construction.hse.training', ondelete='cascade')
    employee_id = fields.Many2one('hr.employee', string='Employee')
    worker_name = fields.Char(string='Worker Name (if not an Employee)')
    company_name = fields.Char(string='Company / Subcontractor')
    attended = fields.Boolean(string='Attended', default=True)

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            self.worker_name = self.employee_id.name
