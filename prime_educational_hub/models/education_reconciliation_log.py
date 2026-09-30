# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class EducationReconciliationLog(models.Model):
    _name = 'education.reconciliation.log'
    _description = 'Fee Ledger Reconciliation Log'
    _order = 'check_datetime desc'
    _inherit = ['mail.thread']

    name = fields.Char(string='Reference', default='New', readonly=True, copy=False)
    check_datetime = fields.Datetime(string='Checked At', default=fields.Datetime.now, readonly=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company,
                                  readonly=True)
    currency_id = fields.Many2one(related='company_id.currency_id', string='Currency')
    total_installment_paid = fields.Monetary(string='Total Installment Paid', readonly=True,
                                              currency_field='currency_id')
    total_allocation_net = fields.Monetary(string='Total Allocation (net of refunds)', readonly=True,
                                            currency_field='currency_id')
    discrepancy = fields.Monetary(string='Discrepancy', readonly=True, currency_field='currency_id')
    state = fields.Selection([
        ('ok', 'Balanced'),
        ('mismatch', 'Mismatch Found'),
    ], string='Result', readonly=True, default='ok')
    notes = fields.Text(string='Notes', readonly=True)

    @api.model
    def _run_check(self, company=None):
        """The fundamental invariant of the whole fee ledger: at any moment,
        the sum of every installment's paid_amount must equal the sum of
        every payment-allocation's amount, net of whatever refunds have
        reversed. If these ever drift apart, something bypassed the normal
        payment/refund flow (a direct DB edit, a bug, a manual data fix) and
        a student's balance is silently wrong somewhere. Returns the created
        log record."""
        company = company or self.env.company
        Installment = self.env['education.installment']
        Allocation = self.env['education.payment.allocation']

        installments = Installment.search([('company_id', '=', company.id)])
        allocations = Allocation.search([('payment_id.company_id', '=', company.id)])

        total_paid = sum(installments.mapped('paid_amount'))
        total_allocated_net = sum(a.amount - a.refunded_amount for a in allocations)
        discrepancy = round(total_paid - total_allocated_net, 2)

        tolerance = 0.01  # floating-point rounding only
        state = 'ok' if abs(discrepancy) <= tolerance else 'mismatch'
        notes = False
        if state == 'mismatch':
            notes = _(
                'Total installment paid_amount (%(paid).2f) does not match total allocation amount net of '
                'refunds (%(alloc).2f). Difference of %(diff).2f suggests a record was edited outside the '
                'normal payment/refund flow, or a bug reversed only one side of the ledger. Check recently '
                'modified education.installment, education.payment.allocation, and education.refund records.'
            ) % {'paid': total_paid, 'alloc': total_allocated_net, 'diff': discrepancy}

        log = self.sudo().create({
            'name': self.env['ir.sequence'].next_by_code('education.reconciliation.log') or 'New',
            'company_id': company.id,
            'total_installment_paid': total_paid,
            'total_allocation_net': total_allocated_net,
            'discrepancy': discrepancy,
            'state': state,
            'notes': notes,
        })

        if state == 'mismatch':
            admin_group = self.env.ref('prime_educational_hub.group_education_admin', raise_if_not_found=False)
            admins = self.env['res.users'].search([('group_ids', 'in', admin_group.id)]) if admin_group else self.env['res.users']
            log.message_post(
                body=_('Fee ledger reconciliation mismatch detected: %s') % notes,
                partner_ids=admins.mapped('partner_id.id'),
            )
            for user in admins:
                log.activity_schedule(
                    'mail.mail_activity_data_todo',
                    summary=_('Fee ledger mismatch - please review'),
                    note=notes,
                    user_id=user.id,
                )
        return log

    @api.model
    def _cron_run_reconciliation_check(self):
        for company in self.env['res.company'].search([]):
            self._run_check(company=company)
