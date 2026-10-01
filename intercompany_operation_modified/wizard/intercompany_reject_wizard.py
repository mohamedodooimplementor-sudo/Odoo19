# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IntercompanyRejectWizard(models.TransientModel):
    _name = 'intercompany.reject.wizard'
    _description = 'Reject Operation / Payment Distribution with Reason'

    res_model = fields.Selection([
        ('intercompany.operation', 'Operation'),
        ('intercompany.payment', 'Payment Distribution'),
        ('intercompany.return', 'Return'),
        ('intercompany.picking.transfer', 'Branches Picking Transfer'),
        ('intercompany.payment.transfer', 'Branches Payment Transfer'),
    ], string='Document Type', required=True)
    res_id = fields.Integer(string='Document ID', required=True)
    document_name = fields.Char(string='Document', compute='_compute_document_name')
    reason = fields.Text(string='Reason for Rejection', required=True)

    @api.depends('res_model', 'res_id')
    def _compute_document_name(self):
        for wiz in self:
            wiz.document_name = ''
            if wiz.res_model and wiz.res_id:
                rec = self.env[wiz.res_model].browse(wiz.res_id)
                if rec.exists():
                    wiz.document_name = rec.display_name

    def action_confirm_reject(self):
        self.ensure_one()
        if not self.reason or not self.reason.strip():
            raise UserError(_('Please provide a reason for rejection.'))
        record = self.env[self.res_model].browse(self.res_id)
        if not record.exists():
            raise UserError(_('The document no longer exists.'))
        record._do_refuse(self.reason)
        return {'type': 'ir.actions.act_window_close'}
