# -*- coding: utf-8 -*-
import json

from odoo import fields, models, api, _
from odoo.exceptions import UserError
from odoo.tools import SQL
from odoo.tools.misc import format_date, get_lang
from collections import defaultdict


class GeneralLedgerCustomHandlerMulti(models.AbstractModel):
    _name = 'account.general.ledger.report.handler.multi'
    _inherit = 'account.general.ledger.report.handler'
    _description = 'General Ledger Custom Handler Currency Multi'

    _PL_LABELS = ('pl_debit', 'pl_credit', 'pl_currency', 'pl_amount', 'pl_balance')
    _EURO_PL_LABELS = ('euro_pl_debit', 'euro_pl_credit', 'euro_pl_currency', 'euro_pl_amount', 'euro_pl_balance')

    def _get_label_currency(self, label):
        """Currency symbol to display for a given column: $ / EUR columns use the
        currencies chosen in the settings, the other columns keep Odoo's default
        (company currency)."""
        if label in self._PL_LABELS:
            return self.env.company.pl_currency
        if label in self._EURO_PL_LABELS:
            return self.env.company.euro_pl_currency
        return None

    def _apply_label_currencies(self, report, options, line):
        for idx, column in enumerate(options['columns']):
            currency = self._get_label_currency(column['expression_label'])
            if not currency or idx >= len(line.get('columns', [])):
                continue
            old = line['columns'][idx]
            value = old.get('no_format')
            if value is None:
                continue
            new = report._build_column_dict(value, column, options=options, currency=currency)
            old.update(new)
        return line

    def _get_account_title_line(self, report, options, account, has_lines, eval_dict):
        line = super()._get_account_title_line(report, options, account, has_lines, eval_dict)
        return self._apply_label_currencies(report, options, line)

    def _get_total_line(self, report, options, eval_dict):
        line = super()._get_total_line(report, options, eval_dict)
        return self._apply_label_currencies(report, options, line)

    def _dynamic_lines_generator(self, report, options, all_column_groups_expression_totals, warnings=None):
        lines = []
        date_from = fields.Date.from_string(options['date']['date_from'])
        company_currency = self.env.company.currency_id

        totals_by_column_group = defaultdict(lambda: {
            'debit': 0, 'credit': 0, 'balance': 0, 'pl_debit': 0, 'pl_credit': 0, 'pl_currency': 0, 'euro_pl_debit': 0, 'euro_pl_credit': 0, 'euro_pl_currency': 0})
        for account, column_group_results in self._query_values(report, options):
            eval_dict = {}
            has_lines = False
            for column_group_key, results in column_group_results.items():
                account_sum = results.get('sum', {})
                account_un_earn = results.get('unaffected_earnings', {})

                account_debit = account_sum.get('debit', 0.0) + account_un_earn.get('debit', 0.0)
                account_credit = account_sum.get('credit', 0.0) + account_un_earn.get('credit', 0.0)
                account_balance = account_sum.get('balance', 0.0) + account_un_earn.get('balance', 0.0)
                account_pl_debit = account_sum.get('pl_debit', 0.0) + account_un_earn.get('pl_debit', 0.0)
                account_pl_credit = account_sum.get('pl_credit', 0.0) + account_un_earn.get('pl_credit', 0.0)
                account_pl_currency = account_sum.get('pl_currency', 0.0) + account_un_earn.get('pl_currency', 0.0)
                account_euro_pl_debit = (account_sum.get('euro_pl_debit', 0.0) or 0) + account_un_earn.get('euro_pl_debit', 0.0)
                account_euro_pl_credit = (account_sum.get('euro_pl_credit', 0.0)or 0) + account_un_earn.get('euro_pl_credit', 0.0)
                account_euro_pl_currency = (account_sum.get('euro_pl_currency', 0.0)or 0) + account_un_earn.get('euro_pl_currency', 0.0)
                eval_dict[column_group_key] = {
                    'amount_currency': account_sum.get('amount_currency', 0.0) + account_un_earn.get('amount_currency',
                                                                                                     0.0),
                    'debit': account_debit,
                    'credit': account_credit,
                    'balance': account_balance,
                    'pl_debit': account_pl_debit,
                    'pl_credit': account_pl_credit,
                    'pl_currency': account_pl_currency,
                    'euro_pl_debit': account_euro_pl_debit,
                    'euro_pl_credit': account_euro_pl_credit,
                    'euro_pl_currency': account_euro_pl_currency,
                }

                max_date = account_sum.get('max_date')
                has_lines = has_lines or (max_date and max_date >= date_from)

                totals_by_column_group[column_group_key]['debit'] += account_debit
                totals_by_column_group[column_group_key]['credit'] += account_credit
                totals_by_column_group[column_group_key]['balance'] += account_balance
                totals_by_column_group[column_group_key]['pl_debit'] += account_pl_debit
                totals_by_column_group[column_group_key]['pl_credit'] += account_pl_credit
                totals_by_column_group[column_group_key]['pl_currency'] += account_pl_currency
                totals_by_column_group[column_group_key]['euro_pl_debit'] += account_euro_pl_debit
                totals_by_column_group[column_group_key]['euro_pl_credit'] += account_euro_pl_credit
                totals_by_column_group[column_group_key]['euro_pl_currency'] += account_euro_pl_currency

            lines.append(self._get_account_title_line(report, options, account, has_lines, eval_dict))

        # Report total line.
        for totals in totals_by_column_group.values():
            totals['balance'] = company_currency.round(totals['balance'])
        #     mrm

        # Tax Declaration lines.
        journal_options = report._get_options_journals(options)
        if len(options['column_groups']) == 1 and len(journal_options) == 1 and journal_options[0]['type'] in (
        'sale', 'purchase'):
            lines += self._tax_declaration_lines(report, options, journal_options[0]['type'])

        # Total line
        lines.append(self._get_total_line(report, options, totals_by_column_group))

        return [(0, line) for line in lines]

    def _get_query_sums(self, report, options):
        """ Construct a query retrieving all the aggregated sums to build the report. It includes:
        - sums for all accounts.
        - sums for the initial balances.
        - sums for the unaffected earnings.
        - sums for the tax declaration.
        :return:                    (query, params)
        """
        options_by_column_group = report._split_options_per_column_group(options)

        queries = []

        # ============================================
        # 1) Get sums for all accounts.
        # ============================================
        for column_group_key, options_group in options_by_column_group.items():
            # if not options.get('general_ledger_strict_range'):
            #     options_group = self._get_options_sum_balance(options_group)

            # Sum is computed including the initial balance of the accounts configured to do so, unless a special option key is used
            # (this is required for trial balance, which is based on general ledger)
            sum_date_scope = 'strict_range' if options_group.get('general_ledger_strict_range') else 'from_beginning'

            query_domain = []

            if not options_group.get('general_ledger_strict_range'):
                date_from = fields.Date.from_string(options_group['date']['date_from'])
                current_fiscalyear_dates = self.env.company.compute_fiscalyear_dates(date_from)
                query_domain += [
                    '|',
                    ('date', '>=', current_fiscalyear_dates['date_from']),
                    ('account_id.include_initial_balance', '=', True),
                ]

            if options_group.get('export_mode') == 'print' and options_group.get('filter_search_bar'):
                query_domain.append(('account_id', 'ilike', options_group['filter_search_bar']))

            if options_group.get('include_current_year_in_unaff_earnings'):
                query_domain += [('account_id.include_initial_balance', '=', True)]

            query = report._get_report_query(options_group, sum_date_scope, domain=query_domain)
            queries.append(SQL(
                """
                SELECT
                    account_move_line.account_id                            AS groupby,
                    'sum'                                                   AS key,
                    MAX(account_move_line.date)                             AS max_date,
                    %(column_group_key)s                                    AS column_group_key,
                    COALESCE(SUM(account_move_line.amount_currency), 0.0)   AS amount_currency,
                    SUM(%(debit_select)s)                                   AS debit,
                    SUM(%(credit_select)s)                                  AS credit,
                    SUM(%(balance_select)s)                                 AS balance,
                    SUM(%(pl_debit_select)s)                                   AS pl_debit,
                    SUM(%(pl_credit_select)s)                                  AS pl_credit,
                    SUM(%(pl_balance_select)s)                                 AS pl_currency,
                    SUM(%(euro_pl_debit_select)s)                                   AS euro_pl_debit,
                    SUM(%(euro_pl_credit_select)s)                                  AS euro_pl_credit,
                    SUM(%(euro_pl_balance_select)s)                                 AS euro_pl_currency
                FROM %(table_references)s
                %(currency_table_join)s
                WHERE %(search_condition)s
                GROUP BY account_move_line.account_id
                """,
                column_group_key=column_group_key,
                table_references=query.from_clause,
                debit_select=report._currency_table_apply_rate(SQL("account_move_line.debit")),
                credit_select=report._currency_table_apply_rate(SQL("account_move_line.credit")),
                balance_select=report._currency_table_apply_rate(SQL("account_move_line.balance")),
                pl_debit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_debit")),
                pl_credit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_credit")),
                pl_balance_select=report._currency_table_apply_rate(SQL("account_move_line.pl_currency")),
                euro_pl_debit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_debit")),
                euro_pl_credit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_credit")),
                euro_pl_balance_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_currency")),
                currency_table_join=report._currency_table_aml_join(options_group),
                search_condition=query.where_clause,
            ))

            # ============================================
            # 2) Get sums for the unaffected earnings.
            # ============================================
            if not options_group.get('general_ledger_strict_range'):
                unaff_earnings_domain = [('account_id.include_initial_balance', '=', False)]

                # The period domain is expressed as:
                # [
                #   ('date' <= fiscalyear['date_from'] - 1),
                #   ('account_id.include_initial_balance', '=', False),
                # ]

                new_options = self._get_options_unaffected_earnings(options_group)
                query = report._get_report_query(new_options, 'strict_range', domain=unaff_earnings_domain)
                queries.append(SQL(
                    """
                    SELECT
                        account_move_line.company_id                            AS groupby,
                        'unaffected_earnings'                                   AS key,
                        NULL                                                    AS max_date,
                        %(column_group_key)s                                    AS column_group_key,
                        COALESCE(SUM(account_move_line.amount_currency), 0.0)   AS amount_currency,
                        SUM(%(debit_select)s)                                   AS debit,
                        SUM(%(credit_select)s)                                  AS credit,
                        SUM(%(balance_select)s)                                 AS balance,
                        SUM(%(pl_debit_select)s)                                   AS pl_debit,
                        SUM(%(pl_credit_select)s)                                  AS pl_credit,
                        SUM(%(pl_balance_select)s)                                 AS pl_currency,
                        SUM(%(euro_pl_debit_select)s)                                   AS euro_pl_debit,
                        SUM(%(euro_pl_credit_select)s)                                  AS euro_pl_credit,
                        SUM(%(euro_pl_balance_select)s)                                 AS euro_pl_balance
                    FROM %(table_references)s
                    %(currency_table_join)s
                    WHERE %(search_condition)s
                    GROUP BY account_move_line.company_id
                    """,
                    column_group_key=column_group_key,
                    table_references=query.from_clause,
                    debit_select=report._currency_table_apply_rate(SQL("account_move_line.debit")),
                    credit_select=report._currency_table_apply_rate(SQL("account_move_line.credit")),
                    balance_select=report._currency_table_apply_rate(SQL("account_move_line.balance")),
                    pl_debit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_debit")),
                    pl_credit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_credit")),
                    pl_balance_select=report._currency_table_apply_rate(SQL("account_move_line.pl_currency")),
                    euro_pl_debit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_debit")),
                    euro_pl_credit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_credit")),
                    euro_pl_balance_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_currency")),
                    currency_table_join=report._currency_table_aml_join(options_group),
                    search_condition=query.where_clause,
                ))

        return SQL(" UNION ALL ").join(queries)

    def _get_aml_values(self, report, options, expanded_account_ids, offset=0, limit=None):
        rslt = {account_id: {} for account_id in expanded_account_ids}
        aml_query = self._get_query_amls(report, options, expanded_account_ids, offset=offset, limit=limit)
        self._cr.execute(aml_query)
        aml_results_number = 0
        has_more = False
        for aml_result in self._cr.dictfetchall():
            aml_results_number += 1
            if aml_results_number == limit:
                has_more = True
                break

            # For asset_receivable the name will already contains the ref with the _compute_name
            if aml_result['ref'] and aml_result['account_type'] != 'asset_receivable':
                aml_result['communication'] = f"{aml_result['ref']} - {aml_result['name']}"
            else:
                aml_result['communication'] = aml_result['name']

            # The same aml can return multiple results when using account_report_cash_basis module, if the receivable/payable
            # is reconciled with multiple payments. In this case, the date shown for the move lines actually corresponds to the
            # reconciliation date. In order to keep distinct lines in this case, we include date in the grouping key.
            aml_key = (aml_result['id'], aml_result['date'])

            account_result = rslt[aml_result['account_id']]
            if not aml_key in account_result:
                account_result[aml_key] = {col_group_key: {} for col_group_key in options['column_groups']}

            already_present_result = account_result[aml_key][aml_result['column_group_key']]
            if already_present_result:
                # In case the same move line gives multiple results at the same date, add them.
                # This does not happen in standard GL report, but could because of custom shadowing of account.move.line,
                # such as the one done in account_report_cash_basis (if the payable/receivable line is reconciled twice at the same date).
                already_present_result['debit'] += aml_result['debit']
                already_present_result['credit'] += aml_result['credit']
                already_present_result['balance'] += aml_result['balance']
                already_present_result['amount_currency'] += aml_result['amount_currency']
                already_present_result['pl_debit'] += aml_result['pl_debit']
                already_present_result['pl_credit'] += aml_result['pl_credit']
                already_present_result['pl_currency'] += aml_result['pl_currency']
                already_present_result['euro_pl_debit'] += aml_result['euro_pl_debit']
                already_present_result['euro_pl_credit'] += aml_result['euro_pl_credit']
                already_present_result['euro_pl_currency'] += aml_result['euro_pl_currency']
            else:
                account_result[aml_key][aml_result['column_group_key']] = aml_result

        return rslt, has_more

    def _get_query_amls(self, report, options, expanded_account_ids, offset=0, limit=None) -> SQL:
        """ Construct a query retrieving the account.move.lines when expanding a report line with or without the load
        more.
        :param options:               The report options.
        :param expanded_account_ids:  The account.account ids corresponding to consider. If None, match every account.
        :param offset:                The offset of the query (used by the load more).
        :param limit:                 The limit of the query (used by the load more).
        :return:                      (query, params)
        """
        additional_domain = [('account_id', 'in', expanded_account_ids)] if expanded_account_ids is not None else None
        queries = []
        journal_name = self.env['account.journal']._field_to_sql('journal', 'name')
        for column_group_key, group_options in report._split_options_per_column_group(options).items():
            # Get sums for the account move lines.
            # period: [('date' <= options['date_to']), ('date', '>=', options['date_from'])]
            query = report._get_report_query(group_options, domain=additional_domain, date_scope='strict_range')
            account_alias = query.join(lhs_alias='account_move_line', lhs_column='account_id', rhs_table='account_account', rhs_column='id', link='account_id')
            account_code = self.env['account.account']._field_to_sql(account_alias, 'code', query)
            account_name = self.env['account.account']._field_to_sql(account_alias, 'name')
            account_type = self.env['account.account']._field_to_sql(account_alias, 'account_type')

            query = SQL(
                '''
                SELECT
                    account_move_line.id,
                    account_move_line.date,
                    account_move_line.date_maturity,
                    account_move_line.name,
                    account_move_line.ref,
                    account_move_line.company_id,
                    account_move_line.account_id,
                    account_move_line.payment_id,
                    account_move_line.partner_id,
                    account_move_line.currency_id,
                    account_move_line.amount_currency,
                    COALESCE(account_move_line.invoice_date, account_move_line.date) AS invoice_date,
                    account_move_line.date                  AS date,
                    %(debit_select)s                                   AS debit,
                    %(credit_select)s                                  AS credit,
                    %(balance_select)s                                 AS balance,
                    %(pl_debit_select)s                                   AS pl_debit,
                    %(pl_credit_select)s                                  AS pl_credit,
                    %(pl_balance_select)s                                 AS pl_currency,
                    %(euro_pl_debit_select)s                                   AS euro_pl_debit,
                    %(euro_pl_credit_select)s                                  AS euro_pl_credit,
                    %(euro_pl_balance_select)s                                   AS euro_pl_currency,
                    move.name                               AS move_name,
                    company.currency_id                     AS company_currency_id,
                    partner.name                            AS partner_name,
                    move.move_type                          AS move_type,
                    %(account_code)s                        AS account_code,
                    %(account_name)s                        AS account_name,
                    %(account_type)s                        AS account_type,
                    journal.code                            AS journal_code,
                    %(journal_name)s                        AS journal_name,
                    full_rec.id                             AS full_rec_name,
                    %(column_group_key)s                    AS column_group_key
                FROM %(table_references)s
                JOIN account_move move                      ON move.id = account_move_line.move_id
                %(currency_table_join)s
                LEFT JOIN res_company company               ON company.id = account_move_line.company_id
                LEFT JOIN res_partner partner               ON partner.id = account_move_line.partner_id
                LEFT JOIN account_journal journal           ON journal.id = account_move_line.journal_id
                LEFT JOIN account_full_reconcile full_rec   ON full_rec.id = account_move_line.full_reconcile_id
                WHERE %(search_condition)s
                ORDER BY account_move_line.date, account_move_line.move_name, account_move_line.id
                ''',
                account_code=account_code,
                account_name=account_name,
                account_type=account_type,
                journal_name=journal_name,
                column_group_key=column_group_key,
                table_references=query.from_clause,
                currency_table_join=report._currency_table_aml_join(group_options),
                debit_select=report._currency_table_apply_rate(SQL("account_move_line.debit")),
                credit_select=report._currency_table_apply_rate(SQL("account_move_line.credit")),
                balance_select=report._currency_table_apply_rate(SQL("account_move_line.balance")),
                pl_debit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_debit")),
                pl_credit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_credit")),
                pl_balance_select=report._currency_table_apply_rate(SQL("account_move_line.pl_currency")),
                euro_pl_debit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_debit")),
                euro_pl_credit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_credit")),
                euro_pl_balance_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_currency")),
                search_condition=query.where_clause,
            )
            queries.append(query)

        full_query = SQL(" UNION ALL ").join(SQL("(%s)", query) for query in queries)

        if offset:
            full_query = SQL('%s OFFSET %s ', full_query, offset)
        if limit:
            full_query = SQL('%s LIMIT %s ', full_query, limit)

        return full_query

    def _get_initial_balance_values(self, report, account_ids, options):
        """
        Get sums for the initial balance.
        """
        queries = []
        for column_group_key, options_group in report._split_options_per_column_group(options).items():
            new_options = self._get_options_initial_balance(options_group)
            domain = [
                ('account_id', 'in', account_ids),
            ]
            if not new_options.get('general_ledger_strict_range'):
                domain += [
                    '|',
                    ('date', '>=', new_options['date']['date_from']),
                    ('account_id.include_initial_balance', '=', True),
                ]
            if new_options.get('include_current_year_in_unaff_earnings'):
                domain += [('account_id.include_initial_balance', '=', True)]
            query = report._get_report_query(new_options, 'from_beginning', domain=domain)
            queries.append(SQL(
                """
                SELECT
                    account_move_line.account_id                          AS groupby,
                    'initial_balance'                                     AS key,
                    NULL                                                  AS max_date,
                    %(column_group_key)s                                  AS column_group_key,
                    COALESCE(SUM(account_move_line.amount_currency), 0.0) AS amount_currency,
                    SUM(%(debit_select)s)                                   AS debit,
                    SUM(%(credit_select)s)                                  AS credit,
                    SUM(%(balance_select)s)                                 AS balance,
                    SUM(%(pl_debit_select)s)                                   AS pl_debit,
                    SUM(%(pl_credit_select)s)                                  AS pl_credit,
                    SUM(%(pl_balance_select)s)                                 AS pl_currency,
                    SUM(%(euro_pl_debit_select)s)                                   AS euro_pl_debit,
                    SUM(%(euro_pl_credit_select)s)                                  AS euro_pl_credit,
                    SUM(%(euro_pl_balance_select)s)                                 AS euro_pl_currency
                FROM %(table_references)s
                %(currency_table_join)s
                WHERE %(search_condition)s
                GROUP BY account_move_line.account_id
                """,
                column_group_key=column_group_key,
                table_references=query.from_clause,
                debit_select=report._currency_table_apply_rate(SQL("account_move_line.debit")),
                credit_select=report._currency_table_apply_rate(SQL("account_move_line.credit")),
                balance_select=report._currency_table_apply_rate(SQL("account_move_line.balance")),
                pl_debit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_debit")),
                pl_credit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_credit")),
                pl_balance_select=report._currency_table_apply_rate(SQL("account_move_line.pl_currency")),
                euro_pl_debit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_debit")),
                euro_pl_credit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_credit")),
                euro_pl_balance_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_currency")),
                currency_table_join=report._currency_table_aml_join(options_group),
                search_condition=query.where_clause,
            ))

        self._cr.execute(SQL(" UNION ALL ").join(queries))

        init_balance_by_col_group = {
            account_id: {column_group_key: {} for column_group_key in options['column_groups']}
            for account_id in account_ids
        }
        for result in self._cr.dictfetchall():
            init_balance_by_col_group[result['groupby']][result['column_group_key']] = result

        accounts = self.env['account.account'].browse(account_ids)
        return {
            account.id: (account, init_balance_by_col_group[account.id])
            for account in accounts
        }

    def _get_aml_line(self, report, parent_line_id, options, eval_dict, init_bal_by_col_group):
        line_columns = []
        for column in options['columns']:
            col_expr_label = column['expression_label']
            col_value = eval_dict[column['column_group_key']].get(col_expr_label)
            col_currency = None
    
            if col_value is None:
                line_columns.append(report._build_column_dict(None, None))
            else:
                # $ / EUR columns must show their own currency symbol
                col_currency = self._get_label_currency(col_expr_label)

                # Handle currency for amount_currency field
                if col_expr_label == 'amount_currency':
                    currency_id = eval_dict[column['column_group_key']].get('currency_id')
                    if currency_id:
                        col_currency = self.env['res.currency'].browse(currency_id)
                
                # Handle balance adjustments
                if col_expr_label == 'balance':
                    if isinstance(init_bal_by_col_group[column['column_group_key']], int):
                        col_value += init_bal_by_col_group[column['column_group_key']]
                    else:
                        col_value += init_bal_by_col_group[column['column_group_key']][0]
                elif col_expr_label == 'pl_currency' or col_expr_label == 'pl_balance':
                    if isinstance(init_bal_by_col_group[column['column_group_key']], int):
                        col_value += init_bal_by_col_group[column['column_group_key']]
                    else:
                        col_value += init_bal_by_col_group[column['column_group_key']][1]
                elif col_expr_label == 'euro_pl_currency':
                    if isinstance(init_bal_by_col_group[column['column_group_key']], int):
                        col_value += init_bal_by_col_group[column['column_group_key']]
                    else:
                        col_value += init_bal_by_col_group[column['column_group_key']][2]
    
                line_columns.append(report._build_column_dict(
                    col_value,
                    column,
                    options=options,
                    currency=col_currency,
                ))
    
        aml_id = None
        move_name = None
        caret_type = None
        for column_group_dict in eval_dict.values():
            aml_id = column_group_dict.get('id', '')
            if aml_id:
                if column_group_dict.get('payment_id'):
                    caret_type = 'account.payment'
                else:
                    caret_type = 'account.move.line'
                move_name = column_group_dict['move_name']
                break
    
        return {
            'id': report._get_generic_line_id('account.move.line', aml_id, parent_line_id=parent_line_id),
            'caret_options': caret_type,
            'parent_id': parent_line_id,
            'name': move_name,
            'columns': line_columns,
            'level': 2,
        }

    def _report_expand_unfoldable_line_general_ledger(self, line_dict_id, groupby, options, progress, offset, unfold_all_batch_data=None):
        def init_load_more_progress(line_dict):
            arr = {}
            bl1 = bl2 = bl3 = 0
            for column, line_col in zip(options['columns'], line_dict['columns']):
                if column['expression_label'] == 'balance':
                    bl1 = line_col.get('no_format', 0)
                if column['expression_label'] == 'pl_currency':
                    bl2 = line_col.get('no_format', 0)
                if column['expression_label'] == 'euro_pl_currency':
                    bl3 = line_col.get('no_format', 0)

                arr[column['column_group_key']] = (bl1, bl2, bl3)
            return arr

        report = self.env.ref('new_gl_pl_report.general_ledger_multi_report_inherit')
        model, model_id = report._get_model_info_from_id(line_dict_id)

        if model != 'account.account':
            raise UserError(_("Wrong ID for general ledger line to expand: %s", line_dict_id))

        lines = []

        # Get initial balance
        if offset == 0:
            if unfold_all_batch_data:
                account, init_balance_by_col_group = unfold_all_batch_data['initial_balances'][model_id]
            else:
                account, init_balance_by_col_group = self._get_initial_balance_values(report, [model_id], options)[model_id]

            initial_balance_line = report._get_partner_and_general_ledger_initial_balance_line(options, line_dict_id, init_balance_by_col_group, account.currency_id)

            if initial_balance_line:
                lines.append(initial_balance_line)

                # For the first expansion of the line, the initial balance line gives the progress
                progress = init_load_more_progress(initial_balance_line)

        # Get move lines
        limit_to_load = report.load_more_limit + 1 if report.load_more_limit and options['export_mode'] != 'print' else None
        if unfold_all_batch_data:
            aml_results = unfold_all_batch_data['aml_results'][model_id]
            has_more = unfold_all_batch_data['has_more'].get(model_id, False)
        else:
            aml_results, has_more = self._get_aml_values(report, options, [model_id], offset=offset, limit=limit_to_load)
            aml_results = aml_results[model_id]

        next_progress = progress
        # print(aml_results)
        for aml_result in aml_results.values():
            new_line = self._get_aml_line(report, line_dict_id, options, aml_result, next_progress)
            lines.append(new_line)
            next_progress = init_load_more_progress(new_line)

        return {
            'lines': lines,
            'offset_increment': report.load_more_limit,
            'has_more': has_more,
            'progress': next_progress,
        }



