/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const STATE_COLORS = {
    draft: "secondary", department: "info", warehouse: "info", budget: "warning",
    approved: "success", processing: "primary", partial: "warning",
    closed: "success", rejected: "danger", cancelled: "dark",
};

export class EmployeeRequestDashboard extends Component {
    static template = "mo_employee_request.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            data: { actions: { chips: [], items: [], total: 0 }, tiles: [], by_state: [], recent: [], departments: [], sections: [], periods: [], total: 0 },
            filters: { period: "all", department_id: false, only_mine: false, date_from: "", date_to: "" },
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        const filters = { ...this.state.filters };
        this.state.data = await this.orm.call("employee.request", "get_dashboard_data", [filters]);
        this.state.loading = false;
    }

    get hasActiveFilters() {
        const f = this.state.filters;
        return f.period !== "all" || f.department_id || f.only_mine;
    }

    tilesOf(section) {
        return this.state.data.tiles.filter((t) => t.section === section);
    }

    stateColor(state) {
        return STATE_COLORS[state] || "secondary";
    }

    barWidth(item) {
        const total = this.state.data.total || 1;
        return Math.max((100 * item.count) / total, 3);
    }

    onPeriod(ev) {
        this.state.filters.period = ev.target.value;
        if (this.state.filters.period !== "custom") {
            this.load();
        }
    }
    onDateFrom(ev) {
        this.state.filters.date_from = ev.target.value;
        this.load();
    }
    onDateTo(ev) {
        this.state.filters.date_to = ev.target.value;
        this.load();
    }
    onDepartment(ev) {
        this.state.filters.department_id = parseInt(ev.target.value) || false;
        this.load();
    }
    onOnlyMine(ev) {
        this.state.filters.only_mine = ev.target.checked;
        this.load();
    }
    resetFilters() {
        this.state.filters = { period: "all", department_id: false, only_mine: false, date_from: "", date_to: "" };
        this.load();
    }

    open(item) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: item.label,
            res_model: item.model || "employee.request",
            views: [[false, "list"], [false, "form"]],
            domain: item.domain,
        });
    }

    openItem(item) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: item.model,
            res_id: item.id,
            views: [[false, "form"]],
        });
    }

    openRequest(rec) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "employee.request",
            res_id: rec.id,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("mo_employee_request.dashboard", EmployeeRequestDashboard);
