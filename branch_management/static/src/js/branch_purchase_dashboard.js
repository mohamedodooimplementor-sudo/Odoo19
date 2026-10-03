/** @odoo-module **/

import { Component, useState, useRef, onWillStart, onMounted, onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const COLORS = ["#6C3EF4", "#FF6B35", "#00B894", "#FF3D71", "#00C2D1", "#FFC93C", "#8E44FF"];

export class BranchPurchaseDashboard extends Component {
    static template = "branch_management.BranchPurchaseDashboard";

    setup() {
        this.orm = useService("orm");
        this.root = useRef("root");
        this.state = useState({
            filters: { date_from: false, date_to: false, branch_id: "", partner_id: "" },
            branches: [],
            partners: [],
            data: { lines: [], totals: {} },
        });
        onWillStart(async () => {
            this.state.branches = await this.orm.searchRead("res.branch", [], ["id", "name"]);
            this.state.partners = await this.orm.searchRead(
                "res.partner", [["supplier_rank", ">", 0]], ["id", "name"], { limit: 200 });
            await this.loadData();
        });
        onMounted(() => this.drawChart());
        onPatched(() => this.drawChart());
    }

    async loadData() {
        const f = this.state.filters;
        this.state.data = await this.orm.call("branch.purchase.report", "get_dashboard_data", [], {
            date_from: f.date_from || false,
            date_to: f.date_to || false,
            branch_id: f.branch_id ? parseInt(f.branch_id) : false,
            partner_id: f.partner_id ? parseInt(f.partner_id) : false,
        });
    }

    onFilterChange(field, ev) {
        this.state.filters[field] = ev.target.value || false;
    }

    onApply() {
        this.loadData();
    }

    getExportParams() {
        const f = this.state.filters;
        const params = new URLSearchParams();
        if (f.date_from) params.set('date_from', f.date_from);
        if (f.date_to) params.set('date_to', f.date_to);
        if (f.branch_id) params.set('branch_id', f.branch_id);
        if (f.partner_id) params.set('partner_id', f.partner_id);
        return params.toString();
    }

    onExportExcel() {
        window.open(`/branch_management/purchase/export_xlsx?${this.getExportParams()}`, '_blank');
    }

    onExportPdf() {
        window.open(`/branch_management/purchase/export_pdf?${this.getExportParams()}`, '_blank');
    }

    formatMoney(value) {
        return (value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    getColor(index) {
        return COLORS[index % COLORS.length];
    }

    drawChart() {
        const canvas = this.root.el && this.root.el.querySelector(".branch_purchase_pie_chart");
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        const lines = this.state.data.lines || [];
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        const total = lines.reduce((s, l) => s + l.purchase_amount, 0);
        if (!total) return;
        const cx = canvas.width / 2;
        const cy = canvas.height / 2;
        const radius = Math.min(cx, cy) - 10;
        let start = -Math.PI / 2;
        lines.forEach((line, i) => {
            const slice = (line.purchase_amount / total) * Math.PI * 2;
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.arc(cx, cy, radius, start, start + slice);
            ctx.closePath();
            ctx.fillStyle = this.getColor(i);
            ctx.fill();
            start += slice;
        });
    }
}

registry.category("actions").add("branch_purchase_dashboard", BranchPurchaseDashboard);
