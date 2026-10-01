/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class ProjectProfitabilityReport extends Component {
    static template = "construction_project_budget.ProfitabilityReport";

    setup() {
        this.orm = useService("orm");

        this.state = useState({
            loading: true,
            projectOptions: [],
            filters: {
                project_id: null,
                date_from: "",
                date_to: "",
            },
            data: null,
            expandedSections: {},
        });

        onWillStart(async () => {
            await this.loadProjects();
            await this.loadReport();
        });
    }

    async loadProjects() {
        const projects = await this.orm.searchRead(
            "project.project",
            [["budget_id", "!=", false]],
            ["id", "display_name"]
        );
        this.state.projectOptions = projects;
    }

    async loadReport() {
        this.state.loading = true;
        const data = await this.orm.call(
            "construction.project.budget",
            "get_profitability_data",
            [],
            {
                project_id: this.state.filters.project_id || false,
                date_from: this.state.filters.date_from || false,
                date_to: this.state.filters.date_to || false,
            }
        );
        this.state.data = data;
        this.state.expandedSections = {};
        this.state.loading = false;
    }

    onProjectChange(ev) {
        const val = ev.target.value;
        this.state.filters.project_id = val ? parseInt(val, 10) : null;
        this.loadReport();
    }

    onDateChange(field, ev) {
        this.state.filters[field] = ev.target.value;
        this.loadReport();
    }

    toggleSection(label) {
        this.state.expandedSections[label] = !this.state.expandedSections[label];
    }

    isExpanded(label) {
        return !!this.state.expandedSections[label];
    }

    toggleGroup(label) {
        const key = "grp:" + label;
        this.state.expandedSections[key] = !this.state.expandedSections[key];
    }

    isGroupExpanded(label) {
        return !!this.state.expandedSections["grp:" + label];
    }

    formatMonetary(value) {
        const rounded = Math.round((value || 0) * 100) / 100;
        const formatted = rounded.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
        const symbol = this.state.data ? this.state.data.currency_symbol : "";
        if (this.state.data && this.state.data.currency_position === "before") {
            return `${symbol}${formatted}`;
        }
        return `${formatted} ${symbol}`;
    }

    formatPercent(value) {
        return (Math.round((value || 0) * 10) / 10).toFixed(1);
    }

    printPdf() {
        const params = new URLSearchParams();
        if (this.state.filters.project_id) {
            params.set("project_id", this.state.filters.project_id);
        }
        if (this.state.filters.date_from) {
            params.set("date_from", this.state.filters.date_from);
        }
        if (this.state.filters.date_to) {
            params.set("date_to", this.state.filters.date_to);
        }
        window.open("/construction_project_budget/profitability_report.pdf?" + params.toString(), "_blank");
    }
}

registry.category("actions").add(
    "construction_project_profitability_report",
    ProjectProfitabilityReport
);
