# -*- coding: utf-8 -*-
"""Plain helper functions (not models) shared across the Fees models to read
the Configuration > Education settings without duplicating the same
ir.config_parameter lookup logic in every file."""


def get_default_currency(env):
    """Returns the configured default fee currency, falling back to the
    current company's currency if none is set."""
    param = env['ir.config_parameter'].sudo().get_param('prime_educational_hub.default_currency_id')
    if param:
        currency = env['res.currency'].browse(int(param)).exists()
        if currency:
            return currency
    return env.company.currency_id


def get_late_penalty_config(env):
    """Returns (penalty_type, value, grace_days) e.g. ('percent', 5.0, 3)."""
    ICP = env['ir.config_parameter'].sudo()
    penalty_type = ICP.get_param('prime_educational_hub.late_penalty_type', 'none')
    value = float(ICP.get_param('prime_educational_hub.late_penalty_value', 0.0) or 0.0)
    grace_days = int(ICP.get_param('prime_educational_hub.late_penalty_grace_days', 3) or 0)
    return penalty_type, value, grace_days


def get_early_discount_config(env):
    """Returns (discount_type, value, days_before) e.g. ('percent', 5.0, 7)."""
    ICP = env['ir.config_parameter'].sudo()
    discount_type = ICP.get_param('prime_educational_hub.early_discount_type', 'none')
    value = float(ICP.get_param('prime_educational_hub.early_discount_value', 0.0) or 0.0)
    days_before = int(ICP.get_param('prime_educational_hub.early_discount_days_before', 7) or 0)
    return discount_type, value, days_before


def get_discount_approval_threshold(env):
    """Returns the configured discount-approval threshold percentage (e.g.
    20.0 meaning 20%). Fees discounted at or above this must be explicitly
    approved by a Supervisor/Admin before they can be confirmed."""
    ICP = env['ir.config_parameter'].sudo()
    return float(ICP.get_param('prime_educational_hub.discount_approval_threshold', 20.0) or 0.0)


def get_default_discount(env):
    """Returns (discount_policy, discount_value) configured as defaults for
    new fees/enrollments, e.g. ('percent', 10.0) or ('none', 0.0)."""
    ICP = env['ir.config_parameter'].sudo()
    policy = ICP.get_param('prime_educational_hub.default_discount_policy', 'none')
    value = float(ICP.get_param('prime_educational_hub.default_discount_value', 0.0) or 0.0)
    return policy, value


def get_school_timezone(env):
    """Returns the timezone every session's wall-clock start/end time (e.g.
    '2:30 PM') should be interpreted in before being converted to the UTC
    Datetime Odoo actually stores. Falls back to the current user's
    timezone, then UTC, if the center hasn't set one explicitly in
    Settings -- but an explicit setting is what you want for a school:
    the schedule means the same local time no matter which staff member
    (or the cron, running as an admin with no personal tz) generates it."""
    ICP = env['ir.config_parameter'].sudo()
    tz_name = ICP.get_param('prime_educational_hub.school_timezone')
    if not tz_name:
        tz_name = env.user.tz
    return tz_name or 'UTC'


def is_pin_required_for_checkin(env):
    """Whether the public self-check-in page must ask for a PIN in addition
    to the student code. Defaults to True (the secure behavior) -- an
    admin can turn it off in Settings for centers that decide the code
    alone is enough."""
    ICP = env['ir.config_parameter'].sudo()
    return ICP.get_param('prime_educational_hub.require_pin_for_checkin', 'True') == 'True'


def has_multi_branch(env):
    """True if the center has more than one active branch configured. Used
    to hide the Branch field entirely for single-branch centers (where it's
    just noise) and require it once a second branch is added."""
    return env['education.branch'].sudo().search_count([]) > 1


def float_to_time_parts(value):
    """Converts a float hour (e.g. 14.5) into (hour, minute) integers (14, 30).
    Shared by the manual session-generation wizard and the daily
    auto-generation cron so a schedule's start/end time is interpreted
    identically in both places."""
    hours = int(value)
    minutes = int(round((value - hours) * 60))
    if minutes == 60:
        minutes = 0
        hours += 1
    return hours, minutes
