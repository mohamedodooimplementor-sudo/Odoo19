from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class StockLocation(models.Model):
    _inherit = 'stock.location'

    is_room = fields.Boolean(string='Department / Room')
    is_lab = fields.Boolean(string='Is Lab')
    rc_responsible_ids = fields.Many2many(
        'res.users', 'rc_location_user_rel', 'location_id', 'user_id',
        string='Room Staff')
    rc_source_location_id = fields.Many2one(
        'stock.location', string='Supply From (Main Store)',
        domain="[('usage', '=', 'internal'), ('is_room', '=', False), ('is_lab', '=', False)]")
    rc_par_ids = fields.One2many('rc.room.par', 'room_id', string='Stock Levels')

    @api.constrains('is_room', 'is_lab', 'usage')
    def _check_rc_internal(self):
        for rec in self:
            if (rec.is_room or rec.is_lab) and rec.usage != 'internal':
                raise ValidationError(_('Room and Lab locations must be of type Internal.'))

    def action_rc_create_issue(self):
        """Create a draft 'Issue to Room' for everything below Max in this room."""
        self.ensure_one()
        if not self.rc_source_location_id:
            raise UserError(_('Choose "Supply From (Main Store)" first.'))
        pars = self.rc_par_ids.filtered(lambda p: p.qty_to_request > 0)
        if not pars:
            raise UserError(_('Nothing to request: every product is at or above its Max.'))
        issue = self.env['rc.issue'].create({
            'company_id': (self.company_id or self.env.company).id,
            'source_location_id': self.rc_source_location_id.id,
            'room_id': self.id,
            'line_ids': [Command.create({
                'product_id': p.product_id.id,
                'qty_issued': p.qty_to_request,
            }) for p in pars],
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'rc.issue',
            'res_id': issue.id,
            'view_mode': 'form',
            'target': 'current',
        }
