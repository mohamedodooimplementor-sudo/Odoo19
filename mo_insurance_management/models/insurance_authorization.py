# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class InsuranceAuthorization(models.Model):
    _name = "insurance.authorization"
    _description = "Insurance Authorization"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    name = fields.Char(string="Authorization Number", required=True, copy=False, default="New")
    partner_id = fields.Many2one("res.partner", string="Customer", required=True, tracking=True)
    insurance_company_id = fields.Many2one("insurance.company", string="Insurance Company", required=True)
    insurance_plan_id = fields.Many2one(
        "insurance.plan",
        string="Insurance Plan",
        domain="[('insurance_company_id', '=', insurance_company_id)]",
    )
    sale_order_id = fields.Many2one("sale.order", string="Related Sales Order")

    requested_services = fields.Text(string="Requested Services")
    requested_amount = fields.Monetary(string="Requested Amount")
    approved_amount = fields.Monetary(string="Approved Amount")

    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id
    )

    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("requested", "Requested"),
            ("pending", "Pending"),
            ("approved", "Approved"),
            ("partially_approved", "Partially Approved"),
            ("rejected", "Rejected"),
            ("expired", "Expired"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )

    request_date = fields.Date(default=fields.Date.context_today)
    approval_date = fields.Date()
    expiry_date = fields.Date()
    notes = fields.Text()

    def action_open_sale_order(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Sales Order",
            "res_model": "sale.order",
            "view_mode": "form",
            "res_id": self.sale_order_id.id,
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "New") == "New":
                vals["name"] = self.env["ir.sequence"].next_by_code("insurance.authorization") or "New"
        return super().create(vals_list)

    def action_request(self):
        self.write({"state": "requested"})

    def action_set_pending(self):
        self.write({"state": "pending"})

    def action_approve(self):
        """Approve the authorization. Set ``approved_amount`` on the record
        before clicking Approve to record a partial approval; if left at
        0 it defaults to the full ``requested_amount``."""
        for rec in self:
            amount = rec.approved_amount or rec.requested_amount
            if amount < rec.requested_amount:
                rec.write({"state": "partially_approved", "approved_amount": amount})
            else:
                rec.write({"state": "approved", "approved_amount": amount})
            rec.approval_date = fields.Date.context_today(rec)

    def action_reject(self):
        self.write({"state": "rejected", "approved_amount": 0.0})

    def action_cancel(self):
        for rec in self:
            if rec.state in ("approved", "partially_approved"):
                raise UserError("Cannot cancel an Authorization that has already been approved and used.")
            rec.state = "cancelled"

    @api.constrains("expiry_date", "request_date")
    def _check_dates(self):
        for rec in self:
            if rec.expiry_date and rec.request_date and rec.expiry_date < rec.request_date:
                raise UserError("Expiry Date cannot be before the Request Date.")

    def unlink(self):
        for rec in self:
            if rec.state in ("approved", "partially_approved") or rec.sale_order_id:
                raise UserError(
                    f"Authorization {rec.name} has been approved or is linked to an order; "
                    "cancel it instead of deleting it."
                )
        return super().unlink()

    # ------------------------------------------------------------------
    # Printing
    # ------------------------------------------------------------------
    def action_print(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_url",
            "url": f"/mo_insurance_management/print/{self._name}/{self.id}",
            "target": "self",
        }

    def _pdf_document_data(self):
        self.ensure_one()
        env = self.env
        company = env.company
        currency = self.currency_id.name or company.currency_id.name or ""
        states = dict(self._fields["state"].selection)
        colors = {
            "approved": "#16A34A",
            "partially_approved": "#D97706",
            "rejected": "#DC2626",
            "cancelled": "#DC2626",
        }

        def money(value):
            return f"{value:,.2f}"

        return {
            "filename": f"Insurance Authorization - {self.name}.pdf".replace("/", "-"),
            "company": company.name,
            "title": "Insurance Authorization",
            "subtitle": self.name,
            "status": (states.get(self.state, self.state), colors.get(self.state, "#64748B")),
            "currency": currency,
            "generated": fields.Datetime.to_string(fields.Datetime.context_timestamp(self, fields.Datetime.now())),
            "user": env.user.name,
            "sections": [
                {
                    "title": "Customer & Insurance",
                    "rows": [
                        ("Customer", self.partner_id.display_name),
                        ("Insurance Company", self.insurance_company_id.display_name),
                        ("Plan", self.insurance_plan_id.display_name),
                        ("Related Sales Order", self.sale_order_id.name),
                    ],
                },
                {
                    "title": "Dates",
                    "rows": [
                        ("Request Date", str(self.request_date or "")),
                        ("Approval Date", str(self.approval_date or "")),
                        ("Expiry Date", str(self.expiry_date or "")),
                    ],
                },
                {
                    "title": f"Amounts ({currency})",
                    "rows": [
                        ("Requested Amount", money(self.requested_amount)),
                        ("Approved Amount", money(self.approved_amount)),
                    ],
                },
            ],
            "texts": [("Requested Services", self.requested_services), ("Notes", self.notes)],
            "signatures": ["Requested by", "Approved by (Insurance Company)"],
        }
