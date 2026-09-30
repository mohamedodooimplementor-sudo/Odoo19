/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

const STATE_COLORS = {
    planned: "#a855f7",
    open: "#22d3c8",
    completed: "#34d399",
    cancelled: "#f87171",
};

const STATE_LABELS = {
    planned: "Planned",
    open: "Open",
    completed: "Completed",
    cancelled: "Cancelled",
};

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTH_LABELS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
];

function pad(n) {
    return String(n).padStart(2, "0");
}

function toIso(date) {
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** A lively, self-contained monthly calendar for sessions - deliberately not a re-skin of
 * the plain Odoo calendar/list views already available from the Sessions menu. Every cell,
 * every session pill, and every day are clickable, in the same purple brand shell (sidebar +
 * header) as the main Prime Education Hub Dashboard. */
export class EducationSessionCalendarDashboard extends Component {
    static template = "prime_educational_hub.EducationSessionCalendarDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.rootRef = useRef("root");

        const today = new Date();
        this.state = useState({
            shell: null,
            loading: true,
            sidebarExpanded: false,
            year: today.getFullYear(),
            month: today.getMonth(), // 0-11
            sessions: [],
            selectedDate: toIso(today),
        });
        this.todayIso = toIso(today);
        this.dayLabels = DAY_LABELS;

        onWillStart(async () => {
            await this._loadMonth();
            this.state.loading = false;
        });
    }

    get monthLabel() {
        return `${MONTH_LABELS[this.state.month]} ${this.state.year}`;
    }

    /** Sunday-first 6-week grid covering the visible month, each day pre-loaded with its
     * own sessions (already fetched for the whole visible range in one RPC call). */
    get weeks() {
        const { year, month, sessions, selectedDate } = this.state;
        const firstOfMonth = new Date(year, month, 1);
        const gridStart = new Date(firstOfMonth);
        gridStart.setDate(gridStart.getDate() - gridStart.getDay());

        const byDate = {};
        for (const s of sessions) {
            (byDate[s.date] = byDate[s.date] || []).push(s);
        }

        const weeks = [];
        const cursor = new Date(gridStart);
        for (let w = 0; w < 6; w++) {
            const days = [];
            for (let d = 0; d < 7; d++) {
                const iso = toIso(cursor);
                days.push({
                    iso,
                    dayNumber: cursor.getDate(),
                    isCurrentMonth: cursor.getMonth() === month,
                    isToday: iso === this.todayIso,
                    isSelected: iso === selectedDate,
                    sessions: (byDate[iso] || []).slice().sort((a, b) => (a.start || "").localeCompare(b.start || "")),
                });
                cursor.setDate(cursor.getDate() + 1);
            }
            weeks.push(days);
        }
        return weeks;
    }

    get selectedDaySessions() {
        return this.state.sessions
            .filter((s) => s.date === this.state.selectedDate)
            .slice()
            .sort((a, b) => (a.start || "").localeCompare(b.start || ""));
    }

    get selectedDateLabel() {
        if (!this.state.selectedDate) return "";
        const [y, m, d] = this.state.selectedDate.split("-").map(Number);
        return new Date(y, m - 1, d).toLocaleDateString(undefined, {
            weekday: "long", month: "long", day: "numeric", year: "numeric",
        });
    }

    stateColor(state) {
        return STATE_COLORS[state] || "#a855f7";
    }

    stateLabel(state) {
        return STATE_LABELS[state] || state;
    }

    async _loadMonth() {
        const { year, month } = this.state;
        // One extra week of padding on each side so the leading/trailing grid days
        // (from the previous/next month) also show their sessions.
        const rangeStart = new Date(year, month, 1);
        rangeStart.setDate(rangeStart.getDate() - rangeStart.getDay() - 7);
        const rangeEnd = new Date(year, month + 1, 0);
        rangeEnd.setDate(rangeEnd.getDate() + (6 - rangeEnd.getDay()) + 7);

        const data = await this.orm.call(
            "education.dashboard", "get_session_calendar_data",
            [toIso(rangeStart), toIso(rangeEnd)]
        );
        this.state.shell = {
            is_admin: !!data.is_admin,
            company_name: data.company_name || "",
            sidebar_items: data.sidebar_items || [],
        };
        this.state.sessions = data.sessions || [];
    }

    async goToMonth(offset) {
        let month = this.state.month + offset;
        let year = this.state.year;
        if (month < 0) { month = 11; year -= 1; }
        if (month > 11) { month = 0; year += 1; }
        this.state.month = month;
        this.state.year = year;
        this.state.loading = true;
        await this._loadMonth();
        this.state.loading = false;
    }

    async goToToday() {
        const today = new Date();
        this.state.month = today.getMonth();
        this.state.year = today.getFullYear();
        this.state.selectedDate = this.todayIso;
        this.state.loading = true;
        await this._loadMonth();
        this.state.loading = false;
    }

    selectDay(day) {
        this.state.selectedDate = day.iso;
    }

    openSession(session) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "education.session",
            res_id: session.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    /** "+ New Session" for the currently selected day. */
    createSession() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "education.session",
            views: [[false, "form"]],
            target: "current",
            context: { default_date: this.state.selectedDate },
        });
    }

    openSidebarItem(item) {
        this.action.doAction(item.action_id);
    }

    openOdooApps() {
        window.location.href = "/odoo";
    }

    toggleSidebar() {
        this.state.sidebarExpanded = !this.state.sidebarExpanded;
    }
}

registry.category("actions").add("education_session_calendar_dashboard_action", EducationSessionCalendarDashboard);
