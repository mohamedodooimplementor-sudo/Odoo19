# -*- coding: utf-8 -*-
import ast

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class EducationDashboardStatCard(models.Model):
    _name = 'education.dashboard.stat.card'
    _description = 'Prime Education Hub Dashboard - Statistics Card'
    _order = 'sequence, id'

    name = fields.Char(string='Title', required=True, translate=True)
    icon = fields.Char(required=True, default='fa-bar-chart')
    sequence = fields.Integer(default=10)
    color = fields.Char(default='#a855f7')
    active = fields.Boolean(default=True)
    group_id = fields.Many2one(
        'res.groups', string='Restrict To Group',
        help='Only users in this group (or a group implying it) see this card. Leave empty '
             'to show it to every user who has read access to the underlying model below.')

    res_model = fields.Char(
        string='Model', required=True,
        help="Technical name of the Odoo model to read, e.g. 'education.student'.")
    domain = fields.Char(
        default='[]',
        help='A plain Odoo domain (same syntax as a normal filter) selecting which records '
             'to count/sum, e.g. [("state","=","active")]. Must be a literal list - no '
             'function calls. For a "today" date filter, use the two fields below instead.')
    date_today_field = fields.Char(
        string="Filter to Today's Date On Field",
        help="Optional. Technical name of a Date field on the model above (e.g. "
             "'session_date'). When set, only records where that field equals today's date "
             "are counted - computed server-side each time the dashboard loads, so it is "
             "always actually today, not a fixed date.")
    measure = fields.Selection([
        ('count', 'Record Count'),
        ('sum', 'Sum of a Field'),
        ('avg_percentage', 'Average of a Field, shown as %'),
        ('ratio_percentage', '% of Domain Matching a Sub-Domain'),
    ], default='count', required=True)
    measure_field = fields.Char(
        string='Field to Sum/Average',
        help="Technical field name on the model above, required when the measure is "
             "'Sum of a Field' or 'Average of a Field'.")
    domain_numerator = fields.Char(
        string='Numerator Sub-Domain',
        help="Only used for the '% of Domain Matching a Sub-Domain' measure (e.g. Today's "
             "Attendance %): this sub-domain (present/on-time records) divided by the main "
             "domain + today filter above, x 100. Also a plain literal list - no function "
             "calls.")
    suffix = fields.Char(help="Shown after the number, e.g. '%'.")

    def _parse_domain(self, domain_str):
        """Turns a stored domain string into an actual Python list, safely: ast.literal_eval
        only accepts literal data (lists/tuples/strings/numbers/None/True/False) and can
        never execute a function call or attribute access, so this can't be used to run
        arbitrary code no matter what an admin types into the field."""
        try:
            domain = ast.literal_eval(domain_str or '[]')
        except (ValueError, SyntaxError):
            raise ValidationError(_('"%s" is not a valid domain.') % domain_str)
        if not isinstance(domain, list):
            raise ValidationError(_('"%s" is not a valid domain (must be a list).') % domain_str)
        return domain

    def _full_domain(self):
        """The configured domain, plus today's date filter appended if requested."""
        self.ensure_one()
        domain = self._parse_domain(self.domain)
        if self.date_today_field:
            domain = domain + [(self.date_today_field, '=', fields.Date.context_today(self))]
        return domain

    @api.constrains('domain')
    def _check_domain(self):
        for card in self:
            card._parse_domain(card.domain)

    @api.constrains('domain_numerator')
    def _check_domain_numerator(self):
        for card in self:
            if card.domain_numerator:
                card._parse_domain(card.domain_numerator)

    @api.constrains('measure', 'measure_field', 'domain_numerator')
    def _check_measure_requirements(self):
        for card in self:
            if card.measure in ('sum', 'avg_percentage') and not card.measure_field:
                raise ValidationError(
                    _('Stat card "%s" needs a "Field to Sum/Average" for its selected measure.')
                    % card.name)
            if card.measure == 'ratio_percentage' and not card.domain_numerator:
                raise ValidationError(
                    _('Stat card "%s" needs a "Numerator Sub-Domain" for its selected measure.')
                    % card.name)

    def _compute_value(self):
        """Reads the live number for this card from its own model/domain - never a hardcoded
        or cached figure, so it is always in sync with the database (and with the current
        user's access rights and active company, since it goes through the normal ORM, which
        applies both automatically)."""
        self.ensure_one()
        try:
            Model = self.env[self.res_model]
        except KeyError:
            return None
        if not Model.has_access('read'):
            return None

        try:
            domain = self._full_domain()
            if self.measure == 'count':
                return Model.search_count(domain)

            if self.measure == 'ratio_percentage':
                denominator = Model.search_count(domain)
                if not denominator:
                    return 0
                numerator_domain = domain + self._parse_domain(self.domain_numerator)
                numerator = Model.search_count(numerator_domain)
                return round(numerator / denominator * 100.0, 1)

            records = Model.search(domain)
            if not records:
                return 0
            values = [v for v in records.mapped(self.measure_field) if isinstance(v, (int, float))]
            if not values:
                return 0
            if self.measure == 'sum':
                return round(sum(values), 2)
            if self.measure == 'avg_percentage':
                return round(sum(values) / len(values), 1)
        except Exception:
            # A misconfigured field/domain on one card should never break the whole
            # dashboard for every other card - just report this one card as unavailable.
            return None
        return None

    @api.model
    def get_visible_cards_data(self):
        """Returns the live [{title, value, icon, color, suffix}, ...] list for every stat
        card the current user is allowed to see."""
        user_groups = self.env.user.group_ids
        cards = self.search([('active', '=', True)])
        data = []
        for card in cards:
            if card.group_id and card.group_id not in user_groups:
                continue
            value = card._compute_value()
            if value is None:
                continue
            try:
                domain = card._full_domain()
            except Exception:
                domain = []
            data.append({
                'id': card.id,
                'title': card.name,
                'icon': card.icon,
                'color': card.color,
                'value': value,
                'suffix': card.suffix or '',
                'res_model': card.res_model,
                'domain': domain,
            })
        return data
