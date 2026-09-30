# -*- coding: utf-8 -*-
import base64
import io

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionBoqImportWizard(models.TransientModel):
    _name = 'construction.boq.import.wizard'
    _description = 'Import BOQ Lines from Excel'

    contract_id = fields.Many2one('construction.contract', string='Contract', required=True)
    file        = fields.Binary(string='Excel File (.xlsx)', required=True)
    filename    = fields.Char(string='Filename')
    note = fields.Text(
        string='Expected Columns', readonly=True,
        default=_('Section | Item Code | Description | Type (work/supply/lump_sum/allowance) | '
                  'UoM | Contract Qty | Unit Price | Total Price (ignored) | Cost Code\n\n'
                  'The first row is treated as a header and skipped. Use the "Export to Excel" '
                  'button first to get a template with the exact column layout.'))

    def action_import(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_('Please upload an Excel file first.'))
        try:
            import openpyxl
        except ImportError:
            raise UserError(_(
                'The "openpyxl" Python library is required to import from Excel. '
                'Please ask your administrator to install it on the server (pip install openpyxl).'))

        content = base64.b64decode(self.file)
        try:
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        except Exception:
            raise UserError(_('Could not read the uploaded file. Please make sure it is a valid .xlsx file.'))
        sheet = wb.active

        BoqLine = self.env['construction.boq.line']
        BoqSection = self.env['construction.boq.section']
        Uom = self.env['uom.uom']
        CostCode = self.env['construction.cost.code']
        default_uom = self.env.ref('uom.product_uom_unit', raise_if_not_found=False)

        section_cache = {}
        valid_types = {'work', 'supply', 'lump_sum', 'allowance'}
        created = 0

        for row in sheet.iter_rows(min_row=2, values_only=True):
            if not row or not any(row):
                continue
            row = list(row) + [None] * (9 - len(row))
            (section_name, item_code, description, line_type, uom_name,
             qty, price, _total_ignored, cost_code_name) = row[:9]

            if not description:
                continue

            section_id = False
            if section_name:
                if section_name not in section_cache:
                    section = BoqSection.search([
                        ('contract_id', '=', self.contract_id.id), ('name', '=', section_name)], limit=1)
                    if not section:
                        section = BoqSection.create({'contract_id': self.contract_id.id, 'name': section_name})
                    section_cache[section_name] = section.id
                section_id = section_cache[section_name]

            uom = Uom.search([('name', '=', uom_name)], limit=1) if uom_name else False
            if not uom:
                uom = default_uom
            if not uom:
                raise UserError(_('Could not determine a Unit of Measure for row: %s') % description)

            cost_code = CostCode.search([('name', '=', cost_code_name)], limit=1) if cost_code_name else False

            BoqLine.create({
                'contract_id': self.contract_id.id,
                'section_id': section_id,
                'item_code': item_code or '',
                'description': description,
                'line_type': line_type if line_type in valid_types else 'work',
                'uom_id': uom.id,
                'qty_contract': qty or 0.0,
                'unit_price': price or 0.0,
                'cost_code_id': cost_code.id if cost_code else False,
            })
            created += 1

        if not created:
            raise UserError(_('No valid BOQ rows were found in the uploaded file.'))

        return {
            'type': 'ir.actions.act_window',
            'name': _('BOQ Lines'),
            'res_model': 'construction.boq.line',
            'view_mode': 'list,form',
            'domain': [('contract_id', '=', self.contract_id.id)],
        }
