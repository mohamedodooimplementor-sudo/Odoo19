# -*- coding: utf-8 -*-
"""Shared fixtures for the insurance tests."""
from odoo import Command, fields
from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class InsuranceCommon(AccountTestInvoicingCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.sale_journal = cls.company_data["default_journal_sale"]
        cls.bank_journal = cls.company_data["default_journal_bank"]
        cls.company.insurance_default_payment_journal_id = cls.bank_journal
        cls.company.insurance_rejection_account_id = cls.company_data["default_account_expense"]

        # An income account for the PRODUCT that differs from the journal's
        # default account, to prove the insurance invoice does not reuse it.
        cls.product_income = cls.env["account.account"].create(
            {"name": "Product Income (test)", "code": "499999", "account_type": "income"}
        )
        cls.product = cls.env["product.product"].create(
            {
                "name": "Consultation",
                "type": "service",
                "list_price": 100.0,
                "property_account_income_id": cls.product_income.id,
                "taxes_id": [Command.clear()],
            }
        )

        cls.insurer_partner = cls.env["res.partner"].create({"name": "Test Insurer"})
        cls.insurer = cls.env["insurance.company"].create(
            {"name": "Test Insurer", "code": "TI", "partner_id": cls.insurer_partner.id}
        )
        cls.plan = cls.env["insurance.plan"].create(
            {
                "name": "Gold",
                "code": "GOLD",
                "insurance_company_id": cls.insurer.id,
                "default_coverage_percentage": 80.0,
            }
        )
        cls.patient = cls.env["res.partner"].create({"name": "Test Patient"})
        cls.policy = cls.env["insurance.policy"].create(
            {
                "partner_id": cls.patient.id,
                "insurance_company_id": cls.insurer.id,
                "plan_id": cls.plan.id,
                "policy_number": "POL-1",
                "state": "active",
                "is_primary": True,
            }
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _insured_order(self, env=None):
        env = env or self.env
        return env["sale.order"].create(
            {
                "partner_id": self.patient.id,
                "insurance_enabled": True,
                "insurance_policy_id": self.policy.id,
                "order_line": [
                    Command.create({"product_id": self.product.id, "product_uom_qty": 1, "price_unit": 100.0})
                ],
            }
        )

    def _insurance_invoice(self, days_ago=0):
        """Confirm + invoice + post an insured order; return the insurance
        company's invoice (80 of the 100, given 80% coverage)."""
        order = self._insured_order()
        order.action_confirm()
        invoice = order._create_invoices()
        invoice.invoice_date = fields.Date.subtract(fields.Date.today(), days=days_ago)
        invoice.action_post()
        return invoice.insurance_sibling_invoice_id

    def _submitted_claim(self):
        claim = self.env["insurance.claim"].create(
            {
                "insurance_company_id": self.insurer.id,
                "date_from": fields.Date.subtract(fields.Date.today(), days=90),
                "date_to": fields.Date.today(),
                "journal_id": self.bank_journal.id,
            }
        )
        claim.action_submit()
        return claim

    def _pay(self, claim, amount):
        wizard = self.env["insurance.claim.payment.wizard"].create(
            {"claim_id": claim.id, "amount_to_pay": amount, "journal_id": self.bank_journal.id}
        )
        wizard.action_confirm()

