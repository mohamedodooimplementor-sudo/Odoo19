# -*- coding: utf-8 -*-
"""Small helpers to stay tolerant to field renames between Odoo versions."""


def pick_field(model, *names):
    """Return the first field name that exists on `model`, else None."""
    for name in names:
        if name in model._fields:
            return name
    return None


def location_warehouse(env, location, company=None):
    """Warehouse a stock location belongs to (its operation types are used for the
    transfers and receipts of that location). Falls back to the first warehouse of the company."""
    wh = location.warehouse_id if location and 'warehouse_id' in location._fields else False
    if not wh:
        company = company or (location.company_id if location else False) or env.company
        wh = env['stock.warehouse'].search([('company_id', '=', company.id)], limit=1)
    return wh


def default_location(env, company=None):
    """Location used when the project has none: the general projects location of the company,
    else the stock location of its first warehouse."""
    company = (company or env.company).sudo()
    if company.er_general_location_id:
        return company.er_general_location_id
    return env['stock.warehouse'].sudo().search(
        [('company_id', '=', company.id)], limit=1).lot_stock_id


def convert_uom(qty, from_uom, to_uom):
    if not from_uom or not to_uom or from_uom == to_uom:
        return qty
    try:
        return from_uom._compute_quantity(qty, to_uom, round=False)
    except Exception:  # incompatible UoMs: keep the raw quantity
        return qty
