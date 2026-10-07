"""v2.0: field-sales features. Keeps existing data meaningful with the new definitions."""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    # visit results: "Customer Closed" is now "Customer Not Available"
    cr.execute("UPDATE mo_sales_visit SET result = 'not_available' WHERE result = 'closed'")
    # every customer that existed before the approval workflow is approved
    cr.execute("UPDATE res_partner SET mo_approval_state = 'approved' WHERE mo_approval_state IS NULL")
    # route stops keep their weekly behaviour
    cr.execute("UPDATE mo_sales_route_line SET frequency = 'weekly' WHERE frequency IS NULL")
    _logger.info('Sales rep portal v2.0 migration done')
