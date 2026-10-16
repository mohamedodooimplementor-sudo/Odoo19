# -*- coding: utf-8 -*-
from . import utils
from . import er_required_field
from . import res_company
from . import res_config_settings
from . import employee_request
from . import employee_request_line
from . import employee_request_approval
from . import employee_purchase_order
from . import stock_inherit
from . import purchase_inherit
# the SQL report reads stock_move.er_project_id: it must be initialised after stock_inherit
from . import er_project_lock
from . import er_project_stock_report
from . import er_expiry
from . import product_coding
from . import employee_request_line_exec
from . import employee_request_exec
from . import project_project
from . import stock_location
from . import res_users
from . import er_request_source
