# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ConstructionApprovalRule(models.Model):
    _name = 'construction.approval.rule'
    _description = 'Approval Matrix Rule'
    _order = 'document_type, sequence, min_amount'

    name = fields.Char(compute='_compute_name', store=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company, required=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    active = fields.Boolean(default=True)

    document_type = fields.Selection([
        ('actual_cost',           'Actual Cost'),
        ('change_order',          'Change Order'),
        ('progress_invoice',      'Progress Invoice'),
        ('material_request',      'Material Request'),
        ('subcontractor_penalty', 'Subcontractor Penalty'),
    ], required=True, default='actual_cost')

    min_amount = fields.Monetary(string='From Amount', currency_field='currency_id', default=0.0)
    max_amount = fields.Monetary(string='To Amount (0 = no limit)', currency_field='currency_id', default=0.0)

    required_role = fields.Selection([
        ('user',      'Site User'),
        ('manager',   'Project Manager'),
        ('financial', 'Financial Manager'),
    ], required=True, default='user')

    _ROLE_GROUPS = {
        'user':      'prime_construction_suite.group_construction_user',
        'manager':   'prime_construction_suite.group_construction_manager',
        'financial': 'prime_construction_suite.group_construction_financial',
    }

    @api.depends('document_type', 'min_amount', 'max_amount', 'required_role')
    def _compute_name(self):
        doc_labels = dict(self._fields['document_type'].selection)
        role_labels = dict(self._fields['required_role'].selection)
        for rec in self:
            upper = rec.max_amount or '∞'
            rec.name = '%s: %s – %s → %s' % (
                doc_labels.get(rec.document_type, ''), rec.min_amount, upper,
                role_labels.get(rec.required_role, ''))

    @api.model
    def get_required_role(self, document_type, amount, company=None):
        """Return the required role code ('user'/'manager'/'financial') for approving a document
        of the given type and amount, per the configured Approval Matrix. Returns False if no
        rule is configured for this document type in this company — callers should then fall
        back to their own default logic, so nothing breaks for companies that haven't set up a
        matrix yet."""
        company = company or self.env.company
        rule = self.search([
            ('document_type', '=', document_type),
            ('company_id', '=', company.id),
            ('min_amount', '<=', amount),
            '|', ('max_amount', '=', 0.0), ('max_amount', '>=', amount),
        ], order='min_amount desc', limit=1)
        return rule.required_role if rule else False

    @api.model
    def check_approval(self, document_type, amount, company=None):
        """Raise a UserError if the current user doesn't hold the role required to approve this
        document per the Approval Matrix. Does nothing if no matching rule is configured."""
        role = self.get_required_role(document_type, amount, company)
        if not role:
            return
        if not self.env.user.has_group(self._ROLE_GROUPS[role]):
            doc_labels = dict(self._fields['document_type'].selection)
            role_labels = dict(self._fields['required_role'].selection)
            raise UserError(_(
                'This %s (amount: %s) requires approval by a %s, based on the configured '
                'Approval Matrix (Settings > Prime Construction Suite > Approval Matrix).') % (
                doc_labels.get(document_type, document_type), amount, role_labels.get(role, role)))
