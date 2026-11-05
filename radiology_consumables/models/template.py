from odoo import fields, models

PHASES = [
    ('prep', 'Preparation'),
    ('scan', 'Scan Room'),
    ('post', 'After Exam'),
]


class RcConsumptionTemplate(models.Model):
    _name = 'rc.consumption.template'
    _description = 'Exam Consumption Template'
    _order = 'name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company)
    service_tmpl_ids = fields.Many2many(
        'product.template', 'rc_template_service_rel', 'template_id', 'tmpl_id',
        string='Exam Services', domain="[('type', '=', 'service')]")
    line_ids = fields.One2many('rc.consumption.template.line', 'template_id', string='Consumables')


class RcConsumptionTemplateLine(models.Model):
    _name = 'rc.consumption.template.line'
    _description = 'Exam Consumption Template Line'
    _order = 'sequence, id'

    template_id = fields.Many2one('rc.consumption.template', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    phase = fields.Selection(PHASES, required=True, default='prep')
    product_id = fields.Many2one('product.product', required=True, domain="[('type', '=', 'consu')]")
    qty = fields.Float(string='Quantity', default=1.0)
    uom_id = fields.Many2one(related='product_id.uom_id')
    condition = fields.Selection([
        ('always', 'Always'),
        ('contrast', 'With Contrast'),
        ('allergy', 'Allergy Case'),
        ('gown', 'Gown Needed'),
    ], default='always', required=True)
