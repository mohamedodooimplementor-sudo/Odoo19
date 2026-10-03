/** @odoo-module **/

import { Component, useState, useRef, onWillStart, onMounted, onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const COLORS = ["#6C3EF4", "#FF6B35", "#00B894", "#FF3D71", "#00C2D1", "#FFC93C", "#8E44FF"];

export class BranchPaymentDashboard extends Component {
    static template = "branch_management.BranchPaymentDashboard";

    setup() {
        this.orm = useService("orm");
        this.root = useRef("root");
        this.state = useState({
            filters: { date_from: false, date_to: false, branch_id: "" },
            branches: [],
            data: { lines: [], totals: {} },
        });
        onWillStart(async () => {
            this.state.branches = await this.orm.searchRead("res.branch", [], ["id", "name"]);
            await this.loadData();
        });
        onMounted(() => this.drawChart());
        onPatched(() => this.drawChart());
    }

    async loadData() {
        const f = this.state.filters;
        this.state.data = await this.orm.call("branch.payment.report", "get_dashboard_data", [], {
            date_from: f.date_from || false,
            date_to: f.date_to || false,
            branch_id: f.branch_id ? parseInt(f.branch_id) : false,
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
        return params.toString();
    }

    onExportExcel() {
        window.open(`/branch_management/payment/export_xlsx?${this.getExportParams()}`, '_blank');
    }

    onExportPdf() {
        window.open(`/branch_management/payment/export_pdf?${this.getExportParams()}`, '_blank');
    }

    formatMoney(value) {
        return (value || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    getColor(index) {
        return COLORS[index % COLORS.length];
    }

    drawChart() {
        const canvas = this.root.el && this.root.el.querySelector(".branch_payment_bar_chart");
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        const lines = this.state.data.lines || [];
        const width = canvas.width;
        const height = canvas.height;
        ctx.clearRect(0, 0, width, height);
        if (!lines.length) return;

        const maxVal = Math.max(1, ...lines.map((l) => Math.max(l.inbound_amount, l.outbound_amount)));
        const padding = 36;
        const chartWidth = width - padding * 2;
        const chartHeight = height - padding * 1.5;
        const groupWidth = chartWidth / lines.length;
        const barWidth = Math.min(28, groupWidth / 3);

        ctx.strokeStyle = "#d7d7e0";
        ctx.beginPath();
        ctx.moveTo(padding, height - padding);
        ctx.lineTo(width - padding / 2, height - padding);
        ctx.stroke();

        ctx.font = "11px sans-serif";
        ctx.textAlign = "center";

        lines.forEach((line, index) => {
            const groupX = padding + index * groupWidth + groupWidth / 2;
            const inH = (line.inbound_amount / maxVal) * chartHeight;
            const outH = (line.outbound_amount / maxVal) * chartHeight;

            ctx.fillStyle = "#00B894";
            ctx.fillRect(groupX - barWidth - 2, height - padding - inH, barWidth, inH);

            ctx.fillStyle = "#FF3D71";
            ctx.fillRect(groupX + 2, height - padding - outH, barWidth, outH);

            ctx.fillStyle = "#5a5a6e";
            const label = line.branch_name.length > 10 ? line.branch_name.slice(0, 9) + "…" : line.branch_name;
            ctx.fillText(label, groupX, height - padding + 14);
        });
    }
}

registry.category("actions").add("branch_payment_dashboard", BranchPaymentDashboard);
