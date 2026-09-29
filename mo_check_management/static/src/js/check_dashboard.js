/** @odoo-module **/

import { Component, onWillStart, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";

const OPEN_STATES = ["draft", "received", "deposited", "under_collection", "handed_over"];

// One colour per status, reused by the doughnut, the badges and the legend.
export const STATE_COLORS = {
    draft: "#64748b",
    received: "#2563eb",
    deposited: "#4f46e5",
    under_collection: "#7c3aed",
    collected: "#059669",
    handed_over: "#0284c7",
    cleared: "#0d9488",
    bounced: "#dc2626",
    cancelled: "#94a3b8",
};

const CARDS = [
    ["total", "Total Checks", "fa-files-o", ""],
    ["incoming", "Incoming", "fa-arrow-down", "incoming"],
    ["outgoing", "Outgoing", "fa-arrow-up", "outgoing"],
    ["under_collection", "Under Collection", "fa-clock-o", "under_collection"],
    ["collected", "Collected / Cleared", "fa-check-circle", "collected"],
    ["bounced", "Bounced", "fa-exclamation-triangle", "bounced"],
    ["due_today", "Due Today", "fa-calendar-check-o", "due_today"],
    ["overdue", "Overdue", "fa-bell", "overdue"],
];

export class CheckDashboard extends Component {
    static template = "mo_check_management.CheckDashboard";

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({ loading: true, data: null, error: null, dark: false, companyFilter: false });
        this.cards = CARDS;
        this.stateColors = STATE_COLORS;
        onWillStart(async () => await this.loadDashboard());
        // Detect dark mode by reading the *actual* rendered background instead of guessing which
        // attribute/class Odoo (or a third-party dark-mode add-on) toggles: this works regardless
        // of the mechanism, current or future. Re-checked whenever <html>/<body> changes.
        this._checkDarkMode = () => { this.state.dark = this._isDarkBackground(); };
        onMounted(() => {
            this._checkDarkMode();
            this._darkModeObserver = new MutationObserver(this._checkDarkMode);
            this._darkModeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "style", "data-bs-theme", "data-color-scheme"] });
            this._darkModeObserver.observe(document.body, { attributes: true, attributeFilter: ["class", "style", "data-bs-theme", "data-color-scheme"] });
        });
        onWillUnmount(() => this._darkModeObserver && this._darkModeObserver.disconnect());
    }

    /** True if the page's own background color is dark, whatever put it that way. */
    _isDarkBackground() {
        const bg = getComputedStyle(document.body).backgroundColor;
        const rgb = bg && bg.match(/\d+(\.\d+)?/g);
        if (!rgb || rgb.length < 3) {
            return false;
        }
        const [r, g, b] = rgb.map(Number);
        // Perceived luminance (ITU-R BT.601); below ~0.5 reads as a dark background.
        return (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.5;
    }

    async loadDashboard() {
        this.state.loading = true;
        try {
            // Forward the user's current context (allowed_company_ids) so the dashboard
            // reflects whichever company/companies are active in the switcher, exactly
            // like every standard list/kanban view does. Without this the controller
            // falls back to the user's default company and ignores company switching.
            this.state.data = await rpc("/mo_check_management/dashboard", {
                context: user.context,
                company_ids: (user.context && user.context.allowed_company_ids) || [],
                filter_company_id: this.state.companyFilter || false,
            });
            this.state.error = null;
        } catch (error) {
            this.state.error = (error.data && error.data.message) || error.message || "Unable to load dashboard";
            this.notification.add(this.state.error, { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    /** Company picker in the banner: "" = all companies ticked in the switcher. */
    async onCompanyFilter(ev) {
        this.state.companyFilter = parseInt(ev.target.value) || false;
        await this.loadDashboard();
    }

    // ------------------------------------------------------------------ formatting
    formatMoney(value) {
        return new Intl.NumberFormat(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value || 0);
    }

    formatCompact(value) {
        const abs = Math.abs(value || 0);
        const trim = (n) => String(Math.round(n * 10) / 10);
        if (abs >= 1e9) return trim(value / 1e9) + "B";
        if (abs >= 1e6) return trim(value / 1e6) + "M";
        if (abs >= 1e3) return trim(value / 1e3) + "K";
        return String(Math.round(value || 0));
    }

    stateColor(key) {
        return STATE_COLORS[key] || "#64748b";
    }

    // ------------------------------------------------------------------ doughnut (status)
    get statusChart() {
        const R = 70;
        const C = 2 * Math.PI * R;
        const items = this.state.data.states.filter((s) => s.amount > 0);
        const total = items.reduce((sum, s) => sum + s.amount, 0);
        let offset = 0;
        const segments = items.map((s) => {
            const fraction = total ? s.amount / total : 0;
            const seg = {
                ...s,
                color: this.stateColor(s.key),
                pct: Math.round(fraction * 1000) / 10,
                dash: `${Math.max(fraction * C - 1.5, 0)} ${C}`,
                offset: -offset,
            };
            offset += fraction * C;
            return seg;
        });
        return { R, C, total, segments };
    }

    // ------------------------------------------------------------------ grouped bars (cash flow)
    get cashflowChart() {
        const W = 640, H = 290, left = 58, right = 14, top = 16, bottom = 46;
        const plotW = W - left - right;
        const plotH = H - top - bottom;
        const data = this.state.data.cashflow;
        const rawMax = Math.max(1, ...data.map((b) => Math.max(b.incoming, b.outgoing)));
        // smallest "nice" step (1, 2, 2.5, 5 x 10^n) whose 4 gridlines cover the tallest bar
        const magnitude = Math.pow(10, Math.floor(Math.log10(rawMax / 4)));
        const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s * 4 >= rawMax);
        const max = step * 4;
        const ticks = [0, 1, 2, 3, 4].map((i) => ({
            value: step * i,
            y: top + plotH - (plotH * step * i) / max,
        }));
        const group = plotW / data.length;
        const barW = Math.min(30, group / 3);
        const bars = data.map((b, i) => {
            const cx = left + group * i + group / 2;
            const hIn = (plotH * b.incoming) / max;
            const hOut = (plotH * b.outgoing) / max;
            return {
                bucket: b,
                cx,
                labelY: H - bottom + 20,
                incoming: { x: cx - barW - 2, y: top + plotH - hIn, w: barW, h: hIn, v: b.incoming },
                outgoing: { x: cx + 2, y: top + plotH - hOut, w: barW, h: hOut, v: b.outgoing },
            };
        });
        const empty = data.every((b) => !b.incoming && !b.outgoing);
        return { W, H, left, right, top, plotH, bars, ticks, empty };
    }

    // ------------------------------------------------------------------ horizontal bars
    get banksChart() {
        const banks = this.state.data.banks;
        const max = Math.max(1, ...banks.map((b) => b.amount));
        return banks.map((b) => ({ ...b, pct: Math.max(3, (b.amount / max) * 100) }));
    }

    get partnersChart() {
        const partners = this.state.data.partners;
        const max = Math.max(1, ...partners.map((p) => p.incoming + p.outgoing));
        return partners.map((p) => ({
            ...p,
            inPct: (p.incoming / max) * 100,
            outPct: (p.outgoing / max) * 100,
        }));
    }

    get netPositive() {
        return this.state.data.net_open >= 0;
    }

    // ------------------------------------------------------------------ navigation
    openChecks(params = {}) {
        const domain = [];
        if (params.check_type) domain.push(["check_type", "=", params.check_type]);
        if (params.state) domain.push(["state", "=", params.state]);
        if (params.states) domain.push(["state", "in", params.states]);
        if (params.overdue) domain.push(["is_overdue", "=", true]);
        if (params.today) domain.push(["is_due_today", "=", true]);
        if (params.open) domain.push(["state", "in", OPEN_STATES]);
        if (params.date_from) domain.push(["due_date", ">=", params.date_from]);
        if (params.date_to) domain.push(["due_date", "<=", params.date_to]);
        if (params.bank) domain.push(["bank_id", "=", params.bank]);
        if (params.partner) domain.push(["partner_id", "=", params.partner]);
        // drill-down must show the same company the dashboard is showing
        if (this.state.data && this.state.data.selected_company) {
            domain.push(["company_id", "=", this.state.data.selected_company]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: params.name || "Checks",
            res_model: "check.management",
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain,
        });
    }

    openCard(key) {
        const map = {
            incoming: { check_type: "incoming" },
            outgoing: { check_type: "outgoing" },
            under_collection: { state: "under_collection" },
            collected: { states: ["collected", "cleared"] },
            bounced: { state: "bounced" },
            due_today: { today: true },
            overdue: { overdue: true },
        };
        this.openChecks(map[key] || {});
    }

    openBucket(bucket, type) {
        this.openChecks({
            open: true, check_type: type, date_from: bucket.date_from || false, date_to: bucket.date_to,
            name: `${bucket.label} - ${type === "incoming" ? "Incoming" : "Outgoing"}`,
        });
    }

    openRow(id) {
        this.action.doAction({
            type: "ir.actions.act_window", res_model: "check.management",
            views: [[false, "form"]], res_id: id,
        });
    }
}

registry.category("actions").add("mo_check_management_dashboard", CheckDashboard);
