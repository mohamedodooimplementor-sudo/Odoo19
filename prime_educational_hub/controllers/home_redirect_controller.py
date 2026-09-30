# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

try:
    from odoo.addons.web.controllers.home import Home
except ImportError:
    Home = None
    _logger.warning(
        "Prime Educational Hub: could not locate Odoo's core login controller to add an "
        "explicit post-login redirect to the Dashboard Home Action. Each user's Home "
        "Action field (Settings > Users) is still set correctly by 'Apply Now to All "
        "Users' - only this extra forced redirect right after login is skipped."
    )

if Home is not None:

    class EducationHomeRedirect(Home):
        """After a normal login (no explicit ?redirect= requested - e.g. someone wasn't
        bounced here from a specific deep link), send the person straight to their Home
        Action if one is set, instead of relying on the web client's own client-side
        bootstrap to notice and navigate there on its own."""

        @http.route('/web/login', type='http', auth='none', sitemap=False)
        def web_login(self, redirect=None, **kw):
            response = super().web_login(redirect=redirect, **kw)
            # Odoo's own login page commonly attaches a generic '?redirect=/odoo' (or
            # '/web', '/') to bounce the user back roughly where they were - that's not a
            # deliberate deep link worth preserving, so it shouldn't block our Home Action
            # override. Only a redirect pointing somewhere more specific is left alone.
            generic_targets = ('', '/', '/odoo', '/odoo/', '/web', '/web/')
            if (not redirect or redirect in generic_targets) and request.session.uid:
                user = request.env.user
                if user.action_id:
                    try:
                        return request.redirect(f'/odoo/action-{user.action_id.id}')
                    except Exception:
                        _logger.exception(
                            "Prime Educational Hub: failed to build the post-login "
                            "redirect URL for user %s's Home Action.", user.id
                        )
            return response
