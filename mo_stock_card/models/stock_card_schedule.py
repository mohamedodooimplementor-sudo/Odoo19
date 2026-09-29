import base64
import logging
from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockCardSchedule(models.Model):
    _name = 'stock.card.schedule'
    _description = 'Stock Card Report — Scheduled Email Delivery'
    _order = 'id desc'

    name = fields.Char(string='Name', required=True, default='Stock Card Schedule')
    active = fields.Boolean(string='Active', default=True)

    frequency = fields.Selection([
        ('weekly', 'Weekly (previous 7 days)'),
        ('monthly', 'Monthly (previous calendar month)'),
    ], string='Frequency', default='monthly', required=True)

    report_format = fields.Selection([
        ('pdf', 'PDF'),
        ('excel', 'Excel'),
        ('both', 'PDF & Excel'),
    ], string='Format', default='pdf', required=True)

    company_id = fields.Many2one(
        'res.company', string='Company', required=True,
        default=lambda self: self.env.company
    )
    location_ids = fields.Many2many(
        'stock.location',
        'stock_card_schedule_location_rel',
        'schedule_id',
        'location_id',
        string='Locations', required=True,
        domain="[('usage', 'in', ['internal', 'transit'])]",
    )
    include_child_locations = fields.Boolean(string='Include Child Locations', default=True)
    group_by = fields.Selection([
        ('product', 'Product'),
        ('category', 'Category'),
        ('warehouse', 'Warehouse'),
    ], string='Group By', default='product', required=True)

    product_ids = fields.Many2many(
        'product.product',
        'stock_card_schedule_product_rel',
        'schedule_id',
        'product_id',
        string='Products',
        help='Leave empty to include all products.'
    )
    categ_ids = fields.Many2many(
        'product.category',
        'stock_card_schedule_category_rel',
        'schedule_id',
        'categ_id',
        string='Product Categories',
        help='Leave empty to include all categories.'
    )
    picking_type_ids = fields.Many2many(
        'stock.picking.type',
        'stock_card_schedule_picking_type_rel',
        'schedule_id',
        'picking_type_id',
        string='Operation Types',
        help='Leave empty to include all operation types.'
    )

    recipient_ids = fields.Many2many('res.partner', string='Recipients', required=True)

    last_sent_date = fields.Datetime(string='Last Sent', readonly=True)
    last_run_status = fields.Selection([
        ('success', 'Success'),
        ('failed', 'Failed'),
    ], string='Last Run Status', readonly=True)
    last_error_message = fields.Text(string='Last Error', readonly=True)
    next_period_note = fields.Char(
        string='Next Period', compute='_compute_next_period_note',
        help='The date range that will be used the next time this schedule runs.'
    )

    @api.depends('frequency')
    def _compute_next_period_note(self):
        today = fields.Date.today()
        for rec in self:
            if rec.frequency == 'monthly':
                first_of_this_month = today.replace(day=1)
                date_to = first_of_this_month - relativedelta(days=1)
                date_from = date_to.replace(day=1)
            else:
                date_to = today - relativedelta(days=1)
                date_from = date_to - relativedelta(days=6)
            rec.next_period_note = f'{date_from} → {date_to}'

    def _get_period(self):
        """Return (date_from, date_to) for the period this schedule should cover."""
        self.ensure_one()
        today = fields.Date.today()
        if self.frequency == 'monthly':
            first_of_this_month = today.replace(day=1)
            date_to = first_of_this_month - relativedelta(days=1)
            date_from = date_to.replace(day=1)
        else:
            date_to = today - relativedelta(days=1)
            date_from = date_to - relativedelta(days=6)
        return date_from, date_to

    def action_send_now(self):
        """Manually trigger this schedule immediately (also used by the cron)."""
        for schedule in self:
            schedule._send_report()
        return True

    def _send_report(self):
        self.ensure_one()
        try:
            self._send_report_unsafe()
        except Exception as e:
            self.write({'last_run_status': 'failed', 'last_error_message': str(e)})
            raise

    def _send_report_unsafe(self):
        self.ensure_one()
        if not self.recipient_ids:
            _logger.warning('Stock Card schedule %s has no recipients, skipping.', self.name)
            return

        date_from, date_to = self._get_period()

        wizard = self.env['stock.card.wizard'].create({
            'date_from': date_from,
            'date_to': date_to,
            'company_id': self.company_id.id,
            'location_ids': [(6, 0, self.location_ids.ids)],
            'include_child_locations': self.include_child_locations,
            'group_by': self.group_by,
            'product_ids': [(6, 0, self.product_ids.ids)],
            'categ_ids': [(6, 0, self.categ_ids.ids)],
            'picking_type_ids': [(6, 0, self.picking_type_ids.ids)],
            'filter_by': 'category' if self.categ_ids else 'product',
        })

        try:
            wizard._generate_stock_card_data()
        except UserError as e:
            _logger.info('Stock Card schedule %s: nothing to report (%s)', self.name, e)
            return

        attachments = []

        if self.report_format in ('pdf', 'both'):
            pdf_content, _report_type = self.env['ir.actions.report']._render_qweb_pdf(
                'mo_stock_card.action_report_stock_card', wizard.ids
            )
            attachments.append((
                f'Stock_Card_Report_{date_from}_{date_to}.pdf',
                base64.b64encode(pdf_content),
            ))

        if self.report_format in ('excel', 'both'):
            excel_bytes = wizard._build_excel_bytes()
            attachments.append((
                f'Stock_Card_Report_{date_from}_{date_to}.xlsx',
                base64.b64encode(excel_bytes),
            ))

        mail_values = {
            'subject': _('Stock Card Report — %(date_from)s to %(date_to)s', date_from=date_from, date_to=date_to),
            'body_html': _(
                '<p>Hi,</p><p>Please find attached the Stock Card report for '
                '<b>%(location)s</b> covering <b>%(date_from)s</b> to <b>%(date_to)s</b>.</p>'
                '<p>This is an automated email from the Stock Card Report schedule '
                '"%(schedule)s".</p>',
                location=', '.join(self.location_ids.mapped('complete_name')),
                date_from=date_from, date_to=date_to, schedule=self.name,
            ),
            'email_to': ','.join(self.recipient_ids.mapped('email')),
            'attachment_ids': [(0, 0, {
                'name': name,
                'datas': data,
                'type': 'binary',
            }) for name, data in attachments],
        }
        self.env['mail.mail'].sudo().create(mail_values).send()

        self.write({
            'last_sent_date': fields.Datetime.now(),
            'last_run_status': 'success',
            'last_error_message': False,
        })

    @api.model
    def _cron_send_scheduled_reports(self):
        """Called daily by ir.cron. Each schedule decides for itself whether it's
        actually due, based on its frequency and last_sent_date."""
        today = fields.Date.today()
        schedules = self.search([('active', '=', True)])
        for schedule in schedules:
            last_sent = schedule.last_sent_date.date() if schedule.last_sent_date else False

            if schedule.frequency == 'monthly':
                due = today.day == 1 and last_sent != today
            else:  # weekly — send every Monday
                due = today.weekday() == 0 and last_sent != today

            if due:
                try:
                    schedule._send_report()
                except Exception:
                    _logger.exception('Failed to send Stock Card schedule %s', schedule.name)
