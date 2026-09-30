/** @odoo-module **/

import {
    Component,
    useState,
    useRef,
    onWillStart,
    onMounted,
    onWillUnmount,
    useExternalListener,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import {
    drawLineChart,
    drawHBarChart,
    drawDonutChart,
    drawColumnChart,
    drawSparkline,
    hitTestLine,
    hitTestHBarRow,
    hitTestDonut,
    hitTestColumn,
} from "./dashboard_charts";

const PRESETS = {
    this_month: "This Month",
    last_3_months: "Last 3 Months",
    last_12_months: "Last 12 Months",
    this_year: "This Year",
    custom: "Custom",
};

const THEME_STORAGE_KEY = "insurance_dashboard_theme";
// The Cards and Charts pages are separate client actions but share one set of
// filters: they are kept for the browser session so switching pages (or
// coming back from a drill-down) does not reset them.
const FILTERS_STORAGE_KEY = "insurance_dashboard_filters";
const DASHBOARD_ACTIONS = {
    cards: "insurance_management.action_insurance_dashboard_cards",
    charts: "insurance_management.action_insurance_dashboard_charts",
};
// Small pause between pressing a card and navigating, so the press/ripple
// feedback is actually seen before the view changes.
const NAVIGATION_DELAY_MS = 160;
const ANIMATION_MS = 650;

function todayIso() {
    return new Date().toISOString().slice(0, 10);
}

function addMonthsIso(dateStr, months) {
    const d = new Date(dateStr);
    d.setDate(1);
    d.setMonth(d.getMonth() + months);
    return d.toISOString().slice(0, 10);
}

/** Start/end dates for a (non-custom) period preset. */
function datesForPreset(preset) {
    const today = todayIso();
    switch (preset) {
        case "this_month":
            return { dateFrom: startOfMonthIso(), dateTo: today };
        case "last_3_months":
            return { dateFrom: addMonthsIso(today, -2), dateTo: today };
        case "this_year":
            return { dateFrom: startOfYearIso(), dateTo: today };
        case "last_12_months":
        default:
            return { dateFrom: addMonthsIso(today, -11), dateTo: today };
    }
}

function startOfYearIso() {
    const d = new Date();
    return `${d.getFullYear()}-01-01`;
}

function startOfMonthIso() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

function endOfMonthIso(firstOfMonthIso) {
    const [year, month] = firstOfMonthIso.split("-").map(Number);
    const last = new Date(year, month, 0).getDate();
    return `${year}-${String(month).padStart(2, "0")}-${String(last).padStart(2, "0")}`;
}

const OPEN_CLAIM_DOMAIN = [["state", "not in", ["paid", "cancelled", "rejected"]]];

export class InsuranceDashboard extends Component {
    static template = "insurance_management.InsuranceDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");

        // Which of the two dashboard pages this is (set by the client action).
        const actionContext = (this.props.action && this.props.action.context) || {};
        this.mode = actionContext.dashboard_mode === "charts" ? "charts" : "cards";

        this.canvases = {
            trend: useRef("trendCanvas"),
            outstanding: useRef("stateCanvas"),
            companies: useRef("companiesCanvas"),
            plans: useRef("plansCanvas"),
            products: useRef("productsCanvas"),
            status: useRef("statusCanvas"),
            coverage: useRef("coverageCanvas"),
            aging: useRef("agingCanvas"),
            funnel: useRef("funnelCanvas"),
            sparkOrders: useRef("sparkOrders"),
            sparkSales: useRef("sparkSales"),
            sparkCovered: useRef("sparkCovered"),
            sparkCustomer: useRef("sparkCustomer"),
        };
        this.tooltipRef = useRef("tooltip");

        this.state = useState({
            loading: true,
            darkMode: this._detectInitialDarkMode(),
            data: null,
            meta: { companies: [], plans: [] },
            tooltip: { visible: false, title: "", rows: [] },
            filters: this._loadStoredFilters() || {
                preset: "last_12_months",
                ...datesForPreset("last_12_months"),
                companyIds: [],
                planIds: [],
            },
        });

        this._hover = {};
        this._progress = 1;
        this._animFrame = null;

        // Follow the OS/browser color scheme live as long as the user
        // hasn't explicitly picked a theme with the toggle button.
        this._systemDarkMql = window.matchMedia
            ? window.matchMedia("(prefers-color-scheme: dark)")
            : null;
        this._onSystemDarkChange = (ev) => {
            if (!localStorage.getItem(THEME_STORAGE_KEY)) {
                this.state.darkMode = ev.matches;
                requestAnimationFrame(() => this._renderCharts());
            }
        };
        if (this._systemDarkMql) {
            this._systemDarkMql.addEventListener("change", this._onSystemDarkChange);
        }

        onWillStart(async () => {
            await this._loadMeta();
            await this._loadData();
        });

        onMounted(() => this._animateCharts());
        onWillUnmount(() => {
            if (this._systemDarkMql) {
                this._systemDarkMql.removeEventListener("change", this._onSystemDarkChange);
            }
            cancelAnimationFrame(this._animFrame);
        });
        useExternalListener(window, "resize", () => this._renderCharts());
    }

    _detectInitialDarkMode() {
        const saved = localStorage.getItem(THEME_STORAGE_KEY);
        if (saved === "dark") return true;
        if (saved === "light") return false;
        // No explicit user choice yet: follow the system/browser theme.
        return Boolean(
            window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
        );
    }

    _loadStoredFilters() {
        try {
            const saved = JSON.parse(sessionStorage.getItem(FILTERS_STORAGE_KEY) || "null");
            if (!saved) {
                return null;
            }
            const filters = {
                preset: saved.preset || "last_12_months",
                dateFrom: saved.dateFrom,
                dateTo: saved.dateTo,
                companyIds: saved.companyIds || [],
                planIds: saved.planIds || [],
            };
            // A saved "Last 3 Months" must mean the last 3 months *today*.
            if (filters.preset !== "custom") {
                Object.assign(filters, datesForPreset(filters.preset));
            }
            return filters;
        } catch {
            return null;
        }
    }

    _saveFilters() {
        try {
            sessionStorage.setItem(FILTERS_STORAGE_KEY, JSON.stringify(this.state.filters));
        } catch {
            // storage unavailable (private mode...): filters just won't persist
        }
    }

    switchMode(mode) {
        if (mode === this.mode) {
            return;
        }
        this._saveFilters();
        this.action.doAction(DASHBOARD_ACTIONS[mode], { clearBreadcrumbs: true });
    }

    async _loadMeta() {
        const meta = await this.orm.call("insurance.dashboard", "get_filters_meta", []);
        this.state.meta = meta;
    }

    async _loadData() {
        this.state.loading = true;
        this._saveFilters();
        const f = this.state.filters;
        const data = await this.orm.call("insurance.dashboard", "get_dashboard_data", [], {
            date_from: f.dateFrom,
            date_to: f.dateTo,
            company_ids: f.companyIds.length ? f.companyIds : false,
            plan_ids: f.planIds.length ? f.planIds : false,
            mode: this.mode,
        });
        this.state.data = data;
        this.state.loading = false;
        this._hover = {};
        requestAnimationFrame(() => this._animateCharts());
    }

    // ------------------------------------------------------------------
    // Filters
    // ------------------------------------------------------------------
    onPresetChange(ev) {
        const preset = ev.target.value;
        this.state.filters.preset = preset;
        if (preset !== "custom") {
            Object.assign(this.state.filters, datesForPreset(preset));
            this._loadData();
        }
    }

    onDateFromChange(ev) {
        this.state.filters.dateFrom = ev.target.value;
        this.state.filters.preset = "custom";
    }

    onDateToChange(ev) {
        this.state.filters.dateTo = ev.target.value;
        this.state.filters.preset = "custom";
    }

    onCompanyToggle(id) {
        const ids = this.state.filters.companyIds;
        const idx = ids.indexOf(id);
        if (idx === -1) ids.push(id);
        else ids.splice(idx, 1);
        this._loadData();
    }

    onPlanToggle(id) {
        const ids = this.state.filters.planIds;
        const idx = ids.indexOf(id);
        if (idx === -1) ids.push(id);
        else ids.splice(idx, 1);
        this._loadData();
    }

    applyCustomRange() {
        this._loadData();
    }

    resetFilters() {
        this.state.filters = {
            preset: "last_12_months",
            ...datesForPreset("last_12_months"),
            companyIds: [],
            planIds: [],
        };
        this._loadData();
    }

    toggleDarkMode() {
        this.state.darkMode = !this.state.darkMode;
        localStorage.setItem(THEME_STORAGE_KEY, this.state.darkMode ? "dark" : "light");
        requestAnimationFrame(() => this._renderCharts());
    }

    get presetLabel() {
        return PRESETS[this.state.filters.preset] || "Custom";
    }

    // ------------------------------------------------------------------
    // Formatting
    // ------------------------------------------------------------------
    formatMoney(value, compact = false) {
        const symbol = (this.state.data && this.state.data.currency_symbol) || "";
        const num = Number(value) || 0;
        if (compact) {
            if (Math.abs(num) >= 1000000) return `${symbol}${(num / 1000000).toFixed(1)}M`;
            if (Math.abs(num) >= 1000) return `${symbol}${(num / 1000).toFixed(1)}k`;
            return `${symbol}${num.toFixed(0)}`;
        }
        return `${symbol}${num.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        })}`;
    }

    formatNumber(value) {
        return Number(value || 0).toLocaleString();
    }

    formatPercent(value) {
        return `${(Number(value) || 0).toFixed(1)}%`;
    }

    formatDays(value) {
        return `${Math.round(Number(value) || 0)} days`;
    }

    /** Returns {cls, icon, text} for a KPI's "vs previous period" badge. */
    getDelta(key) {
        const deltas = this.state.data && this.state.data.kpi_deltas;
        if (!deltas || !(key in deltas)) {
            return null;
        }
        const value = deltas[key];
        if (value === null) {
            return { cls: "o_id_delta_new", icon: "fa-star", text: "New" };
        }
        if (value === 0) {
            return { cls: "o_id_delta_flat", icon: "fa-minus", text: "0%" };
        }
        const up = value > 0;
        return {
            cls: up ? "o_id_delta_up" : "o_id_delta_down",
            icon: up ? "fa-arrow-up" : "fa-arrow-down",
            text: `${Math.abs(value).toFixed(1)}%`,
        };
    }

    // ------------------------------------------------------------------
    // Press feedback: ripple on every clickable card
    // ------------------------------------------------------------------
    onPointerDown(ev) {
        const card = ev.target.closest && ev.target.closest(".o_id_ripple");
        if (!card) {
            return;
        }
        const rect = card.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height) * 1.6;
        const wave = document.createElement("span");
        wave.className = "o_id_ripple_wave";
        wave.style.width = wave.style.height = `${size}px`;
        wave.style.left = `${ev.clientX - rect.left - size / 2}px`;
        wave.style.top = `${ev.clientY - rect.top - size / 2}px`;
        card.appendChild(wave);
        setTimeout(() => wave.remove(), 650);
    }

    // ------------------------------------------------------------------
    // Drill-down (click-through) navigation
    // ------------------------------------------------------------------
    _saleDrillDomain(extra = []) {
        const f = this.state.filters;
        const domain = [
            ["insurance_enabled", "=", true],
            ["state", "in", ["sale", "done"]],
            ["date_order", ">=", `${f.dateFrom} 00:00:00`],
            ["date_order", "<=", `${f.dateTo} 23:59:59`],
        ];
        if (f.companyIds.length) domain.push(["insurance_company_id", "in", f.companyIds]);
        if (f.planIds.length) domain.push(["insurance_plan_id", "in", f.planIds]);
        return domain.concat(extra);
    }

    _claimDrillDomain(extra = []) {
        const f = this.state.filters;
        const domain = [
            ["date_from", "<=", f.dateTo],
            ["date_to", ">=", f.dateFrom],
        ];
        if (f.companyIds.length) domain.push(["insurance_company_id", "in", f.companyIds]);
        return domain.concat(extra);
    }

    _navigate(actionDef) {
        setTimeout(() => this.action.doAction(actionDef), NAVIGATION_DELAY_MS);
    }

    _openSaleOrders(name, extraDomain = [], overrideDomain = null) {
        this._navigate({
            type: "ir.actions.act_window",
            name,
            res_model: "sale.order",
            view_mode: "list,form",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain: overrideDomain || this._saleDrillDomain(extraDomain),
            target: "current",
        });
    }

    _openClaims(name, extraDomain = []) {
        this._navigate({
            type: "ir.actions.act_window",
            name,
            res_model: "insurance.claim",
            view_mode: "list,form",
            views: [
                [false, "kanban"],
                [false, "list"],
                [false, "form"],
            ],
            domain: this._claimDrillDomain(extraDomain),
            target: "current",
        });
    }

    _openInvoices(name, domain) {
        this._navigate({
            type: "ir.actions.act_window",
            name,
            res_model: "account.move",
            view_mode: "list,form",
            views: [
                [false, "list"],
                [false, "form"],
            ],
            domain,
            target: "current",
        });
    }

    openClaim(id) {
        this._navigate({
            type: "ir.actions.act_window",
            res_model: "insurance.claim",
            res_id: id,
            view_mode: "form",
            views: [[false, "form"]],
            target: "current",
        });
    }

    openPatientOrders(patient) {
        this._openSaleOrders(patient.name, [["partner_id", "=", patient.id]]);
    }

    // KPI cards ---------------------------------------------------------
    onKpiOrdersClick() {
        this._openSaleOrders("Insured Orders");
    }
    onKpiTotalSalesClick() {
        this._openSaleOrders("Insured Sales");
    }
    onKpiCoveredClick() {
        this._openSaleOrders("Insurance Covered Orders");
    }
    onKpiCustomerClick() {
        this._openSaleOrders("Customer Share Orders");
    }
    onKpiClaimedClick() {
        this._openClaims("Insurance Claims");
    }
    onKpiCollectedClick() {
        this._openClaims("Insurance Claims");
    }
    onKpiRejectedClick() {
        this._openClaims("Insurance Claims (with rejections)", [["total_rejected", ">", 0]]);
    }
    onKpiOutstandingClick() {
        this._openClaims("Open Claims", OPEN_CLAIM_DOMAIN);
    }
    onKpiOpenClaimsClick() {
        this._openClaims("Open Claims", OPEN_CLAIM_DOMAIN);
    }
    onKpiClaimsCountClick() {
        this._openClaims("Insurance Claims");
    }
    onKpiOpenReceivableClick() {
        this._openInvoices("Open Insurance Invoices", this.state.data.aging.base_domain);
    }
    onKpiOverdueClick() {
        this._openInvoices("Overdue Insurance Invoices", this.state.data.aging.overdue_domain);
    }

    // Legends -------------------------------------------------------------
    onStatusLegendClick(index) {
        const status = this.state.data.claim_status;
        this._openClaims(status.labels[index], [["state", "=", status.keys[index]]]);
    }

    // ------------------------------------------------------------------
    // Charts: definitions (draw / hit-test / tooltip / click) per canvas
    // ------------------------------------------------------------------
    _chartDefs() {
        const d = this.state.data;
        if (!d || this.mode !== "charts") {
            return {};
        }
        const dark = this.state.darkMode;
        const compact = (v) => this.formatMoney(v, true);
        const full = (v) => this.formatMoney(v);
        const el = (key) => this.canvases[key].el;
        const k = d.kpis;

        const funnel = {
            labels: ["Claimed", "Rejected", "Collected", "Outstanding"],
            values: [k.total_claimed, k.total_rejected, k.total_collected, k.total_outstanding],
            colors: ["#6366F1", "#EF4444", "#22C55E", "#F59E0B"],
        };
        const hbar = (key, block, color, click) => ({
            hit: (ev) => hitTestHBarRow(el(key), block.labels.length, ev.clientY),
            draw: (p, h) => drawHBarChart(el(key), block.labels, block.values, dark, compact, color, p, h),
            tip: (i) => ({
                title: block.labels[i],
                rows: [{ color, label: "Amount", value: full(block.values[i]) }],
            }),
            click,
        });

        return {
            trend: {
                hit: (ev) => hitTestLine(el("trend"), d.sales_trend.labels.length, ev.clientX),
                draw: (p, h) =>
                    drawLineChart(el("trend"), d.sales_trend.labels, d.sales_trend.series, dark, compact, p, h),
                tip: (i) => ({
                    title: d.sales_trend.labels[i],
                    rows: d.sales_trend.series
                        .map((s) => ({ color: s.color, label: s.label, value: full(s.data[i]) }))
                        .concat([
                            {
                                color: "#94A3B8",
                                label: "Orders",
                                value: this.formatNumber(d.sales_trend.order_counts[i]),
                            },
                        ]),
                }),
                click: (i) => {
                    const first = d.sales_trend.months[i];
                    this._openSaleOrders(
                        d.sales_trend.labels[i],
                        [
                            ["date_order", ">=", `${first} 00:00:00`],
                            ["date_order", "<=", `${endOfMonthIso(first)} 23:59:59`],
                        ]
                    );
                },
            },
            status: {
                hit: (ev) => hitTestDonut(el("status"), d.claim_status.counts, ev.clientX, ev.clientY),
                draw: (p, h) =>
                    drawDonutChart(
                        el("status"),
                        d.claim_status.counts,
                        d.claim_status.colors,
                        dark,
                        "Claims",
                        String(d.claim_status.counts.reduce((a, b) => a + b, 0)),
                        p,
                        h
                    ),
                tip: (i) => ({
                    title: d.claim_status.labels[i],
                    rows: [
                        { color: d.claim_status.colors[i], label: "Claims", value: this.formatNumber(d.claim_status.counts[i]) },
                        { color: d.claim_status.colors[i], label: "Claimed", value: full(d.claim_status.amounts[i]) },
                    ],
                }),
                click: (i) => this.onStatusLegendClick(i),
            },
            coverage: {
                hit: (ev) => hitTestDonut(el("coverage"), d.coverage_split.values, ev.clientX, ev.clientY),
                draw: (p, h) =>
                    drawDonutChart(
                        el("coverage"),
                        d.coverage_split.values,
                        d.coverage_split.colors,
                        dark,
                        "Covered",
                        this.formatPercent(k.coverage_ratio),
                        p,
                        h
                    ),
                tip: (i) => ({
                    title: d.coverage_split.labels[i],
                    rows: [{ color: d.coverage_split.colors[i], label: "Amount", value: full(d.coverage_split.values[i]) }],
                }),
                click: () => this._openSaleOrders("Insured Orders"),
            },
            aging: {
                hit: (ev) => hitTestColumn(el("aging"), d.aging.labels.length, ev.clientX),
                draw: (p, h) =>
                    drawColumnChart(el("aging"), d.aging.labels, d.aging.values, d.aging.colors, dark, compact, p, h),
                tip: (i) => ({
                    title: d.aging.labels[i],
                    rows: [
                        { color: d.aging.colors[i], label: "Open amount", value: full(d.aging.values[i]) },
                        { color: d.aging.colors[i], label: "Invoices", value: this.formatNumber(d.aging.counts[i]) },
                    ],
                }),
                click: (i) => this._openInvoices(`Insurance invoices - ${d.aging.labels[i]}`, d.aging.domains[i]),
            },
            funnel: {
                hit: (ev) => hitTestColumn(el("funnel"), funnel.labels.length, ev.clientX),
                draw: (p, h) => drawColumnChart(el("funnel"), funnel.labels, funnel.values, funnel.colors, dark, compact, p, h),
                tip: (i) => ({
                    title: funnel.labels[i],
                    rows: [{ color: funnel.colors[i], label: "Amount", value: full(funnel.values[i]) }],
                }),
                click: (i) =>
                    i === 3
                        ? this._openClaims("Open Claims", OPEN_CLAIM_DOMAIN)
                        : i === 1
                        ? this._openClaims("Insurance Claims (with rejections)", [["total_rejected", ">", 0]])
                        : this._openClaims("Insurance Claims"),
            },
            outstanding: hbar("outstanding", d.outstanding_by_company, "#F59E0B", (i) =>
                this._openClaims(d.outstanding_by_company.labels[i], [
                    ["insurance_company_id", "=", d.outstanding_by_company.ids[i]],
                    ...OPEN_CLAIM_DOMAIN,
                ])
            ),
            companies: hbar("companies", d.top_companies, "#6366F1", (i) =>
                this._openSaleOrders(d.top_companies.labels[i], [["insurance_company_id", "=", d.top_companies.ids[i]]])
            ),
            plans: hbar("plans", d.top_plans, "#F59E0B", (i) =>
                this._openSaleOrders(d.top_plans.labels[i], [["insurance_plan_id", "=", d.top_plans.ids[i]]])
            ),
            products: hbar("products", d.top_products, "#14B8A6", (i) =>
                this._openSaleOrders(d.top_products.labels[i], [["order_line.product_id", "=", d.top_products.ids[i]]])
            ),
        };
    }

    onChartMove(key, ev) {
        const def = this._chartDefs()[key];
        if (!def || !this.canvases[key].el) {
            return;
        }
        const index = def.hit(ev);
        if (index !== (this._hover[key] ?? -1)) {
            this._hover[key] = index;
            def.draw(1, index);
            if (index >= 0) {
                const tip = def.tip(index);
                this.state.tooltip.title = tip.title;
                this.state.tooltip.rows = tip.rows;
                this.state.tooltip.visible = true;
            } else {
                this.state.tooltip.visible = false;
            }
            ev.target.style.cursor = index >= 0 ? "pointer" : "default";
        }
        this._positionTooltip(ev);
    }

    onChartLeave(key) {
        const def = this._chartDefs()[key];
        this._hover[key] = -1;
        if (def && this.canvases[key].el) {
            def.draw(1, -1);
        }
        this.state.tooltip.visible = false;
    }

    onChartClick(key, ev) {
        const def = this._chartDefs()[key];
        if (!def) {
            return;
        }
        const index = def.hit(ev);
        if (index >= 0) {
            this.state.tooltip.visible = false;
            def.click(index);
        }
    }

    _positionTooltip(ev) {
        const tip = this.tooltipRef.el;
        if (!tip) {
            return;
        }
        const gap = 16;
        let x = ev.clientX + gap;
        let y = ev.clientY + gap;
        if (x + tip.offsetWidth > window.innerWidth - 8) {
            x = ev.clientX - tip.offsetWidth - gap;
        }
        if (y + tip.offsetHeight > window.innerHeight - 8) {
            y = ev.clientY - tip.offsetHeight - gap;
        }
        tip.style.left = `${Math.max(8, x)}px`;
        tip.style.top = `${Math.max(8, y)}px`;
    }

    // ------------------------------------------------------------------
    // Rendering
    // ------------------------------------------------------------------
    _animateCharts() {
        cancelAnimationFrame(this._animFrame);
        if (!this.state.data) {
            return;
        }
        const start = performance.now();
        const step = (now) => {
            const x = Math.min(1, (now - start) / ANIMATION_MS);
            this._progress = 1 - Math.pow(1 - x, 3);
            this._renderCharts();
            if (x < 1) {
                this._animFrame = requestAnimationFrame(step);
            } else {
                this._progress = 1;
            }
        };
        this._animFrame = requestAnimationFrame(step);
    }

    _renderCharts() {
        const data = this.state.data;
        if (!data) {
            return;
        }
        const defs = this._chartDefs();
        for (const [key, def] of Object.entries(defs)) {
            if (this.canvases[key] && this.canvases[key].el) {
                def.draw(this._progress, this._hover[key] ?? -1);
            }
        }

        const trend = data.sales_trend;
        if (this.canvases.sparkOrders.el) {
            drawSparkline(this.canvases.sparkOrders.el, trend.order_counts, "#6366F1");
        }
        if (this.canvases.sparkSales.el) {
            drawSparkline(this.canvases.sparkSales.el, trend.series[0].data, "#3B82F6");
        }
        if (this.canvases.sparkCovered.el) {
            drawSparkline(this.canvases.sparkCovered.el, trend.series[1].data, "#22C55E");
        }
        if (this.canvases.sparkCustomer.el) {
            drawSparkline(this.canvases.sparkCustomer.el, trend.series[2].data, "#F59E0B");
        }
    }
}

registry.category("actions").add("insurance_dashboard", InsuranceDashboard);
