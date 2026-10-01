import logging

from . import controllers
from . import models
from . import wizard
from . import report

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """The Profitability Report PDF is generated with ReportLab (a pure-Python
    library, unlike wkhtmltopdf-based QWeb PDF rendering, which is a frequent
    source of printing failures on Windows installs). Most Odoo installs
    already ship it as a dependency of other addons, but if it's missing,
    install it automatically instead of leaving the report broken. This also
    runs lazily on first PDF generation (see ensure_reportlab), which is what
    covers upgrades of an already-installed module - this hook only fires on
    a fresh install.
    """
    from .report.profitability_report_pdf import ensure_reportlab
    try:
        ensure_reportlab()
    except Exception:
        _logger.warning(
            "construction_project_budget: could not automatically install reportlab. "
            "Please run 'pip install reportlab' manually for the Profitability Report "
            "PDF to work.", exc_info=True,
        )
