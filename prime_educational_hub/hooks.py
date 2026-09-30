# -*- coding: utf-8 -*-
from .models.education_dependency_utils import check_and_install_dependencies


def post_init_hook(env):
    """Runs automatically right after this module is installed (and again
    on every upgrade). Makes sure reportlab / XlsxWriter (PDF & Excel
    reports) and qrcode (QR self-attendance) are present on the server,
    installing whichever ones are missing via pip instead of leaving the
    admin to discover it later from a broken report or a missing QR
    button. Never blocks or fails the installation — if pip can't reach
    the internet, it just logs a warning and records the status for the
    Settings > Education screen."""
    check_and_install_dependencies(env)
