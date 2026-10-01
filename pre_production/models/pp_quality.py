from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

from .pp_stage import STAGE_CODES, STAGE_GROUPS, QUALITY_STAGES


class PPQualityTemplate(models.Model):
    _name = 'pp.quality.template'
    _description = 'Quality Report Template'

    name = fields.Char(required=True)
    stage_code = fields.Selection([c for c in STAGE_CODES if c[0] in QUALITY_STAGES], 'Stage', required=True,
                                  help="A stage can have several templates: one Quality Check is created for each of them "
                                       "and the stage is complete only when all of them are approved.")
    active = fields.Boolean(default=True)
    line_ids = fields.One2many('pp.quality.template.line', 'template_id', 'Inspection Items', copy=True)


class PPQualityTemplateLine(models.Model):
    _name = 'pp.quality.template.line'
    _description = 'Quality Template Item'
    _order = 'sequence, id'

    template_id = fields.Many2one('pp.quality.template', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    line_type = fields.Selection([
        ('manual', 'Written Item'),
        ('material', 'Raw Materials (auto)'),
        ('packaging', 'Packaging Materials (auto)'),
        ('finished', 'Finished Product (auto)'),
    ], 'Type', default='manual', required=True,
        help="Written Item: the text you type is the inspection item.\n"
             "Raw / Packaging Materials: one inspection item is generated automatically for every material / packaging "
             "line of the order (product | lot | quantity).\n"
             "Finished Product: one item is generated for the product of the order (product | planned quantity).")
    name = fields.Char('Inspection Item', help="Required for written items. For automatic items it is an optional prefix.")

    @api.constrains('line_type', 'name')
    def _check_name(self):
        for l in self:
            if l.line_type == 'manual' and not (l.name or '').strip():
                raise ValidationError(_("Please write the inspection item text."))


class PPQualityCheck(models.Model):
    _name = 'pp.quality.check'
    _description = 'Pre-Production Quality Check'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(compute='_compute_name', store=True)
    order_id = fields.Many2one('pp.order', required=True, ondelete='restrict', index=True)
    partner_id = fields.Many2one(related='order_id.partner_id', store=True)
    product_id = fields.Many2one(related='order_id.product_id', store=True)
    stage_id = fields.Many2one('pp.stage', 'Stage', required=True)
    stage_code = fields.Selection(related='stage_id.code', store=True)
    attempt = fields.Integer(default=1)
    template_id = fields.Many2one('pp.quality.template', 'Template')
    state = fields.Selection([('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')],
                             default='pending', tracking=True)
    line_ids = fields.One2many('pp.quality.check.line', 'check_id', 'Inspection Items')
    inspector_id = fields.Many2one('res.users', 'Inspector', readonly=True)
    date = fields.Datetime(readonly=True)
    notes = fields.Text('Notes')
    reject_reason = fields.Text('Rejection Reason')
    approved_by = fields.Many2one('res.users', readonly=True)
    approved_date = fields.Datetime(readonly=True)
    rejected_by = fields.Many2one('res.users', readonly=True)
    rejected_date = fields.Datetime(readonly=True)

    check_all = fields.Boolean('Check All', compute='_compute_check_all', inverse='_inverse_check_all')

    @api.depends('line_ids.checked')
    def _compute_check_all(self):
        for c in self:
            c.check_all = bool(c.line_ids) and all(c.line_ids.mapped('checked'))

    def _inverse_check_all(self):
        for c in self:
            c.line_ids.write({'checked': c.check_all})

    @api.onchange('check_all')
    def _onchange_check_all(self):
        value = self.check_all  # read once: ticking the first line recomputes check_all
        for l in self.line_ids:
            l.checked = value

    @api.depends('order_id.name', 'stage_id.name', 'attempt', 'template_id.name')
    def _compute_name(self):
        Template = self.env['pp.quality.template']
        for c in self:
            parts = [c.order_id.name, c.stage_id.name]
            if c.template_id and Template.search_count([('stage_code', '=', c.stage_id.code)]) > 1:
                parts.append(c.template_id.name)
            c.name = '%s / #%s' % (' / '.join(p or '' for p in parts), c.attempt)

    @api.model
    def _template_lines(self, order, tmpl):
        lines = []
        for tl in tmpl.line_ids:
            prefix = (tl.name or '').strip()
            if tl.line_type == 'manual':
                lines.append((0, 0, {'name': tl.name, 'sequence': tl.sequence}))
            elif tl.line_type in ('material', 'packaging'):
                for ml in order.line_ids.filtered(lambda l: l.line_type == tl.line_type):
                    lot = ml.lot_summary or _('No lot')
                    text = '%s | %s | %s %s' % (ml.product_id.display_name, lot, ml.required_qty, ml.uom_id.name)
                    lines.append((0, 0, {'name': '%s | %s' % (prefix, text) if prefix else text, 'sequence': tl.sequence}))
            elif tl.line_type == 'finished':
                text = '%s | %s' % (order.product_id.display_name, order.product_qty)
                lines.append((0, 0, {'name': '%s | %s' % (prefix, text) if prefix else text, 'sequence': tl.sequence}))
        return lines

    @api.model
    def _create_for_order(self, order, stage, templates=None):
        """One Quality Check per active template of the stage (a stage can have several templates)."""
        if templates is None:
            templates = self.env['pp.quality.template'].search([('stage_code', '=', stage.code)])
        templates = templates or [self.env['pp.quality.template']]  # no template: a single empty check
        checks = self.browse()
        for tmpl in templates:
            attempt = self.search_count([('order_id', '=', order.id), ('stage_id', '=', stage.id),
                                         ('template_id', '=', tmpl.id or False)]) + 1
            checks |= self.with_context(pp_create_lines=True).create({
                'order_id': order.id, 'stage_id': stage.id, 'attempt': attempt,
                'template_id': tmpl.id or False, 'line_ids': self._template_lines(order, tmpl)})
        return checks

    def _check_can_act(self):
        self.ensure_one()
        order = self.order_id
        if not self.env.user.has_group(STAGE_GROUPS[self.stage_code]):
            raise ValidationError(_("You do not have permission to approve this stage."))
        if self.state != 'pending' or order.state != 'in_progress' or order.current_stage_id != self.stage_id:
            raise ValidationError(_("This check cannot be processed at the current stage of the order."))

    def action_approve(self):
        for c in self:
            c._check_can_act()
            if any(not l.checked for l in c.line_ids):
                raise ValidationError(_("All inspection items must be checked to approve. Reject the check if an item failed."))
            c.with_context(pp_internal=True).write({
                'state': 'approved', 'approved_by': self.env.user.id, 'approved_date': fields.Datetime.now(),
                'inspector_id': self.env.user.id, 'date': fields.Datetime.now()})
            c.order_id._log(c.stage_id, _('Approved'), c.notes or '')
            if c.order_id._stage_checks_approved(c.stage_id):
                c.order_id._advance()

    def action_reject(self):
        for c in self:
            c._check_can_act()
            if not c.reject_reason:
                raise ValidationError(_("Please enter a rejection reason."))
            c.with_context(pp_internal=True).write({
                'state': 'rejected', 'rejected_by': self.env.user.id, 'rejected_date': fields.Datetime.now(),
                'inspector_id': self.env.user.id, 'date': fields.Datetime.now()})
            c.order_id.state = 'rejected'
            c.order_id._log(c.stage_id, _('Rejected'), c.reject_reason)

    def action_print(self):
        self.ensure_one()
        return self.env.ref('pre_production.report_pp_check_%s' % self.stage_code).report_action(self)

    def write(self, vals):
        if not self.env.context.get('pp_internal'):
            for c in self:
                if c.state != 'pending':
                    raise ValidationError(_("A processed Quality Check cannot be modified."))
                if not self.env.user.has_group(STAGE_GROUPS[c.stage_code]) and not self.env.su:
                    raise ValidationError(_("You do not have permission to approve this stage."))
        return super().write(vals)

    def unlink(self):
        raise ValidationError(_("Quality Checks cannot be deleted; history must be kept."))


class PPQualityCheckLine(models.Model):
    _name = 'pp.quality.check.line'
    _description = 'Quality Check Item'
    _order = 'sequence, id'

    check_id = fields.Many2one('pp.quality.check', required=True, ondelete='restrict')
    sequence = fields.Integer(default=10)
    name = fields.Char('Inspection Item', required=True)
    checked = fields.Boolean('Checked')
    notes = fields.Char()

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('pp_create_lines') and not self.env.su:
            raise ValidationError(_("Inspection items cannot be added. Edit the Quality Report Template instead."))
        return super().create(vals_list)

    def unlink(self):
        if not self.env.su:
            raise ValidationError(_("Inspection items cannot be removed. Edit the Quality Report Template instead."))
        return super().unlink()

    def write(self, vals):
        if {'name', 'sequence', 'check_id'} & set(vals) and not self.env.su:
            raise ValidationError(_("Inspection items cannot be changed. Edit the Quality Report Template instead."))
        for l in self:
            c = l.check_id
            if c.state != 'pending' or not self.env.user.has_group(STAGE_GROUPS[c.stage_code]):
                raise ValidationError(_("You do not have permission to edit this Quality Check."))
        return super().write(vals)
