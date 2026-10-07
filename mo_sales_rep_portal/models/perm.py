"""Pure helpers for per-representative permissions (no Odoo imports, unit-testable)."""

MODES = ('default', 'yes', 'no')


def resolve(mode, global_value):
    """'yes' / 'no' override the global setting; anything else follows it."""
    if mode == 'yes':
        return True
    if mode == 'no':
        return False
    return bool(global_value)


def discount_cap(discount_allowed, rep_max, global_max):
    """Maximum discount % for a representative.

    The representative's own value (when > 0) replaces the global maximum, so one rep can be
    given more *or* less room than the others.
    """
    if not discount_allowed:
        return 0.0
    if rep_max and rep_max > 0:
        return float(rep_max)
    return float(global_max or 0.0)
