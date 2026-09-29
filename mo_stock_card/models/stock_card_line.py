from odoo import models, fields, api


class StockCardLine(models.TransientModel):
    _name = 'stock.card.line'
    _description = 'Stock Card Line'
    _order = 'product_id, sequence, date, id'

    wizard_id = fields.Many2one('stock.card.wizard', string='Wizard', ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    line_type = fields.Selection([
        ('opening', 'Opening Balance'),
        ('transaction', 'Transaction'),
        ('closing', 'Closing Balance'),
        ('group_header', 'Group Header'),
    ], string='Line Type', default='transaction')
    
    date = fields.Date(string='Date')
    product_id = fields.Many2one('product.product', string='Product')
    product_tmpl_id = fields.Many2one('product.template', string='Product Template', related='product_id.product_tmpl_id', store=True)
    categ_id = fields.Many2one('product.category', string='Category', related='product_id.categ_id', store=True)
    
    reference = fields.Char(string='Reference')
    source_document = fields.Char(string='Source Document')
    partner_id = fields.Many2one('res.partner', string='Partner')
    picking_id = fields.Many2one(
        'stock.picking', string='Transfer',
        help='The Transfer (Receipt, Delivery, Internal Transfer, ...) this line comes from, '
             'if any. Click the arrow icon in the list to open it directly.'
    )
    
    qty_in = fields.Float(string='In Qty', digits='Product Unit of Measure')
    qty_out = fields.Float(string='Out Qty', digits='Product Unit of Measure')
    balance = fields.Float(string='Balance', digits='Product Unit of Measure', group_operator=None)
    initial_balance = fields.Float(string='Initial Balance', digits='Product Unit of Measure', group_operator=None)
    
    unit_cost = fields.Float(string='Unit Cost', digits='Product Price', group_operator=None)
    value_in = fields.Float(string='Value In', digits='Product Price')
    value_out = fields.Float(string='Value Out', digits='Product Price')
    balance_value = fields.Float(string='Balance Value', digits='Product Price', group_operator=None)
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        help='Currency the Unit Cost / Value In / Value Out / Balance Value figures on this '
             'line are expressed in. Matches the report\'s consolidation currency when several '
             'companies with different currencies are combined into one report.'
    )
    
    location_id = fields.Many2one('stock.location', string='Source Location')
    location_dest_id = fields.Many2one('stock.location', string='Destination Location')
    move_id = fields.Many2one('stock.move', string='Stock Move')
    move_line_id = fields.Many2one('stock.move.line', string='Stock Move Line')
    
    change_percent = fields.Float(string='Change %', digits=(16, 2))
    avg_cost_in = fields.Float(string='Avg. Cost (In, Period)', digits='Product Price')
    turnover_ratio = fields.Float(string='Turnover Ratio', digits=(16, 2))
    days_of_stock = fields.Float(string='Days of Stock', digits=(16, 1))

    lot_id = fields.Many2one('stock.lot', string='Lot/Serial')
    picking_type_id = fields.Many2one('stock.picking.type', string='Operation Type')

    is_negative = fields.Boolean(string='Negative Balance', default=False)
    system_qty = fields.Float(string='System On-Hand Qty', digits='Product Unit of Measure')
    reconciliation_diff = fields.Float(string='Reconciliation Difference', digits='Product Unit of Measure')
    is_reconciliation_checked = fields.Boolean(string='Reconciliation Checked', default=False)

    display_name = fields.Char(string='Display Name', compute='_compute_display_name')
    is_group_line = fields.Boolean(string='Is Group Line', compute='_compute_is_group_line', store=True)
    group_name = fields.Char(string='Group Name')
    transaction_count = fields.Integer(string='Transaction Count')

    @api.depends('line_type')
    def _compute_is_group_line(self):
        for line in self:
            line.is_group_line = line.line_type == 'group_header'

    @api.depends('product_id', 'line_type', 'reference')
    def _compute_display_name(self):
        for line in self:
            if line.line_type == 'opening':
                line.display_name = 'Opening Balance'
            elif line.line_type == 'closing':
                line.display_name = 'Closing Balance'
            elif line.line_type == 'group_header':
                line.display_name = line.group_name or ''
            else:
                line.display_name = line.reference or ''

    def action_open_source_document(self):
        """Open the Transfer (stock.picking) this transaction line came from,
        instead of making the person search for it manually."""
        self.ensure_one()
        if not self.picking_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': self.picking_id.name,
            'res_model': 'stock.picking',
            'res_id': self.picking_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
