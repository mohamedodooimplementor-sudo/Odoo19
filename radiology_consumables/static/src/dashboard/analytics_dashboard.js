/** @odoo-module **/
import { Component, onMounted, onWillStart, proxy } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

const PALETTE = ["#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#06b6d4", "#ef4444", "#14b8a6", "#ec4899", "#6366f1", "#84cc16"];
const SOURCE_COLORS = { valuation: "#22c55e", standard: "#f59e0b" };
const pad = (n) => String(n).padStart(2, "0");
const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const FILTER_KEYS = ["room_ids", "exam_ids", "product_ids"];

class RcCostAnalyticsDashboard extends Component {
    static template = "radiology_consumables.CostAnalyticsDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this._req = 0;
        this.state = proxy({
            loading: true,
            error: "",
            dark: false,
            menu: "",
            search: "",
            tip: null,
            trendMetric: "cost",
            productNames: {},
            filters: this.defaultFilters(),
            data: {
                kpis: {}, previous: null, trend: [], rooms: [], exams_by_type: [], products: [],
                sources: [], options: { rooms: [], exams: [] }, exam_ids: [], currency: "",
            },
        });
        onWillStart(() => this.loadData());
        onMounted(() => {
            this.state.dark = this.detectDark();
        });
    }

    // Odoo's dark mode does not change --bs-body-bg, so detect it from the real page colours.
    detectDark() {
        const parse = (css) => {
            const m = (css || "").match(/rgba?\(([^)]+)\)/);
            if (!m) {
                return null;
            }
            const [r, g, b, a = 1] = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number);
            return a > 0.5 ? 0.2126 * r + 0.7152 * g + 0.0722 * b : null;
        };
        let el = document.querySelector(".o_rc_analytics");
        while (el) {
            const lum = parse(getComputedStyle(el).backgroundColor);
            if (lum !== null) {
                return lum < 128;
            }
            el = el.parentElement;
        }
        return /(?:^|;\s*)color_scheme=dark/.test(document.cookie);
    }

    // ------------------------------------------------------------------ filters
    defaultFilters() {
        const [from, to] = this.presetRange("this_year");
        return {
            preset: "this_year", date_from: iso(from), date_to: iso(to),
            room_ids: [], exam_ids: [], product_ids: [], sources: [], granularity: "month",
        };
    }

    get presets() {
        return [
            { id: "this_month", label: _t("This month"), gran: "day" },
            { id: "last_month", label: _t("Last month"), gran: "day" },
            { id: "last_30", label: _t("Last 30 days"), gran: "day" },
            { id: "this_quarter", label: _t("This quarter"), gran: "week" },
            { id: "this_year", label: _t("This year"), gran: "month" },
            { id: "all", label: _t("All time"), gran: "month" },
        ];
    }

    get metrics() {
        return [
            { id: "cost", label: _t("Cost") },
            { id: "exams", label: _t("Exams") },
            { id: "avg", label: _t("Avg / exam") },
        ];
    }

    get grans() {
        return [
            { id: "day", label: _t("Day") },
            { id: "week", label: _t("Week") },
            { id: "month", label: _t("Month") },
        ];
    }

    get sourceModes() {
        return [
            { id: "", label: _t("All sources") },
            { id: "valuation", label: _t("Stock valuation") },
            { id: "standard", label: _t("Cost fallback") },
        ];
    }

    presetRange(id) {
        const t = new Date();
        const y = t.getFullYear();
        const m = t.getMonth();
        switch (id) {
            case "this_month": return [new Date(y, m, 1), new Date(y, m + 1, 0)];
            case "last_month": return [new Date(y, m - 1, 1), new Date(y, m, 0)];
            case "last_30": return [new Date(y, m, t.getDate() - 29), t];
            case "this_quarter": {
                const q = Math.floor(m / 3) * 3;
                return [new Date(y, q, 1), new Date(y, q + 3, 0)];
            }
            case "this_year": return [new Date(y, 0, 1), new Date(y, 11, 31)];
            default: return [null, null];
        }
    }

    autoGranularity(from, to) {
        if (!from || !to) {
            return "month";
        }
        const days = (new Date(to) - new Date(from)) / 86400000 + 1;
        return days <= 45 ? "day" : days <= 200 ? "week" : "month";
    }

    async applyPreset(preset) {
        const [from, to] = this.presetRange(preset.id);
        const f = this.state.filters;
        f.preset = preset.id;
        f.date_from = from ? iso(from) : "";
        f.date_to = to ? iso(to) : "";
        f.granularity = preset.gran;
        await this.loadData();
    }

    async setDate(which, value) {
        const f = this.state.filters;
        f[which] = value || "";
        f.preset = "custom";
        f.granularity = this.autoGranularity(f.date_from, f.date_to);
        await this.loadData();
    }

    async setGranularity(gran) {
        this.state.filters.granularity = gran;
        await this.loadData();
    }

    async setSource(source) {
        this.state.filters.sources = source ? [source] : [];
        await this.loadData();
    }

    async toggleFilter(key, id, name) {
        if (!id) {
            return;
        }
        const list = this.state.filters[key];
        if (list.includes(id)) {
            this.state.filters[key] = list.filter((x) => x !== id);
        } else {
            this.state.filters[key] = [...list, id];
            if (key === "product_ids" && name) {
                this.state.productNames = { ...this.state.productNames, [id]: name };
            }
        }
        await this.loadData();
    }

    async removeFilter(key, id) {
        if (key === "sources") {
            this.state.filters.sources = [];
        } else {
            this.state.filters[key] = this.state.filters[key].filter((x) => x !== id);
        }
        await this.loadData();
    }

    async clearFilters() {
        this.state.filters = this.defaultFilters();
        this.state.menu = "";
        await this.loadData();
    }

    async drillBucket(bucket) {
        if (!bucket || !bucket.cost) {
            return;
        }
        const f = this.state.filters;
        f.date_from = bucket.start;
        f.date_to = bucket.end;
        f.preset = "custom";
        f.granularity = "day";
        await this.loadData();
    }

    isSelected(key, id) {
        return this.state.filters[key].includes(id);
    }

    toggleMenu(name) {
        this.state.menu = this.state.menu === name ? "" : name;
        this.state.search = "";
    }

    closeMenu() {
        this.state.menu = "";
    }

    menuOptions(kind) {
        const list = this.state.data.options[kind] || [];
        const q = (this.state.search || "").toLowerCase();
        return q ? list.filter((o) => o.name.toLowerCase().includes(q)) : list;
    }

    get chips() {
        const f = this.state.filters;
        const opts = this.state.data.options;
        const name = (list, id) => (list.find((o) => o.id === id) || {}).name || `#${id}`;
        const chips = [];
        f.room_ids.forEach((id) => chips.push({ key: `room:${id}`, type: "room_ids", id, text: `${_t("Room")}: ${name(opts.rooms, id)}` }));
        f.exam_ids.forEach((id) => chips.push({ key: `exam:${id}`, type: "exam_ids", id, text: `${_t("Exam")}: ${name(opts.exams, id)}` }));
        f.product_ids.forEach((id) => chips.push({ key: `prod:${id}`, type: "product_ids", id, text: `${_t("Product")}: ${this.state.productNames[id] || "#" + id}` }));
        f.sources.forEach((s) => chips.push({
            key: `src:${s}`, type: "sources", id: s,
            text: `${_t("Source")}: ${s === "valuation" ? _t("Stock valuation") : _t("Cost fallback")}`,
        }));
        return chips;
    }

    get hasActiveFilters() {
        const f = this.state.filters;
        return f.preset !== "this_year" || FILTER_KEYS.some((k) => f[k].length) || f.sources.length > 0;
    }

    // ------------------------------------------------------------------ data
    async loadData() {
        const req = ++this._req;
        this.state.loading = true;
        this.state.error = "";
        try {
            const f = this.state.filters;
            const data = await this.orm.call("rc.exam.consumption", "get_analytics_dashboard_data", [{
                date_from: f.date_from || false,
                date_to: f.date_to || false,
                room_ids: [...f.room_ids],
                exam_ids: [...f.exam_ids],
                product_ids: [...f.product_ids],
                sources: [...f.sources],
                granularity: f.granularity,
            }]);
            if (req === this._req) {
                this.state.data = data;
            }
        } catch (e) {
            if (req === this._req) {
                this.state.error = (e.data && e.data.message) || e.message || _t("Unable to load analytics.");
            }
        } finally {
            if (req === this._req) {
                this.state.loading = false;
            }
        }
    }

    openExams() {
        const ids = this.state.data.exam_ids || [];
        if (!ids.length) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("Filtered Examinations"),
            res_model: "rc.exam.consumption",
            views: [[false, "list"], [false, "form"]],
            domain: [["id", "in", [...ids]]],
            target: "current",
        });
    }

    open(xmlId) {
        return this.action.doAction(xmlId);
    }

    // ------------------------------------------------------------------ formatting
    money(v) {
        return `${this.state.data.currency || ""} ${Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim();
    }

    num(v) {
        return Number(v || 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
    }

    compact(v) {
        v = Number(v || 0);
        const a = Math.abs(v);
        if (a >= 1e6) {
            return `${Number((v / 1e6).toFixed(1))}M`;
        }
        if (a >= 1e3) {
            return `${Number((v / 1e3).toFixed(a >= 1e4 ? 0 : 1))}K`;
        }
        return String(Number(v.toFixed(1)));
    }

    pct(v) {
        return `${Number(v || 0).toFixed(1)}%`;
    }

    delta(cur, prev) {
        if (!prev) {
            return null;
        }
        return ((cur - prev) / prev) * 100;
    }

    // ------------------------------------------------------------------ KPI cards
    get kpiCards() {
        const d = this.state.data;
        const k = d.kpis || {};
        const p = d.previous;
        const rooms = d.rooms || [];
        const topRoom = rooms[0];
        const totalCost = k.cost || 0;
        const valuation = (d.sources || []).find((s) => s.id === "valuation");
        const coverage = totalCost ? ((valuation ? valuation.cost : 0) / totalCost) * 100 : 0;
        const card = (key, label, value, cls, icon, cur, prev, sub, isText = false) => {
            const delta = p ? this.delta(cur, prev) : null;
            return {
                key, label, value, cls, icon, sub, isText, delta,
                deltaText: delta === null ? "" : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}%`,
                deltaTitle: p ? `${_t("vs previous period")} (${p.date_from} → ${p.date_to})` : "",
            };
        };
        return [
            card("cost", _t("Total consumables cost"), this.money(totalCost), "rc-green", "fa-money", k.cost, p && p.cost, ""),
            card("exams", _t("Examinations"), this.num(k.exams), "rc-blue", "fa-stethoscope", k.exams, p && p.exams, _t("with validated consumption")),
            card("avg", _t("Avg cost / exam"), this.money(k.average), "rc-cyan", "fa-line-chart", k.average, p && p.average, ""),
            card("qty", _t("Consumed quantity"), this.num(k.qty), "rc-purple", "fa-cubes", k.qty, p && p.qty, ""),
            card("room", _t("Top cost room"), topRoom ? topRoom.name : "—", "rc-orange", "fa-hospital-o", 0, 0,
                topRoom ? `${this.money(topRoom.cost)} · ${this.pct(topRoom.share)}` : "", true),
            card("cov", _t("Valuation coverage"), this.pct(coverage), "rc-teal", "fa-shield", 0, 0, _t("cost backed by stock valuation")),
        ];
    }

    // ------------------------------------------------------------------ charts
    niceMax(v) {
        if (v <= 0) {
            return 1;
        }
        const p = Math.pow(10, Math.floor(Math.log10(v)));
        const f = v / p;
        return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
    }

    get trend() {
        const pts = this.state.data.trend || [];
        const metric = this.state.trendMetric;
        const W = 720, H = 260, L = 58, R = 16, T = 16, B = 38;
        const iw = W - L - R, ih = H - T - B, base = T + ih;
        const val = (p) => (metric === "exams" ? p.exams : metric === "avg" ? p.average : p.cost);
        const max = this.niceMax(Math.max(0, ...pts.map(val)));
        const n = pts.length;
        const step = n ? iw / n : iw;
        const fmt = (v) => (metric === "exams" ? this.num(v) : this.compact(v));
        const ticks = [0, 1, 2, 3, 4].map((i) => ({ i, y: base - (ih * i) / 4, label: fmt((max * i) / 4) }));
        const every = Math.max(1, Math.ceil(n / 8));
        const cols = pts.map((p, i) => {
            const v = val(p);
            const cx = L + step * (i + 0.5);
            return {
                key: p.key, b: p, cx, cy: base - (max ? (ih * v) / max : 0), x: L + step * i, w: step,
                label: p.label, showLabel: i % every === 0,
                tipTitle: p.label,
                tipLines: [
                    `${_t("Cost")}: ${this.money(p.cost)}`,
                    `${_t("Exams")}: ${p.exams}`,
                    `${_t("Avg / exam")}: ${this.money(p.average)}`,
                    `${_t("Quantity")}: ${this.num(p.qty)}`,
                    ...(p.cost ? [_t("Click to drill down")] : []),
                ],
            };
        });
        const line = cols.map((c, i) => `${i ? "L" : "M"}${c.cx.toFixed(1)},${c.cy.toFixed(1)}`).join(" ");
        const area = n ? `${line} L${cols[n - 1].cx.toFixed(1)},${base} L${cols[0].cx.toFixed(1)},${base} Z` : "";
        return { L, T, ih, gridEnd: W - R, labelY: H - 12, ticks, cols, line, area };
    }

    get donut() {
        const src = this.state.data.sources || [];
        const total = src.reduce((a, s) => a + s.cost, 0);
        let cum = 0;
        const segs = src.map((s) => {
            const pct = total ? (s.cost / total) * 100 : 0;
            const len = Math.max(pct - 0.8, 0.1);
            const seg = {
                id: s.id, name: s.name, cost: s.cost, pct, color: SOURCE_COLORS[s.id] || "#64748b",
                dash: `${len.toFixed(2)} ${(100 - len).toFixed(2)}`, offset: (25 - cum).toFixed(2),
                selected: this.state.filters.sources.includes(s.id),
                tipTitle: s.name,
                tipLines: [this.money(s.cost), this.pct(pct), `${s.lines} ${_t("lines")}`, _t("Click to filter")],
            };
            cum += pct;
            return seg;
        });
        return { segs, center: this.compact(total) };
    }

    barRows(list, key, valueKey = "cost") {
        const rows = [...(list || [])];
        if (valueKey === "average") {
            rows.sort((a, b) => b.average - a.average);
        }
        const max = Math.max(0, ...rows.map((r) => r[valueKey])) || 1;
        return rows.map((r, i) => ({
            key: `${key}:${valueKey}:${r.id || r.name}`,
            id: r.id, name: r.name, filterKey: key,
            pct: Math.max(2, (r[valueKey] / max) * 100),
            color: PALETTE[i % PALETTE.length],
            selected: this.isSelected(key, r.id),
            valueText: this.money(valueKey === "average" ? r.average : r.cost),
            tipTitle: r.name,
            tipLines: [
                `${_t("Cost")}: ${this.money(r.cost)} (${this.pct(r.share)})`,
                `${_t("Exams")}: ${r.exams}`,
                `${_t("Avg / exam")}: ${this.money(r.average)}`,
                `${_t("Quantity")}: ${this.num(r.qty)}`,
                ...(r.id ? [_t("Click to filter")] : []),
            ],
        }));
    }

    get roomBars() { return this.barRows(this.state.data.rooms, "room_ids"); }
    get roomAvgBars() { return this.barRows(this.state.data.rooms, "room_ids", "average"); }
    get examBars() { return this.barRows(this.state.data.exams_by_type, "exam_ids"); }
    get productBars() { return this.barRows(this.state.data.products, "product_ids"); }

    get tableRows() {
        return (this.state.data.rooms || []).map((r, i) => ({ ...r, color: PALETTE[i % PALETTE.length] }));
    }

    // ------------------------------------------------------------------ tooltip
    showTip(ev, item) {
        if (!item || !item.tipLines) {
            return;
        }
        const x = ev.clientX + 240 > window.innerWidth ? ev.clientX - 230 : ev.clientX + 14;
        this.state.tip = { x, y: ev.clientY + 14, title: item.tipTitle, lines: item.tipLines };
    }

    hideTip() {
        this.state.tip = null;
    }
}

registry.category("actions").add("radiology_consumables.cost_analytics", RcCostAnalyticsDashboard);
