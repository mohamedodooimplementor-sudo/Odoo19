from odoo import Command, fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    rc_is_exam = fields.Boolean(
        string='Radiology Exam',
        help='When a sales order containing this service is confirmed, a draft Exam Consumption is created for it.')
    rc_room_id = fields.Many2one(
        'stock.location', string='Default Room / Lab',
        domain="[('usage', '=', 'internal'), '|', ('is_room', '=', True), ('is_lab', '=', True)]",
        help='Room that performs this exam. Used for the exam consumption created from sales orders.')
    rc_template_id = fields.Many2one(
        'rc.consumption.template', string='Consumption Template',
        compute='_compute_rc_template_id', inverse='_inverse_rc_template_id')
    rc_line_ids = fields.One2many(
        related='rc_template_id.line_ids', string='Exam Consumables', readonly=False)

    def _compute_rc_template_id(self):
        Template = self.env['rc.consumption.template'].sudo()
        for rec in self:
            real_id = rec._origin.id or rec.id
            rec.rc_template_id = Template.search(
                [('service_tmpl_ids', 'in', real_id)], limit=1) if real_id else False

    def _inverse_rc_template_id(self):
        Template = self.env['rc.consumption.template']
        for rec in self:
            old = Template.search([('service_tmpl_ids', 'in', rec.id)]) - rec.rc_template_id
            for tmpl in old:
                tmpl.service_tmpl_ids = [Command.unlink(rec.id)]
            if rec.rc_template_id:
                rec.rc_template_id.service_tmpl_ids = [Command.link(rec.id)]

    def action_rc_create_template(self):
        for rec in self:
            if not rec.rc_template_id:
                self.env['rc.consumption.template'].create({
                    'name': rec.name,
                    'service_tmpl_ids': [Command.link(rec.id)],
                })
        return True
