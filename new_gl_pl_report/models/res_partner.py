# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    # Display only: nothing is stored, nothing else in Odoo reads these two fields.
    pl_button_amount = fields.Monetary(
        string="Partner Ledger Balance",
        compute='_compute_pl_button_amount',
        currency_field='pl_button_currency_id',
    )
    pl_button_currency_id = fields.Many2one(
        'res.currency', compute='_compute_pl_button_amount')

    # ------------------------------------------------------------------
    # Which ledger / currency belongs to a partner
    # ------------------------------------------------------------------
    def _get_ledger_currencies(self):
        """Currencies shown on the partner form (customer pricelist currency,
        vendor currency), whichever fields exist in this database."""
        currencies = self.env['res.currency']
        for partner in self:
            if 'property_product_pricelist' in partner._fields:
                currencies |= partner.property_product_pricelist.currency_id
            if 'property_purchase_currency_id' in partner._fields:
                currencies |= partner.property_purchase_currency_id
        return currencies

    def _get_ledger_choice(self):
        """'usd', 'eur', 'both' or 'company' for these partners."""
        company = self.env.company
        currencies = self._get_ledger_currencies()
        has_usd = bool(company.pl_currency) and company.pl_currency in currencies
        has_eur = bool(company.euro_pl_currency) and company.euro_pl_currency in currencies
        if has_usd and has_eur:
            return 'both'
        if has_usd:
            return 'usd'
        if has_eur:
            return 'eur'
        return 'company'

    # ------------------------------------------------------------------
    # Smart button: amount shown on it
    # ------------------------------------------------------------------
    @api.depends_context('company')
    def _compute_pl_button_amount(self):
        company = self.env.company
        sums = {}
        ids = [partner.id for partner in self if partner.id]
        # Same rule as the Odoo button (accounting readers only): nothing is
        # read for other users.
        if ids and self.env.user.has_group('account.group_account_readonly'):
            groups = self.env['account.move.line']._read_group(
                [('partner_id', 'in', ids),
                 ('company_id', '=', company.id),
                 ('parent_state', '=', 'posted'),
                 ('account_id.account_type', 'in', ('asset_receivable', 'liability_payable'))],
                groupby=['partner_id'],
                aggregates=['balance:sum', 'pl_currency:sum', 'euro_pl_currency:sum'],
            )
            for partner, balance, usd, eur in groups:
                sums[partner.id] = (balance, usd, eur)
        for partner in self:
            balance, usd, eur = sums.get(partner.id, (0.0, 0.0, 0.0))
            choice = partner._get_ledger_choice()
            if choice == 'usd':
                partner.pl_button_amount, partner.pl_button_currency_id = usd, company.pl_currency
            elif choice == 'eur':
                partner.pl_button_amount, partner.pl_button_currency_id = eur, company.euro_pl_currency
            else:
                partner.pl_button_amount, partner.pl_button_currency_id = balance, company.currency_id

    @api.model
    def _get_view(self, view_id=None, view_type='form', **options):
        """Put the balance on Odoo's own Partner Ledger button. The button is
        looked up by name, so if it is not in the form nothing is changed."""
        arch, view = super()._get_view(view_id, view_type, **options)
        if view_type == 'form':
            for button in arch.xpath("//button[@name='open_partner_ledger']"):
                for child in list(button):
                    button.remove(child)
                button.text = None
                button.attrib.pop('string', None)
                classes = (button.get('class') or '').split()
                if 'oe_stat_button' not in classes:
                    classes.append('oe_stat_button')
                button.set('class', ' '.join(classes))
                info = arch.makeelement('div', {'class': 'o_field_widget o_stat_info'})
                value = arch.makeelement('span', {'class': 'o_stat_value'})
                value.append(arch.makeelement('field', {
                    'name': 'pl_button_amount',
                    'widget': 'monetary',
                    'options': "{'currency_field': 'pl_button_currency_id'}",
                }))
                label = arch.makeelement('span', {'class': 'o_stat_text'})
                label.text = _("Partner Ledger")
                info.append(value)
                info.append(label)
                info.append(arch.makeelement('field', {
                    'name': 'pl_button_currency_id', 'invisible': '1'}))
                button.append(info)
        return arch, view

    # ------------------------------------------------------------------
    # Smart button: report that opens
    # ------------------------------------------------------------------
    def open_partner_ledger(self):
        """Open OUR Partner Ledger on the partner's own currency.
        USD partner -> USD report, EUR partner -> EUR report, both -> Combined,
        anything else -> Company Currency report."""
        xmlid = {
            'usd': 'new_gl_pl_report.action_account_report_partner_ledger_usd',
            'eur': 'new_gl_pl_report.action_account_report_partner_ledger_eur',
            'both': 'new_gl_pl_report.action_account_multi_report_partner_ledger',
            'company': 'new_gl_pl_report.action_account_report_partner_ledger_company',
        }[self._get_ledger_choice()]
        action = self.env['ir.actions.actions']._for_xml_id(xmlid)
        action['params'] = {
            'options': {'partner_ids': self.ids, 'unfold_all': True},
            'ignore_session': True,
        }
        return action
