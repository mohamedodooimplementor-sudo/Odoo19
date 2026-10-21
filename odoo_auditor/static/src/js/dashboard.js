/** @odoo-module **/
import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

const SEVERITY_ORDER = ["critical", "high", "medium", "low", "informational"];

export class AuditorDashboard extends Component {
    static template = "odoo_auditor.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null });
        onWillStart(async () => {
            this.state.data = await this.orm.call("odoo.auditor.finding", "get_dashboard_data", []);
        });
    }

    get severityLabels() {
        return {
            critical: _t("Critical"), high: _t("High"), medium: _t("Medium"),
            low: _t("Low"), informational: _t("Informational"),
        };
    }

    get domainLabels() {
        return {
            financial: _t("Financial"), inventory: _t("Inventory"), sales: _t("Sales"), purchase: _t("Purchase"),
            hr: _t("HR"), manufacturing: _t("Manufacturing"), access: _t("Access"), other: _t("Other"),
        };
    }

    get openLabel() {
        return _t("Open findings");
    }

    get severities() {
        const labels = this.severityLabels;
        return SEVERITY_ORDER.map((key) => ({ key, label: labels[key], count: this.state.data.severity[key] || 0 }));
    }

    get domains() {
        const labels = this.domainLabels;
        return this.state.data.domains.map((d) => ({ ...d, label: labels[d.key] || d.key }));
    }

    get maxSeverity() {
        return Math.max(1, ...this.severities.map((s) => s.count));
    }

    barWidth(value, max) {
        return Math.round((value / max) * 100) + "%";
    }

    openFindings(name, domain) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: "odoo.auditor.finding",
            views: [[false, "list"], [false, "form"]],
            domain,
        });
    }

    openSeverity(key) {
        this.openFindings(this.severityLabels[key], [["severity", "=", key], ["state", "not in", ["closed", "rejected"]]]);
    }

    openDomain(key) {
        this.openFindings(this.domainLabels[key] || key, [["domain_area", "=", key], ["state", "not in", ["closed", "rejected"]]]);
    }

    openRule(id) {
        this.openFindings(_t("Rule findings"), [["rule_id", "=", id], ["state", "not in", ["closed", "rejected"]]]);
    }

    openOverdueActions() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Overdue Actions"),
            res_model: "odoo.auditor.action",
            views: [[false, "list"], [false, "form"]],
            domain: [["is_overdue", "=", true]],
        });
    }

    openRun(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "odoo.auditor.run",
            res_id: id,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("odoo_auditor.dashboard", AuditorDashboard);
