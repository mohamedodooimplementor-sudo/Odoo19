/** @odoo-module **/

import { Component, useState, useRef, onWillStart, onMounted, onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class BranchSalesDashboard extends Component {
    static template = "branch_management.BranchSalesDashboard";

    setup() {
        this.orm = useService("orm");
        this.root = useRef("root");

        this.state = useState({
            filters: {
                date_from: this.getDefaultDateFrom(),
                date_to: this.getDefaultDateTo(),
                branch_id: false,
                partner_id: false,
                user_id: false,
            },
            branches: [],
            partners: [],
            users: [],
            data: { lines: [], totals: {} },
        });

        onWillStart(async () => {
            await this.loadFilterOptions();
            await this.loadData();
        });

        onMounted(() => this.drawChart());
        onPatched(() => this.drawChart());
    }

    getDefaultDateFrom() {
        const d = new Date();
        d.setDate(1);
        return d.toISOString().slice(0, 10);
    }

    getDefaultDateTo() {
        return new Date().toISOString().slice(0, 10);
    }

    async loadFilterOptions() {
        this.state.branches = await this.orm.searchRead("res.branch", [], ["id", "name"]);
        this.state.partners = await this.orm.searchRead(
            "res.partner", [["customer_rank", ">", 0]], ["id", "name"], { limit: 200 });
        this.state.users = await this.orm.searchRead("res.users", [], ["id", "name"]);
    }

    async loadData() {
        const f = this.state.filters;
        const data = await this.orm.call("branch.sales.report", "get_dashboard_data", [], {
            date_from: f.date_from || false,
            date_to: f.date_to || false,
            branch_id: f.branch_id || false,
            partner_id: f.partner_id || false,
            user_id: f.user_id || false,
        });
        this.state.data = data;
    }

    onFilterChange(field, ev) {
        const raw = ev.target.value;
        if (!raw) {
            this.state.filters[field] = false;
        } else if (field === "date_from" || field === "date_to") {
            this.state.filters[field] = raw;
        } else {
            this.state.filters[field] = parseInt(raw, 10);
        }
    }

    onApply() {
        this.loadData();
    }

    formatMoney(value) {
        return (value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    drawChart() {
        const canvas = this.root.el && this.root.el.querySelector(".branch_pie_chart");
        if (!canvas) {
            return;
        }
        const ctx = canvas.getContext("2d");
        const lines = this.state.data.lines || [];
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        const total = lines.reduce((sum, l) => sum + l.sales_amount, 0);
        if (!total) {
            return;
        }
        const colors = ["#4a3aff", "#ff8c3a", "#3ac96a", "#ff3a5e", "#3ac9c9", "#c93aff", "#ffd23a"];
        let start = -Math.PI / 2;
        const cx = canvas.width / 2;
        const cy = canvas.height / 2;
        const radius = Math.min(cx, cy) - 4;
        lines.forEach((line, index) => {
            const slice = (line.sales_amount / total) * 2 * Math.PI;
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.arc(cx, cy, radius, start, start + slice);
            ctx.closePath();
            ctx.fillStyle = colors[index % colors.length];
            ctx.fill();
            start += slice;
        });
    }

    getColor(index) {
        const colors = ["#4a3aff", "#ff8c3a", "#3ac96a", "#ff3a5e", "#3ac9c9", "#c93aff", "#ffd23a"];
        return colors[index % colors.length];
    }

    getExportUrl(kind) {
        const f = this.state.filters;
        const params = new URLSearchParams();
        if (f.date_from) params.append("date_from", f.date_from);
        if (f.date_to) params.append("date_to", f.date_to);
        if (f.branch_id) params.append("branch_id", f.branch_id);
        if (f.partner_id) params.append("partner_id", f.partner_id);
        if (f.user_id) params.append("user_id", f.user_id);
        return `/branch_management/export_${kind}?${params.toString()}`;
    }

    onExportExcel() {
        window.open(this.getExportUrl("xlsx"), "_blank");
    }

    onExportPdf() {
        window.open(this.getExportUrl("pdf"), "_blank");
    }
}

registry.category("actions").add("branch_sales_dashboard", BranchSalesDashboard);
