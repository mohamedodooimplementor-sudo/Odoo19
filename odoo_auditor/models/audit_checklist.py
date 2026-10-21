from odoo import fields, models
from odoo.exceptions import UserError

PERIOD_END = [
    "Review draft entries outstanding (FIN001)", "Review large manual journal entries (FIN002)",
    "Review duplicate vendor bills and customer invoices (FIN003 / FIN004)", "Review backdated postings (FIN006)",
    "Review overdue receivables and payables (FIN007)", "Review pending transfers and negative stock (INV001 / INV002)",
    "Review inventory adjustments (INV003)", "Review bank reconciliation and outstanding items (manual)",
    "Review clearing and suspense account balances (manual)", "Review open findings and overdue corrective actions",
]
YEAR_END = [
    "Review access rights and segregation of duties (SOD001)", "Compare physical inventory count to system quantities",
    "Review tax configuration changes", "Review risk register and control effectiveness",
    "Conclude the audit plan and document the final conclusion",
]


class AuditorChecklist(models.Model):
    _name = 'odoo.auditor.checklist'
    _description = 'Period / Year-end Audit Checklist'
    _inherit = ['mail.thread']

    name = fields.Char(required=True)
    kind = fields.Selection([('period_end', 'Period-end'), ('year_end', 'Year-end')], default='period_end', required=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    period = fields.Char(help="e.g. 2026-09 or FY2026")
    plan_id = fields.Many2one('odoo.auditor.plan')
    state = fields.Selection([('open', 'Open'), ('done', 'Completed')], default='open', tracking=True)
    line_ids = fields.One2many('odoo.auditor.checklist.line', 'checklist_id')

    def action_generate_lines(self):
        for c in self:
            items = PERIOD_END + (YEAR_END if c.kind == 'year_end' else [])
            c.line_ids.unlink()
            self.env['odoo.auditor.checklist.line'].create(
                [{'checklist_id': c.id, 'sequence': i, 'item': t} for i, t in enumerate(items, 1)])

    def action_complete(self):
        for c in self:
            if not c.line_ids or any(not l.done for l in c.line_ids):
                raise UserError(self.env._("Complete all checklist items first."))
            c.state = 'done'


class AuditorChecklistLine(models.Model):
    _name = 'odoo.auditor.checklist.line'
    _description = 'Checklist Line'
    _order = 'sequence, id'

    checklist_id = fields.Many2one('odoo.auditor.checklist', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    item = fields.Char(required=True)
    done = fields.Boolean()
    done_by = fields.Many2one('res.users', readonly=True)
    done_date = fields.Datetime(readonly=True)
    note = fields.Char()

    def write(self, vals):
        if 'done' in vals:
            vals.update({'done_by': self.env.uid if vals['done'] else False,
                         'done_date': fields.Datetime.now() if vals['done'] else False})
        return super().write(vals)
