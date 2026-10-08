# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import is_html_empty


class ErRequiredField(models.Model):
    """One row per field of the request / purchase order that the administrator
    can mark as required (Configuration > Required Field)."""
    _name = 'er.required.field'
    _description = 'Required Field Setting'
    _order = 'document_type, scope, sequence, id'

    _field_id_unique = models.Constraint(
        'UNIQUE(field_id)', "This field is already configured.")

    sequence = fields.Integer(default=10)
    document_type = fields.Selection([
        ('request', 'Employee Request'),
        ('purchase_order', 'Purchase Order'),
    ], string='Document', required=True)
    scope = fields.Selection([
        ('header', 'Document'),
        ('line', 'Lines'),
    ], string='Section', required=True, default='header')
    field_id = fields.Many2one('ir.model.fields', string='Field', required=True,
                               ondelete='cascade', index=True)
    model_name = fields.Char(related='field_id.model', string='Model', store=True)
    field_name = fields.Char(related='field_id.name', string='Technical Name')
    is_required = fields.Boolean(string='Required', default=False)

    @api.model
    def _get_required(self, model_name):
        """Required settings (sudo) of `model_name`."""
        return self.sudo().search([('model_name', '=', model_name),
                                   ('is_required', '=', True)])


class ErRequiredMixin(models.AbstractModel):
    """Shared by the request and the purchase order: exposes the required field
    names to the form views and validates them from the workflow buttons."""
    _name = 'er.required.mixin'
    _description = 'Required Fields Mixin'

    er_required_fields = fields.Json(string='Required Fields',
                                     compute='_compute_er_required_fields')
    er_required_line_fields = fields.Json(string='Required Line Fields',
                                          compute='_compute_er_required_fields')

    def _compute_er_required_fields(self):
        config = self.env['er.required.field']
        header = config._get_required(self._name).mapped('field_name')
        line_model = self._fields['line_ids'].comodel_name
        lines = config._get_required(line_model).mapped('field_name')
        for rec in self:
            rec.er_required_fields = header
            rec.er_required_line_fields = lines

    @api.model
    def _er_is_empty(self, record, name):
        field = record._fields[name]
        value = record[name]
        if field.type == 'html':
            return is_html_empty(value)
        if field.type in ('char', 'text'):
            return not (value or '').strip()
        if field.type in ('boolean', 'integer', 'float', 'monetary'):
            return False  # 0 / False are valid values
        return not value

    def _er_check_required(self):
        """Raise when a field flagged in Configuration > Required Field is empty."""
        config = self.env['er.required.field']
        header_cfg = config._get_required(self._name)
        line_cfg = config._get_required(self._fields['line_ids'].comodel_name)
        if not header_cfg and not line_cfg:
            return
        for rec in self:
            details = []
            for cfg in header_cfg:
                if self._er_is_empty(rec, cfg.field_name):
                    details.append("- %s" % cfg.field_id.field_description)
            for line in rec.line_ids:
                for cfg in line_cfg:
                    if self._er_is_empty(line, cfg.field_name):
                        details.append("- %s" % _(
                            "%(field)s (line: %(product)s)",
                            field=cfg.field_id.field_description,
                            product=line.product_id.display_name or line.name or ''))
            if details:
                raise ValidationError(_(
                    "Some required fields are empty in %(document)s:\n%(details)s",
                    document=rec.display_name, details="\n".join(details)))
