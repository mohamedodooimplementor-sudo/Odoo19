/** @odoo-module **/

import { registry } from "@web/core/registry";
import { loadJS } from "@web/core/assets";
import { Component, onWillStart, onMounted, onWillUnmount, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class EducationDashboard extends Component {
    static template = "prime_educational_hub.EducationDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null, loading: true, sidebarExpanded: false });
        this.charts = {};
        this.chartJsAvailable = true;

        this.studentsChartRef = useRef("studentsChart");
        this.attendanceChartRef = useRef("attendanceChart");
        this.collectionsChartRef = useRef("collectionsChart");
        this.outstandingChartRef = useRef("outstandingChart");
        this.examPerfChartRef = useRef("examPerfChart");
        this.passRateChartRef = useRef("passRateChart");
        this.certDistChartRef = useRef("certDistChart");
        this.rootRef = useRef("root");
        this.isDark = false;

        onWillStart(async () => {
            const [data] = await Promise.all([
                this.orm.call("education.dashboard", "get_dashboard_data", []),
                this._loadChartJs(),
            ]);
            this.state.data = this._normalize(data);
            this.state.loading = false;
        });

        onMounted(() => {
            this._applyTheme();
            if (this.state.data) {
                this._renderCharts();
            }
            // Odoo toggles dark mode by flipping a class/attribute somewhere in the
            // page (the exact mechanism varies by version/theme add-on, so we don't
            // hardcode it - see _computeIsDark). Watch broadly for any attribute
            // change on <html>/<body> and re-measure instead of guessing a name.
            this._themeObserver = new MutationObserver(() => {
                const wasDark = this.isDark;
                this._applyTheme();
                if (wasDark !== this.isDark && this.state.data) {
                    Object.values(this.charts).forEach((c) => c && c.destroy && c.destroy());
                    this.charts = {};
                    this._renderCharts();
                }
            });
            this._themeObserver.observe(document.documentElement, { attributes: true });
            this._themeObserver.observe(document.body, { attributes: true });
        });

        onWillUnmount(() => {
            if (this._themeObserver) this._themeObserver.disconnect();
            Object.values(this.charts).forEach((c) => c && c.destroy && c.destroy());
        });
    }

    /** Fills in safe defaults for every list/object the template reads, so a stale or
     * partial response (e.g. server not fully restarted after an update) never crashes
     * the QWeb render with "undefined is not iterable" - it just shows empty sections. */
    _normalize(data) {
        const d = data || {};
        d.kpis = d.kpis || {};
        d.currency_symbol = d.currency_symbol || "";
        d.students_by_group = d.students_by_group || [];
        d.attendance_trend = d.attendance_trend || [];
        d.exam_performance_by_group = d.exam_performance_by_group || [];
        d.collections_by_month = d.collections_by_month || [];
        d.outstanding_by_group = d.outstanding_by_group || [];
        d.top_performers = d.top_performers || [];
        d.low_performers = d.low_performers || [];
        d.teacher_activity = d.teacher_activity || [];
        d.low_attendance_groups = d.low_attendance_groups || [];
        d.certificate_distribution = d.certificate_distribution || [];
        d.pass_rate = d.pass_rate || { passed: 0, failed: 0 };
        d.planner_days = (d.planner_days || []).map((day) => ({ ...day, items: day.items || [] }));
        d.sidebar_items = d.sidebar_items || [];
        d.stat_cards = d.stat_cards || [];
        d.is_admin = !!d.is_admin;
        d.company_name = d.company_name || "";
        return d;
    }

    /** Generic act_window opener - every KPI/chart click routes through
     * this so navigation stays a one-line call at each call site. */
    _openList(resModel, domain, name, extraContext) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: resModel,
            name,
            domain,
            views: [[false, "list"], [false, "form"]],
            target: "current",
            context: extraContext || {},
        });
    }

    _today() {
        const d = new Date();
        return d.toISOString().slice(0, 10);
    }

    openStudents() {
        this._openList("education.student", [["state", "=", "active"]], "Active Students");
    }
    openGroups() {
        this._openList("education.group", [["state", "=", "active"]], "Active Groups");
    }
    openTodaysSessions() {
        this._openList("education.session", [["date", "=", this._today()]], "Today's Sessions");
    }
    openTodaysAttendance() {
        this._openList("education.attendance", [["session_date", "=", this._today()]], "Today's Attendance");
    }
    openUpcomingExams() {
        this._openList("education.exam", [["exam_date", ">=", this._today()], ["state", "!=", "closed"]],
            "Upcoming Exams");
    }
    openMonthlyCollections() {
        const d = new Date();
        const monthStart = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
        this._openList("education.payment",
            [["state", "=", "confirmed"], ["payment_date", ">=", monthStart], ["payment_date", "<=", this._today()]],
            "Monthly Collections");
    }
    openOutstandingFees() {
        this._openList("education.enrollment", [["state", "=", "active"], ["outstanding_amount", ">", 0]],
            "Outstanding Fees");
    }
    openCertificates() {
        this._openList("education.certificate", [["state", "=", "issued"]], "Certificates Issued");
    }
    openTeachers() {
        this._openList("education.teacher", [], "Teachers");
    }
    openPendingPayouts() {
        this._openList("education.teacher.payout", [["state", "!=", "paid"]], "Pending Teacher Payouts");
    }

    /** Sidebar icon click - every item comes from education.dashboard.menu.item, already
     * filtered server-side to items this user is both configured AND actually allowed to
     * open (see get_visible_items()). Clicking always calls the real Odoo action behind it,
     * through the normal action service - never a static/decorative button. */
    openSidebarItem(item) {
        if (item.is_dashboard_home) return; // already home, nothing to navigate to
        this.action.doAction(item.action_id);
    }

    /** Admin-only escape hatch back to the standard Odoo Apps switcher, since the dashboard
     * is now the default landing page for module users (see res.config.settings > Dashboard
     * as Home Page). Only rendered for members of the Administration / Settings group. */
    openOdooApps() {
        window.location.href = "/odoo";
    }

    /** Sidebar hamburger - purely a compact/expanded visual toggle for the icon rail. */
    toggleSidebar() {
        this.state.sidebarExpanded = !this.state.sidebarExpanded;
    }

    /** Opens a single record's form view - used by every clickable row (top/low
     * performers, teacher activity, low-attendance groups, exam performance by group...). */
    openRecord(resModel, resId) {
        if (!resModel || !resId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: resModel,
            res_id: resId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    /** Headline stat card click (Students/Teachers/Courses/Lessons/Attendance/Performance) -
     * opens the same live list the card's own number was computed from. */
    openStatCard(card) {
        if (!card.res_model) return;
        this._openList(card.res_model, card.domain || [], card.title);
    }

    /** Planner item click - opens the actual session/exam record. */
    openPlannerItem(item) {
        if (!item.res_model || !item.res_id) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: item.res_model,
            res_id: item.res_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    /** Odoo bundles Chart.js for its own dashboards; reuse it instead of adding a new
     * external dependency. If it can't be loaded for any reason, we fall back to the
     * lightweight hand-drawn canvas charts so the dashboard still works. */
    async _loadChartJs() {
        try {
            await loadJS("/web/static/lib/Chart/Chart.js");
            this.chartJsAvailable = typeof window.Chart !== "undefined";
        } catch {
            this.chartJsAvailable = false;
        }
    }

    _renderCharts() {
        const d = this.state.data;
        if (this.chartJsAvailable) {
            this._chart(this.studentsChartRef, "bar", d.students_by_group, "#4361ee", "Students",
                (p) => p.res_id && this._openList("education.enrollment",
                    [["state", "=", "active"], ["group_id", "=", p.res_id]], p.label));
            this._chart(this.attendanceChartRef, "line", d.attendance_trend, "#00b8d9", "Attendance %",
                (p) => p.date && this._openList("education.attendance",
                    [["session_date", "=", p.date]], p.label));
            this._chart(this.collectionsChartRef, "bar", d.collections_by_month, "#00c853", "Collections",
                (p) => p.date_from && this._openList("education.payment",
                    [["state", "=", "confirmed"], ["payment_date", ">=", p.date_from], ["payment_date", "<=", p.date_to]],
                    p.label));
            this._chart(this.outstandingChartRef, "bar", d.outstanding_by_group, "#ffab00", "Outstanding",
                (p) => p.res_id && this._openList("education.enrollment",
                    [["state", "=", "active"], ["group_id", "=", p.res_id], ["outstanding_amount", ">", 0]], p.label));
            this._chart(this.examPerfChartRef, "bar", d.exam_performance_by_group, "#b026ff", "Avg %",
                (p) => p.res_id && this._openList("education.exam.result",
                    [["group_id", "=", p.res_id]], p.label));
            this._doughnut(this.passRateChartRef, [
                { label: "Passed", value: d.pass_rate.passed, color: "#00c853" },
                { label: "Failed", value: d.pass_rate.failed, color: "#ff1744" },
            ], (row) => this._openList("education.exam.result",
                [["passed", "=", row.label === "Passed"]], row.label));
            this._doughnut(
                this.certDistChartRef,
                d.certificate_distribution.map((row, i) => ({
                    label: row.label,
                    value: row.value,
                    color: ["#4361ee", "#00c853", "#ff1744", "#ffab00"][i % 4],
                })),
                (row) => this._openList("education.certificate",
                    [["state", "=", row.label.toLowerCase()]], row.label)
            );
        } else {
            const dark = this._isDarkMode();
            this._drawBarChart(this.studentsChartRef.el, d.students_by_group, "#4361ee", dark);
            this._drawLineChart(this.attendanceChartRef.el, d.attendance_trend, "#00b8d9", dark);
            this._drawBarChart(this.collectionsChartRef.el, d.collections_by_month, "#00c853", dark);
            this._drawBarChart(this.outstandingChartRef.el, d.outstanding_by_group, "#ffab00", dark);
            this._drawBarChart(this.examPerfChartRef.el, d.exam_performance_by_group, "#b026ff", dark);
        }
    }

    /** Bar/line chart using Chart.js, built from the same {label, value} point arrays
     * the backend already prepares. */
    /** Doesn't guess which class/attribute this Odoo build uses for dark mode -
     * instead it measures the *actual rendered background color* around the
     * dashboard and decides light/dark from its luminance. That works no matter
     * what mechanism (native toggle, OS preference, a theme add-on) produced it. */
    _computeIsDark() {
        let el = this.rootRef.el && this.rootRef.el.parentElement;
        for (let i = 0; el && i < 12; i++, el = el.parentElement) {
            const bg = window.getComputedStyle(el).backgroundColor;
            const parts = bg.match(/[\d.]+/g);
            if (!parts || parts.length < 3) continue;
            const [r, g, b] = parts.map(Number);
            const a = parts.length > 3 ? Number(parts[3]) : 1;
            if (a < 0.5) continue; // transparent - keep looking further up
            const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
            return luminance < 0.5;
        }
        return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
    }

    /** The Prime dashboard now always uses its own purple brand look (see the reference
     * design) instead of following Odoo's light/dark toggle, so this always resolves to
     * dark - which keeps chart text/grid colors readable against the dark purple cards
     * no matter what theme the rest of the backend is in. */
    _applyTheme() {
        this.isDark = true;
        if (this.rootRef.el) {
            this.rootRef.el.classList.add("o_education_dark");
        }
    }

    _isDarkMode() {
        return this.isDark;
    }

    _chart(ref, type, points, color, seriesLabel, onPointClick) {
        if (!ref.el || !points || !points.length) return;
        const dark = this._isDarkMode();
        const textColor = dark ? "#9aa0b4" : "#6b7280";
        const gridColor = dark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)";
        const key = ref.el.getAttribute("t-ref") || Math.random();
        this.charts[key] = new window.Chart(ref.el.getContext("2d"), {
            type,
            data: {
                labels: points.map((p) => p.label),
                datasets: [
                    {
                        label: seriesLabel,
                        data: points.map((p) => p.value),
                        backgroundColor: type === "line" ? "transparent" : color,
                        borderColor: color,
                        borderWidth: 2,
                        tension: 0.3,
                        spanGaps: true,
                        pointRadius: type === "line" ? 3 : 0,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                onClick: onPointClick ? (evt, elements) => {
                    if (elements.length) onPointClick(points[elements[0].index]);
                } : undefined,
                onHover: onPointClick ? (evt, elements) => {
                    evt.native.target.style.cursor = elements.length ? "pointer" : "default";
                } : undefined,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: textColor }, grid: { color: gridColor } },
                    y: { beginAtZero: true, ticks: { color: textColor }, grid: { color: gridColor } },
                },
            },
        });
    }

    /** Doughnut chart for distributions (pass/fail, certificate status...). */
    _doughnut(ref, rows, onSliceClick) {
        if (!ref.el || !rows || !rows.filter((r) => r.value).length) return;
        const dark = this._isDarkMode();
        const textColor = dark ? "#c3c7d9" : "#374151";
        const key = (ref.el.getAttribute("t-ref") || "") + "_doughnut";
        this.charts[key] = new window.Chart(ref.el.getContext("2d"), {
            type: "doughnut",
            data: {
                labels: rows.map((r) => r.label),
                datasets: [
                    {
                        data: rows.map((r) => r.value),
                        backgroundColor: rows.map((r) => r.color),
                        borderWidth: 1,
                        borderColor: dark ? "#1c1e2b" : "#ffffff",
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                onClick: onSliceClick ? (evt, elements) => {
                    if (elements.length) onSliceClick(rows[elements[0].index]);
                } : undefined,
                onHover: onSliceClick ? (evt, elements) => {
                    evt.native.target.style.cursor = elements.length ? "pointer" : "default";
                } : undefined,
                plugins: {
                    legend: {
                        position: "bottom",
                        labels: { boxWidth: 12, font: { size: 11 }, color: textColor },
                    },
                },
            },
        });
    }

    /** Minimal dependency-free canvas bar chart (fallback only, if Chart.js can't load). */
    _drawBarChart(canvas, points, color, dark) {
        if (!canvas || !points || !points.length) return;
        const ctx = canvas.getContext("2d");
        const dpr = window.devicePixelRatio || 1;
        const width = canvas.clientWidth;
        const height = canvas.clientHeight;
        canvas.width = width * dpr;
        canvas.height = height * dpr;
        ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, width, height);

        const values = points.map((p) => p.value || 0);
        const max = Math.max(...values, 1);
        const padding = 24;
        const barGap = 8;
        const barWidth = (width - padding * 2) / points.length - barGap;
        const labelColor = dark ? "#9aa0b4" : "#6b7280";
        const valueColor = dark ? "#e7e8f2" : "#1f2333";

        ctx.font = "10px sans-serif";
        ctx.fillStyle = labelColor;

        points.forEach((p, i) => {
            const barHeight = ((p.value || 0) / max) * (height - padding * 2);
            const x = padding + i * (barWidth + barGap);
            const y = height - padding - barHeight;
            ctx.fillStyle = color;
            ctx.fillRect(x, y, barWidth, barHeight);
            ctx.fillStyle = valueColor;
            ctx.textAlign = "center";
            ctx.fillText(String(p.value ?? 0), x + barWidth / 2, y - 4);
            ctx.fillStyle = labelColor;
            const label = (p.label || "").toString().slice(0, 10);
            ctx.fillText(label, x + barWidth / 2, height - 6);
        });
    }

    /** Minimal dependency-free canvas line chart (fallback only, if Chart.js can't load). */
    _drawLineChart(canvas, points, color, dark) {
        if (!canvas || !points || !points.length) return;
        const ctx = canvas.getContext("2d");
        const dpr = window.devicePixelRatio || 1;
        const width = canvas.clientWidth;
        const height = canvas.clientHeight;
        canvas.width = width * dpr;
        canvas.height = height * dpr;
        ctx.scale(dpr, dpr);
        ctx.clearRect(0, 0, width, height);

        const padding = 24;
        const validValues = points.map((p) => p.value).filter((v) => v !== null && v !== undefined);
        const max = Math.max(...validValues, 100);
        const stepX = (width - padding * 2) / Math.max(points.length - 1, 1);

        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        let started = false;
        points.forEach((p, i) => {
            if (p.value === null || p.value === undefined) return;
            const x = padding + i * stepX;
            const y = height - padding - (p.value / max) * (height - padding * 2);
            if (!started) {
                ctx.moveTo(x, y);
                started = true;
            } else {
                ctx.lineTo(x, y);
            }
        });
        ctx.stroke();

        ctx.fillStyle = dark ? "#9aa0b4" : "#6b7280";
        ctx.font = "9px sans-serif";
        ctx.textAlign = "center";
        points.forEach((p, i) => {
            if (i % 2 !== 0) return;
            const x = padding + i * stepX;
            ctx.fillText(p.label, x, height - 6);
        });
    }
}

registry.category("actions").add("education_dashboard_action", EducationDashboard);
