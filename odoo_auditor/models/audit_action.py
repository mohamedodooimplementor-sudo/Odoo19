from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError


class AuditorAction(models.Model):
    _name = 'odoo.auditor.action'
    _description = 'Corrective Action'
    _inherit = ['odoo.auditor.logged.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'deadline, id'
    _log_fields = ('state', 'responsible_user_id', 'deadline', 'priority')

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')
    title = fields.Char(required=True)
    finding_id = fields.Many2one('odoo.auditor.finding', required=True, ondelete='restrict', index=True)
    company_id = fields.Many2one(related='finding_id.company_id', store=True)
    description = fields.Text(string='Action Description', required=True)
    root_cause = fields.Text()
    responsible_user_id = fields.Many2one('res.users', string='Responsible', required=True, tracking=True)
    responsible_department = fields.Char()
    priority = fields.Selection([('0', 'Low'), ('1', 'Normal'), ('2', 'High'), ('3', 'Urgent')], default='1')
    deadline = fields.Date(required=True, tracking=True)
    state = fields.Selection([('open', 'Open'), ('in_progress', 'In Progress'), ('completed', 'Completed'),
                              ('verified', 'Verified'), ('cancelled', 'Cancelled')], default='open',
                             tracking=True, required=True, copy=False)
    completion_notes = fields.Text()
    completed_by = fields.Many2one('res.users', readonly=True, copy=False)
    completion_evidence_ids = fields.Many2many('ir.attachment', string='Completion Evidence')
    verified_by = fields.Many2one('res.users', readonly=True, copy=False)
    verification_date = fields.Date(readonly=True, copy=False)
    effectiveness_review = fields.Text()
    escalation_count = fields.Integer(readonly=True)
    escalation_history = fields.Text(readonly=True)
    is_overdue = fields.Boolean(compute='_compute_overdue', search='_search_overdue')

    @api.depends('deadline', 'state')
    def _compute_overdue(self):
        today = fields.Date.today()
        for a in self:
            a.is_overdue = bool(a.deadline and a.deadline < today and a.state in ('open', 'in_progress'))

    def _search_overdue(self, operator, value):
        return [('deadline', '<', fields.Date.today()), ('state', 'in', ('open', 'in_progress'))]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('odoo.auditor.action') or 'New'
        return super().create(vals_list)

    def action_start(self):
        self.filtered(lambda a: a.state == 'open').write({'state': 'in_progress'})

    def action_complete(self):
        for a in self:
            if a.state not in ('open', 'in_progress'):
                raise UserError(self.env._("Only open actions can be completed."))
            if not a.completion_notes:
                raise UserError(self.env._("Completion notes are required."))
            a.write({'state': 'completed', 'completed_by': self.env.uid})

    def action_verify(self):
        if not self.env.user.has_group('odoo_auditor.group_auditor_manager'):
            raise UserError(self.env._("Only an Audit Manager can verify actions."))
        for a in self:
            if a.state != 'completed':
                raise UserError(self.env._("Only completed actions can be verified."))
            if self.env.user in (a.responsible_user_id | a.completed_by):
                raise UserError(self.env._(
                    "Segregation of duties: the action owner cannot verify their own action."))
            a.write({'state': 'verified', 'verified_by': self.env.uid,
                     'verification_date': fields.Date.today()})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    @api.model
    def cron_escalate_overdue(self):
        for a in self.search([('is_overdue', '=', True)]):
            line = "%s: overdue since %s (escalation #%s)" % (
                fields.Date.today(), a.deadline, a.escalation_count + 1)
            a.write({'escalation_count': a.escalation_count + 1,
                     'escalation_history': ((a.escalation_history or '') + line + '\n')})
            a.activity_schedule('mail.mail_activity_data_todo', date_deadline=fields.Date.today(),
                                user_id=a.responsible_user_id.id,
                                summary=self.env._("Overdue corrective action %s", a.name))
