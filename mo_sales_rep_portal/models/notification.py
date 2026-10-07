from odoo import fields, models


class SalesRepNotification(models.Model):
    _name = 'mo.sales.rep.notification'
    _description = 'Sales Representative Notification'
    _order = 'id desc'

    rep_id = fields.Many2one('mo.sales.rep', required=True, ondelete='cascade')
    name = fields.Char('Title', required=True)
    body = fields.Text()
    url = fields.Char()
    is_read = fields.Boolean(default=False)
    key = fields.Char(index=True, help='Deduplication key: the same event never notifies twice.')
