# -*- coding: utf-8 -*-
"""Bundled fallback for the two third-party libraries this module's own
reports need (ReportLab for PDFs, XlsxWriter for Excel).

Odoo itself already requires both, so on a normal installation they are simply
imported from Odoo's Python and nothing here has any effect. Only if one of
them is missing is the verified copy in ``libs/`` used - and then only *inside*
a report build of this module (see ``private_bundled_libs``), never globally,
so it cannot influence Odoo's own reports in any way.
"""
import contextlib
import functools
import hashlib
import importlib.util
import os
import sys
import threading

_lock = threading.RLock()
_LIBRARIES = ("reportlab", "xlsxwriter")

_LIBS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libs")
FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fonts")


def bundled_libs_intact():
    """True only if every file in ``libs/`` is exactly what was shipped: same
    SHA-256 as in ``libs/CHECKSUMS.sha256`` and no extra files (a stray
    ``.pth`` / ``.py`` dropped there would otherwise run inside Odoo). This
    catches corruption and partial tampering; someone who can rewrite the
    whole module folder can of course also rewrite the manifest."""
    manifest = os.path.join(_LIBS_DIR, "CHECKSUMS.sha256")
    try:
        expected = {}
        with open(manifest, encoding="utf-8") as handle:
            for line in handle:
                digest, _sep, rel = line.rstrip("\n").partition("  ")
                if digest and rel:
                    expected[rel] = digest
        present = set()
        for folder, _dirs, files in os.walk(_LIBS_DIR):
            for name in files:
                rel = os.path.relpath(os.path.join(folder, name), _LIBS_DIR).replace(os.sep, "/")
                if rel != "CHECKSUMS.sha256" and not name.endswith(".pyc"):
                    present.add(rel)
        if present != set(expected):
            return False
        for rel, digest in expected.items():
            with open(os.path.join(_LIBS_DIR, rel), "rb") as handle:
                if hashlib.sha256(handle.read()).hexdigest() != digest:
                    return False
        return True
    except OSError:
        return False


@contextlib.contextmanager
def private_bundled_libs():
    """Make ReportLab / XlsxWriter importable for the duration of ONE report
    build, and leave no trace afterwards.

    Nothing happens when Odoo's Python already has them (the normal case: Odoo
    itself requires both). If one is missing, the verified copy in ``libs/`` is
    put on ``sys.path`` only while the report is being built, and both the path
    entry and the modules imported from it are removed again at the end - so
    the copies are never visible to Odoo's own code, and this module never
    changes how Odoo's reports work.
    """
    missing = [name for name in _LIBRARIES if importlib.util.find_spec(name) is None]
    if not missing:
        yield
        return
    with _lock:
        if not bundled_libs_intact():
            raise ImportError(
                f"{', '.join(missing)} is not installed in Odoo's Python and the bundled copy in "
                "mo_insurance_management/libs failed its integrity check. Install the missing "
                "package(s) with pip in Odoo's Python environment."
            )
        already_loaded = set(sys.modules)
        sys.path.append(_LIBS_DIR)
        try:
            yield
        finally:
            try:
                sys.path.remove(_LIBS_DIR)
            except ValueError:
                pass
            for module_name in list(sys.modules):
                if module_name not in already_loaded and module_name.split(".")[0] in missing:
                    del sys.modules[module_name]


def uses_bundled_libs(func):
    """Decorator for the functions that build PDFs / Excel files."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with private_bundled_libs():
            return func(*args, **kwargs)

    return wrapper
