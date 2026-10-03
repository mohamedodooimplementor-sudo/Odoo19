/** @odoo-module **/

import { Component, useState, useRef, onWillStart, onMounted, onPatched, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

const PALETTE = [
    "#4F46E5", "#0EA5E9", "#10B981", "#F59E0B",
    "#EF4444", "#8B5CF6", "#14B8A6", "#F97316",
];
const SALES_COLOR = "#4F46E5";
const PURCHASE_COLOR = "#F59E0B";

const pad = (n) => String(n).padStart(2, "0");
// Local-date ISO string (toISOString() would shift the day for non-UTC users).
const toISO = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

export class BranchOverviewDashboard extends Component {
    static template = "branch_management.BranchOverviewDashboard";

    setup() {
        this.orm = useService("orm");
        this.root = useRef("root");
        this.barRef = useRef("barChart");
        this.donutRef = useRef("donutChart");
        this.tipRef = useRef("tooltip");

        this.presets = [
            { key: "month", label: _t("This month") },
            { key: "30d", label: _t("Last 30 days") },
            { key: "quarter", label: _t("This quarter") },
            { key: "6m", label: _t("6 months") },
            { key: "year", label: _t("This year") },
        ];

        const range = this.getPresetRange("6m");
        this.state = useState({
            loading: true,
            preset: "6m",
            filters: { date_from: range.from, date_to: range.to, branch_id: "" },
            branches: [],
            data: { lines: [], totals: {}, currency_symbol: "" },
            updatedAt: "",
            dark: false,
        });

        this._onResize = () => this.drawCharts();
        this._barGeom = [];

        onWillStart(async () => {
            this.state.branches = await this.orm.searchRead("res.branch", [], ["id", "name"]);
            await this.loadData();
        });
        onMounted(() => {
            this.detectDark();
            this.drawCharts();
            window.addEventListener("resize", this._onResize);
        });
        onPatched(() => {
            this.detectDark();
            this.drawCharts();
        });
        onWillUnmount(() => window.removeEventListener("resize", this._onResize));
    }

    // ------------------------------------------------------------------
    // Filters
    // ------------------------------------------------------------------
    getPresetRange(key) {
        const today = new Date();
        const start = new Date(today);
        if (key === "month") {
            start.setDate(1);
        } else if (key === "30d") {
            start.setDate(start.getDate() - 29);
        } else if (key === "quarter") {
            start.setMonth(Math.floor(today.getMonth() / 3) * 3, 1);
        } else if (key === "year") {
            start.setMonth(0, 1);
        } else {
            start.setMonth(start.getMonth() - 5, 1);
        }
        return { from: toISO(start), to: toISO(today) };
    }

    setPreset(key) {
        const range = this.getPresetRange(key);
        this.state.preset = key;
        this.state.filters.date_from = range.from;
        this.state.filters.date_to = range.to;
        this.loadData();
    }

    onDateChange() {
        this.state.preset = "custom";
        this.loadData();
    }

    onBranchChange() {
        this.loadData();
    }

    onRowClick(branchId) {
        if (String(this.state.filters.branch_id) === String(branchId)) {
            return;
        }
        this.state.filters.branch_id = String(branchId);
        this.loadData();
    }

    clearBranch() {
        this.state.filters.branch_id = "";
        this.loadData();
    }

    async loadData() {
        const f = this.state.filters;
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call("branch.overview.report", "get_dashboard_data", [], {
                date_from: f.date_from || false,
                date_to: f.date_to || false,
                branch_id: f.branch_id ? parseInt(f.branch_id, 10) : false,
            });
            this.state.updatedAt = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        } finally {
            this.state.loading = false;
        }
    }

    // ------------------------------------------------------------------
    // View helpers
    // ------------------------------------------------------------------
    get symbol() {
        return this.state.data.currency_symbol || "";
    }

    get totals() {
        return this.state.data.totals || {};
    }

    get hasData() {
        return (this.state.data.lines || []).length > 0;
    }

    get branchLabel() {
        const id = this.state.filters.branch_id;
        if (!id) {
            return _t("All branches");
        }
        const b = this.state.branches.find((x) => String(x.id) === String(id));
        return b ? b.name : "";
    }

    formatMoney(value, digits = 2) {
        return (value || 0).toLocaleString(undefined, {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
        });
    }

    formatCompact(value) {
        const n = Math.abs(value || 0);
        const sign = value < 0 ? "-" : "";
        if (n >= 1e9) { return `${sign}${(n / 1e9).toFixed(1)}B`; }
        if (n >= 1e6) { return `${sign}${(n / 1e6).toFixed(1)}M`; }
        if (n >= 1e3) { return `${sign}${(n / 1e3).toFixed(1)}K`; }
        return `${sign}${n.toFixed(0)}`;
    }

    getColor(index) {
        return PALETTE[index % PALETTE.length];
    }

    signClass(value) {
        return value < 0 ? "text-danger" : "text-success";
    }

    usageClass(pct) {
        if (pct >= 90) { return "is-danger"; }
        if (pct >= 70) { return "is-warning"; }
        return "is-ok";
    }

    get kpis() {
        const t = this.totals;
        const sales = t.sales_amount || 0;
        const outstanding = t.outstanding_amount || 0;
        const collected = sales ? Math.max(0, Math.min(100, ((sales - outstanding) / sales) * 100)) : 0;
        const net = t.net_amount || 0;
        return [
            {
                key: "sales", icon: "fa-line-chart", tone: "indigo",
                label: _t("Total Sales"), value: this.formatMoney(sales, 0),
                sub: `${t.so_count || 0} ${_t("confirmed orders")}`,
            },
            {
                key: "purchases", icon: "fa-shopping-basket", tone: "amber",
                label: _t("Total Purchases"), value: this.formatMoney(t.purchase_amount, 0),
                sub: `${t.po_count || 0} ${_t("purchase orders")}`,
            },
            {
                key: "net", icon: "fa-balance-scale", tone: net < 0 ? "red" : "green",
                label: _t("Net Result"), value: this.formatMoney(net, 0),
                sub: _t("Sales minus purchases"),
            },
            {
                key: "outstanding", icon: "fa-clock-o", tone: "red",
                label: _t("Outstanding"), value: this.formatMoney(outstanding, 0),
                sub: `${collected.toFixed(0)}% ${_t("collected")}`,
            },
            {
                key: "payments", icon: "fa-money", tone: "teal",
                label: _t("Net Payments"), value: this.formatMoney(t.payments_net_amount, 0),
                sub: `${t.payments_count || 0} ${_t("payments")}`,
            },
            {
                key: "transfers", icon: "fa-exchange", tone: "sky",
                label: _t("Transfers"), value: String(t.transfers_count || 0),
                sub: `${t.branches_count || 0} ${_t("active branches")}`,
                plain: true,
            },
        ];
    }

    get rows() {
        const lines = this.state.data.lines || [];
        const totalSales = this.totals.sales_amount || 0;
        return lines.map((l, i) => {
            const collection = l.sales_amount
                ? Math.max(0, Math.min(100, ((l.sales_amount - l.outstanding_amount) / l.sales_amount) * 100))
                : null;
            const creditUsage = l.credit_limit > 0
                ? Math.max(0, (l.outstanding_amount / l.credit_limit) * 100)
                : null;
            return {
                ...l,
                rank: i + 1,
                color: this.getColor(i),
                share: totalSales ? (l.sales_amount / totalSales) * 100 : 0,
                collection,
                creditUsage,
                creditBar: creditUsage === null ? 0 : Math.min(creditUsage, 100),
            };
        });
    }

    // ------------------------------------------------------------------
    // Charts (canvas, HiDPI aware, theme aware)
    // ------------------------------------------------------------------
    _theme() {
        const cs = getComputedStyle(this.root.el);
        return {
            text: cs.getPropertyValue("--bd-muted").trim() || "#6b7280",
            grid: cs.getPropertyValue("--bd-border").trim() || "#e5e7eb",
            strong: cs.color || "#111827",
        };
    }

    _prepCanvas(canvas) {
        const dpr = window.devicePixelRatio || 1;
        const w = canvas.clientWidth;
        const h = canvas.clientHeight;
        if (!w || !h) {
            return null;
        }
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(h * dpr);
        const ctx = canvas.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, w, h);
        return { ctx, w, h };
    }

    _niceMax(v) {
        if (v <= 0) { return 1; }
        const exp = Math.pow(10, Math.floor(Math.log10(v)));
        const f = v / exp;
        return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * exp;
    }

    _roundedTopRect(ctx, x, y, w, h, r) {
        if (h <= 0) { return; }
        r = Math.min(r, w / 2, h);
        ctx.beginPath();
        ctx.moveTo(x, y + h);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.lineTo(x + w - r, y);
        ctx.quadraticCurveTo(x + w, y, x + w, y + r);
        ctx.lineTo(x + w, y + h);
        ctx.closePath();
        ctx.fill();
    }

    detectDark() {
        // Odoo's dark mode is not exposed the same way in every edition, so
        // read the real page background and decide from its brightness.
        const host = this.root.el && (this.root.el.closest(".o_action_manager") || document.body);
        const m = host && getComputedStyle(host).backgroundColor.match(/\d+(\.\d+)?/g);
        if (!m || (m.length > 3 && parseFloat(m[3]) === 0)) {
            return;
        }
        const [r, g, b] = m.map(Number);
        const dark = (0.299 * r + 0.587 * g + 0.114 * b) < 128;
        if (dark !== this.state.dark) {
            this.state.dark = dark;
        }
    }

    drawCharts() {
        if (!this.root.el) { return; }
        this.drawBarChart();
        this.drawDonut();
    }

    drawBarChart() {
        const canvas = this.barRef.el;
        this._barGeom = [];
        if (!canvas) { return; }
        const prep = this._prepCanvas(canvas);
        if (!prep) { return; }
        const { ctx, w, h } = prep;
        const theme = this._theme();
        const lines = this.state.data.lines || [];
        if (!lines.length) { return; }

        const padL = 52, padR = 12, padT = 12, padB = 30;
        const chartW = w - padL - padR;
        const chartH = h - padT - padB;
        const maxVal = this._niceMax(Math.max(...lines.map((l) => Math.max(l.sales_amount, l.purchase_amount, 0))));
        const ticks = 4;

        ctx.font = "11px system-ui, -apple-system, sans-serif";
        ctx.textBaseline = "middle";
        ctx.textAlign = "right";
        for (let i = 0; i <= ticks; i++) {
            const val = (maxVal / ticks) * i;
            const y = padT + chartH - (val / maxVal) * chartH;
            ctx.strokeStyle = theme.grid;
            ctx.lineWidth = 1;
            ctx.setLineDash(i === 0 ? [] : [3, 4]);
            ctx.beginPath();
            ctx.moveTo(padL, y + 0.5);
            ctx.lineTo(w - padR, y + 0.5);
            ctx.stroke();
            ctx.fillStyle = theme.text;
            ctx.fillText(this.formatCompact(val), padL - 8, y);
        }
        ctx.setLineDash([]);

        const groupW = chartW / lines.length;
        const barW = Math.max(6, Math.min(34, groupW / 3.2));
        ctx.textAlign = "center";
        lines.forEach((line, i) => {
            const cx = padL + i * groupW + groupW / 2;
            const sH = (Math.max(line.sales_amount, 0) / maxVal) * chartH;
            const pH = (Math.max(line.purchase_amount, 0) / maxVal) * chartH;
            ctx.fillStyle = SALES_COLOR;
            this._roundedTopRect(ctx, cx - barW - 2, padT + chartH - sH, barW, sH, 5);
            ctx.fillStyle = PURCHASE_COLOR;
            this._roundedTopRect(ctx, cx + 2, padT + chartH - pH, barW, pH, 5);

            const maxChars = Math.max(4, Math.floor(groupW / 7));
            const label = line.branch_name.length > maxChars
                ? line.branch_name.slice(0, maxChars - 1) + "…"
                : line.branch_name;
            ctx.fillStyle = theme.text;
            ctx.textBaseline = "alphabetic";
            ctx.fillText(label, cx, h - 8);
            ctx.textBaseline = "middle";
            this._barGeom.push({ x0: padL + i * groupW, x1: padL + (i + 1) * groupW, line });
        });
    }

    drawDonut() {
        const canvas = this.donutRef.el;
        if (!canvas) { return; }
        const prep = this._prepCanvas(canvas);
        if (!prep) { return; }
        const { ctx, w, h } = prep;
        const theme = this._theme();
        const rows = this.rows;
        const total = rows.reduce((s, r) => s + Math.max(r.sales_amount, 0), 0);
        const cx = w / 2;
        const cy = h / 2;
        const outer = Math.min(cx, cy) - 4;
        const inner = outer * 0.66;

        ctx.lineWidth = outer - inner;
        const radius = (outer + inner) / 2;
        if (!total) {
            ctx.strokeStyle = theme.grid;
            ctx.beginPath();
            ctx.arc(cx, cy, radius, 0, Math.PI * 2);
            ctx.stroke();
        } else {
            let start = -Math.PI / 2;
            const gap = rows.length > 1 ? 0.025 : 0;
            rows.forEach((r) => {
                const slice = (Math.max(r.sales_amount, 0) / total) * Math.PI * 2;
                if (slice <= 0) { return; }
                ctx.strokeStyle = r.color;
                ctx.beginPath();
                ctx.arc(cx, cy, radius, start + gap / 2, start + slice - gap / 2);
                ctx.stroke();
                start += slice;
            });
        }
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = theme.strong;
        ctx.font = "600 20px system-ui, -apple-system, sans-serif";
        ctx.fillText(this.formatCompact(total), cx, cy - 7);
        ctx.fillStyle = theme.text;
        ctx.font = "11px system-ui, -apple-system, sans-serif";
        ctx.fillText(_t("Total sales"), cx, cy + 14);
    }

    onBarMove(ev) {
        const tip = this.tipRef.el;
        const canvas = this.barRef.el;
        if (!tip || !canvas) { return; }
        const rect = canvas.getBoundingClientRect();
        const x = ev.clientX - rect.left;
        const hit = this._barGeom.find((g) => x >= g.x0 && x < g.x1);
        if (!hit) {
            tip.style.display = "none";
            return;
        }
        const l = hit.line;
        tip.replaceChildren();
        const title = document.createElement("div");
        title.className = "o_bd_tip_title";
        title.textContent = l.branch_name;
        tip.appendChild(title);
        [
            [_t("Sales"), l.sales_amount, SALES_COLOR],
            [_t("Purchases"), l.purchase_amount, PURCHASE_COLOR],
            [_t("Net"), l.net_amount, null],
        ].forEach(([label, value, color]) => {
            const row = document.createElement("div");
            row.className = "o_bd_tip_row";
            const dot = document.createElement("span");
            dot.className = "o_legend_dot";
            if (color) { dot.style.background = color; } else { dot.style.visibility = "hidden"; }
            const name = document.createElement("span");
            name.textContent = label;
            const val = document.createElement("strong");
            val.textContent = `${this.formatMoney(value)} ${this.symbol}`;
            row.append(dot, name, val);
            tip.appendChild(row);
        });
        tip.style.display = "block";
        const parentW = canvas.parentElement.clientWidth;
        const left = Math.min(x + 14, parentW - tip.offsetWidth - 4);
        tip.style.left = `${Math.max(4, left)}px`;
        tip.style.top = `${Math.max(4, ev.clientY - rect.top - 20)}px`;
    }

    onBarLeave() {
        if (this.tipRef.el) {
            this.tipRef.el.style.display = "none";
        }
    }
}

registry.category("actions").add("branch_overview_dashboard", BranchOverviewDashboard);
