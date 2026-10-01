# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_is_zero

from .mrp_bom import COST_TYPES

_logger = logging.getLogger(__name__)


class MrpProductionCostLine(models.Model):
    """Snapshot of the BOM manufacturing costs taken when the MO is created/confirmed."""
    _name = 'mrp.production.cost.line'
    _description = 'Manufacturing Order BOM Cost Line'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)
    production_id = fields.Many2one('mrp.production', required=True, ondelete='cascade', index=True)
    currency_id = fields.Many2one(related='production_id.company_id.currency_id')
    cost_type = fields.Selection(COST_TYPES, string='Cost Type', required=True)
    name = fields.Char(string='Description')
    account_id = fields.Many2one(
        'account.account', string='Account',
        domain="[('account_type', 'not in', ('asset_receivable', 'liability_payable'))]")
    amount_unit = fields.Float(string='Cost / Unit', digits='Product Price')
    amount_total = fields.Monetary(
        string='Total Cost', compute='_compute_amount_total', currency_field='currency_id')

    @api.constrains('amount_unit', 'account_id')
    def _check_cost_line(self):
        for line in self:
            if line.amount_unit < 0.0:
                raise ValidationError(_('The cost per unit cannot be negative.'))
            if line.account_id.account_type in ('asset_receivable', 'liability_payable'):
                raise ValidationError(_('Receivable and payable accounts cannot be used for manufacturing costs.'))

    @api.depends('amount_unit', 'production_id.qty_produced', 'production_id.product_qty',
                 'production_id.state', 'production_id.product_uom_id')
    def _compute_amount_total(self):
        for line in self:
            production = line.production_id
            qty = production.qty_produced if production.state == 'done' else production.product_qty
            qty = production.product_uom_id._compute_quantity(
                qty, production.product_id.uom_id, round=False)
            line.amount_total = line.amount_unit * qty


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    tm_cost_line_ids = fields.One2many(
        'mrp.production.cost.line', 'production_id', string='BOM Manufacturing Costs', copy=False)
    tm_unit_cost = fields.Float(
        'BOM Manufacturing Cost / Unit', digits='Product Price', readonly=True, copy=False,
        help='Labour + Overhead + Other from the BOM, per unit of the product. '
             'Added once to the standard MO Extra Cost.')
    tm_cost_move_id = fields.Many2one(
        'account.move', string='Manufacturing Cost Entry', readonly=True, copy=False)

    # ------------------------------------------------------------------
    # BOM cost -> standard MO "Extra Cost" (single source of truth for valuation)
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        productions = super().create(vals_list)
        productions._tm_apply_bom_costs()
        return productions

    def write(self, vals):
        res = super().write(vals)
        if 'bom_id' in vals:
            self.filtered(lambda p: p.state in ('draft', 'confirmed'))._tm_apply_bom_costs()
        return res

    def action_confirm(self):
        # the BOM may have been edited since the draft MO was created
        self.filtered(lambda p: p.state == 'draft')._tm_apply_bom_costs()
        return super().action_confirm()

    def _tm_apply_bom_costs(self):
        for production in self:
            if production.state in ('done', 'cancel'):
                continue
            old_unit = production.tm_unit_cost
            lines = []
            new_unit = 0.0
            bom = production.bom_id.sudo()
            if bom and bom.type == 'normal':
                factor = bom._tm_unit_factor()
                for cost in bom.mfg_cost_line_ids:
                    unit_amount = cost.amount * factor
                    new_unit += unit_amount
                    lines.append((0, 0, {
                        'sequence': cost.sequence,
                        'cost_type': cost.cost_type,
                        'name': cost.name or dict(COST_TYPES)[cost.cost_type],
                        'account_id': cost.account_id.id,
                        'amount_unit': unit_amount,
                    }))
            if not lines and not production.sudo().tm_cost_line_ids:
                continue
            if 'extra_cost' not in production._fields:
                raise UserError(_(
                    'The standard Manufacturing "Extra Cost" field (mrp_account) was not found, '
                    'so BOM manufacturing costs cannot be added to the production cost.'))
            # the cost lines are system-generated: users only need read access on them
            production.sudo().write({'tm_cost_line_ids': [(5, 0, 0)] + lines})
            production.write({
                'tm_unit_cost': new_unit,
                # keep any extra cost coming from elsewhere (e.g. subcontracting): swap only ours
                'extra_cost': max(production.extra_cost - old_unit, 0.0) + new_unit,
            })

    # ------------------------------------------------------------------
    # Accounting: route the credit of the absorbed cost to the BOM accounts
    # ------------------------------------------------------------------
    def button_mark_done(self):
        res = super().button_mark_done()
        self.filtered(lambda p: p.state == 'done')._tm_post_cost_entry()
        return res

    def action_tm_post_cost_entry(self):
        user = self.env.user
        if not (user.has_group('tender_management.group_tender_manager')
                or user.has_group('mrp.group_mrp_manager')):
            raise AccessError(_('Only Tender Managers or Manufacturing Managers can post the cost entry.'))
        self._tm_post_cost_entry(raise_errors=True)
        return True

    def _tm_post_cost_entry(self, raise_errors=False):
        """Standard valuation already put (Materials + BOM costs) into the finished product
        value; the difference sits as a credit on the valuation counterpart account of the
        finished move. This entry moves that credit to the accounts chosen on the BOM cost
        lines. It never touches inventory accounts, so the cost is not counted twice."""
        for production in self:
            if production.state != 'done' or production.tm_cost_move_id \
                    or not production.tm_cost_line_ids:
                continue
            try:
                with self.env.cr.savepoint():
                    production._tm_create_cost_entry()
            except Exception as error:  # noqa: BLE001 - never block the manufacturing flow
                if raise_errors:
                    raise
                _logger.exception('Tender Management: cost entry failed for %s', production.name)
                production.message_post(body=_(
                    'The manufacturing cost entry could not be posted automatically (%s). '
                    'Inventory valuation is not affected. Use "Post Cost Entry" to retry.'
                ) % error)

    def _tm_find_counterpart_account(self, entries, total):
        """The WIP / production account: debited by the consumed components and credited by the
        finished product, so its net balance is a credit equal to the absorbed extra cost."""
        self.ensure_one()
        balances = {}
        for line in entries.line_ids:
            pair = balances.setdefault(line.account_id, [0.0, 0.0])
            pair[0] += line.debit
            pair[1] += line.credit
        candidates = [(account, credit - debit) for account, (debit, credit) in balances.items()
                      if debit > 0 and credit > debit]
        if candidates:
            return min(candidates, key=lambda c: abs(c[1] - total))[0]
        categ = self.product_id.categ_id
        if 'property_stock_account_production_cost_id' in categ._fields:
            return categ.property_stock_account_production_cost_id
        return self.env['account.account']

    def _tm_create_cost_entry(self):
        self.ensure_one()
        AccountMove = self.env['account.move'].sudo()
        currency = self.company_id.currency_id
        uom = self.product_id.uom_id
        qty = self.product_uom_id._compute_quantity(self.qty_produced, uom, round=False)
        if float_is_zero(qty, precision_rounding=uom.rounding):
            return
        amounts = {}
        for line in self.tm_cost_line_ids:
            amount = currency.round(line.amount_unit * qty)
            if currency.is_zero(amount):
                continue
            if not line.account_id:
                raise UserError(_('The %s cost line has no account.') % line.name)
            amounts[line.account_id] = amounts.get(line.account_id, 0.0) + amount
        total = sum(amounts.values())
        if currency.is_zero(total):
            return

        # Valuation entries of this MO (materials -> WIP, WIP -> finished product).
        # Odoo 19 groups them per MO with the MO name as reference, so search by reference
        # and, when the field exists, also by the finished stock moves.
        entries = AccountMove.search([
            ('ref', '=', self.name), ('state', '!=', 'cancel'), ('move_type', '=', 'entry')])
        if 'stock_move_id' in AccountMove._fields:
            finished = self.move_finished_ids.filtered(lambda m: m.state == 'done')
            entries |= AccountMove.search([
                ('stock_move_id', 'in', finished.ids), ('state', '!=', 'cancel')])
        entries -= self.tm_cost_move_id.sudo()

        counterpart = self._tm_find_counterpart_account(entries, total)
        if not counterpart:
            self.message_post(body=_(
                'Manufacturing costs are included in inventory valuation, but the WIP / '
                'production account could not be found, so no account entry was generated.'))
            return
        journal = entries[:1].journal_id or self.env['account.journal'].sudo().search([
            ('type', '=', 'general'), ('company_id', '=', self.company_id.id)], limit=1)
        label = _('%s - Manufacturing costs absorbed') % self.name
        move_lines = [(0, 0, {
            'name': label, 'account_id': counterpart.id, 'debit': total, 'credit': 0.0})]
        for account, amount in amounts.items():
            move_lines.append((0, 0, {
                'name': label, 'account_id': account.id, 'debit': 0.0, 'credit': amount}))
        finished_date = self.date_finished or fields.Datetime.now()
        move = AccountMove.create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': fields.Date.to_date(finished_date),
            'ref': label,
            'company_id': self.company_id.id,
            'line_ids': move_lines,
        })
        move.action_post()
        self.tm_cost_move_id = move
        self.message_post(body=_('Manufacturing cost entry %s posted for %s.') % (
            move.name, currency.format(total)))
