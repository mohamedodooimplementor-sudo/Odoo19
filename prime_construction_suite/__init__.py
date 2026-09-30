# -*- coding: utf-8 -*-
from . import models
from . import wizard
from . import controllers


def _post_init_hook(env):
    """Best-effort auto-install of the reportlab library used to generate every PDF report in
    this module (no wkhtmltopdf dependency). If pip isn't reachable from the server (e.g. no
    internet access), this silently does nothing — an administrator can then run
    `pip install reportlab` manually and PDF reports will start working without any other change."""
    try:
        import reportlab  # noqa: F401
    except ImportError:
        try:
            import subprocess
            import sys
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', 'reportlab'])
        except Exception:
            pass

