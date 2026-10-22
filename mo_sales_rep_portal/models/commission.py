"""Sales commission: rules chosen by the manager per representative, monthly statements approved by the manager.

A RULE says what the commission is based on and how it is calculated:

    basis   = confirmed sales orders | collected payments | target achievement
    method  = percentage | tiered | fixed amount

    basis order / collection   percentage -> rate x amount of each document
                               tiered     -> slabs: every slice of the period total is paid at its own rate
                               fixed      -> a fixed amount for each document
    basis target               percentage -> rate x sales (or collection) once the minimum achievement is reached
                               tiered     -> the rate of the highest achievement level reached x sales (or collection)
                               fixed      -> a fixed bonus once the minimum achievement is reached

A STATEMENT is one representative + one period. The manager computes it, can adjust or add lines while it is a
draft, then approves it. Only approved / paid statements are visible to the representative in the portal.
"""
from datetime import datetime, time, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

BASIS = [('order', 'Confirmed sales orders'), ('collection', 'Collected payments'), ('target', 'Target achievement')]
METHODS = [('percent', 'Percentage'), ('tiered', 'Tiered'), ('fixed', 'Fixed amount')]
TARGET_METRICS = [('overall', 'Overall achievement'), ('sales', 'Sales'), ('collection', 'Collection'),
                  ('orders', 'Orders'), ('visits', 'Visits'), ('new_customers', 'New Customers')]


# ----------------------------------------------------------------------
# pure calculation helpers (no database access)
# ----------------------------------------------------------------------
def slab_commission(tiers, amount):
    """Marginal slabs. `tiers` = [(threshold, rate %), ...] sorted by threshold.
    Every slice of `amount` is paid at the rate of the slab it falls in."""
    total = 0.0
    for i, (low, rate) in enumerate(tiers):
        high = tiers[i + 1][0] if i + 1 < len(tiers) else None
        top = amount if high is None else min(amount, high)
        if top > low:
            total += (top - low) * rate / 100.0
    return total


def level_rate(tiers, value):
    """Rate (%) of the highest level whose threshold is reached by `value` (0 when none)."""
    rate = 0.0
    for low, r in tiers:
        if value >= low:
            rate = r
    return rate


def month_bounds(day):
    first = day.replace(day=1)
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return first, last


class CommissionTier(models.Model):
    _name = 'mo.sales.commission.tier'
    _description = 'Sales Commission Tier'
    _order = 'threshold, id'

    rule_id = fields.Many2one('mo.sales.commission.rule', required=True, ondelete='cascade')
    threshold = fields.Float('From', help='Orders / collection rules: the amount from which this rate applies.\n'
                                          'Target rules: the achievement % from which this rate applies.')
    rate = fields.Float('Rate %', required=True)


class CommissionRule(models.Model):
    _name = 'mo.sales.commission.rule'
    _description = 'Sales Commission Rule'
    _inherit = ['mail.thread']
    _order = 'sequence, id'

    name = fields.Char(required=True, tracking=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company)
    rep_ids = fields.Many2many('mo.sales.rep', 'mo_commission_rule_rep_rel', 'rule_id', 'rep_id',
                               string='Sales Representatives',
                               help='Leave empty to apply the rule to every sales representative.')
    basis = fields.Selection(BASIS, 'Based On', required=True, default='order', tracking=True)
    method = fields.Selection(METHODS, 'Calculation', required=True, default='percent', tracking=True)
    amount_basis = fields.Selection([('untaxed', 'Untaxed amount'), ('total', 'Total including tax')],
                                    'Order Amount', default='untaxed', required=True)
    percent = fields.Float('Rate %', tracking=True)
    fixed_amount = fields.Float('Fixed Amount', tracking=True,
                                help='Orders / collection: paid for every document.\n'
                                     'Target: paid once when the minimum achievement is reached.')
    tier_ids = fields.One2many('mo.sales.commission.tier', 'rule_id', 'Tiers', copy=True)
    target_metric = fields.Selection(TARGET_METRICS, 'Achievement Measured On', default='overall')
    target_amount_on = fields.Selection([('sales', 'Sales'), ('collection', 'Collection')],
                                        'Commission Is Paid On', default='sales',
                                        help='The amount the rate is applied to once the target condition is met.')
    min_achievement = fields.Float('Minimum Achievement %', default=100.0,
                                   help='Nothing is paid below this achievement.')
    note = fields.Text('Notes')
    currency_id = fields.Many2one(related='company_id.currency_id')

    @api.constrains('percent', 'fixed_amount', 'tier_ids', 'method')
    def _check_values(self):
        for rule in self:
            if rule.percent < 0 or rule.fixed_amount < 0 or any(t.rate < 0 or t.threshold < 0 for t in rule.tier_ids):
                raise ValidationError(_('Rates, amounts and thresholds cannot be negative.'))
            if rule.method == 'tiered' and not rule.tier_ids:
                raise ValidationError(_('A tiered rule needs at least one tier.'))

    @api.model
    def rules_for(self, rep):
        """Active rules that apply to a representative."""
        return self.sudo().search([
            ('active', '=', True), ('company_id', 'in', (False, rep.company_id.id)),
            '|', ('rep_ids', '=', False), ('rep_ids', 'in', rep.ids)])

    # ------------------------------------------------------------------
    def _tiers(self):
        self.ensure_one()
        return [(t.threshold, t.rate) for t in self.tier_ids.sorted(lambda t: (t.threshold, t.id))]

    def _documents(self, rep, d_from, d_to):
        """[(date, reference, partner, amount)] the rule is based on, oldest first."""
        self.ensure_one()
        env = self.env
        if self.basis == 'order':
            start, end = datetime.combine(d_from, time.min), datetime.combine(d_to, time.max)
            orders = env['sale.order'].sudo().search([
                ('state', 'in', ('sale', 'done')), '|', ('mo_rep_id', '=', rep.id), ('user_id', '=', rep.user_id.id),
                ('date_order', '>=', start), ('date_order', '<=', end)], order='date_order, id')
            field = 'amount_untaxed' if self.amount_basis == 'untaxed' else 'amount_total'
            return [(o.date_order.date(), o.name, o.partner_id, o[field]) for o in orders]
        pays = env['account.payment'].sudo().search([
            ('payment_type', '=', 'inbound'), ('state', 'not in', ('draft', 'canceled', 'rejected')),
            '|', ('mo_rep_id', '=', rep.id), ('create_uid', '=', rep.user_id.id),
            ('date', '>=', d_from), ('date', '<=', d_to)], order='date, id')
        return [(p.date, p.name or _('Payment'), p.partner_id, p.amount) for p in pays]

    def _line(self, d_to, description, base=0.0, rate=0.0, amount=0.0, date=None, partner=None):
        return {'rule_id': self.id, 'date': date or d_to, 'description': description,
                'partner_id': partner.id if partner else False, 'base_amount': base, 'rate': rate, 'amount': amount}

    def build_lines(self, rep, d_from, d_to):
        """Commission lines (dicts ready for mo.sales.commission.line) of one representative for a period."""
        self.ensure_one()
        if self.basis == 'target':
            return self._build_target_lines(rep, d_from, d_to)
        tiers = self._tiers()
        lines, cumulative = [], 0.0
        for date, ref, partner, amount in self._documents(rep, d_from, d_to):
            if self.method == 'percent':
                commission = amount * self.percent / 100.0
            elif self.method == 'fixed':
                commission = self.fixed_amount
            else:  # tiered: this document's share of the period slabs
                commission = slab_commission(tiers, cumulative + amount) - slab_commission(tiers, cumulative)
            cumulative += amount
            rate = commission / amount * 100.0 if amount else 0.0
            lines.append(self._line(d_to, ref, amount, rate, commission, date=date, partner=partner))
        return lines

    def _build_target_lines(self, rep, d_from, d_to):
        self.ensure_one()
        target = self.env['mo.sales.target'].sudo().search([
            ('rep_id', '=', rep.id), ('date_from', '<=', d_to), ('date_to', '>=', d_from)],
            order='date_to desc', limit=1)
        label = dict(self._fields['target_metric'].selection)[self.target_metric]
        if not target:
            return [self._line(d_to, _('No target is defined for this period'))]
        if self.target_metric == 'overall':
            achievement = target._achievement()
        else:
            row = next((r for r in target.progress() if r['key'] == self.target_metric), None)
            if not row:
                return [self._line(d_to, _('No %s target is defined for this period', label))]
            achievement = row['pct']
        base = rep.performance(d_from, d_to).get(self.target_amount_on, 0.0)
        text = _('%(metric)s achievement: %(pct).1f%%', metric=label, pct=achievement)
        rate, amount = 0.0, 0.0
        if self.method == 'tiered':
            rate = level_rate(self._tiers(), achievement)
            amount = base * rate / 100.0
        elif achievement >= self.min_achievement:
            if self.method == 'percent':
                rate = self.percent
                amount = base * rate / 100.0
            else:
                amount = self.fixed_amount
        return [self._line(d_to, text, base if self.method != 'fixed' else 0.0, rate, amount)]

    @api.model
    def estimate(self, rep, d_from, d_to):
        """Live estimate for the portal: ([{'rule', 'lines', 'total'}], grand total). Nothing is saved."""
        groups, grand = [], 0.0
        for rule in self.rules_for(rep):
            lines = rule.build_lines(rep, d_from, d_to)
            total = sum(l['amount'] for l in lines)
            groups.append({'rule': rule, 'lines': lines, 'total': total})
            grand += total
        return groups, grand


class CommissionLine(models.Model):
    _name = 'mo.sales.commission.line'
    _description = 'Sales Commission Line'
    _order = 'rule_id, date, id'

    statement_id = fields.Many2one('mo.sales.commission', required=True, ondelete='cascade', index=True)
    rule_id = fields.Many2one('mo.sales.commission.rule', 'Rule', ondelete='set null')
    date = fields.Date()
    description = fields.Char('Reference / Description', required=True)
    partner_id = fields.Many2one('res.partner', 'Customer')
    base_amount = fields.Float('Base Amount')
    rate = fields.Float('Rate %')
    amount = fields.Float('Commission')
    currency_id = fields.Many2one(related='statement_id.currency_id')


class CommissionStatement(models.Model):
    _name = 'mo.sales.commission'
    _description = 'Sales Commission Statement'
    _inherit = ['mail.thread']
    _order = 'date_from desc, rep_id'

    name = fields.Char(compute='_compute_name', store=True)
    rep_id = fields.Many2one('mo.sales.rep', 'Sales Representative', required=True, ondelete='restrict', tracking=True)
    date_from = fields.Date('From', required=True, tracking=True,
                            default=lambda s: month_bounds(fields.Date.context_today(s))[0])
    date_to = fields.Date('To', required=True, tracking=True,
                          default=lambda s: month_bounds(fields.Date.context_today(s))[1])
    state = fields.Selection([('draft', 'Draft'), ('approved', 'Approved'), ('paid', 'Paid')],
                             default='draft', required=True, tracking=True, copy=False)
    line_ids = fields.One2many('mo.sales.commission.line', 'statement_id', 'Lines', copy=False)
    total = fields.Monetary(compute='_compute_total', store=True, currency_field='currency_id')
    company_id = fields.Many2one('res.company', related='rep_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    approved_by = fields.Many2one('res.users', readonly=True, copy=False)
    approved_date = fields.Datetime(readonly=True, copy=False)
    paid_date = fields.Date(readonly=True, copy=False)
    note = fields.Text('Notes')

    @api.depends('rep_id.name', 'date_from', 'date_to')
    def _compute_name(self):
        for st in self:
            st.name = '%s  %s → %s' % (st.rep_id.name or '', st.date_from or '', st.date_to or '')

    @api.depends('line_ids.amount')
    def _compute_total(self):
        for st in self:
            st.total = sum(st.line_ids.mapped('amount'))

    @api.constrains('date_from', 'date_to', 'rep_id')
    def _check_period(self):
        for st in self:
            if st.date_to < st.date_from:
                raise ValidationError(_('The end of the period must be after its start.'))
            if self.search_count([('rep_id', '=', st.rep_id.id), ('id', '!=', st.id),
                                  ('date_from', '<=', st.date_to), ('date_to', '>=', st.date_from)]):
                raise ValidationError(_('This representative already has a commission statement overlapping this period.'))

    def unlink(self):
        if any(st.state != 'draft' for st in self):
            raise UserError(_('Only a draft statement can be deleted. Reset it to draft first.'))
        return super().unlink()

    # ------------------------------------------------------------------
    def action_compute(self):
        """(Re)build the lines from the rules. Manual changes of a draft are replaced."""
        Rule = self.env['mo.sales.commission.rule']
        for st in self:
            if st.state != 'draft':
                raise UserError(_('Only a draft statement can be recalculated.'))
            rules = Rule.rules_for(st.rep_id)
            if not rules:
                raise UserError(_('No commission rule applies to %s.', st.rep_id.name))
            vals = []
            for rule in rules:
                vals += rule.build_lines(st.rep_id, st.date_from, st.date_to)
            st.line_ids.unlink()
            st.write({'line_ids': [(0, 0, v) for v in vals]})
        return True

    def action_approve(self):
        for st in self:
            if st.state != 'draft':
                continue
            if not st.line_ids:
                raise UserError(_('Calculate the statement before approving it.'))
            st.write({'state': 'approved', 'approved_by': self.env.user.id, 'approved_date': fields.Datetime.now()})
            st.rep_id._notify(_('Commission statement approved'), '%s: %.2f' % (st.name, st.total),
                              '/rep/commission/%s' % st.id, key='commission:%s' % st.id)
        return True

    def action_paid(self):
        for st in self.filtered(lambda s: s.state == 'approved'):
            st.write({'state': 'paid', 'paid_date': fields.Date.context_today(st)})
        return True

    def action_draft(self):
        for st in self.filtered(lambda s: s.state != 'draft'):
            st.write({'state': 'draft', 'approved_by': False, 'approved_date': False, 'paid_date': False})
        return True


class CommissionGenerate(models.TransientModel):
    _name = 'mo.sales.commission.generate'
    _description = 'Generate Commission Statements'

    date_from = fields.Date('From', required=True,
                            default=lambda s: month_bounds(fields.Date.context_today(s).replace(day=1) - timedelta(days=1))[0])
    date_to = fields.Date('To', required=True,
                          default=lambda s: fields.Date.context_today(s).replace(day=1) - timedelta(days=1))
    rep_ids = fields.Many2many('mo.sales.rep', string='Sales Representatives',
                               help='Leave empty to generate for every representative that has a commission rule.')

    def action_generate(self):
        self.ensure_one()
        Statement, Rule = self.env['mo.sales.commission'], self.env['mo.sales.commission.rule']
        created = Statement
        for rep in (self.rep_ids or self.env['mo.sales.rep'].search([])):
            if not Rule.rules_for(rep):
                continue
            if Statement.search_count([('rep_id', '=', rep.id), ('date_from', '<=', self.date_to),
                                       ('date_to', '>=', self.date_from)]):
                continue
            st = Statement.create({'rep_id': rep.id, 'date_from': self.date_from, 'date_to': self.date_to})
            st.action_compute()
            created |= st
        if not created:
            raise UserError(_('Nothing was generated: every representative with a rule already has a statement '
                              'for this period, or no rule applies.'))
        return {'type': 'ir.actions.act_window', 'name': _('Commission Statements'), 'res_model': Statement._name,
                'view_mode': 'list,form', 'domain': [('id', 'in', created.ids)]}
