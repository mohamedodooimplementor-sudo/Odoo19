# -*- coding: utf-8 -*-
"""Auto-detects and installs the external Python packages this module needs
(reportlab + XlsxWriter for PDF/Excel reports, qrcode for the QR
self-attendance feature). Used from:
  - post_init_hook (runs once right after install/upgrade)
  - the "Check / Install Libraries" button on Settings > Education
so an admin never has to go dig through server logs to find out a report
or the QR feature is silently failing because of a missing library.
"""
import importlib
import logging
import subprocess
import sys

_logger = logging.getLogger(__name__)

# import name -> pip package name (only differs for XlsxWriter)
REQUIRED_PACKAGES = {
    'reportlab': 'reportlab',
    'xlsxwriter': 'XlsxWriter',
    'qrcode': 'qrcode',
}


def _pip_install(pip_name):
    """Tries a plain `pip install` first. On Debian/Ubuntu servers with
    PEP 668 'externally-managed-environment' protection, a plain install
    fails silently-ish with an error — retry once with
    --break-system-packages so it actually goes through. Never raises;
    returns True/False."""
    base_cmd = [sys.executable, '-m', 'pip', 'install', pip_name]
    try:
        subprocess.check_call(base_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        pass
    try:
        subprocess.check_call(base_cmd + ['--break-system-packages'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as exc:
        _logger.warning(
            "Prime Educational Hub: could not auto-install '%s' (%s). "
            "Install it manually on the server with: pip install %s", pip_name, exc, pip_name)
        return False


def check_and_install_dependencies(env=None):
    """Checks every package in REQUIRED_PACKAGES; pip-installs whatever is
    missing. Idempotent — safe to call on every install/upgrade or as many
    times as you like from the Settings button. Returns
    {import_name: True/False}. If `env` is given, also writes a
    human-readable summary to ir.config_parameter so Settings can display
    it without needing server log access."""
    results = {}
    for import_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(import_name)
            results[import_name] = True
            continue
        except ImportError:
            _logger.info("Prime Educational Hub: '%s' not found — attempting install...", import_name)

        if _pip_install(pip_name):
            importlib.invalidate_caches()
            try:
                importlib.import_module(import_name)
                results[import_name] = True
                _logger.info("Prime Educational Hub: '%s' installed successfully.", import_name)
            except ImportError:
                results[import_name] = False
        else:
            results[import_name] = False

    if env is not None:
        missing = [name for name, ok in results.items() if not ok]
        if missing:
            summary = ('Missing: %s — could not auto-install (no internet access on the server, or '
                       'pip is unavailable). Install manually with: pip install %s') % (
                ', '.join(missing), ' '.join(REQUIRED_PACKAGES[m] for m in missing))
        else:
            summary = 'All required libraries (reportlab, XlsxWriter, qrcode) are installed.'
        env['ir.config_parameter'].sudo().set_param(
            'prime_educational_hub.dependencies_status', summary)

    return results
