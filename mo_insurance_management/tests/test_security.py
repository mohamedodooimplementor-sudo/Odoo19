# -*- coding: utf-8 -*-
"""Security regression tests: every hole closed in the pre-go-live review has
a test here so it cannot silently come back."""
import zipfile
from io import BytesIO

from odoo import Command, fields
from odoo.addons.insurance_management.report.report_builders import build_xlsx
from odoo.addons.mail.tests.common import mail_new_test_user
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import InsuranceCommon


@tagged("post_install", "-at_install")
class TestInsuranceSecurity(InsuranceCommon):
    # ------------------------------------------------------------------
    # business-logic integrity
    # ------------------------------------------------------------------
    def test_another_customers_policy_cannot_be_used_on_an_order(self):
        stranger = self.env["res.partner"].create({"name": "Someone Else"})
        order = self.env["sale.order"].create({"partner_id": stranger.id})
        with self.assertRaises(ValidationError):
            order.write({"insurance_enabled": True, "insurance_policy_id": self.policy.id})

    def test_values_typed_into_insurance_fields_do_not_survive_confirmation(self):
        order = self._insured_order()
        order.order_line.write({"insurance_amount": 100.0, "customer_copay_amount": 0.0})  # tampering
        order.action_confirm()
        self.assertEqual(order.order_line.insurance_amount, 80.0)

    def test_payment_can_only_be_linked_to_its_own_insurers_claim(self):
        self._insurance_invoice()
        claim = self._submitted_claim()
        other = self.env["res.partner"].create({"name": "Not The Insurer"})
        with self.assertRaises(ValidationError):
            self.env["account.payment"].create(
                {
                    "payment_type": "inbound",
                    "partner_type": "customer",
                    "partner_id": other.id,
                    "amount": 10.0,
                    "journal_id": self.bank_journal.id,
                    "insurance_claim_id": claim.id,
                }
            )

    def test_payment_wizard_rejects_a_non_bank_journal(self):
        self._insurance_invoice()
        claim = self._submitted_claim()
        wizard = self.env["insurance.claim.payment.wizard"].create(
            {"claim_id": claim.id, "amount_to_pay": 10.0, "journal_id": self.sale_journal.id}
        )
        with self.assertRaises(UserError):
            wizard.action_confirm()

    # ------------------------------------------------------------------
    # accounting trail cannot be deleted
    # ------------------------------------------------------------------
    def test_submitted_claim_and_used_policy_cannot_be_deleted(self):
        self._insurance_invoice()
        claim = self._submitted_claim()
        with self.assertRaises(UserError):
            claim.unlink()
        with self.assertRaises(UserError):
            claim.claim_line_ids.unlink()
        order = self._insured_order()
        order.action_confirm()
        with self.assertRaises(UserError):
            self.policy.unlink()

    # ------------------------------------------------------------------
    # who may call what
    # ------------------------------------------------------------------
    def test_dashboard_rpc_is_closed_to_users_without_an_insurance_group(self):
        plain = mail_new_test_user(
            self.env, login="dash_plain", name="Dash Plain",
            groups="base.group_user,sales_team.group_sale_salesman",
        )
        dashboard = self.env["insurance.dashboard"].with_user(plain)
        with self.assertRaises(AccessError):
            dashboard.get_dashboard_data()
        with self.assertRaises(AccessError):
            dashboard.get_filters_meta()

    def test_booking_a_rejection_needs_an_accounting_group(self):
        self._insurance_invoice()
        claim = self._submitted_claim()
        clerk = mail_new_test_user(
            self.env, login="claims_clerk", name="Claims Clerk",
            groups="base.group_user,insurance_management.group_insurance_officer",
        )
        self.assertFalse(clerk.has_group("account.group_account_invoice"))
        with self.assertRaises(AccessError):
            claim.with_user(clerk).claim_line_ids.write({"rejected_amount": 10.0})

    # ------------------------------------------------------------------
    # exports
    # ------------------------------------------------------------------
    def test_excel_export_never_turns_data_into_formulas_or_links(self):
        hostile = ['=HYPERLINK("http://evil.example","x")', "=cmd|' /C calc'!A0", "@SUM(1)", "https://evil.example"]
        data = {
            "title": "T", "company": "=BAD()", "currency": "EGP", "generated": "x", "user": "u",
            "rtl": False, "sheet_name": "S", "filters": [("=F", "=G")],
            "columns": [{"key": "name", "label": "=Label", "kind": "text", "width": 30}],
            "rows": [{"name": value} for value in hostile], "sheets": [],
        }
        book = zipfile.ZipFile(BytesIO(build_xlsx(data)))
        sheet_xml = book.read("xl/worksheets/sheet1.xml")
        self.assertNotIn(b"<f>", sheet_xml)  # no formula cell at all
        self.assertNotIn(b"hyperlink", sheet_xml.lower())

    # ------------------------------------------------------------------
    # counter role / personal data
    # ------------------------------------------------------------------
    def _policy_vals(self, number):
        return {
            "partner_id": self.patient.id,
            "insurance_company_id": self.insurer.id,
            "plan_id": self.plan.id,
            "policy_number": number,
            "state": "active",
        }

    def test_counter_role_cannot_create_policies_but_officer_can(self):
        counter = mail_new_test_user(
            self.env, login="counter_user", name="Counter",
            groups="base.group_user,insurance_management.group_insurance_user",
        )
        officer = mail_new_test_user(
            self.env, login="officer_user", name="Officer",
            groups="base.group_user,insurance_management.group_insurance_officer",
        )
        with self.assertRaises(AccessError):
            self.env["insurance.policy"].with_user(counter).create(self._policy_vals("POL-COUNTER"))
        self.assertTrue(self.env["insurance.policy"].with_user(officer).create(self._policy_vals("POL-OFFICER")))

    def test_personal_policy_data_is_hidden_from_sales_and_billing_users(self):
        self.policy.write({"member_id": "M-123", "card_number": "C-456", "notes": "private"})
        order = self._insured_order()
        for login, groups in (
            ("pii_sales", "base.group_user,sales_team.group_sale_salesman"),
            ("pii_billing", "base.group_user,account.group_account_invoice"),
        ):
            user = mail_new_test_user(self.env, login=login, name=login, groups=groups)
            policy = self.policy.with_user(user)
            self.assertEqual(policy.read(["policy_number"])[0]["policy_number"], "POL-1")  # can still pick it
            for field_name in ("member_id", "card_number", "notes"):
                with self.assertRaises(AccessError, msg=f"{login} must not read {field_name}"):
                    policy.read([field_name])
        sales = mail_new_test_user(
            self.env, login="pii_sales2", name="s2", groups="base.group_user,sales_team.group_sale_salesman"
        )
        with self.assertRaises(AccessError):
            order.with_user(sales).read(["insurance_member_id"])
        counter = mail_new_test_user(
            self.env, login="pii_counter", name="c",
            groups="base.group_user,insurance_management.group_insurance_user",
        )
        self.assertEqual(self.policy.with_user(counter).read(["member_id"])[0]["member_id"], "M-123")

    # ------------------------------------------------------------------
    # automatic, editable codes
    # ------------------------------------------------------------------
    def test_company_and_plan_codes_are_generated_and_can_be_changed(self):
        partner = self.env["res.partner"].create({"name": "Auto Code Insurer"})
        company = self.env["insurance.company"].create({"name": "Auto Code Insurer", "partner_id": partner.id})
        self.assertTrue(company.code.startswith("INS"), company.code)
        other = self.env["insurance.company"].create(
            {"name": "Second", "partner_id": partner.id, "code": "MY-CODE"}
        )
        self.assertEqual(other.code, "MY-CODE")  # typed by hand: kept
        company.code = "CHANGED"  # and any generated code can be edited later
        self.assertEqual(company.code, "CHANGED")
        plan = self.env["insurance.plan"].create(
            {"name": "Auto Plan", "insurance_company_id": company.id, "default_coverage_percentage": 50.0}
        )
        self.assertTrue(plan.code.startswith("PLN"), plan.code)
        plan_two = self.env["insurance.plan"].create(
            {"name": "Auto Plan 2", "insurance_company_id": company.id, "default_coverage_percentage": 50.0}
        )
        self.assertNotEqual(plan.code, plan_two.code)

    # ------------------------------------------------------------------
    # no hook of any kind into Odoo's own reports
    # ------------------------------------------------------------------
    def test_module_has_no_wkhtmltopdf_or_report_engine_hook(self):
        self.assertNotIn("insurance.system.setup", self.env.registry)
        modules = {cls.__module__ for cls in type(self.env["ir.actions.report"]).__mro__}
        self.assertFalse([m for m in modules if m.startswith("odoo.addons.insurance_management")])
        self.assertFalse(
            self.env["ir.actions.report"].search([("report_name", "like", "insurance_management.")])
        )

