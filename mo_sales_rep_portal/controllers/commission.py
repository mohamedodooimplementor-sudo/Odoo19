"""Portal: the representative's commission (live estimate for the month + approved monthly statements)."""
from odoo import fields, http
from odoo.http import request

from ..models.commission import month_bounds
from .i18n import T
from .main import _forbidden, _redir, _render, _today, rep_required

LINES_SHOWN = 300


class RepCommission(http.Controller):

    @http.route('/rep/commissions', type='http', auth='user')
    @rep_required
    def commissions(self, rep, **kw):
        env = request.env
        if not rep.has_commission():
            return _redir('/rep', T('This action is not allowed.'), 'err')
        today = _today()
        d_from, d_to = month_bounds(today)
        groups, grand = env['mo.sales.commission.rule'].estimate(rep, d_from, d_to)
        partner_ids = {l['partner_id'] for g in groups for l in g['lines'] if l['partner_id']}
        partners = {p.id: p.display_name for p in env['res.partner'].sudo().browse(list(partner_ids)).exists()}
        statements = env['mo.sales.commission'].sudo().search(
            [('rep_id', '=', rep.id), ('state', 'in', ('approved', 'paid'))], limit=24)
        return _render('mo_sales_rep_portal.tpl_commissions', rep, 'more', T('My Commission'),
                       d_from=d_from, d_to=d_to, groups=groups, grand=grand, partners=partners,
                       statements=statements, shown=LINES_SHOWN)

    @http.route('/rep/commission/<int:statement_id>', type='http', auth='user')
    @rep_required
    def commission(self, rep, statement_id, **kw):
        st = request.env['mo.sales.commission'].sudo().search(
            [('id', '=', statement_id), ('rep_id', '=', rep.id), ('state', 'in', ('approved', 'paid'))], limit=1)
        if not st:
            return _redir('/rep/commissions', T('Record not found.'), 'err')
        by_rule = {}
        for line in st.line_ids:
            by_rule.setdefault(line.rule_id, []).append(line)
        return _render('mo_sales_rep_portal.tpl_commission', rep, 'more', T('Commission Statement'),
                       st=st, by_rule=list(by_rule.items()), shown=LINES_SHOWN)
