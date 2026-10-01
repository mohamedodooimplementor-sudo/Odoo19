from odoo import api, fields, models


class PPStageLog(models.Model):
    _name = 'pp.stage.log'
    _description = 'Pre-Production Time per Stage'
    _order = 'id'

    order_id = fields.Many2one('pp.order', required=True, ondelete='cascade', index=True)
    stage_id = fields.Many2one('pp.stage', 'Stage', required=True)
    user_id = fields.Many2one('res.users', 'Moved By', default=lambda s: s.env.user)
    date_start = fields.Datetime('Entered', default=fields.Datetime.now, required=True)
    date_end = fields.Datetime('Left')
    duration_hours = fields.Float('Duration (hours)', compute='_compute_duration', store=True)

    @api.depends('date_start', 'date_end')
    def _compute_duration(self):
        for l in self:
            if l.date_start and l.date_end:
                l.duration_hours = (l.date_end - l.date_start).total_seconds() / 3600.0
            else:
                l.duration_hours = 0.0
