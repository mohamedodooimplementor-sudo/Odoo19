# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionBoqTemplate(models.Model):
    _name = 'construction.boq.template'
    _description = 'BOQ Template'
    _rec_name = 'name'

    name        = fields.Char(string='Template Name', required=True)
    description = fields.Text(string='Description')
    line_ids    = fields.One2many('construction.boq.template.line', 'template_id', string='Template Lines')
    line_count  = fields.Integer(compute='_compute_line_count')

    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    def action_apply_to_contract(self, contract):
        """Copy this template's lines onto the given construction.contract record."""
        self.ensure_one()
        BoqLine = self.env['construction.boq.line']
        for line in self.line_ids:
            BoqLine.create({
                'contract_id': contract.id,
                'item_code': line.item_code,
                'description': line.description,
                'cost_code_id': line.cost_code_id.id,
                'uom_id': line.uom_id.id,
                'qty_contract': line.default_qty,
                'unit_price': line.default_unit_price,
            })


class ConstructionBoqTemplateLine(models.Model):
    _name = 'construction.boq.template.line'
    _description = 'BOQ Template Line'
    _order = 'sequence'

    template_id  = fields.Many2one('construction.boq.template', required=True, ondelete='cascade')
    sequence     = fields.Integer(default=10)
    item_code    = fields.Char(string='Item Code')
    description  = fields.Char(string='Description', required=True)
    cost_code_id = fields.Many2one('construction.cost.code', string='Cost Code (WBS)')
    uom_id       = fields.Many2one('uom.uom', string='UoM')
    default_qty        = fields.Float(string='Default Qty', default=1.0)
    default_unit_price = fields.Float(string='Default Unit Price')


class ConstructionContractApplyTemplateWizard(models.TransientModel):
    _name = 'construction.contract.apply.template.wizard'
    _description = 'Apply BOQ Template to Contract'

    contract_id = fields.Many2one('construction.contract', required=True)
    template_id = fields.Many2one('construction.boq.template', required=True)

    def action_apply(self):
        self.ensure_one()
        if not self.template_id.line_ids:
            raise UserError(_('The selected template has no lines to apply.'))
        self.template_id.action_apply_to_contract(self.contract_id)
        return {'type': 'ir.actions.act_window_close'}
