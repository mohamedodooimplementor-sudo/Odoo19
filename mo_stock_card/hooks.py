# -*- coding: utf-8 -*-
import importlib
import logging
import subprocess
import sys

_logger = logging.getLogger(__name__)

# Python libraries required by this module's PDF/Excel report engines.
# 'import_name' is what we try to `import`, 'pip_name' is what we `pip install`.
REQUIRED_LIBS = [
    {"import_name": "reportlab", "pip_name": "reportlab"},
    {"import_name": "xlsxwriter", "pip_name": "xlsxwriter"},
    {"import_name": "arabic_reshaper", "pip_name": "arabic-reshaper"},
    {"import_name": "bidi", "pip_name": "python-bidi"},
]


def _ensure_python_libs():
    """Make sure the PDF/Excel libraries are available, installing them via
    pip automatically if they are missing, so the admin doesn't have to
    touch the server's shell after installing the module."""
    for lib in REQUIRED_LIBS:
        try:
            importlib.import_module(lib["import_name"])
            _logger.info("mo_stock_card: '%s' is already installed.", lib["import_name"])
            continue
        except ImportError:
            pass

        _logger.info(
            "mo_stock_card: '%s' not found, installing automatically via pip...",
            lib["pip_name"],
        )
        try:
            subprocess.check_call(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--break-system-packages",
                    lib["pip_name"],
                ]
            )
            importlib.invalidate_caches()
            importlib.import_module(lib["import_name"])
            _logger.info("mo_stock_card: '%s' installed successfully.", lib["pip_name"])
        except Exception:
            # Fall back to a plain pip install without the flag, in case the
            # running Python/pip doesn't support --break-system-packages
            # (older pip versions).
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", lib["pip_name"]]
                )
                importlib.invalidate_caches()
                importlib.import_module(lib["import_name"])
                _logger.info("mo_stock_card: '%s' installed successfully.", lib["pip_name"])
            except Exception:
                _logger.warning(
                    "mo_stock_card: could not automatically install '%s'. "
                    "Please install it manually on the server: pip install %s",
                    lib["pip_name"],
                    lib["pip_name"],
                    exc_info=True,
                )


def post_init_hook(env):
    """Odoo 17+/18/19 post_init_hook signature: receives the environment
    directly (older versions received (cr, registry); this hook only needs
    to run pip installs, so the incoming argument itself is unused)."""
    _ensure_python_libs()
