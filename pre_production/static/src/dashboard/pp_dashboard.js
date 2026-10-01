/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";
import { Component, onWillStart, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";

const EMPTY = {
    date_from: "", date_to: "", partner_id: "", product_id: "", warehouse_id: "",
    stage_id: "", state: "", sale_order: "", lot: "",
};
const PALETTE = ["#714B67", "#0d6efd", "#20c997", "#fd7e14", "#dc3545", "#6f42c1", "#0dcaf0", "#198754", "#ffc107", "#6c757d"];

export class PPDashboard extends Component {
    static template = "pre_production.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null, filters: { ...EMPTY } });
        this.charts = {};
        this.refs = {
            stage: useRef("c_stage"), duration: useRef("c_duration"), quality: useRef("c_quality"), issue: useRef("c_issue"),
            product: useRef("c_product"), warehouse: useRef("c_warehouse"),
        };
        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            await this.load();
        });
        this.rootRef = useRef("root");
        onMounted(() => {
            this.applyTheme();
            this.drawCharts();
        });
        onWillUnmount(() => Object.values(this.charts).forEach((c) => c.destroy()));
    }

    // The dashboard follows the web client theme: detect a dark client from the colour of its text.
    applyTheme() {
        const root = this.rootRef.el;
        if (!root) { return; }
        const m = getComputedStyle(document.body).color.match(/[\d.]+/g) || [33, 37, 41];
        const luminance = 0.299 * m[0] + 0.587 * m[1] + 0.114 * m[2];
        root.classList.toggle("pp_dark", luminance > 150);
    }

    isSel(key, id) {
        return String(id) === this.state.filters[key];
    }

    async load() {
        this.state.data = await this.orm.call("pp.dashboard", "get_data", [], { filters: { ...this.state.filters } });
    }

    async onFilter(key, ev) {
        this.state.filters[key] = ev.target.value;
        await this.load();
        this.drawCharts();
    }

    async resetFilters() {
        Object.assign(this.state.filters, EMPTY);
        await this.load();
        this.drawCharts();
    }

    openKpi(kpi) {
        this.action.doAction({
            type: "ir.actions.act_window", name: kpi.label, res_model: "pp.order",
            views: [[false, "list"], [false, "form"]], domain: kpi.domain,
        });
    }

    drawCharts() {
        const c = this.state.data.charts;
        const specs = {
            stage: { type: "bar", label: "Orders", colors: PALETTE[0] },
            duration: { type: "bar", label: "Avg. Hours", colors: PALETTE[3], precision: 1 },
            quality: { type: "doughnut", colors: ["#198754", "#dc3545", "#ffc107"] },
            issue: { type: "doughnut", colors: ["#fd7e14", "#198754"] },
            product: { type: "bar", label: "Orders", colors: PALETTE[1], horizontal: true },
            warehouse: { type: "pie", colors: PALETTE },
        };
        for (const [key, spec] of Object.entries(specs)) {
            const el = this.refs[key].el;
            if (!el) { continue; }
            // follow the current (light / dark) theme
            const textColor = getComputedStyle(el).color;
            const gridColor = "rgba(128, 128, 128, 0.25)";
            if (this.charts[key]) { this.charts[key].destroy(); }
            const isBar = spec.type === "bar";
            this.charts[key] = new Chart(el, {
                type: spec.type,
                data: {
                    labels: c[key].labels,
                    datasets: [{ label: spec.label, data: c[key].values, backgroundColor: spec.colors, borderWidth: 0 }],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    indexAxis: spec.horizontal ? "y" : "x",
                    plugins: { legend: { display: !isBar, position: "bottom", labels: { color: textColor } } },
                    scales: isBar ? {
                        x: { beginAtZero: true, ticks: { precision: spec.precision ?? 0, color: textColor }, grid: { color: gridColor } },
                        y: { beginAtZero: true, ticks: { precision: spec.precision ?? 0, color: textColor }, grid: { color: gridColor } },
                    } : {},
                },
            });
        }
    }
}

registry.category("actions").add("pre_production.dashboard", PPDashboard);
