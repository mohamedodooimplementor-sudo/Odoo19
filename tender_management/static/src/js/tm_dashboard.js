/** @odoo-module **/
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, onPatched, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";

const STATE_COLORS = {
    draft: "secondary",
    submitted: "warning",
    approved: "info",
    quotation: "primary",
    won: "success",
    delivered: "teal",
    invoiced: "indigo",
    paid: "tm-paid",
    lost: "danger",
    cancelled: "secondary-color",
};

export class TenderDashboard extends Component {
    static template = "tender_management.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.rootRef = useRef("root");
        this.stageCanvas = useRef("stageCanvas");
        this.valueCanvas = useRef("valueCanvas");
        this.monthCanvas = useRef("monthCanvas");
        this.customerCanvas = useRef("customerCanvas");
        this.lostCanvas = useRef("lostCanvas");
        this.periods = [
            { key: "month", label: _t("This Month") },
            { key: "quarter", label: _t("This Quarter") },
            { key: "year", label: _t("This Year") },
            { key: "all", label: _t("All Time") },
        ];
        this.state = useState({ period: "year", data: null });
        this.onResize = () => this.drawAll();

        onWillStart(() => this.load());
        onMounted(() => {
            window.addEventListener("resize", this.onResize);
            this.drawAll();
        });
        onPatched(() => this.drawAll());
        onWillUnmount(() => window.removeEventListener("resize", this.onResize));
    }

    async load() {
        this.state.data = await this.orm.call("tm.tender", "get_dashboard_data", [], {
            period: this.state.period,
        });
    }

    async setPeriod(period) {
        this.state.period = period;
        await this.load();
    }

    // ------------------------------------------------------------ actions
    openKpi(kpi) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: kpi.label,
            res_model: "tm.tender",
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain: kpi.domain,
        });
    }

    openTender(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "tm.tender",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    // ------------------------------------------------------------ formatting
    compact(value) {
        return new Intl.NumberFormat(undefined, {
            notation: "compact",
            maximumFractionDigits: 1,
        }).format(value || 0);
    }

    formatMoney(value) {
        const cur = this.state.data.currency;
        const num = new Intl.NumberFormat(undefined, {
            minimumFractionDigits: 0,
            maximumFractionDigits: 0,
        }).format(value || 0);
        return cur.position === "before" ? `${cur.symbol} ${num}` : `${num} ${cur.symbol}`;
    }

    formatValue(value, type) {
        if (type === "money") {
            return this.formatMoney(value);
        }
        if (type === "percent") {
            return `${(value || 0).toFixed(1)}%`;
        }
        return String(value ?? 0);
    }

    // ------------------------------------------------------------ canvas helpers
    cssVar(name, fallback) {
        const el = this.rootRef.el;
        const value = el ? getComputedStyle(el).getPropertyValue(name).trim() : "";
        return value || fallback;
    }

    prepareCanvas(ref) {
        const canvas = ref.el;
        if (!canvas) {
            return null;
        }
        const dpr = window.devicePixelRatio || 1;
        const width = canvas.clientWidth || 300;
        const height = canvas.clientHeight || 260;
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
        const ctx = canvas.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, width, height);
        ctx.font = "12px sans-serif";
        return {
            ctx,
            width,
            height,
            text: this.cssVar("--bs-body-color", "#212529"),
            muted: this.cssVar("--bs-secondary-color", "#6c757d"),
            grid: this.cssVar("--bs-border-color", "#dee2e6"),
        };
    }

    drawEmpty(c) {
        c.ctx.fillStyle = c.muted;
        c.ctx.textAlign = "center";
        c.ctx.fillText(_t("No data"), c.width / 2, c.height / 2);
    }

    niceMax(value) {
        if (value <= 0) {
            return 1;
        }
        const pow = Math.pow(10, Math.floor(Math.log10(value)));
        const n = value / pow;
        const step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
        return step * pow;
    }

    /** Vertical grouped bars. series: [{color, values}] */
    drawBars(ref, labels, series, showValues) {
        const c = this.prepareCanvas(ref);
        if (!c) {
            return;
        }
        const all = series.flatMap((s) => s.values);
        if (!all.some((v) => v > 0)) {
            return this.drawEmpty(c);
        }
        const { ctx } = c;
        const left = 48, right = 8, top = 16, bottom = 28;
        const plotW = c.width - left - right;
        const plotH = c.height - top - bottom;
        const max = this.niceMax(Math.max(...all));
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";
        for (let i = 0; i <= 4; i++) {
            const y = top + plotH - (plotH * i) / 4;
            ctx.strokeStyle = c.grid;
            ctx.beginPath();
            ctx.moveTo(left, y);
            ctx.lineTo(c.width - right, y);
            ctx.stroke();
            ctx.fillStyle = c.muted;
            ctx.fillText(this.compact((max * i) / 4), left - 6, y);
        }
        const groupW = plotW / labels.length;
        const barW = Math.min(36, (groupW * 0.7) / series.length);
        labels.forEach((label, gi) => {
            const start = left + gi * groupW + (groupW - barW * series.length) / 2;
            series.forEach((s, si) => {
                const h = (s.values[gi] / max) * plotH;
                ctx.fillStyle = s.color;
                ctx.fillRect(start + si * barW, top + plotH - h, barW - 2, h);
                if (showValues && s.values[gi] > 0) {
                    ctx.fillStyle = c.text;
                    ctx.textAlign = "center";
                    ctx.textBaseline = "bottom";
                    ctx.fillText(this.compact(s.values[gi]), start + si * barW + barW / 2, top + plotH - h - 2);
                }
            });
            ctx.fillStyle = c.muted;
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            ctx.fillText(label, left + gi * groupW + groupW / 2, top + plotH + 8);
        });
    }

    /** Horizontal bars for a ranking. */
    drawHBars(ref, labels, values, color) {
        const c = this.prepareCanvas(ref);
        if (!c) {
            return;
        }
        if (!values.some((v) => v > 0)) {
            return this.drawEmpty(c);
        }
        const { ctx } = c;
        const left = 120, right = 60, top = 8;
        const rowH = (c.height - top * 2) / labels.length;
        const max = Math.max(...values);
        ctx.textBaseline = "middle";
        labels.forEach((label, i) => {
            const y = top + i * rowH + rowH / 2;
            const w = (values[i] / max) * (c.width - left - right);
            ctx.fillStyle = c.text;
            ctx.textAlign = "right";
            const text = label.length > 17 ? label.slice(0, 16) + "…" : label;
            ctx.fillText(text, left - 8, y);
            ctx.fillStyle = color;
            ctx.fillRect(left, y - rowH * 0.28, Math.max(w, 2), rowH * 0.56);
            ctx.fillStyle = c.muted;
            ctx.textAlign = "left";
            ctx.fillText(this.compact(values[i]), left + w + 6, y);
        });
    }

    drawAll() {
        const data = this.state.data;
        if (!data || !this.stageCanvas.el) {
            return;
        }
        const fallback = { teal: "#20c997", indigo: "#6610f2", "tm-paid": "#146c43" };
        const color = (name) => this.cssVar(`--bs-${name}`, fallback[name] || "#6c757d");
        const stateColors = data.states.map((s) => color(STATE_COLORS[s.key]));
        const labels = data.states.map((s) => s.label);

        // one series per bar so every stage keeps its own color
        this.drawBarsPerColor(this.stageCanvas, labels, data.states.map((s) => s.count), stateColors);
        this.drawBarsPerColor(this.valueCanvas, labels, data.states.map((s) => s.sale), stateColors);
        this.drawBars(
            this.monthCanvas,
            data.months.map((m) => m.label),
            [
                { color: color("primary"), values: data.months.map((m) => m.sale) },
                { color: color("warning"), values: data.months.map((m) => m.cost) },
            ],
            false
        );
        this.drawHBars(
            this.customerCanvas,
            data.customers.map((c) => c.label),
            data.customers.map((c) => c.value),
            color("primary")
        );
        this.drawHBars(
            this.lostCanvas,
            data.lost_reasons.map((r) => r.label),
            data.lost_reasons.map((r) => r.value),
            color("danger")
        );
    }

    drawBarsPerColor(ref, labels, values, colors) {
        const c = this.prepareCanvas(ref);
        if (!c) {
            return;
        }
        if (!values.some((v) => v > 0)) {
            return this.drawEmpty(c);
        }
        const { ctx } = c;
        const left = 48, right = 8, top = 18, bottom = 28;
        const plotW = c.width - left - right;
        const plotH = c.height - top - bottom;
        const max = this.niceMax(Math.max(...values));
        ctx.textBaseline = "middle";
        for (let i = 0; i <= 4; i++) {
            const y = top + plotH - (plotH * i) / 4;
            ctx.strokeStyle = c.grid;
            ctx.beginPath();
            ctx.moveTo(left, y);
            ctx.lineTo(c.width - right, y);
            ctx.stroke();
            ctx.fillStyle = c.muted;
            ctx.textAlign = "right";
            ctx.fillText(this.compact((max * i) / 4), left - 6, y);
        }
        const slot = plotW / labels.length;
        const barW = Math.min(40, slot * 0.6);
        labels.forEach((label, i) => {
            const h = (values[i] / max) * plotH;
            const x = left + i * slot + (slot - barW) / 2;
            ctx.fillStyle = colors[i];
            ctx.fillRect(x, top + plotH - h, barW, h);
            if (values[i] > 0) {
                ctx.fillStyle = c.text;
                ctx.textAlign = "center";
                ctx.textBaseline = "bottom";
                ctx.fillText(this.compact(values[i]), x + barW / 2, top + plotH - h - 2);
            }
            ctx.fillStyle = c.muted;
            ctx.textAlign = "center";
            ctx.textBaseline = "top";
            ctx.fillText(label.length > 9 ? label.slice(0, 8) + "…" : label, left + i * slot + slot / 2, top + plotH + 8);
        });
    }
}

registry.category("actions").add("tm_dashboard", TenderDashboard);
