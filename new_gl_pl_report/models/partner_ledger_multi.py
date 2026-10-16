# -*- coding: utf-8 -*-
import json

from odoo import fields, models, api, _
from odoo.exceptions import ValidationError
from collections import defaultdict
from odoo.exceptions import UserError
from odoo.tools import SQL
from odoo.tools.misc import format_date, get_lang


class PartnerLedgerCustomHandlerMulti(models.AbstractModel):
    _name = 'account.partner.ledger.report.handler.multi'
    _inherit = 'account.partner.ledger.report.handler'
    _description = 'Partner Ledger Custom Handler Currency Multi'

    def _get_additional_column_aml_values(self):
        # Not present in every account_reports build: fall back to "no extra column".
        parent = getattr(super(), '_get_additional_column_aml_values', None)
        return parent() if parent else SQL('')


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
        journal_name = self.env['account.journal']._field_to_sql('journal', 'name')
        report = self.env.ref('account_reports.partner_ledger_report')
        for column_group_key, group_options in report._split_options_per_column_group(options).items():
            query = report._get_report_query(group_options, 'strict_range')
            account_alias = query.left_join(lhs_alias='account_move_line', lhs_column='account_id', rhs_table='account_account', rhs_column='id', link='account_id')
            account_code = self.env['account.account']._field_to_sql(account_alias, 'code', query)
            account_name = self.env['account.account']._field_to_sql(account_alias, 'name')
            additional_columns = self._get_additional_column_aml_values()

            # For the move lines directly linked to this partner
            queries.append(SQL(
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
                    account_move_line.matching_number,
                    %(additional_columns)s
                    COALESCE(account_move_line.invoice_date, account_move_line.date) AS invoice_date,
                    %(debit_select)s           AS debit,
                    %(credit_select)s          AS credit,
                    %(balance_select)s         AS amount,
                    %(balance_select)s         AS balance,
                    %(pl_debit_select)s        AS pl_debit,
                    %(pl_credit_select)s       AS pl_credit,
                    %(pl_balance_select)s      AS pl_amount,
                    %(pl_balance_select)s      AS pl_balance,
                    %(euro_pl_debit_select)s   AS euro_pl_debit,
                    %(euro_pl_credit_select)s  AS euro_pl_credit,
                    %(euro_pl_balance_select)s AS euro_pl_amount,
                    %(euro_pl_balance_select)s AS euro_pl_balance,
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
                debit_select=report._currency_table_apply_rate(SQL("account_move_line.debit")),
                credit_select=report._currency_table_apply_rate(SQL("account_move_line.credit")),
                balance_select=report._currency_table_apply_rate(SQL("account_move_line.balance")),
                pl_debit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_debit")),
                pl_credit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_credit")),
                pl_balance_select=report._currency_table_apply_rate(SQL("account_move_line.pl_currency")),
                euro_pl_debit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_debit")),
                euro_pl_credit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_credit")),
                euro_pl_balance_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_currency")),
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
            queries.append(SQL(
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
                    aml_with_partner.partner_id,
                    account_move_line.currency_id,
                    account_move_line.amount_currency,
                    account_move_line.matching_number,
                    %(additional_columns)s
                    COALESCE(account_move_line.invoice_date, account_move_line.date) AS invoice_date,
                    %(debit_select)s           AS debit,
                    %(credit_select)s          AS credit,
                    %(balance_select)s         AS amount,
                    %(balance_select)s         AS balance,
                    %(pl_debit_select)s        AS pl_debit,
                    %(pl_credit_select)s       AS pl_credit,
                    %(pl_balance_select)s      AS pl_amount,
                    %(pl_balance_select)s      AS pl_balance,
                    %(euro_pl_debit_select)s   AS euro_pl_debit,
                    %(euro_pl_credit_select)s  AS euro_pl_credit,
                    %(euro_pl_balance_select)s AS euro_pl_amount,
                    %(euro_pl_balance_select)s AS euro_pl_balance,
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
                debit_select=report._currency_table_apply_rate(SQL("aml_with_partner.debit")),
                credit_select=report._currency_table_apply_rate(SQL("aml_with_partner.credit")),
                balance_select=report._currency_table_apply_rate(SQL("aml_with_partner.balance")),
                pl_debit_select=report._currency_table_apply_rate(SQL("aml_with_partner.pl_debit")),
                pl_credit_select=report._currency_table_apply_rate(SQL("aml_with_partner.pl_credit")),
                pl_balance_select=report._currency_table_apply_rate(SQL("aml_with_partner.pl_currency")),
                euro_pl_debit_select=report._currency_table_apply_rate(SQL("aml_with_partner.euro_pl_debit")),
                euro_pl_credit_select=report._currency_table_apply_rate(SQL("aml_with_partner.euro_pl_credit")),
                euro_pl_balance_select=report._currency_table_apply_rate(SQL("aml_with_partner.euro_pl_currency")),
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

                        'pl_debit': aml_result['pl_credit'],
                        'pl_credit': aml_result['pl_debit'],
                        'pl_amount': aml_result['pl_credit'] - aml_result['pl_debit'],
                        'pl_balance': -aml_result['pl_balance'],
                        
                        'euro_pl_debit': aml_result['euro_pl_credit'],
                        'euro_pl_credit': aml_result['euro_pl_debit'],
                        'euro_pl_amount': aml_result['euro_pl_credit'] - aml_result['pl_debit'],
                        'euro_pl_balance': -aml_result['euro_pl_balance'],

                    })
            else:
                rslt[aml_result['partner_id']].append(aml_result)

        return rslt

    def _get_query_sums(self, *args) -> SQL:
        # Compatible with both signatures: (options) and (report, options),
        # depending on the installed account_reports build.
        options = args[-1]
        report = args[0] if len(args) > 1 else self.env.ref('account_reports.partner_ledger_report')
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
                    SUM(%(credit_select)s)          AS credit,
                    SUM(%(balance_select)s)         AS amount,
                    SUM(%(balance_select)s)         AS balance,
                    SUM(%(pl_debit_select)s)        AS pl_debit,
                    SUM(%(pl_credit_select)s)       AS pl_credit,
                    SUM(%(pl_balance_select)s)      AS pl_amount,
                    SUM(%(pl_balance_select)s)      AS pl_balance,
                    SUM(%(euro_pl_debit_select)s)   AS euro_pl_debit,
                    SUM(%(euro_pl_credit_select)s)  AS euro_pl_credit,
                    SUM(%(euro_pl_balance_select)s) AS euro_pl_amount,
                    SUM(%(euro_pl_balance_select)s) AS euro_pl_balance
                FROM %(table_references)s
                %(currency_table_join)s
                WHERE %(search_condition)s
                GROUP BY account_move_line.partner_id
            """,
            column_group_key=column_group_key,
            debit_select=report._currency_table_apply_rate(SQL("account_move_line.debit")),
            credit_select=report._currency_table_apply_rate(SQL("account_move_line.credit")),
            balance_select=report._currency_table_apply_rate(SQL("account_move_line.balance")),
            pl_debit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_debit")),
            pl_credit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_credit")),
            pl_balance_select=report._currency_table_apply_rate(SQL("account_move_line.pl_currency")),
            euro_pl_debit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_debit")),
            euro_pl_credit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_credit")),
            euro_pl_balance_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_currency")),
            table_references=query.from_clause,
            currency_table_join=report._currency_table_aml_join(column_group_options),
            search_condition=query.where_clause,
            ))
            
            """
                SELECT
                    account_move_line.partner_id                                                          AS groupby,
                    %(column_group_key)s                                                                                AS column_group_key,
                    SUM(%(debit_select)s)           AS debit,
                    SUM(%(credit_select)s)          AS credit,
                    SUM(%(balance_select)s)         AS amount,
                    SUM(%(balance_select)s)         AS balance,
                    SUM(%(pl_debit_select)s)        AS pl_debit,
                    SUM(%(pl_credit_select)s)       AS pl_credit,
                    SUM(%(pl_balance_select)s)      AS pl_amount,
                    SUM(%(pl_balance_select)s)      AS pl_balance,
                    SUM(%(euro_pl_debit_select)s)   AS euro_pl_debit,
                    SUM(%(euro_pl_credit_select)s)  AS euro_pl_credit,
                    SUM(%(euro_pl_balance_select)s) AS euro_pl_amount,
                    SUM(%(euro_pl_balance_select)s) AS euro_pl_balance
                FROM %(table_references)s
                %(currency_table_join)s
                WHERE %(search_condition)s
                GROUP BY account_move_line.partner_id
            """

        return SQL(' UNION ALL ').join(queries)

    def _query_partners(self, *args):
        options = args[-1]
        report = args[0] if len(args) > 1 else self.env.ref('account_reports.partner_ledger_report')
        """ Executes the queries and performs all the computation.
        :return:        A list of tuple (partner, column_group_values) sorted by the table's model _order:
                        - partner is a res.parter record.
                        - column_group_values is a dict(column_group_key, fetched_values), where
                            - column_group_key is a string identifying a column group, like in options['column_groups']
                            - fetched_values is a dictionary containing:
                                - sum:                              {'debit': float, 'credit': float, 'balance': float}
                                - (optional) initial_balance:       {'debit': float, 'credit': float, 'balance': float}
                                - (optional) lines:                 [line_vals_1, line_vals_2, ...]
        """
        def assign_sum(row):
            fields_to_assign = ['balance', 'debit', 'credit', 'pl_debit', 'pl_credit', 'pl_balance', 'euro_pl_debit', 'euro_pl_credit', 'euro_pl_balance']
            if any(not company_currency.is_zero(row[field]) for field in fields_to_assign):
                groupby_partners.setdefault(row['groupby'], defaultdict(lambda: defaultdict(float)))
                for field in fields_to_assign:
                    groupby_partners[row['groupby']][row['column_group_key']][field] += row[field]

        company_currency = self.env.company.currency_id

        # Execute the queries and dispatch the results.
        query = self._get_query_sums(report, options)
        
        groupby_partners = {}

        self._cr.execute(query)
        for res in self._cr.dictfetchall():
            assign_sum(res)

        # Correct the sums per partner, for the lines without partner reconciled with a line having a partner
        query = self._get_sums_without_partner(options)
        
        self._cr.execute(query)
        totals = {}
        for total_field in ['debit', 'credit','amount', 'balance', 'pl_debit', 'euro_pl_amount','pl_credit','pl_amount', 'pl_balance', 'euro_pl_debit', 'euro_pl_credit', 'euro_pl_balance']:
            totals[total_field] = {col_group_key: 0 for col_group_key in options['column_groups']}

        for row in self._cr.dictfetchall():
            totals['debit'][row['column_group_key']] += row['debit']
            totals['credit'][row['column_group_key']] += row['credit']
            totals['amount'][row['column_group_key']] += row['amount']
            totals['balance'][row['column_group_key']] += row['balance']
            totals['pl_debit'][row['column_group_key']] += row['pl_debit']
            totals['pl_credit'][row['column_group_key']] += row['pl_credit']
            totals['pl_amount'][row['column_group_key']] += row['pl_amount']
            totals['pl_balance'][row['column_group_key']] += row['pl_balance']
            totals['euro_pl_debit'][row['column_group_key']] += row['euro_pl_debit']
            totals['euro_pl_credit'][row['column_group_key']] += row['euro_pl_credit']
            totals['euro_pl_amount'][row['column_group_key']] += row['euro_pl_amount']
            totals['euro_pl_balance'][row['column_group_key']] += row['euro_pl_balance']

            if row['groupby'] not in groupby_partners:
                continue

            assign_sum(row)

        if None in groupby_partners:
            # Debit/credit are inverted for the unknown partner as the computation is made regarding the balance of the known partner
            for column_group_key in options['column_groups']:
                groupby_partners[None][column_group_key]['debit'] += totals['credit'][column_group_key]
                groupby_partners[None][column_group_key]['credit'] += totals['debit'][column_group_key]
                groupby_partners[None][column_group_key]['amount'] += totals['amount'][column_group_key]
                groupby_partners[None][column_group_key]['balance'] -= totals['balance'][column_group_key]
                
                groupby_partners[None][column_group_key]['pl_debit'] += totals['pl_credit'][column_group_key]
                groupby_partners[None][column_group_key]['pl_credit'] += totals['pl_debit'][column_group_key]
                groupby_partners[None][column_group_key]['pl_amount'] += totals['pl_amount'][column_group_key]
                groupby_partners[None][column_group_key]['pl_balance'] -= totals['pl_balance'][column_group_key]
                
                groupby_partners[None][column_group_key]['euro_pl_debit'] += totals['euro_pl_credit'][column_group_key]
                groupby_partners[None][column_group_key]['euro_pl_credit'] += totals['euro_pl_debit'][column_group_key]
                groupby_partners[None][column_group_key]['euro_pl_amount'] += totals['euro_pl_amount'][column_group_key]
                groupby_partners[None][column_group_key]['euro_pl_balance'] -= totals['euro_pl_balance'][column_group_key]

        # Retrieve the partners to browse.
        # groupby_partners.keys() contains all account ids affected by:
        # - the amls in the current period.
        # - the amls affecting the initial balance.
        if groupby_partners:
            # Note a search is done instead of a browse to preserve the table ordering.
            partners = self.env['res.partner'].with_context(active_test=False).search_fetch([('id', 'in', list(groupby_partners.keys()))], ["id", "name", "trust", "company_registry", "vat"])
        else:
            partners = []

        # Add 'Partner Unknown' if needed
        if None in groupby_partners.keys():
            partners = [p for p in partners] + [None]

        return [(partner, groupby_partners[partner.id if partner else None]) for partner in partners]

    def _get_initial_balance_values(self, partner_ids, options):
        queries = []
        report = self.env.ref('account_reports.partner_ledger_report')
        for column_group_key, column_group_options in report._split_options_per_column_group(options).items():
            # Get sums for the initial balance.
            # period: [('date' <= options['date_from'] - 1)]
            new_options = self._get_options_initial_balance(column_group_options)
            query = report._get_report_query(new_options, 'from_beginning', domain=[('partner_id', 'in', partner_ids)])
            
            queries.append(SQL(
                """
                SELECT
                    account_move_line.partner_id,
                    %(column_group_key)s          AS column_group_key,
                    SUM(%(debit_select)s)           AS debit,
                    SUM(%(credit_select)s)          AS credit,
                    SUM(%(balance_select)s)         AS amount,
                    SUM(%(balance_select)s)         AS balance,
                    SUM(%(pl_debit_select)s)        AS pl_debit,
                    SUM(%(pl_credit_select)s)       AS pl_credit,
                    SUM(%(pl_balance_select)s)      AS pl_amount,
                    SUM(%(pl_balance_select)s)      AS pl_balance,
                    SUM(%(euro_pl_debit_select)s)   AS euro_pl_debit,
                    SUM(%(euro_pl_credit_select)s)  AS euro_pl_credit,
                    SUM(%(euro_pl_balance_select)s) AS euro_pl_amount,
                    SUM(%(euro_pl_balance_select)s) AS euro_pl_balance
                FROM %(table_references)s
                %(currency_table_join)s
                WHERE %(search_condition)s
                GROUP BY account_move_line.partner_id
                """,
                column_group_key=column_group_key,
                debit_select=report._currency_table_apply_rate(SQL("account_move_line.debit")),
                credit_select=report._currency_table_apply_rate(SQL("account_move_line.credit")),
                balance_select=report._currency_table_apply_rate(SQL("account_move_line.balance")),
                pl_debit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_debit")),
                pl_credit_select=report._currency_table_apply_rate(SQL("account_move_line.pl_credit")),
                pl_balance_select=report._currency_table_apply_rate(SQL("account_move_line.pl_currency")),
                euro_pl_debit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_debit")),
                euro_pl_credit_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_credit")),
                euro_pl_balance_select=report._currency_table_apply_rate(SQL("account_move_line.euro_pl_currency")),
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

    def _build_partner_lines(self, report, options, level_shift=0):
        lines = []

        totals_by_column_group = {
            column_group_key: {
                total: 0.0
                for total in ['debit', 'credit', 'amount', 'balance', 'pl_debit', 'pl_credit', 'pl_amount', 'pl_balance', 'euro_pl_debit', 'euro_pl_credit', 'euro_pl_amount', 'euro_pl_balance']
            }
            for column_group_key in options['column_groups']
        }
        partners_results = self._query_partners(report, options)
        
        search_filter = options.get('filter_search_bar', '')
        accept_unknown_in_filter = search_filter.lower() in self._get_no_partner_line_label().lower()
        for partner, results in partners_results:
            if options['export_mode'] == 'print' and search_filter and not partner and not accept_unknown_in_filter:
                # When printing and searching for a specific partner, make it so we only show its lines, not the 'Unknown Partner' one, that would be
                # shown in case a misc entry with no partner was reconciled with one of the target partner's entries.
                continue
            
            partner_values = defaultdict(dict)
            for column_group_key in options['column_groups']:
                partner_sum = results.get(column_group_key, {})

                partner_values[column_group_key]['debit'] = partner_sum.get('debit', 0.0)
                partner_values[column_group_key]['credit'] = partner_sum.get('credit', 0.0)
                partner_values[column_group_key]['amount'] = partner_sum.get('amount', 0.0)
                partner_values[column_group_key]['balance'] = partner_sum.get('balance', 0.0)
                
                partner_values[column_group_key]['pl_debit'] = partner_sum.get('pl_debit', 0.0)
                partner_values[column_group_key]['pl_credit'] = partner_sum.get('pl_credit', 0.0)
                partner_values[column_group_key]['pl_amount'] = partner_sum.get('pl_amount', 0.0)
                partner_values[column_group_key]['pl_balance'] = partner_sum.get('pl_balance', 0.0)

                partner_values[column_group_key]['euro_pl_debit'] = partner_sum.get('euro_pl_debit', 0.0)
                partner_values[column_group_key]['euro_pl_credit'] = partner_sum.get('euro_pl_credit', 0.0)
                partner_values[column_group_key]['euro_pl_amount'] = partner_sum.get('euro_pl_amount', 0.0)
                partner_values[column_group_key]['euro_pl_balance'] = partner_sum.get('euro_pl_balance', 0.0)

                totals_by_column_group[column_group_key]['debit'] += partner_values[column_group_key]['debit']
                totals_by_column_group[column_group_key]['credit'] += partner_values[column_group_key]['credit']
                totals_by_column_group[column_group_key]['amount'] += partner_values[column_group_key]['amount']
                totals_by_column_group[column_group_key]['balance'] += partner_values[column_group_key]['balance']
                
                totals_by_column_group[column_group_key]['pl_debit'] += partner_values[column_group_key]['pl_debit']
                totals_by_column_group[column_group_key]['pl_credit'] += partner_values[column_group_key]['pl_credit']
                totals_by_column_group[column_group_key]['pl_amount'] += partner_values[column_group_key]['pl_amount']
                totals_by_column_group[column_group_key]['pl_balance'] += partner_values[column_group_key]['pl_balance']

                totals_by_column_group[column_group_key]['euro_pl_debit'] += partner_values[column_group_key]['euro_pl_debit']
                totals_by_column_group[column_group_key]['euro_pl_credit'] += partner_values[column_group_key]['euro_pl_credit']
                totals_by_column_group[column_group_key]['euro_pl_amount'] += partner_values[column_group_key]['euro_pl_amount']
                totals_by_column_group[column_group_key]['euro_pl_balance'] += partner_values[column_group_key]['euro_pl_balance']

            lines.append(self._get_report_line_partners(options, partner, partner_values, level_shift=level_shift))

        return lines, totals_by_column_group


    def _get_report_line_move_line(self, options, aml_query_result, partner_line_id, init_bal_by_col_group, level_shift=0):
        if aml_query_result['payment_id']:
            caret_type = 'account.payment'
        else:
            caret_type = 'account.move.line'

        columns = []
        report = self.env['account.report'].browse(options['report_id'])
        for column in options['columns']:
            col_expr_label = column['expression_label']
            
            if col_expr_label == 'ref':
                col_value = self._format_aml_name(aml_query_result['name'], aml_query_result['ref'], aml_query_result['move_name'])
            else:
                col_value = aml_query_result[col_expr_label] if column['column_group_key'] == aml_query_result['column_group_key'] else None

            if col_value is None:
                columns.append(report._build_column_dict(None, None))
            else:
                currency = False
                company = self.env['res.company'].browse(aml_query_result['company_id'])

                if col_expr_label == 'amount_currency':
                    currency = self.env['res.currency'].browse(aml_query_result['currency_id'])
                elif col_expr_label in ['debit', 'credit', 'balance']:
                    currency = company.currency_id
                elif col_expr_label in ['pl_debit', 'pl_credit', 'pl_amount', 'pl_balance']:
                    currency = company.pl_currency
                elif col_expr_label in ['euro_pl_debit', 'euro_pl_credit', 'euro_pl_amount', 'euro_pl_balance']:
                    currency = company.euro_pl_currency
                
                # print(currency)
                
                if col_expr_label == 'balance':
                    if isinstance(init_bal_by_col_group[column['column_group_key']], int):
                        col_value += init_bal_by_col_group[column['column_group_key']]
                    else:
                        col_value += init_bal_by_col_group[column['column_group_key']][0]
                        
                elif col_expr_label == 'pl_balance':
                    if isinstance(init_bal_by_col_group[column['column_group_key']], int):
                        col_value += init_bal_by_col_group[column['column_group_key']]
                    else:
                        col_value += init_bal_by_col_group[column['column_group_key']][1]
                        
                elif col_expr_label == 'euro_pl_balance':
                    if isinstance(init_bal_by_col_group[column['column_group_key']], int):
                        col_value += init_bal_by_col_group[column['column_group_key']]
                    else:
                        col_value += init_bal_by_col_group[column['column_group_key']][2]

                columns.append(report._build_column_dict(col_value, column, options=options, currency=currency))


        return {
            'id': report._get_generic_line_id('account.move.line', aml_query_result['id'], parent_line_id=partner_line_id, markup=aml_query_result['partial_id']),
            'parent_id': partner_line_id,
            'name': format_date(self.env, aml_query_result['date']),
            'class': 'text-muted' if aml_query_result['key'] == 'indirectly_linked_aml' else 'text',  # do not format as date to prevent text centering
            'columns': columns,
            'caret_options': caret_type,
            'level': 4 + level_shift,
        }

    def _report_expand_unfoldable_line_partner_ledger(self, line_dict_id, groupby, options, progress, offset, unfold_all_batch_data=None):
        def init_load_more_progress(line_dict):
            arr = {}
            bl1 = bl2 = bl3 = 0
            for column, line_col in zip(options['columns'], line_dict['columns']):
                if column['expression_label'] == 'balance':
                    bl1 = line_col.get('no_format', 0)
                if column['expression_label'] == 'pl_balance':
                    bl2 = line_col.get('no_format', 0)
                if column['expression_label'] == 'euro_pl_balance':
                    bl3 = line_col.get('no_format', 0)

                arr[column['column_group_key']] = (bl1, bl2, bl3)
            return arr

        report = self.env.ref('account_reports.partner_ledger_report')
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
            initial_balance_line = self._get_partner_and_general_ledger_initial_balance_line_with_currency(options, report, line_dict_id, init_balance_by_col_group, level_shift=level_shift)
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

    def _get_partner_and_general_ledger_initial_balance_line_with_currency(self, options, report, parent_line_id, eval_dict, account_currency=None, level_shift=0):
        line_columns = []
        for column in options['columns']:
            col_value = eval_dict[column['column_group_key']].get(column['expression_label'])
            col_expr_label = column['expression_label']
            currency = None

            if col_expr_label == 'amount_currency':
                currency = account_currency
            if col_expr_label in ['pl_debit', 'pl_credit', 'pl_amount', 'pl_balance']:
                currency = self.env.company.pl_currency
            elif col_expr_label in ['euro_pl_debit', 'euro_pl_credit', 'euro_pl_amount', 'euro_pl_balance']:
                currency = self.env.company.euro_pl_currency
            
            if col_value is None or (col_expr_label in ['amount_currency','pl_amount','euro_pl_amount'] and not account_currency):
                line_columns.append(report._build_column_dict(None, None))
            else:
                line_columns.append(report._build_column_dict(
                    col_value,
                    column,
                    options=options,
                    currency=currency,
                ))
            
        # Display unfold & initial balance even when debit/credit column is hidden and the balance == 0
        if not any(isinstance(column.get('no_format'), (int, float)) and column.get('expression_label') != 'balance' for column in line_columns):
            return None

        return {
            'id': report._get_generic_line_id(None, None, parent_line_id=parent_line_id, markup='initial'),
            'name': _("Initial Balance"),
            'level': 3 + level_shift,
            'parent_id': parent_line_id,
            'columns': line_columns,
        }
        
    def _get_report_line_partners(self, options, partner, partner_values, level_shift=0):
        company_currency = self.env.company.currency_id

        partner_data = next(iter(partner_values.values()))
        unfoldable = not company_currency.is_zero(partner_data.get('debit', 0) or partner_data.get('credit', 0))
        column_values = []
        report = self.env['account.report'].browse(options['report_id'])
        for column in options['columns']:
            col_expr_label = column['expression_label']
            value = partner_values[column['column_group_key']].get(col_expr_label)
            unfoldable = unfoldable or (col_expr_label in ('debit', 'credit', 'amount', 'pl_debit', 'pl_credit', 'pl_amount', 'euro_pl_debit', 'euro_pl_credit', 'euro_pl_amount') and not company_currency.is_zero(value))
            currency = None
            if col_expr_label in ('pl_debit', 'pl_credit', 'pl_amount', 'pl_balance'):
                currency = self.env.company.pl_currency
            elif col_expr_label in ('euro_pl_debit', 'euro_pl_credit', 'euro_pl_amount', 'euro_pl_balance'):
                currency = self.env.company.euro_pl_currency
            column_values.append(report._build_column_dict(value, column, options=options, currency=currency))


        line_id = report._get_generic_line_id('res.partner', partner.id) if partner else report._get_generic_line_id('res.partner', None, markup='no_partner')

        return {
            'id': line_id,
            'name': partner is not None and (partner.name or '')[:128] or self._get_no_partner_line_label(),
            'columns': column_values,
            'level': 1 + level_shift,
            'trust': partner.trust if partner else None,
            'unfoldable': unfoldable,
            'unfolded': line_id in options['unfolded_lines'] or options['unfold_all'],
            'expand_function': '_report_expand_unfoldable_line_partner_ledger',
        }
        
    def _get_report_line_total(self, options, totals_by_column_group):
        column_values = []
        report = self.env['account.report'].browse(options['report_id'])
        for column in options['columns']:
            col_expr_label = column['expression_label']
            col_value = totals_by_column_group[column['column_group_key']].get(column['expression_label'])
            currency = None
            if col_expr_label in ('pl_debit', 'pl_credit', 'pl_amount', 'pl_balance'):
                currency = self.env.company.pl_currency
            elif col_expr_label in ('euro_pl_debit', 'euro_pl_credit', 'euro_pl_amount', 'euro_pl_balance'):
                currency = self.env.company.euro_pl_currency
            column_values.append(report._build_column_dict(col_value, column, options=options, currency=currency))

        return {
            'id': report._get_generic_line_id(None, None, markup='total'),
            'name': _('Total'),
            'level': 1,
            'columns': column_values,
        }