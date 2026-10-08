# -*- coding: utf-8 -*-
"""Small helpers to stay tolerant to field renames between Odoo versions."""


def pick_field(model, *names):
    """Return the first field name that exists on `model`, else None."""
    for name in names:
        if name in model._fields:
            return name
    return None


def convert_uom(qty, from_uom, to_uom):
    if not from_uom or not to_uom or from_uom == to_uom:
        return qty
    try:
        return from_uom._compute_quantity(qty, to_uom, round=False)
    except Exception:  # incompatible UoMs: keep the raw quantity
        return qty
