# -*- coding: utf-8 -*-
from odoo import fields, models, tools


class ErProjectStockReport(models.Model):
    """Stock held per project: received for the project minus issued to it."""
    _name = 'er.project.stock.report'
    _description = 'Project Stock Report'
    _auto = False
    _order = 'project_id, location_id, product_id'

    project_id = fields.Many2one('project.project', string='Project', readonly=True)
    location_id = fields.Many2one('stock.location', string='Location', readonly=True)
    product_id = fields.Many2one('product.product', string='Product', readonly=True)
    product_uom_id = fields.Many2one('uom.uom', string='UoM', readonly=True)
    company_id = fields.Many2one('res.company', string='Company', readonly=True)
    qty_received = fields.Float(string='Received', readonly=True, digits='Product Unit')
    qty_allocated = fields.Float(string='Allocated', readonly=True, digits='Product Unit')
    qty_issued = fields.Float(string='Issued', readonly=True, digits='Product Unit')
    qty_held = fields.Float(string='Held for Project', readonly=True, digits='Product Unit')
    value_held = fields.Float(string='Value Held', readonly=True,
                              help="Held quantity x the product's current cost.")

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT row_number() OVER () AS id,
                       t.project_id, t.location_id, t.product_id, t.company_id,
                       pt.uom_id AS product_uom_id,
                       t.qty_received, t.qty_allocated, t.qty_issued,
                       t.qty_received + t.qty_allocated - t.qty_issued AS qty_held,
                       (t.qty_received + t.qty_allocated - t.qty_issued) * COALESCE(
                           (SELECT (pp.standard_price->>t.company_id::text)::numeric), 0)
                           AS value_held
                FROM (
                    SELECT u.project_id, u.location_id, u.product_id, u.company_id,
                           SUM(u.qty_received) AS qty_received,
                           SUM(u.qty_allocated) AS qty_allocated,
                           SUM(u.qty_issued) AS qty_issued
                    FROM (
                        SELECT m.er_project_id AS project_id,
                               CASE WHEN spt.code = 'incoming' THEN m.location_dest_id
                                    ELSE m.location_id END AS location_id,
                               m.product_id AS product_id,
                               m.company_id AS company_id,
                               SUM(CASE WHEN spt.code = 'incoming'
                                        THEN ml.quantity_product_uom ELSE 0 END) AS qty_received,
                               0 AS qty_allocated,
                               SUM(CASE WHEN spt.code = 'outgoing'
                                        THEN ml.quantity_product_uom ELSE 0 END) AS qty_issued
                        FROM stock_move m
                        JOIN stock_move_line ml ON ml.move_id = m.id
                        JOIN stock_picking_type spt ON spt.id = m.picking_type_id
                        WHERE m.state = 'done'
                          AND m.er_project_id IS NOT NULL
                          AND spt.code IN ('incoming', 'outgoing')
                        GROUP BY m.er_project_id,
                                 CASE WHEN spt.code = 'incoming' THEN m.location_dest_id
                                      ELSE m.location_id END,
                                 m.product_id, m.company_id
                        UNION ALL
                        SELECT a.project_id, a.location_id, a.product_id, a.company_id,
                               0, SUM(CASE WHEN a.kind = 'release' THEN -a.qty ELSE a.qty END), 0
                        FROM er_project_allocation a
                        WHERE a.state = 'confirmed'
                        GROUP BY a.project_id, a.location_id, a.product_id, a.company_id
                    ) u
                    GROUP BY u.project_id, u.location_id, u.product_id, u.company_id
                ) t
                JOIN product_product pp ON pp.id = t.product_id
                JOIN product_template pt ON pt.id = pp.product_tmpl_id
            )""" % self._table)
