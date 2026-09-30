# -*- coding: utf-8 -*-
from odoo import fields, models


class EducationLeadStage(models.Model):
    _name = 'education.lead.stage'
    _description = 'Admissions Pipeline Stage'
    _order = 'sequence, id'

    name = fields.Char(string='Stage Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    fold = fields.Boolean(
        string='Folded in Kanban',
        help='Kanban columns for this stage are folded by default, the way '
             'a closed pipeline stage usually is.')
    is_won = fields.Boolean(
        string='Is Enrolled Stage',
        help='Leads reaching this stage are considered successfully enrolled. '
             'Used to unlock "Convert to Student".')
    is_lost = fields.Boolean(
        string='Is Lost Stage',
        help='Leads reaching this stage are considered lost. Used by the '
             '"Mark Lost" button and the Active filter.')
    active = fields.Boolean(default=True)
