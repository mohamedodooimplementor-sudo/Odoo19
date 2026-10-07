"""Tiny runtime translation layer for the portal (Arabic).

The portal is rendered for external users, so the strings are resolved at render
time from the user's language instead of relying on .po term segmentation of QWeb.
"""
from odoo.http import request

from .ar_terms import AR


def is_ar():
    try:
        lang = request.env.lang or request.env.user.lang or ''
    except Exception:
        return False
    return str(lang).startswith('ar')


def T(src, *args, **kwargs):
    text = AR.get(src, src) if (src and is_ar()) else src
    if args:
        return text % args
    if kwargs:
        return text % kwargs
    return text
