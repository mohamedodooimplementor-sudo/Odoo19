# -*- coding: utf-8 -*-
import json

from odoo import fields, models, api, _
from odoo.exceptions import UserError
from odoo.tools import SQL
from odoo.tools.misc import format_date, get_lang
from collections import defaultdict


class PartnerLedgerCustomHandlerCur(models.AbstractModel):
    _name = 'account.partner.ledger.report.handler.cur'
    _inherit = 'account.partner.ledger.report.handler'
    _description = 'Partner Ledger Custom Handler Currency'

    def _get_additional_column_aml_values(self):
        # Not present in every account_reports build: fall back to "no extra column".
        parent = getattr(super(), '_get_additional_column_aml_values', None)
        return parent() if parent else SQL('')


    @api.model
    def _get_query_currency_table(self, options):
        ''' Construct the currency table as a mapping company -> rate to convert the amount to the user's company
        currency in a multi-company/multi-currency environment.
        The currency_table is a small postgresql table construct with VALUES.
        :param options: The report options.
        :return:        The query representing the currency table.
        '''

        user_company = self.env.company
        user_currency = user_company.pl_currency
        companies = self.env.companies

        conversion_date = options['date']['date_to']
        if user_currency:
            currency_rates = user_company.currency_id._convert(1.0, user_currency, user_company, conversion_date)
        else:
            currency_rates = 1.0

        # print(user_currency.mapped('id')._get_rates(user_company, conversion_date))

        conversion_rates = []
        for company in companies:
            conversion_rates.extend((
                company.id,
                currency_rates,
                user_currency.decimal_places,
            ))
        query = '(VALUES %s) AS currency_table(company_id, rate, precision)' % ','.join(
            '(%s, %s, %s)' for i in companies)
        return self.env.cr.mogrify(query, conversion_rates).decode(self.env.cr.connection.encoding)

    def _get_query_sums(self, *args) -> SQL:
        # Compatible with both signatures: (options) and (report, options),
        # depending on the installed account_reports build.
        options = args[-1]
        report = args[0] if len(args) > 1 else self.env.ref('new_gl_pl_report.partner_ledger_cur_report')
        """ Construct a query retrieving all the aggregated sums to build the report. It includes:
        - sums for all partners.
        - sums for the initial balances.
        :param options:             The report options.
        :return:                    query as SQL object
        """
        queries = []

        # Create the currency table.
        for column_group_key, column_group_options in report._split_options_per_column_group(options).items():
            query = report._get_report_query(column_group_options, 'from_beginning')
            queries.append(SQL("""
                SELECT
                    account_move_line.partner_id                                                          AS groupby,
                    %(column_group_key)s                                                                                AS column_group_key,
                    SUM(%(debit_select)s)           AS debit,
                    SUM(%(credit_select)s)           AS credit,
                    SUM(%(balance_select)s)          AS Amount,
                    SUM(%(balance_select)s)          AS balance
                FROM %(table_references)s
                %(currency_table_join)s
                WHERE %(search_condition)s
                GROUP BY account_move_line.partner_id
            """,
            column_group_key=column_group_key,
            debit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_debit")),
            credit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_credit")),
            balance_select=report._currency_table_apply_rate(SQL("account_move_line.pl_currency")),
            table_references=query.from_clause,
            currency_table_join=report._currency_table_aml_join(column_group_options),
            search_condition=query.where_clause,
            ))

        return SQL(' UNION ALL ').join(queries)

    def _get_initial_balance_values(self, partner_ids, options):
        queries = []
        report = self.env.ref('new_gl_pl_report.partner_ledger_cur_report')
        for column_group_key, column_group_options in report._split_options_per_column_group(options).items():
            # Get sums for the initial balance.
            # period: [('date' <= options['date_from'] - 1)]
            new_options = self._get_options_initial_balance(column_group_options)
            query = report._get_report_query(new_options, 'from_beginning', domain=[('partner_id', 'in', partner_ids)])
            queries.append(SQL("""
                SELECT
                    account_move_line.partner_id,
                    %(column_group_key)s          AS column_group_key,
                    SUM(%(debit_select)s)         AS debit,
                    SUM(%(credit_select)s)        AS credit,
                    SUM(%(balance_select)s)       AS amount,
                    SUM(%(balance_select)s)       AS balance
                FROM %(table_references)s
                %(currency_table_join)s
                WHERE %(search_condition)s
                GROUP BY account_move_line.partner_id
            """,
            column_group_key=column_group_key,
            debit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_debit")),
            credit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_credit")),
            balance_select=report._currency_table_apply_rate(SQL("account_move_line.pl_currency")),
            table_references=query.from_clause,
            currency_table_join=report._currency_table_aml_join(column_group_options),
            search_condition=query.where_clause,
            ))

        self._cr.execute(SQL(" UNION ALL ").join(queries))

        init_balance_by_col_group = {
            partner_id: {column_group_key: {} for column_group_key in options['column_groups']}
            for partner_id in partner_ids
        }
        for result in self._cr.dictfetchall():
            init_balance_by_col_group[result['partner_id']][result['column_group_key']] = result

        return init_balance_by_col_group

    # def _get_sums_without_partner(self, options):
    #     """ Get the sum of lines without partner reconciled with a line with a partner, grouped by partner. Those lines
    #     should be considered as belonging to the partner for the reconciled amount as it may clear some of the partner
    #     invoice/bill and they have to be accounted in the partner balance."""
    #     queries = []
    #     report = self.env.ref('new_gl_pl_report.partner_ledger_cur_report')
    #     for column_group_key, column_group_options in report._split_options_per_column_group(options).items():
    #         query = report._get_report_query(column_group_options, 'from_beginning')

    #         queries.append(f"""
    #             SELECT
    #                 %s                                                                                                    AS column_group_key,
    #                 aml_with_partner.partner_id                                                                           AS groupby,
    #                 COALESCE(SUM(CASE WHEN aml_with_partner.balance > 0 THEN 0 ELSE ROUND(
    #                         partial.amount * currency_table.rate, currency_table.precision) END), 0)                      AS debit, 
    #                 COALESCE(SUM(CASE WHEN aml_with_partner.balance < 0 THEN 0 ELSE ROUND(
    #                         partial.amount * currency_table.rate, currency_table.precision) END), 0)                      AS credit, 
    #                 COALESCE(SUM(- sign(aml_with_partner.balance) * ROUND(
    #                         partial.amount * currency_table.rate, currency_table.precision)), 0)                          AS balance 
    #             FROM {tables}
    #             JOIN account_partial_reconcile partial
    #                 ON account_move_line.id = partial.debit_move_id OR account_move_line.id = partial.credit_move_id
    #             JOIN account_move_line aml_with_partner ON
    #                 (aml_with_partner.id = partial.debit_move_id OR aml_with_partner.id = partial.credit_move_id)
    #                 AND aml_with_partner.partner_id IS NOT NULL
    #             LEFT JOIN {ct_query} ON currency_table.company_id = account_move_line.company_id
    #             WHERE partial.max_date <= %s AND {where_clause}
    #                 AND account_move_line.partner_id IS NULL
    #             GROUP BY aml_with_partner.partner_id
    #         """)

    #     return SQL(" UNION ALL ").join(queries)

    # vv
    def _get_aml_values(self, options, partner_ids, offset=0, limit=None):
        rslt = {partner_id: [] for partner_id in partner_ids}

        partner_ids_wo_none = [x for x in partner_ids if x]
        directly_linked_aml_partner_clauses = []
        indirectly_linked_aml_partner_clause = SQL('aml_with_partner.partner_id IS NOT NULL')
        if None in partner_ids:
            directly_linked_aml_partner_clauses.append(SQL('account_move_line.partner_id IS NULL'))
        if partner_ids_wo_none:
            directly_linked_aml_partner_clauses.append(SQL('account_move_line.partner_id IN %s', tuple(partner_ids_wo_none)))
            indirectly_linked_aml_partner_clause = SQL('aml_with_partner.partner_id IN %s', tuple(partner_ids_wo_none))
        directly_linked_aml_partner_clause = SQL('(%s)', SQL(' OR ').join(directly_linked_aml_partner_clauses))

        queries = []
        lang = self.env.lang or get_lang(self.env).code
        journal_name = f"COALESCE(journal.name->>'{lang}', journal.name->>'en_US')" if \
            self.pool['account.journal'].name.translate else 'journal.name'
        account_name = f"COALESCE(account.name->>'{lang}', account.name->>'en_US')" if \
            self.pool['account.account'].name.translate else 'account.name'
        report = self.env.ref('new_gl_pl_report.partner_ledger_cur_report')
        additional_columns = self._get_additional_column_aml_values()
        for column_group_key, group_options in report._split_options_per_column_group(options).items():
            query = report._get_report_query(group_options, 'strict_range')
            account_alias = query.left_join(lhs_alias='account_move_line', lhs_column='account_id', rhs_table='account_account', rhs_column='id', link='account_id')
            account_code = self.env['account.account']._field_to_sql(account_alias, 'code', query)
            account_name = self.env['account.account']._field_to_sql(account_alias, 'name')

            # For the move lines directly linked to this partner
            queries.append(SQL(
                '''
                SELECT
                    account_move_line.id,
                    account_move_line.date_maturity,
                    account_move_line.name,
                    account_move_line.ref,
                    account_move_line.company_id,
                    account_move_line.account_id,
                    account_move_line.payment_id,
                    account_move_line.partner_id,
                    account_move_line.currency_id,
                    account_move_line.amount_currency,
                    account_move_line.matching_number,
                    %(additional_columns)s
                    COALESCE(account_move_line.invoice_date, account_move_line.date) AS invoice_date,
                    %(debit_select)s                                                 AS debit,
                    %(credit_select)s                                                AS credit,
                    %(balance_select)s                                               AS amount,
                    %(balance_select)s                                               AS balance,
                    account_move.name                                                AS move_name,
                    account_move.move_type                                           AS move_type,
                    %(account_code)s                                                 AS account_code,
                    %(account_name)s                                                 AS account_name,
                    journal.code                                                     AS journal_code,
                    %(journal_name)s                                                 AS journal_name,
                    %(column_group_key)s                                             AS column_group_key,
                    'directly_linked_aml'                                            AS key,
                    0                                                                AS partial_id
                FROM %(table_references)s
                JOIN account_move ON account_move.id = account_move_line.move_id
                %(currency_table_join)s
                LEFT JOIN res_company company               ON company.id = account_move_line.company_id
                LEFT JOIN res_partner partner               ON partner.id = account_move_line.partner_id
                LEFT JOIN account_journal journal           ON journal.id = account_move_line.journal_id
                WHERE %(search_condition)s AND %(directly_linked_aml_partner_clause)s
                ORDER BY account_move_line.date, account_move_line.id
                ''',
                additional_columns=additional_columns,
                debit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_debit")),
                credit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_credit")),
                balance_select=report._currency_table_apply_rate(SQL("account_move_line.pl_currency")),
                account_code=account_code,
                account_name=account_name,
                journal_name=journal_name,
                column_group_key=column_group_key,
                table_references=query.from_clause,
                currency_table_join=report._currency_table_aml_join(group_options),
                search_condition=query.where_clause,
                directly_linked_aml_partner_clause=directly_linked_aml_partner_clause,
            ))

            # For the move lines linked to no partner, but reconciled with this partner. They will appear in grey in the report
            queries.append(SQL('''
                SELECT
                    account_move_line.id,
                    account_move_line.date_maturity,
                    account_move_line.name,
                    account_move_line.ref,
                    account_move_line.company_id,
                    account_move_line.account_id,
                    account_move_line.payment_id,
                    aml_with_partner.partner_id,
                    account_move_line.currency_id,
                    account_move_line.amount_currency,
                    account_move_line.matching_number,
                    %(additional_columns)s
                    COALESCE(account_move_line.invoice_date, account_move_line.date) AS invoice_date,
                    %(debit_select)s                                                 AS debit,
                    %(credit_select)s                                                AS credit,
                    %(balance_select)s                                               AS amount,
                    %(balance_select)s                                               AS balance,
                    account_move.name                                                AS move_name,
                    account_move.move_type                                           AS move_type,
                    %(account_code)s                                                 AS account_code,
                    %(account_name)s                                                 AS account_name,
                    journal.code                                                     AS journal_code,
                    %(journal_name)s                                                 AS journal_name,
                    %(column_group_key)s                                             AS column_group_key,
                    'indirectly_linked_aml'                                          AS key,
                    partial.id                                                       AS partial_id
                FROM %(table_references)s
                    %(currency_table_join)s,
                    account_partial_reconcile partial,
                    account_move,
                    account_move_line aml_with_partner,
                    account_journal journal
                WHERE
                    (account_move_line.id = partial.debit_move_id OR account_move_line.id = partial.credit_move_id)
                    AND account_move_line.partner_id IS NULL
                    AND account_move.id = account_move_line.move_id
                    AND (aml_with_partner.id = partial.debit_move_id OR aml_with_partner.id = partial.credit_move_id)
                    AND %(indirectly_linked_aml_partner_clause)s
                    AND journal.id = account_move_line.journal_id
                    AND %(account_alias)s.id = account_move_line.account_id
                    AND %(search_condition)s
                    AND partial.max_date BETWEEN %(date_from)s AND %(date_to)s
                ORDER BY account_move_line.date, account_move_line.id
            ''',
            additional_columns=additional_columns,
                debit_select=report._currency_table_apply_rate(SQL("CASE WHEN aml_with_partner.balance > 0 THEN 0 ELSE partial.amount END")),
                credit_select=report._currency_table_apply_rate(SQL("CASE WHEN aml_with_partner.balance < 0 THEN 0 ELSE partial.amount END")),
                balance_select=report._currency_table_apply_rate(SQL("-SIGN(aml_with_partner.balance) * partial.amount")),
                account_code=account_code,
                account_name=account_name,
                journal_name=journal_name,
                column_group_key=column_group_key,
                table_references=query.from_clause,
                currency_table_join=report._currency_table_aml_join(group_options),
                indirectly_linked_aml_partner_clause=indirectly_linked_aml_partner_clause,
                account_alias=SQL.identifier(account_alias),
                search_condition=query.where_clause,
                date_from=group_options['date']['date_from'],
                date_to=group_options['date']['date_to'],
            ))

        query = SQL(" UNION ALL ").join(SQL("(%s)", query) for query in queries)

        if offset:
            query = SQL('%s OFFSET %s ', query, offset)


        if limit:
            query = SQL('%s LIMIT %s ', query, limit)


        self._cr.execute(query)
        for aml_result in self._cr.dictfetchall():
            if aml_result['key'] == 'indirectly_linked_aml':

                # Append the line to the partner found through the reconciliation.
                if aml_result['partner_id'] in rslt:
                    rslt[aml_result['partner_id']].append(aml_result)

                # Balance it with an additional line in the Unknown Partner section but having reversed amounts.
                if None in rslt:
                    rslt[None].append({
                        **aml_result,
                        'debit': aml_result['credit'],
                        'credit': aml_result['debit'],
                        'amount': aml_result['credit'] - aml_result['debit'],
                        'balance': -aml_result['balance'],
                    })
            else:
                rslt[aml_result['partner_id']].append(aml_result)

        return rslt


    def _report_expand_unfoldable_line_partner_ledger(self, line_dict_id, groupby, options, progress, offset, unfold_all_batch_data=None):
        def init_load_more_progress(line_dict):
            return {
                column['column_group_key']: line_col.get('no_format', 0)
                for column, line_col in  zip(options['columns'], line_dict['columns'])
                if column['expression_label'] == 'balance'
            }

        report = self.env.ref('new_gl_pl_report.partner_ledger_cur_report')
        markup, model, record_id = report._parse_line_id(line_dict_id)[-1]

        if model != 'res.partner':
            raise UserError(_("Wrong ID for partner ledger line to expand: %s", line_dict_id))

        prefix_groups_count = 0
        for markup, dummy1, dummy2 in report._parse_line_id(line_dict_id):
            if isinstance(markup, dict) and 'groupby_prefix_group' in markup:
                prefix_groups_count += 1
        level_shift = prefix_groups_count * 2

        lines = []

        # Get initial balance
        if offset == 0:
            if unfold_all_batch_data:
                init_balance_by_col_group = unfold_all_batch_data['initial_balances'][record_id]
            else:
                init_balance_by_col_group = self._get_initial_balance_values([record_id], options)[record_id]
            initial_balance_line = report._get_partner_and_general_ledger_initial_balance_line(options, line_dict_id, init_balance_by_col_group, level_shift=level_shift)
            if initial_balance_line:
                lines.append(initial_balance_line)

                # For the first expansion of the line, the initial balance line gives the progress
                progress = init_load_more_progress(initial_balance_line)

        limit_to_load = report.load_more_limit + 1 if report.load_more_limit and options['export_mode'] != 'print' else None

        if unfold_all_batch_data:
            aml_results = unfold_all_batch_data['aml_values'][record_id]
        else:
            aml_results = self._get_aml_values(options, [record_id], offset=offset, limit=limit_to_load)[record_id]

        has_more = False
        treated_results_count = 0
        next_progress = progress
        for result in aml_results:
            if options['export_mode'] != 'print' and report.load_more_limit and treated_results_count == report.load_more_limit:
                # We loaded one more than the limit on purpose: this way we know we need a "load more" line
                has_more = True
                break

            new_line = self._get_report_line_move_line(options, result, line_dict_id, next_progress, level_shift=level_shift)
            lines.append(new_line)
            next_progress = init_load_more_progress(new_line)
            treated_results_count += 1

        return {
            'lines': lines,
            'offset_increment': treated_results_count,
            'has_more': has_more,
            'progress': next_progress
        }


