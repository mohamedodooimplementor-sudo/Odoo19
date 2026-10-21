from odoo import fields, models


class AuditorSetupWizard(models.TransientModel):
    _name = 'odoo.auditor.setup.wizard'
    _description = 'Odoo Auditor Quick Setup'

    manual_entry_amount = fields.Float(string='Large manual entry (FIN002)', default=50000)
    credit_note_amount = fields.Float(string='Large credit note (FIN005)', default=10000)
    stale_days = fields.Integer(string='Stale drafts / overdue / MOs (days)', default=30)
    bank_line_days = fields.Integer(string='Unreconciled bank line (days)', default=30)
    transfer_days = fields.Integer(string='Pending transfer (days)', default=14)
    adjustment_qty = fields.Float(string='Large inventory adjustment (units)', default=100)
    max_discount = fields.Float(string='Maximum discount % (SAL001)', default=20)
    min_margin = fields.Float(string='Minimum margin % (SAL002)', default=0)
    sales_threshold = fields.Float(string='Sales approval threshold (SAL003)', default=50000)
    purchase_threshold = fields.Float(string='Purchase approval threshold (PUR001/002)', default=100000)
    price_variance = fields.Float(string='Purchase price variance % (PUR004)', default=20)
    consumption_tolerance = fields.Float(string='Component consumption tolerance % (MRP001)', default=10)
    expense_limit = fields.Float(string='Expense limit (HR004)', default=1000)
    receipt_above = fields.Float(string='Receipt required above (HR005)', default=100)
    payroll_deviation = fields.Float(string='Payroll deviation % (HR006)', default=30)
    bank_change_days = fields.Integer(string='Payment after bank change (days)', default=14)
    expiry_days = fields.Integer(string='Near-expiry window (days)', default=30)
    frequency = fields.Selection([('manual', 'Manual only'), ('daily', 'Daily'), ('weekly', 'Weekly'),
                                  ('monthly', 'Monthly')], default='weekly', required=True)
    activate_applicable = fields.Boolean(string='Activate rules whose apps are installed', default=True)

    def action_apply(self):
        self.ensure_one()
        mapping = {
            'FIN001': {'threshold_days': self.stale_days}, 'FIN002': {'threshold_amount': self.manual_entry_amount},
            'FIN005': {'threshold_amount': self.credit_note_amount}, 'FIN007': {'threshold_days': self.stale_days},
            'FIN011': {'threshold_days': self.bank_line_days}, 'INV002': {'threshold_days': self.transfer_days},
            'INV003': {'threshold_amount': self.adjustment_qty}, 'MRP002': {'threshold_days': self.stale_days},
            'SAL001': {'threshold_percent': self.max_discount}, 'SAL002': {'threshold_percent': self.min_margin},
            'SAL003': {'threshold_amount': self.sales_threshold}, 'PUR001': {'threshold_amount': self.purchase_threshold},
            'PUR002': {'threshold_amount': self.purchase_threshold}, 'PUR004': {'threshold_percent': self.price_variance},
            'MRP001': {'threshold_percent': self.consumption_tolerance}, 'HR004': {'threshold_amount': self.expense_limit},
            'HR005': {'threshold_amount': self.receipt_above},
            'PUR005': {'threshold_days': self.bank_change_days}, 'INV005': {'threshold_days': self.expiry_days}, 'HR006': {'threshold_percent': self.payroll_deviation},
        }
        Rule = self.env['odoo.auditor.rule'].with_context(active_test=False)
        for code, vals in mapping.items():
            Rule.search([('code', '=', code)], limit=1).write(vals)
        activated = skipped = 0
        if self.activate_applicable:
            for rule in Rule.search([('code', '!=', 'FIN009')]):  # FIN009 needs account codes first
                if rule.config_ok:
                    rule.write({'active': True, 'frequency': self.frequency})
                    activated += 1
                else:
                    skipped += 1
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': self.env._("Setup applied"), 'type': 'success', 'sticky': False,
            'message': self.env._("%(a)s rules ready, %(s)s skipped (app not installed).", a=activated, s=skipped),
            'next': {'type': 'ir.actions.act_window_close'}}}
