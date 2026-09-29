/** @odoo-module **/

import { Component, onWillStart, onMounted, onWillUnmount, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const MODEL = "repacking.screening.operation";

// Vivid, saturated palette — deliberately punchy rather than pastel.
const PALETTE = {
    purple: "#7C3AED",
    purpleSoft: "#A78BFA",
    teal: "#0EA5E9",
    tealSoft: "#67E8F9",
    orange: "#F97316",
    orangeSoft: "#FDBA74",
    pink: "#EC4899",
    pinkSoft: "#F9A8D4",
    green: "#10B981",
    greenSoft: "#6EE7B7",
    red: "#EF4444",
    redSoft: "#FCA5A5",
    slate: "#334155",
};

const STATE_COLORS = {
    draft: "#94A3B8",
    transferred: PALETTE.tealSoft,
    confirmed: PALETTE.teal,
    manufacturing: PALETTE.purple,
    done: PALETTE.green,
    cancelled: PALETTE.red,
};

const STATE_LABELS = {
    draft: "Draft",
    transferred: "Transferred to Manufacturing",
    confirmed: "Confirmed",
    manufacturing: "Manufacturing",
    done: "Done",
    cancelled: "Cancelled",
};

export class RepackingDashboard extends Component {
    static template = "repacking_screening.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.companyService = useService("company");

        this.donutRef = useRef("donutCanvas");
        this.barRef = useRef("barCanvas");
        this.rootRef = useRef("dashboardRoot");

        this.state = useState({
            loading: true,
            currencySymbol: "",
            kpi: {
                total_ops: 0,
                total_cost: 0,
                avg_yield: 0,
                avg_loss: 0,
            },
            byType: [],
            byState: [],
            recent: [],
        });

        onWillStart(async () => {
            await this.loadData();
        });

        onMounted(() => {
            this._drawCharts();
            this._resizeHandler = () => this._drawCharts();
            window.addEventListener("resize", this._resizeHandler);

            // Redraw the canvas-based charts whenever Odoo's Dark Mode is
            // toggled (o_dark_mode class on <html>) — CSS alone can't
            // repaint already-drawn canvas pixels.
            this._themeObserver = new MutationObserver(() => this._drawCharts());
            this._themeObserver.observe(document.documentElement, {
                attributes: true, attributeFilter: ["class"],
            });

            // Fallback for the OS-level preference (no Odoo Dark Mode class).
            this._darkMediaQuery = window.matchMedia("(prefers-color-scheme: dark)");
            this._darkMediaHandler = () => this._drawCharts();
            if (this._darkMediaQuery.addEventListener) {
                this._darkMediaQuery.addEventListener("change", this._darkMediaHandler);
            }
        });

        onWillUnmount(() => {
            if (this._resizeHandler) {
                window.removeEventListener("resize", this._resizeHandler);
            }
            if (this._themeObserver) {
                this._themeObserver.disconnect();
            }
            if (this._darkMediaQuery && this._darkMediaQuery.removeEventListener) {
                this._darkMediaQuery.removeEventListener("change", this._darkMediaHandler);
            }
        });
    }

    async loadData() {
        try {
            const companyId = this.companyService.currentCompany.id;
            const [company] = await this.orm.read("res.company", [companyId], ["currency_id"]);
            if (company && company.currency_id) {
                const [currency] = await this.orm.read(
                    "res.currency", [company.currency_id[0]], ["symbol"]
                );
                this.state.currencySymbol = currency ? currency.symbol : "";
            }
        } catch {
            this.state.currencySymbol = "";
        }

        const allRecords = await this.orm.searchRead(
            MODEL, [],
            ["operation_type", "state", "total_input_cost", "yield_percentage",
             "loss_percentage", "output_quantity", "product_id", "scheduled_date"]
        );

        const total_ops = allRecords.length;
        const total_cost = allRecords.reduce((s, r) => s + (r.total_input_cost || 0), 0);
        const doneRecords = allRecords.filter((r) => r.state === "done");
        const avg_yield = doneRecords.length
            ? doneRecords.reduce((s, r) => s + (r.yield_percentage || 0), 0) / doneRecords.length
            : 0;
        const avg_loss = doneRecords.length
            ? doneRecords.reduce((s, r) => s + (r.loss_percentage || 0), 0) / doneRecords.length
            : 0;

        this.state.kpi = { total_ops, total_cost, avg_yield, avg_loss };

        // Group by operation type
        const typeCounts = {};
        for (const r of allRecords) {
            typeCounts[r.operation_type] = (typeCounts[r.operation_type] || 0) + 1;
        }
        this.state.byType = Object.entries(typeCounts).map(([key, count]) => ({
            key,
            label: key === "repacking" ? "Repacking" : "Screening",
            count,
            color: key === "repacking" ? PALETTE.purple : PALETTE.orange,
        }));

        // Group by state, in a fixed, meaningful order — always show all.
        const stateOrder = ["draft", "transferred", "confirmed", "manufacturing", "done", "cancelled"];
        const stateCounts = {};
        for (const r of allRecords) {
            stateCounts[r.state] = (stateCounts[r.state] || 0) + 1;
        }
        this.state.byState = stateOrder.map((key) => ({
            key,
            label: STATE_LABELS[key],
            count: stateCounts[key] || 0,
            color: STATE_COLORS[key],
        }));

        // Recent operations
        const recent = await this.orm.searchRead(
            MODEL, [],
            ["name", "operation_type", "state", "product_id", "output_quantity",
             "total_input_cost", "yield_percentage", "loss_percentage", "scheduled_date"],
            { limit: 6, order: "scheduled_date desc" }
        );
        this.state.recent = recent;

        this.state.loading = false;
    }

    formatCost(value) {
        const n = (value || 0).toLocaleString(undefined, {
            minimumFractionDigits: 2, maximumFractionDigits: 2,
        });
        return this.state.currencySymbol ? `${this.state.currencySymbol} ${n}` : n;
    }

    formatPct(value) {
        return (value || 0).toFixed(1) + "%";
    }

    openAll() {
        this.actionService.doAction("repacking_screening.action_repacking_screening_operation");
    }

    openFiltered(stateKey) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: STATE_LABELS[stateKey] || "Operations",
            res_model: MODEL,
            views: [[false, "list"], [false, "form"]],
            domain: [["state", "=", stateKey]],
        });
    }

    openDone() {
        this.openFiltered("done");
    }

    openRecord(id) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: MODEL,
            views: [[false, "form"]],
            res_id: id,
        });
    }

    // ── Canvas drawing (deliberately dependency-free) ──────────────────────

    // Reads a theme token defined in dashboard.scss (--rp-*), so canvas
    // drawing stays in sync with light/dark mode without duplicating colors.
    _themeVar(name, fallback) {
        const root = this.rootRef.el;
        if (!root) return fallback;
        const value = getComputedStyle(root).getPropertyValue(name).trim();
        return value || fallback;
    }

    _drawCharts() {
        this._drawDonut();
        this._drawBar();
    }

    _setupCanvas(canvas) {
        const rect = canvas.parentElement.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        const width = Math.max(rect.width, 200);
        const height = canvas.getAttribute("data-height")
            ? parseInt(canvas.getAttribute("data-height"), 10)
            : 220;
        canvas.width = width * dpr;
        canvas.height = height * dpr;
        canvas.style.width = width + "px";
        canvas.style.height = height + "px";
        const ctx = canvas.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, width, height);
        return { ctx, width, height };
    }

    _drawDonut() {
        const canvas = this.donutRef.el;
        if (!canvas) return;
        const { ctx, width, height } = this._setupCanvas(canvas);
        const data = this.state.byType;
        const total = data.reduce((s, d) => s + d.count, 0);

        const emptyTrack = this._themeVar("--rp-canvas-empty-track", "#E2E8F0");
        const centerBg = this._themeVar("--rp-canvas-center-bg", "#FFFFFF");
        const textStrong = this._themeVar("--rp-text-strong", PALETTE.slate);
        const textMuted = this._themeVar("--rp-text-muted", "#64748B");

        const cx = width / 2.6;
        const cy = height / 2;
        const outerR = Math.min(cx, cy) - 10;
        const innerR = outerR * 0.62;

        if (!total) {
            ctx.beginPath();
            ctx.arc(cx, cy, outerR, 0, Math.PI * 2);
            ctx.fillStyle = emptyTrack;
            ctx.fill();
        } else {
            let start = -Math.PI / 2;
            for (const d of data) {
                const slice = (d.count / total) * Math.PI * 2;
                ctx.beginPath();
                ctx.moveTo(cx, cy);
                ctx.arc(cx, cy, outerR, start, start + slice);
                ctx.closePath();
                ctx.fillStyle = d.color;
                ctx.fill();
                start += slice;
            }
            ctx.beginPath();
            ctx.arc(cx, cy, innerR, 0, Math.PI * 2);
            ctx.fillStyle = centerBg;
            ctx.fill();
        }

        // Center label
        ctx.fillStyle = textStrong;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.font = "700 22px sans-serif";
        ctx.fillText(String(total), cx, cy - 6);
        ctx.font = "500 11px sans-serif";
        ctx.fillStyle = textMuted;
        ctx.fillText("Operations", cx, cy + 14);

        // Legend
        const legendX = width - (width - cx - outerR) + 20;
        let legendY = cy - (data.length * 22) / 2;
        ctx.textAlign = "left";
        for (const d of data) {
            ctx.fillStyle = d.color;
            ctx.beginPath();
            ctx.arc(legendX, legendY, 6, 0, Math.PI * 2);
            ctx.fill();
            ctx.fillStyle = textStrong;
            ctx.font = "600 12px sans-serif";
            ctx.fillText(`${d.label} (${d.count})`, legendX + 14, legendY + 4);
            legendY += 22;
        }
    }

    _drawBar() {
        const canvas = this.barRef.el;
        if (!canvas) return;
        const { ctx, width, height } = this._setupCanvas(canvas);
        const data = this.state.byState;
        const max = Math.max(...data.map((d) => d.count), 1);

        const trackBg = this._themeVar("--rp-track-bg", "#F1F5F9");
        const textTitle = this._themeVar("--rp-text-title", PALETTE.slate);
        const textMuted = this._themeVar("--rp-text-muted", "#94A3B8");

        const paddingLeft = 90;
        const paddingRight = 30;
        const paddingTop = 10;
        const paddingBottom = 10;
        const chartW = width - paddingLeft - paddingRight;
        const chartH = height - paddingTop - paddingBottom;
        const barH = Math.min(24, chartH / data.length - 12);
        const gap = chartH / data.length;

        data.forEach((d, i) => {
            const y = paddingTop + i * gap + (gap - barH) / 2;
            const barW = (d.count / max) * chartW;

            // Track
            ctx.fillStyle = trackBg;
            ctx.beginPath();
            this._roundRect(ctx, paddingLeft, y, chartW, barH, barH / 2);
            ctx.fill();

            // Bar
            if (d.count > 0) {
                ctx.fillStyle = d.color;
                ctx.beginPath();
                this._roundRect(ctx, paddingLeft, y, Math.max(barW, barH), barH, barH / 2);
                ctx.fill();
            }

            // Label
            ctx.fillStyle = textTitle;
            ctx.font = "600 12px sans-serif";
            ctx.textAlign = "right";
            ctx.textBaseline = "middle";
            ctx.fillText(d.label, paddingLeft - 12, y + barH / 2);

            // Count
            ctx.textAlign = "left";
            if (d.count > 0) {
                ctx.font = "700 12px sans-serif";
                const textX = Math.max(barW, barH) + paddingLeft - 22;
                ctx.fillStyle = barW > 26 ? "#FFFFFF" : textTitle;
                ctx.textAlign = barW > 26 ? "right" : "left";
                ctx.fillText(
                    String(d.count),
                    barW > 26 ? textX : paddingLeft + barW + 8,
                    y + barH / 2
                );
            } else {
                ctx.fillStyle = textMuted;
                ctx.font = "600 12px sans-serif";
                ctx.fillText("0", paddingLeft + 8, y + barH / 2);
            }
        });
    }

    _roundRect(ctx, x, y, w, h, r) {
        r = Math.min(r, h / 2, w / 2 > 0 ? w / 2 : r);
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + w, y, x + w, y + h, r);
        ctx.arcTo(x + w, y + h, x, y + h, r);
        ctx.arcTo(x, y + h, x, y, r);
        ctx.arcTo(x, y, x + w, y, r);
    }
}

registry.category("actions").add("repacking_screening_dashboard", RepackingDashboard);
