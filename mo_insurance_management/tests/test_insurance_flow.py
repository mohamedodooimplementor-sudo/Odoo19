# -*- coding: utf-8 -*-
"""End-to-end tests of the insurance billing flow:

    insured sale order -> patient invoice + insurance company invoice ->
    claim -> payments (oldest invoice first) -> rejections / credit notes

plus the permission rules (a user with NO Insurance group can still work
with insured orders/invoices, but cannot see or open the Insurance app).
"""
from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.addons.mo_insurance_management.report.claim_statement import ClaimStatement
from odoo.addons.mo_insurance_management.report.document_builder import build_document_pdf
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import InsuranceCommon


@tagged("post_install", "-at_install")
class TestInsuranceFlow(InsuranceCommon):
    # ------------------------------------------------------------------
    # invoices
    # ------------------------------------------------------------------
    def test_insurance_invoice_uses_journal_default_account(self):
        insurance_invoice = self._insurance_invoice()
        self.assertTrue(insurance_invoice, "the insurance company's invoice must be created")
        self.assertEqual(insurance_invoice.amount_total, 80.0)
        line = insurance_invoice.invoice_line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.account_id, insurance_invoice.journal_id.default_account_id)
        patient_invoice = insurance_invoice.insurance_sibling_invoice_id
        self.assertNotEqual(
            line.account_id, patient_invoice.invoice_line_ids.account_id,
            "the insurance invoice must not reuse the patient line's product income account",
        )

    def test_sale_order_insurance_invoice_button_count(self):
        order = self._insured_order()
        order.action_confirm()
        self.assertEqual(order.insurance_invoice_count, 0)  # button hidden until the invoice exists
        invoice = order._create_invoices()
        invoice.action_post()
        order.invalidate_recordset()
        self.assertEqual(order.insurance_invoice_count, 1)
        action = order.action_view_insurance_invoices()
        self.assertEqual(action["res_id"], invoice.insurance_sibling_invoice_id.id)

    # ------------------------------------------------------------------
    # claim payments
    # ------------------------------------------------------------------
    def test_payment_settles_oldest_invoice_first(self):
        newer = self._insurance_invoice(days_ago=10)
        older = self._insurance_invoice(days_ago=40)
        claim = self._submitted_claim()
        self.assertEqual(claim.total_claimed, 160.0)

        self._pay(claim, 100.0)
        self.assertEqual(older.amount_residual, 0.0, "the oldest invoice is settled first")
        self.assertEqual(newer.amount_residual, 60.0)
        self.assertEqual(claim.state, "partial_paid")
        self.assertEqual(claim.total_paid, 100.0)
        self.assertEqual(claim.remaining_balance, 60.0)
        self.assertEqual(claim.payment_count, 1)

        self._pay(claim, 60.0)
        self.assertEqual(newer.amount_residual, 0.0)
        self.assertEqual(claim.state, "paid")
        self.assertEqual(claim.remaining_balance, 0.0)

    def test_full_payment_in_one_go(self):
        self._insurance_invoice()
        claim = self._submitted_claim()
        self._pay(claim, 80.0)
        self.assertEqual(claim.state, "paid")

    # ------------------------------------------------------------------
    # rejections and credit notes
    # ------------------------------------------------------------------
    def test_partial_rejection_posts_credit_note_and_closes_balance(self):
        invoice = self._insurance_invoice()
        claim = self._submitted_claim()
        line = claim.claim_line_ids
        # saving a rejected amount books it straight away - no extra button
        line.write({"rejected_amount": 30.0, "rejection_reason": "Not covered"})

        self.assertTrue(line.rejection_move_id)
        self.assertEqual(line.rejection_move_id.move_type, "out_refund")
        self.assertEqual(invoice.amount_residual, 50.0)
        self.assertEqual(claim.total_rejected, 30.0)
        self.assertEqual(claim.remaining_balance, 50.0)
        self.assertEqual(claim.state, "submitted")

        # the payment wizard proposes what is really still owed
        defaults = self.env["insurance.claim.payment.wizard"].with_context(
            default_claim_id=claim.id
        ).default_get(["claim_id", "amount_to_pay", "memo"])
        self.assertEqual(defaults["amount_to_pay"], 50.0)

        self._pay(claim, 50.0)
        self.assertEqual(claim.state, "paid")
        self.assertEqual(claim.total_paid, 50.0)

    def test_booked_rejection_is_locked_and_can_be_undone(self):
        invoice = self._insurance_invoice()
        claim = self._submitted_claim()
        line = claim.claim_line_ids
        line.write({"rejected_amount": 30.0, "rejection_reason": "Not covered"})
        with self.assertRaises(UserError):
            line.write({"rejected_amount": 10.0})  # already booked

        line.action_cancel_rejection()
        self.assertFalse(line.rejection_move_id)
        self.assertEqual(line.rejected_amount, 0.0)
        self.assertEqual(invoice.amount_residual, 80.0)
        self.assertEqual(claim.remaining_balance, 80.0)

        line.write({"rejected_amount": 20.0})  # can be entered again
        self.assertEqual(claim.remaining_balance, 60.0)

    # ------------------------------------------------------------------
    # policies
    # ------------------------------------------------------------------
    def test_policy_status_buttons_and_renewal(self):
        policy = self.policy
        policy.action_suspend()
        self.assertEqual(policy.state, "suspended")
        self.assertFalse(policy.is_valid)
        policy.action_reactivate()
        self.assertEqual(policy.state, "active")

        policy.date_end = fields.Date.subtract(fields.Date.today(), days=5)
        policy.action_expire()
        with self.assertRaises(UserError):
            policy.action_reactivate()  # the expiry date has passed
        policy.action_renew()
        self.assertEqual(policy.state, "active")
        self.assertGreater(policy.date_end, fields.Date.today())
        self.assertTrue(policy.is_valid)

        policy.action_cancel()
        self.assertEqual(policy.state, "cancelled")

    def test_expiry_cron_expires_outdated_active_policies(self):
        self.policy.date_end = fields.Date.subtract(fields.Date.today(), days=1)
        self.env["insurance.policy"]._cron_expire_policies()
        self.assertEqual(self.policy.state, "expired")

    def test_policy_and_authorization_documents_render(self):
        data = self.policy._pdf_document_data()
        self.assertTrue(build_document_pdf(data).startswith(b"%PDF"))
        authorization = self.env["insurance.authorization"].create(
            {
                "partner_id": self.patient.id,
                "insurance_company_id": self.insurer.id,
                "requested_amount": 500.0,
                "requested_services": "Consultation",
            }
        )
        self.assertTrue(build_document_pdf(authorization._pdf_document_data()).startswith(b"%PDF"))
        self.assertIn("/mo_insurance_management/print/insurance.policy/", self.policy.action_print()["url"])

    def test_credit_note_after_submission_is_picked_up_by_refresh(self):
        invoice = self._insurance_invoice()
        claim = self._submitted_claim()
        self.assertFalse(claim.credit_notes_pending)

        invoice._reverse_moves([{"invoice_date": fields.Date.today()}], cancel=True)
        claim.invalidate_recordset()
        self.assertTrue(claim.credit_notes_pending)

        claim.action_refresh_credit_notes()
        self.assertFalse(claim.credit_notes_pending)
        self.assertEqual(claim.total_claimed, 0.0)

    # ------------------------------------------------------------------
    # reports
    # ------------------------------------------------------------------
    def test_report_wizard_builds_every_report(self):
        self._insurance_invoice(days_ago=45)
        claim = self._submitted_claim()
        self._pay(claim, 20.0)
        for report_type in ("claims", "coverage", "aging"):
            wizard = self.env["insurance.report.wizard"].create({"report_type": report_type})
            data = wizard._collect()
            self.assertTrue(data["rows"], f"{report_type} report returned no rows")
            for action in (wizard.action_print_pdf(), wizard.action_export_xlsx()):
                self.assertEqual(action["type"], "ir.actions.act_url")
        aging = self.env["insurance.report.wizard"].create({"report_type": "aging"})._collect()["rows"][0]
        self.assertEqual(aging["total"], 60.0)  # 80 invoice - 20 paid
        self.assertEqual(sum(aging[k] for k in ("current", "d30", "d60", "d90", "d90p")), 60.0)

    def test_module_does_not_hook_into_odoo_reports(self):
        """Odoo's own reports (invoices, orders...) must stay untouched: this
        module neither extends ir.actions.report nor defines report actions."""
        modules = {cls.__module__ for cls in type(self.env["ir.actions.report"]).__mro__}
        self.assertFalse([m for m in modules if m.startswith("odoo.addons.mo_insurance_management")])
        self.assertFalse(
            self.env["ir.actions.report"].search([("report_name", "like", "mo_insurance_management.")])
        )

    def test_claim_statement_is_a_reportlab_pdf(self):
        self._insurance_invoice()
        claim = self._submitted_claim()
        pdf = ClaimStatement(self.env).render(claim)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(claim.action_print_statement()["url"], f"/mo_insurance_management/claim_statement/{claim.id}")

    def test_dashboard_data_has_all_widgets(self):
        self._insurance_invoice(days_ago=45)
        claim = self._submitted_claim()
        self._pay(claim, 20.0)
        data = self.env["insurance.dashboard"].get_dashboard_data()
        for key in ("claim_status", "coverage_split", "aging", "snapshot", "top_products", "top_patients", "recent_claims"):
            self.assertIn(key, data)
        self.assertEqual(data["aging"]["snapshot"]["open_amount"], 60.0)
        self.assertEqual(len(data["aging"]["labels"]), len(data["aging"]["domains"]))
        self.assertTrue(data["recent_claims"])
        for key in ("total_rejected", "avg_order_value", "patients_count", "claims_count"):
            self.assertIn(key, data["kpis"])

    def test_dashboard_pages_only_load_their_own_widgets(self):
        self._insurance_invoice(days_ago=45)
        dashboard = self.env["insurance.dashboard"]
        cards = dashboard.get_dashboard_data(mode="cards")
        charts = dashboard.get_dashboard_data(mode="charts")
        for key in ("kpis", "snapshot", "aging", "sales_trend"):  # shared by both pages
            self.assertIn(key, cards)
            self.assertIn(key, charts)
        for key in ("kpi_deltas", "recent_claims", "top_patients"):
            self.assertIn(key, cards)
            self.assertNotIn(key, charts)
        for key in ("claim_status", "coverage_split", "top_products", "outstanding_by_company",
                    "top_companies", "top_plans"):
            self.assertIn(key, charts)
            self.assertNotIn(key, cards)

    # ------------------------------------------------------------------
    # permissions
    # ------------------------------------------------------------------
    def test_sales_user_without_insurance_group_can_still_work_with_insured_orders(self):
        user = mail_new_test_user(
            self.env,
            login="plain_salesman",
            name="Plain Salesman",
            groups="base.group_user,sales_team.group_sale_salesman",
        )
        self.assertFalse(user.has_group("mo_insurance_management.group_insurance_user"))

        order = self._insured_order(env=self.env(user=user))
        self.assertEqual(order.order_line.insurance_amount, 80.0)
        used_before = self.policy.coverage_used
        order.action_confirm()  # writes the policy's used coverage - must not raise AccessError
        self.assertEqual(order.state, "sale")
        self.assertEqual(self.policy.coverage_used, used_before + 80.0)

        # ... but the insurance management side stays closed to them
        with self.assertRaises(AccessError):
            self.env["insurance.claim"].with_user(user).search([])
        root_menu = self.env.ref("mo_insurance_management.menu_insurance_root")
        self.assertFalse(self.env["ir.ui.menu"].with_user(user).search([("id", "=", root_menu.id)]))

    def test_accountant_without_insurance_group_can_open_insured_invoices(self):
        insurance_invoice = self._insurance_invoice()
        accountant = mail_new_test_user(
            self.env,
            login="plain_accountant",
            name="Plain Accountant",
            groups="base.group_user,account.group_account_invoice",
        )
        move = insurance_invoice.with_user(accountant)
        move.read(["name", "amount_total", "insurance_claim_count", "insurance_customer_product_line_ids"])
        move.insurance_sibling_invoice_id.read(["name", "insurance_claim_count"])
