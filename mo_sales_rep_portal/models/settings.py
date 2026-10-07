from odoo import api, fields, models, _


class SalesRepSettings(models.Model):
    """Single-record settings model (explicit booleans, no ir.config_parameter gotchas)."""
    _name = 'mo.sales.rep.settings'
    _description = 'Sales Representative Portal Settings'

    name = fields.Char(default='Sales Representative Portal Settings', readonly=True)
    # General
    enable_gps = fields.Boolean('Enable GPS', default=True)
    enable_tracking = fields.Boolean('Enable Visit Tracking (periodic location while a visit is open)', default=False)
    tracking_interval = fields.Integer('Tracking Interval (seconds)', default=120)
    enable_attachments = fields.Boolean('Enable Attachments', default=True)
    enable_whatsapp = fields.Boolean('Enable WhatsApp', default=True)
    enable_customer_location = fields.Boolean('Enable Customer Location', default=True)
    notify_by_email = fields.Boolean('Send Notifications by Email', default=False,
                                     help='Also email each notification to the representative (needs outgoing mail and an email on the user).')
    # Customers / ranking / suggestions
    customer_approval = fields.Boolean('Require Approval for New Customers', default=False,
                                       help='Customers created from the portal wait for a manager approval (Waiting Approval > Approved).')
    allow_new_customer = fields.Boolean('Allow Creating Customers from the Portal', default=True)
    allow_expense = fields.Boolean('Allow Expenses', default=True)
    allow_customer_return = fields.Boolean('Allow Customer Returns', default=True)
    allow_ranking = fields.Boolean('Show Ranking to Representatives', default=False)
    ranking_metric = fields.Selection([('target', 'Target Achievement'), ('sales', 'Sales'), ('collection', 'Collection'),
                                       ('visits', 'Visits'), ('new_customers', 'New Customers')],
                                      'Ranking Based On', default='target', required=True)
    ranking_show_values = fields.Boolean('Show Amounts in the Ranking', default=False,
                                         help='Off: representatives only see rank, name and score %, never other people\'s amounts.')
    suggest_no_visit_days = fields.Integer('Suggest Customers Not Visited For (days)', default=30)
    suggest_no_order_days = fields.Integer('Suggest Customers Without Order For (days)', default=30)
    suggest_outstanding_min = fields.Float('Suggest Customers Owing At Least', default=1000.0)
    # Sales
    allow_quotation = fields.Boolean('Allow Quotation', default=True)
    allow_sales_order = fields.Boolean('Allow Sales Order', default=True)
    allow_discount = fields.Boolean('Allow Discount', default=True)
    max_discount = fields.Float('Maximum Discount %', default=20.0)
    allow_price_change = fields.Boolean('Allow Price Change', default=False)
    # Accounting
    allow_invoice_creation = fields.Boolean('Allow Invoice Creation', default=True)
    allow_direct_invoice = fields.Boolean('Allow Invoice without Sales Order', default=False)
    auto_post_invoice = fields.Boolean('Post Invoice Automatically', default=True)
    allow_payment = fields.Boolean('Allow Payment Registration', default=True)
    # Inventory
    allow_stock_view = fields.Boolean('Allow Stock View', default=True)
    allow_internal_transfer = fields.Boolean('Allow Internal Transfer', default=True)
    allow_return = fields.Boolean('Allow Return', default=True)
    allow_delivery_validation = fields.Boolean('Allow Delivery Validation', default=False)
    allow_auto_validate = fields.Boolean('Allow Automatic Validation of Stock Operations', default=False,
                                         help='Default for every representative; each one can be overridden on his own profile.')
    main_warehouse_id = fields.Many2one('stock.warehouse', 'Main Warehouse (source for Receive / target for Return)')

    @api.model
    def get_settings(self):
        rec = self.sudo().search([], limit=1)
        if not rec:
            rec = self.sudo().create({})
        return rec

    @api.model
    def action_open_settings(self):
        rec = self.get_settings()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sales Representative Portal Settings'),
            'res_model': self._name,
            'res_id': rec.id,
            'view_mode': 'form',
            'target': 'current',
        }
