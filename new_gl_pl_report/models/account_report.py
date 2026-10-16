from odoo import models, _



class AccountReport(models.Model):

    _inherit = 'account.report'

    def _get_partner_and_general_ledger_initial_balance_line(self, options, parent_line_id, eval_dict, account_currency=None, level_shift=0):
        """ Helper to generate dynamic 'initial balance' lines, used by general ledger and partner ledger.
        """
        line_columns = []
        for column in options['columns']:
            col_value = eval_dict[column['column_group_key']].get(column['expression_label'])
            col_expr_label = column['expression_label']

            if col_value is None or (col_expr_label in ['amount_currency','pl_amount','euro_pl_amount'] and not account_currency):
                line_columns.append(self._build_column_dict(None, None))
            else:
                line_columns.append(self._build_column_dict(
                    col_value,
                    column,
                    options=options,
                    currency=account_currency if col_expr_label == 'amount_currency' else None,
                ))
        # Display unfold & initial balance even when debit/credit column is hidden and the balance == 0
        if not any(isinstance(column.get('no_format'), (int, float)) and column.get('expression_label') != 'balance' for column in line_columns):
            return None

        return {
            'id': self._get_generic_line_id(None, None, parent_line_id=parent_line_id, markup='initial'),
            'name': _("Initial Balance"),
            'level': 3 + level_shift,
            'parent_id': parent_line_id,
            'columns': line_columns,
        }