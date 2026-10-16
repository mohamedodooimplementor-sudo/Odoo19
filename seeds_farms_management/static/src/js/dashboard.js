/** @odoo-module **/
import { Component, onMounted, onWillStart, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class SeedsDashboard extends Component {
    static template = "seeds_farms_management.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.canvas = useRef("canvas");
        this.state = useState({ data: null });
        onWillStart(async () => {
            this.state.data = await this.orm.call("seeds.receipt", "get_dashboard_data", []);
        });
        onMounted(() => this.draw());
    }

    fmt(n, d = 0) {
        return Number(n || 0).toLocaleString("en-US", {
            minimumFractionDigits: d,
            maximumFractionDigits: d,
        });
    }

    get contractPercent() {
        const d = this.state.data;
        return d.contracted ? Math.min((d.delivered / d.contracted) * 100, 100) : 0;
    }

    openReceipts() {
        this.action.doAction("seeds_farms_management.action_seeds_receipt");
    }

    openContracts() {
        this.action.doAction("seeds_farms_management.action_seeds_contract");
    }

    openSettlements() {
        this.action.doAction("seeds_farms_management.action_seeds_settlement");
    }

    draw() {
        const el = this.canvas.el;
        if (!el || !this.state.data) {
            return;
        }
        const rows = this.state.data.monthly;
        const ratio = window.devicePixelRatio || 1;
        const w = el.clientWidth || 600;
        const h = el.clientHeight || 240;
        el.width = w * ratio;
        el.height = h * ratio;
        const ctx = el.getContext("2d");
        ctx.scale(ratio, ratio);
        ctx.clearRect(0, 0, w, h);
        if (!rows.length) {
            ctx.fillStyle = "#5b6e60";
            ctx.font = "14px sans-serif";
            ctx.fillText("No data yet", 10, 24);
            return;
        }
        const max = Math.max(...rows.map((r) => r.value), 1);
        const padL = 10, padB = 28, padT = 22;
        const slot = (w - padL * 2) / rows.length;
        const bw = Math.min(slot * 0.6, 56);
        rows.forEach((r, i) => {
            const bh = ((h - padB - padT) * r.value) / max;
            const x = padL + slot * i + (slot - bw) / 2;
            const y = h - padB - bh;
            ctx.fillStyle = "#2e6b3a";
            ctx.fillRect(x, y, bw, bh);
            ctx.fillStyle = "#1d2b22";
            ctx.font = "12px sans-serif";
            ctx.textAlign = "center";
            ctx.fillText(this.fmt(r.value), x + bw / 2, y - 6);
            ctx.fillStyle = "#5b6e60";
            ctx.fillText(r.label, x + bw / 2, h - 10);
        });
    }
}

registry.category("actions").add("seeds_dashboard", SeedsDashboard);
