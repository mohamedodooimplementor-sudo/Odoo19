/** @odoo-module **/

import { Component, useState, useRef, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { loadJS } from "@web/core/assets";

export class ConstructionBudgetDashboard extends Component {
    static template = "construction_project_budget.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.rootRef = useRef("root");
        this.chartRef = useRef("categoryChart");
        this.sourceChartRef = useRef("sourceChart");
        this.trendChartRef = useRef("trendChart");
        this.chart = null;
        this.sourceChart = null;
        this.trendChart = null;

        this.state = useState({
            loading: true,
            kpis: {
                total_budgets: 0,
                active_budgets: 0,
                total_planned: 0,
                total_committed: 0,
                total_actual: 0,
                total_income: 0,
                net_profit: 0,
                over_budget_count: 0,
                actual_trend_pct: 0,
                currency_symbol: "",
                currency_position: "after",
            },
            projects: [],
            categories: [],
            sources: [],
            monthly_trend: [],
            alerts: [],
            recent_expenses: [],
            projectOptions: [],
            selectedProject: null,
        });

        onWillStart(async () => {
            await loadJS("/web/static/lib/Chart/Chart.js");
            // Chart.js v3/v4's tree-shakeable build requires every controller/
            // element/plugin to be explicitly registered before use - only the
            // older, fully-bundled "auto" build registers everything globally
            // on load. Register defensively so this dashboard's charts render
            // regardless of which build this Odoo version bundles; harmless
            // (a no-op) if everything is already auto-registered.
            if (window.Chart && window.Chart.register && window.Chart.registerables) {
                window.Chart.register(...window.Chart.registerables);
            }
            await this.loadData();
        });

        onMounted(() => {
            this.renderCharts();
        });

        onWillUnmount(() => {
            if (this.chart) {
                this.chart.destroy();
            }
            if (this.sourceChart) {
                this.sourceChart.destroy();
            }
            if (this.trendChart) {
                this.trendChart.destroy();
            }
        });
    }

    async loadData() {
        const data = await this.orm.call(
            "construction.project.budget",
            "get_dashboard_data",
            [],
            { project_id: this.state.selectedProject || false }
        );
        this.state.kpis = data.kpis;
        this.state.projects = data.projects;
        this.state.categories = data.categories;
        this.state.sources = data.sources || [];
        this.state.monthly_trend = data.monthly_trend || [];
        this.state.alerts = data.alerts || [];
        this.state.recent_expenses = data.recent_expenses;
        this.state.projectOptions = data.project_options || [];
        this.state.loading = false;
        requestAnimationFrame(() => this.renderCharts());
    }

    onProjectFilterChange(ev) {
        const val = ev.target.value;
        this.state.selectedProject = val ? parseInt(val, 10) : null;
        this.loadData();
    }

    /**
     * Resolve any CSS color (including var(--bs-...)) to a concrete "rgb(r, g, b)"
     * string by letting the browser compute it. Chart.js draws on a canvas and
     * cannot read CSS variables itself, so this is how the charts follow
     * whichever theme (light / dark) Odoo is currently displaying.
     */
    resolveColor(cssValue, fallback) {
        const host = this.rootRef.el || document.body;
        const probe = document.createElement("span");
        probe.style.color = cssValue;
        probe.style.display = "none";
        host.appendChild(probe);
        const color = getComputedStyle(probe).color;
        probe.remove();
        return color || fallback;
    }

    withAlpha(color, alpha) {
        const parts = (color || "").match(/[\d.]+/g);
        if (!parts || parts.length < 3) {
            return color;
        }
        return `rgba(${parts[0]}, ${parts[1]}, ${parts[2]}, ${alpha})`;
    }

    getChartColors() {
        const text = this.resolveColor("var(--bs-secondary-color)", "#6b7280");
        const body = this.resolveColor("var(--bs-body-color)", "#1f2430");
        const surface = this.resolveColor("var(--bs-body-bg)", "#ffffff");
        return {
            text,
            grid: this.withAlpha(body, 0.1),
            surface,
        };
    }

    renderCharts() {
        try {
            this.renderCategoryChart();
        } catch (e) {
            console.error("Construction Budget dashboard: category chart failed to render", e);
        }
        try {
            this.renderSourceChart();
        } catch (e) {
            console.error("Construction Budget dashboard: source chart failed to render", e);
        }
        try {
            this.renderTrendChart();
        } catch (e) {
            console.error("Construction Budget dashboard: trend chart failed to render", e);
        }
    }

    renderCategoryChart() {
        if (!this.chartRef.el) {
            return;
        }
        if (this.chart) {
            this.chart.destroy();
            this.chart = null;
        }
        if (!this.state.categories.length) {
            return;
        }
        const ctx = this.chartRef.el.getContext("2d");
        const { text: textColor, grid: gridColor } = this.getChartColors();
        this.chart = new Chart(ctx, {
            type: "bar",
            data: {
                labels: this.state.categories.map((c) => c.name),
                datasets: [
                    {
                        label: "Planned",
                        backgroundColor: "#8b6cf7",
                        borderRadius: 4,
                        data: this.state.categories.map((c) => c.planned),
                    },
                    {
                        label: "Actual",
                        backgroundColor: "#ec4899",
                        borderRadius: 4,
                        data: this.state.categories.map((c) => c.actual),
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                onHover: (event, elements) => {
                    event.native.target.style.cursor = elements.length ? "pointer" : "default";
                },
                onClick: (event, elements) => {
                    if (!elements.length) {
                        return;
                    }
                    const category = this.state.categories[elements[0].index];
                    if (category) {
                        this.openCategoryActuals(category.name);
                    }
                },
                plugins: {
                    legend: { position: "top", align: "end", labels: { color: textColor, boxWidth: 10 } },
                },
                scales: {
                    x: { ticks: { color: textColor }, grid: { display: false } },
                    y: { beginAtZero: true, ticks: { color: textColor }, grid: { color: gridColor } },
                },
            },
        });
    }

    renderSourceChart() {
        if (!this.sourceChartRef.el) {
            return;
        }
        if (this.sourceChart) {
            this.sourceChart.destroy();
            this.sourceChart = null;
        }
        if (!this.state.sources.length) {
            return;
        }
        const { text: textColor, surface: surfaceColor } = this.getChartColors();
        const palette = ["#8b6cf7", "#ec4899", "#f59e0b", "#3b82f6", "#14b8a6", "#ef4444", "#22c55e"];
        const ctx = this.sourceChartRef.el.getContext("2d");
        this.sourceChart = new Chart(ctx, {
            type: "doughnut",
            data: {
                labels: this.state.sources.map((s) => this.sourceLabel(s.name)),
                datasets: [
                    {
                        data: this.state.sources.map((s) => s.amount),
                        backgroundColor: this.state.sources.map((s, i) => palette[i % palette.length]),
                        borderWidth: 3,
                        borderColor: surfaceColor,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                onHover: (event, elements) => {
                    event.native.target.style.cursor = elements.length ? "pointer" : "default";
                },
                onClick: (event, elements) => {
                    if (!elements.length) {
                        return;
                    }
                    const source = this.state.sources[elements[0].index];
                    if (source) {
                        this.openSourceActuals(source.name);
                    }
                },
                plugins: {
                    legend: { display: false },
                },
                cutout: "68%",
            },
        });
    }

    renderTrendChart() {
        if (!this.trendChartRef.el) {
            return;
        }
        if (this.trendChart) {
            this.trendChart.destroy();
            this.trendChart = null;
        }
        if (!this.state.monthly_trend.length) {
            return;
        }
        const { text: textColor, grid: gridColor } = this.getChartColors();
        const ctx = this.trendChartRef.el.getContext("2d");
        const costGradient = ctx.createLinearGradient(0, 0, 0, 200);
        costGradient.addColorStop(0, "rgba(236, 72, 153, 0.3)");
        costGradient.addColorStop(1, "rgba(236, 72, 153, 0)");
        const incomeGradient = ctx.createLinearGradient(0, 0, 0, 200);
        incomeGradient.addColorStop(0, "rgba(34, 197, 94, 0.3)");
        incomeGradient.addColorStop(1, "rgba(34, 197, 94, 0)");
        const hasIncome = this.state.monthly_trend.some((m) => m.income);
        const datasets = [
            {
                label: "Cost",
                data: this.state.monthly_trend.map((m) => m.actual),
                borderColor: "#ec4899",
                backgroundColor: costGradient,
                fill: true,
                tension: 0.35,
                pointBackgroundColor: "#ec4899",
                pointRadius: 3,
            },
        ];
        if (hasIncome) {
            datasets.push({
                label: "Income",
                data: this.state.monthly_trend.map((m) => m.income),
                borderColor: "#22c55e",
                backgroundColor: incomeGradient,
                fill: true,
                tension: 0.35,
                pointBackgroundColor: "#22c55e",
                pointRadius: 3,
            });
        }
        this.trendChart = new Chart(ctx, {
            type: "line",
            data: {
                labels: this.state.monthly_trend.map((m) => m.label),
                datasets: datasets,
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: hasIncome, position: "top", align: "end", labels: { color: textColor, boxWidth: 10 } } },
                scales: {
                    x: { ticks: { color: textColor }, grid: { display: false } },
                    y: { beginAtZero: true, ticks: { color: textColor }, grid: { color: gridColor } },
                },
            },
        });
    }

    formatMonetary(value, symbolOverride) {
        const rounded = Math.round((value || 0) * 100) / 100;
        const formatted = rounded.toLocaleString(undefined, {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        });
        const symbol = symbolOverride || this.state.kpis.currency_symbol || "";
        if (this.state.kpis.currency_position === "before") {
            return `${symbol}${formatted}`;
        }
        return `${formatted} ${symbol}`;
    }

    formatPercent(value) {
        return Math.round(value || 0);
    }

    sourceLabel(key) {
        const labels = {
            manual: "Manual Expenses",
            employee_expense: "Employee Expenses",
            vendor_bill: "Vendor Bills",
            customer_invoice: "Customer Invoices",
            journal_entry: "Journal Entries",
            timesheet: "Timesheets",
            labor: "Labor",
            stock_consumption: "Stock Consumption",
            other: "Other",
        };
        return labels[key] || key;
    }

    utilizationClass(value) {
        if (value > 100) return "o_cbd_bar_danger";
        if (value > 80) return "o_cbd_bar_warning";
        return "o_cbd_bar_success";
    }

    alertIcon(type) {
        if (type === "danger") return "fa-exclamation-circle";
        if (type === "warning") return "fa-exclamation-triangle";
        return "fa-info-circle";
    }

    openBudget(budgetId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "construction.project.budget",
            res_id: budgetId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openAllBudgets() {
        this.actionService.doAction("construction_project_budget.action_construction_project_budget");
    }

    /**
     * Generic drill-down: open the Budgets list already filtered, so every
     * clickable KPI/chart element leads somewhere useful instead of just
     * being decorative.
     */
    openBudgetsFiltered(domain, name) {
        const baseDomain = this.state.selectedProject ? [["project_id", "=", this.state.selectedProject]] : [];
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: name || "Construction Budgets",
            res_model: "construction.project.budget",
            views: [[false, "list"], [false, "form"]],
            domain: baseDomain.concat(domain || []),
            target: "current",
        });
    }

    openOverBudget() {
        this.openBudgetsFiltered([["utilization", ">", 100]], "Over Budget");
    }

    /** Drill down into the Actual ledger, optionally filtered by category or source. */
    openActuals(domain, name) {
        const baseDomain = this.state.selectedProject ? [["project_id", "=", this.state.selectedProject]] : [];
        this.actionService.doAction({
            type: "ir.actions.act_window",
            name: name || "Actual Spending",
            res_model: "construction.project.budget.expense",
            views: [[false, "list"], [false, "form"]],
            domain: baseDomain.concat(domain || []),
            target: "current",
        });
    }

    openCategoryActuals(categoryName) {
        this.openActuals([["category_id.name", "=", categoryName]], categoryName);
    }

    openSourceActuals(sourceKey) {
        this.openActuals([["source_type", "=", sourceKey]], this.sourceLabel(sourceKey));
    }

    openActualRecord(expenseId) {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "construction.project.budget.expense",
            res_id: expenseId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add(
    "construction_budget_dashboard_client",
    ConstructionBudgetDashboard
);
