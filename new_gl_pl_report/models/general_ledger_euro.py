# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import json

from odoo import models, fields, api, _
from odoo.tools.misc import format_date
from odoo.tools import get_lang, SQL
from odoo.exceptions import UserError

from datetime import timedelta
from collections import defaultdict


class GeneralLedgerCustomHandlerCurEuro(models.AbstractModel):
    _name = 'account.general.ledger.report.handler.cur.euro'
    _inherit = 'account.general.ledger.report.handler'
    _description = 'General Ledger Custom Handler Currency Euro'


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
                    %(debit_select)s                        AS debit,
                    %(credit_select)s                       AS credit,
                    %(balance_select)s                      AS balance,
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
                debit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_debit")),
                credit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_credit")),
                balance_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_currency")),
                search_condition=query.where_clause,
            )
            queries.append(query)

        full_query = SQL(" UNION ALL ").join(SQL("(%s)", query) for query in queries)

        if offset:
            full_query = SQL('%s OFFSET %s ', full_query, offset)
        if limit:
            full_query = SQL('%s LIMIT %s ', full_query, limit)

        return full_query

    def _report_expand_unfoldable_line_general_ledger(self, line_dict_id, groupby, options, progress, offset, unfold_all_batch_data=None):
        def init_load_more_progress(line_dict):
            return {
                column['column_group_key']: line_col.get('no_format', 0)
                for column, line_col in  zip(options['columns'], line_dict['columns'])
                if column['expression_label'] == 'balance'
            }

        report = self.env.ref('new_gl_pl_report.general_ledger_cur_euro_report_inherit')
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
        limit_to_load = report.load_more_limit + 1 if report.load_more_limit and not self._context.get('print_mode') else None
        has_more = False
        if unfold_all_batch_data:
            aml_results = unfold_all_batch_data['aml_values'][model_id]
        else:
            aml_results, has_more = self._get_aml_values(report, options, [model_id], offset=offset, limit=limit_to_load)
            aml_results = aml_results[model_id]

        next_progress = progress
        for aml_result in aml_results.values():
            new_line = self._get_aml_line(report, line_dict_id, options, aml_result, next_progress)
            lines.append(new_line)
            next_progress = init_load_more_progress(new_line)

        return {
            'lines': lines,
            'offset_increment': report.load_more_limit,
            'has_more': has_more,
            'progress': json.dumps(next_progress),
        }

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
                    SUM(%(debit_select)s)                                 AS debit,
                    SUM(%(credit_select)s)                                AS credit,
                    SUM(%(balance_select)s)                               AS balance
                FROM %(table_references)s
                %(currency_table_join)s
                WHERE %(search_condition)s
                GROUP BY account_move_line.account_id
                """,
                column_group_key=column_group_key,
                table_references=query.from_clause,
                debit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_debit")),
                credit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_credit")),
                balance_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_currency")),
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
                    SUM(%(debit_select)s)   AS debit,
                    SUM(%(credit_select)s)  AS credit,
                    SUM(%(balance_select)s) AS balance
                FROM %(table_references)s
                %(currency_table_join)s
                WHERE %(search_condition)s
                GROUP BY account_move_line.account_id
                """,
                column_group_key=column_group_key,
                table_references=query.from_clause,
                debit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_debit")),
                credit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_credit")),
                balance_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_currency")),
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
                        SUM(%(balance_select)s) AS balance
                    FROM %(table_references)s
                    %(currency_table_join)s
                    WHERE %(search_condition)s
                    GROUP BY account_move_line.company_id
                    """,
                    column_group_key=column_group_key,
                    table_references=query.from_clause,
                    debit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_debit")),
                    credit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_credit")),
                    balance_select=report._currency_table_apply_rate(SQL("account_move_line.pl_currency")),
                    currency_table_join=report._currency_table_aml_join(options_group),
                    search_condition=query.where_clause,
                ))

        return SQL(" UNION ALL ").join(queries)
