from odoo import api, fields, models
from odoo.exceptions import UserError


class AuditorPlan(models.Model):
    _name = 'odoo.auditor.plan'
    _description = 'Audit Plan'
    _inherit = ['odoo.auditor.logged.mixin', 'mail.thread']
    _order = 'date_start desc'
    _log_fields = ('state', 'lead_user_id')

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    title = fields.Char(required=True)
    fiscal_year = fields.Char(string='Fiscal Year / Period', required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    objective = fields.Text()
    risk_assessment = fields.Text()
    scope = fields.Text()
    departments = fields.Char(string='Departments & Processes')
    date_start = fields.Date()
    date_end = fields.Date()
    lead_user_id = fields.Many2one('res.users', string='Lead Auditor')
    team_ids = fields.Many2many('res.users', string='Audit Team')
    budget_hours = fields.Float(string='Budgeted Effort (hours)')
    state = fields.Selection([('draft', 'Draft'), ('approved', 'Approved'), ('in_progress', 'In Progress'),
                              ('done', 'Completed'), ('cancelled', 'Cancelled')], default='draft',
                             tracking=True, required=True, copy=False)
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    program_ids = fields.One2many('odoo.auditor.program', 'plan_id')
    conclusion = fields.Text()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('odoo.auditor.plan') or 'New'
        return super().create(vals_list)

    def action_approve(self):
        if not self.env.user.has_group('odoo_auditor.group_auditor_manager'):
            raise UserError(self.env._("Only an Audit Manager can approve plans."))
        self.write({'state': 'approved', 'approved_by': self.env.uid})

    def action_start(self):
        self.write({'state': 'in_progress'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})


class AuditorProgram(models.Model):
    _name = 'odoo.auditor.program'
    _description = 'Audit Program'
    _inherit = ['mail.thread']

    name = fields.Char(required=True)
    plan_id = fields.Many2one('odoo.auditor.plan', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='plan_id.company_id', store=True)
    objective = fields.Text()
    procedures = fields.Text()
    workpaper_ids = fields.One2many('odoo.auditor.workpaper', 'program_id')


class AuditorWorkpaper(models.Model):
    _name = 'odoo.auditor.workpaper'
    _description = 'Audit Workpaper'
    _inherit = ['odoo.auditor.logged.mixin', 'mail.thread']
    _log_fields = ('state', 'test_result')

    name = fields.Char(required=True)
    program_id = fields.Many2one('odoo.auditor.program', required=True, ondelete='cascade')
    company_id = fields.Many2one(related='program_id.company_id', store=True)
    objective = fields.Text()
    sample_method = fields.Selection([('full', 'Full population'), ('random', 'Random'),
                                      ('judgmental', 'Judgmental'), ('statistical', 'Statistical')],
                                     default='judgmental')
    sample_seed = fields.Integer(help="Seed used for random selection, to allow reproduction.")
    population_size = fields.Integer()
    sample_size = fields.Integer()
    sample_selection = fields.Text(string='Selected Sample (IDs / references)',
                                   help="Preserved as selected at the time of testing.")
    testing_performed = fields.Text()
    test_result = fields.Selection([('not_tested', 'Not tested'), ('passed', 'Passed'),
                                    ('passed_exceptions', 'Passed with exceptions'), ('failed', 'Failed')],
                                   default='not_tested', tracking=True)
    exceptions = fields.Text()
    finding_ids = fields.Many2many('odoo.auditor.finding', string='Resulting Findings')
    evidence_ids = fields.One2many('odoo.auditor.evidence', 'workpaper_id')
    reviewer_comments = fields.Text()
    state = fields.Selection([('draft', 'Draft'), ('prepared', 'Prepared'), ('reviewed', 'Reviewed / Approved')],
                             default='draft', tracking=True)
    prepared_by = fields.Many2one('res.users', readonly=True)
    prepared_date = fields.Datetime(readonly=True)
    reviewed_by = fields.Many2one('res.users', readonly=True)
    reviewed_date = fields.Datetime(readonly=True)

    @api.constrains('sample_size', 'population_size')
    def _check_sizes(self):
        for w in self:
            if w.population_size and w.sample_size > w.population_size:
                raise UserError(self.env._("Sample size cannot exceed the population size."))

    def action_prepare(self):
        self.write({'state': 'prepared', 'prepared_by': self.env.uid, 'prepared_date': fields.Datetime.now()})

    def action_review(self):
        for w in self:
            if w.state != 'prepared':
                raise UserError(self.env._("Only prepared workpapers can be reviewed."))
            if w.prepared_by == self.env.user:
                raise UserError(self.env._("The preparer cannot review their own workpaper."))
            w.write({'state': 'reviewed', 'reviewed_by': self.env.uid, 'reviewed_date': fields.Datetime.now()})
