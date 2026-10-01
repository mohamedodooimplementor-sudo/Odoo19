from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError, ValidationError


@tagged("post_install", "-at_install")
class TestStockBudgetActual(TransactionCase):
    """Regression tests for the "one stock.move -> one Actual" architecture.

    NOTE: these were written and reviewed for correctness against the module's
    code, but this environment has no live Odoo database to actually execute
    them against - run `odoo-bin -d <db> --test-enable -i construction_project_budget
    --stop-after-init` (or your usual test runner) to confirm before relying on
    them. Depending on the target database's installed Chart of Accounts, the
    account setup in setUp() may need adjusting (account codes/types) - it's
    written to be self-contained rather than depend on demo data.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        # Minimal accounts needed for real-time inventory valuation.
        cls.stock_valuation_account = cls.env["account.account"].create({
            "name": "Test Stock Valuation",
            "code": "TSTV01",
            "account_type": "asset_current",
            "company_ids": [(6, 0, [cls.company.id])],
        })
        cls.expense_account = cls.env["account.account"].create({
            "name": "Test Project Expenses",
            "code": "TSTE01",
            "account_type": "expense",
            "company_ids": [(6, 0, [cls.company.id])],
        })
        cls.counterpart_account = cls.env["account.account"].create({
            "name": "Test Cash",
            "code": "TSTC01",
            "account_type": "asset_cash",
            "company_ids": [(6, 0, [cls.company.id])],
        })
        cls.journal = cls.env["account.journal"].search([
            ("type", "=", "general"), ("company_id", "=", cls.company.id),
        ], limit=1) or cls.env["account.journal"].create({
            "name": "Test Misc", "type": "general", "code": "TMISC", "company_id": cls.company.id,
        })

        cls.categ = cls.env["product.category"].create({
            "name": "Test Construction Materials",
            "property_valuation": "real_time",
            "property_cost_method": "standard",
            "property_stock_valuation_account_id": cls.stock_valuation_account.id,
            "property_stock_account_input_categ_id": cls.stock_valuation_account.id,
            "property_stock_account_output_categ_id": cls.expense_account.id,
        })
        cls.product = cls.env["product.product"].create({
            "name": "Test Construct Material A",
            "type": "product",
            "categ_id": cls.categ.id,
            "standard_price": 100.0,
        })

        cls.warehouse = cls.env["stock.warehouse"].search([("company_id", "=", cls.company.id)], limit=1)
        cls.project_location = cls.env["stock.location"].create({
            "name": "Test Project Consumption",
            "usage": "inventory",
            "company_id": cls.company.id,
        })

        cls.project = cls.env["project.project"].create({"name": "Test Project A"})
        cls.materials_category = cls.env["construction.budget.category"].create({
            "name": "Test Materials", "type": "cost", "expense_account_id": cls.expense_account.id,
        })
        cls.budget = cls.env["construction.project.budget"].create({
            "project_id": cls.project.id,
            "expense_journal_id": cls.journal.id,
            "expense_counterpart_account_id": cls.counterpart_account.id,
            "line_ids": [(0, 0, {"category_id": cls.materials_category.id, "planned_amount": 50000})],
        })

        # Give the product some stock to consume/return in tests.
        cls.env["stock.quant"]._update_available_quantity(cls.product, cls.warehouse.lot_stock_id, 1000)

    def _make_picking(self, source, dest, qty, category=None):
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.int_type_id.id,
            "location_id": source.id,
            "location_dest_id": dest.id,
            "construction_project_id": self.project.id,
            "construction_budget_id": self.budget.id,
            "construction_category_id": (category or self.materials_category).id,
            "move_ids": [(0, 0, {
                "name": self.product.name,
                "product_id": self.product.id,
                "product_uom_qty": qty,
                "product_uom": self.product.uom_id.id,
                "location_id": source.id,
                "location_dest_id": dest.id,
            })],
        })
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = qty
        return picking

    def _expenses(self):
        return self.env["construction.project.budget.expense"].search([("budget_id", "=", self.budget.id)])

    # -- A: basic consumption -------------------------------------------------
    def test_a_material_consumption_creates_actual(self):
        picking = self._make_picking(self.warehouse.lot_stock_id, self.project_location, 10)
        picking.button_validate()
        self.assertAlmostEqual(self.budget.actual_total, 1000.0, places=2)

    # -- B: the valuation journal entry must not double the actual -----------
    def test_b_valuation_entry_does_not_duplicate_actual(self):
        picking = self._make_picking(self.warehouse.lot_stock_id, self.project_location, 10)
        picking.button_validate()
        move = self.env["account.move"].search([
            ("construction_budget_id", "=", self.budget.id), ("move_type", "=", "entry"),
        ])
        self.assertTrue(move, "Stock valuation entry should be tagged with the budget")
        self.assertTrue(move.skip_budget_actual_post)
        self.assertAlmostEqual(self.budget.actual_total, 1000.0, places=2)

    # -- C: multiple materials in one picking ---------------------------------
    def test_c_multiple_materials_total_correctly(self):
        product_b = self.product.copy({"name": "Test Construct Material B", "standard_price": 50.0})
        self.env["stock.quant"]._update_available_quantity(product_b, self.warehouse.lot_stock_id, 1000)
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.int_type_id.id,
            "location_id": self.warehouse.lot_stock_id.id,
            "location_dest_id": self.project_location.id,
            "construction_project_id": self.project.id,
            "construction_budget_id": self.budget.id,
            "construction_category_id": self.materials_category.id,
            "move_ids": [
                (0, 0, {
                    "name": self.product.name, "product_id": self.product.id, "product_uom_qty": 10,
                    "product_uom": self.product.uom_id.id,
                    "location_id": self.warehouse.lot_stock_id.id, "location_dest_id": self.project_location.id,
                }),
                (0, 0, {
                    "name": product_b.name, "product_id": product_b.id, "product_uom_qty": 20,
                    "product_uom": product_b.uom_id.id,
                    "location_id": self.warehouse.lot_stock_id.id, "location_dest_id": self.project_location.id,
                }),
            ],
        })
        picking.action_confirm()
        picking.action_assign()
        for move in picking.move_ids:
            move.quantity = move.product_uom_qty
        picking.button_validate()
        # 10 * 100 + 20 * 50 = 2000
        self.assertAlmostEqual(self.budget.actual_total, 2000.0, places=2)
        self.assertEqual(len(self._expenses()), 2)

    # -- D: plain internal transfer must not create any actual ---------------
    def test_d_internal_transfer_creates_no_actual(self):
        other_location = self.env["stock.location"].create({
            "name": "Test Other Internal", "usage": "internal", "company_id": self.company.id,
        })
        picking = self._make_picking(self.warehouse.lot_stock_id, other_location, 10)
        picking.button_validate()
        self.assertAlmostEqual(self.budget.actual_total, 0.0, places=2)

    # -- E: a return should reduce the net actual -----------------------------
    def test_e_return_reduces_actual(self):
        picking = self._make_picking(self.warehouse.lot_stock_id, self.project_location, 10)
        picking.button_validate()
        self.assertAlmostEqual(self.budget.actual_total, 1000.0, places=2)

        return_picking = self._make_picking(self.project_location, self.warehouse.lot_stock_id, 3)
        return_picking.button_validate()
        self.assertAlmostEqual(self.budget.actual_total, 700.0, places=2)

    # -- G: reset to draft + repost of the valuation entry must not duplicate -
    def test_g_repost_valuation_entry_no_duplicate(self):
        picking = self._make_picking(self.warehouse.lot_stock_id, self.project_location, 10)
        picking.button_validate()
        move = self.env["account.move"].search([
            ("construction_budget_id", "=", self.budget.id), ("move_type", "=", "entry"),
        ])
        move.button_draft()
        move.action_post()
        self.assertAlmostEqual(self.budget.actual_total, 1000.0, places=2)

    # -- N: a closed budget must block, not silently drop, new activity ------
    def test_n_closed_budget_blocks_validation(self):
        self.budget.is_closed = True
        picking = self.env["stock.picking"].create({
            "picking_type_id": self.warehouse.int_type_id.id,
            "location_id": self.warehouse.lot_stock_id.id,
            "location_dest_id": self.project_location.id,
            "move_ids": [(0, 0, {
                "name": self.product.name, "product_id": self.product.id, "product_uom_qty": 5,
                "product_uom": self.product.uom_id.id,
                "location_id": self.warehouse.lot_stock_id.id, "location_dest_id": self.project_location.id,
            })],
        })
        with self.assertRaises(ValidationError):
            picking.write({"construction_project_id": self.project.id, "construction_budget_id": self.budget.id})
