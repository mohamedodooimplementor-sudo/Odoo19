from odoo import fields, models


class FindingResolutionWizard(models.TransientModel):
    _name = 'odoo.auditor.finding.resolution.wizard'
    _description = 'Close / Reject Finding'

    finding_id = fields.Many2one('odoo.auditor.finding', required=True)
    mode = fields.Selection([('close', 'Close'), ('reject', 'Reject (duplicate / false positive)'),
                             ('ignore', 'Reject and ignore in future runs')],
                            required=True, default='close')
    note = fields.Text(string='Closure Note / Justification', required=True)

    def action_confirm(self):
        self.ensure_one()
        if self.mode == 'close':
            self.finding_id._close(self.note)
        elif self.mode == 'reject':
            self.finding_id._reject(self.note)
        else:
            self.finding_id._ignore_future(self.note)
        return {'type': 'ir.actions.act_window_close'}
