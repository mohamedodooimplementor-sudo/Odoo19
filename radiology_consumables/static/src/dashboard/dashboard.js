/** @odoo-module **/

import { Component, onWillStart, proxy, signal } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class RadiologyConsumablesDashboard extends Component {
    static template = "radiology_consumables.Dashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({
            loading: true,
            error: "",
            data: { rooms: [], kpis: {}, recent: [], recent_issues: [], domains: {} },
        });
        // Owl 3: t-model binds to signals (callable with a .set method)
        this.roomId = signal("");
        this.dateFrom = signal("");
        this.dateTo = signal("");
        onWillStart(() => this.loadData());
    }

    get examCards() {
        const k = this.state.data.kpis;
        return [
            { label: "Total Exams", value: k.total, icon: "fa-stethoscope", cls: "rc-blue", key: "total", model: "rc.exam.consumption", title: "Total Exams" },
            { label: "Completed", value: k.done, icon: "fa-check-circle", cls: "rc-green", key: "done", model: "rc.exam.consumption", title: "Completed Exams" },
            { label: "In Progress", value: k.progress, icon: "fa-spinner", cls: "rc-cyan", key: "progress", model: "rc.exam.consumption", title: "Exams In Progress" },
            { label: "Draft Exams", value: k.draft, icon: "fa-file-o", cls: "rc-slate", key: "draft", model: "rc.exam.consumption", title: "Draft Exams" },
            { label: "Consumables Used", value: k.used_qty, icon: "fa-flask", cls: "rc-purple", key: "used", model: "rc.exam.consumption.line", title: "Consumables Used" },
        ];
    }

    get stockCards() {
        const k = this.state.data.kpis;
        return [
            { label: "Pending Receipts", value: k.pending_issues, icon: "fa-truck", cls: "rc-orange", key: "pending_receipts", model: "rc.issue", title: "Pending Receipts" },
            { label: "Received", value: k.received, icon: "fa-inbox", cls: "rc-teal", key: "received", model: "rc.issue", title: "Received" },
            { label: "Requests (Draft)", value: k.requests, icon: "fa-shopping-cart", cls: "rc-indigo", key: "requests", model: "rc.issue", title: "Requests" },
            { label: "Receipts With Difference", value: k.differences, icon: "fa-exclamation-triangle", cls: "rc-pink", key: "differences", model: "rc.issue", title: "Receipts With Difference" },
            { label: "Items Below Max", value: k.low_stock, icon: "fa-arrow-down", cls: "rc-red", key: "low_stock", action: "radiology_consumables.rc_room_levels_action" },
        ];
    }

    onCardClick(card) {
        if (card.action) {
            return this.action.doAction(card.action);
        }
        return this.openRecords(this.state.data.domains[card.key] || [], card.title, card.model);
    }

    async loadData() {
        this.state.loading = true;
        this.state.error = "";
        try {
            const data = await this.orm.call(
                "rc.exam.consumption",
                "get_dashboard_data",
                [
                    this.roomId() || false,
                    this.dateFrom() || false,
                    this.dateTo() || false,
                ]
            );
            this.state.data = data;
            if (!this.roomId() && data.selected_room_id) {
                this.roomId.set(String(data.selected_room_id));
            }
        } catch (error) {
            this.state.error = error.message || "Unable to load dashboard data.";
        } finally {
            this.state.loading = false;
        }
    }

    async onFilterChange() {
        await this.loadData();
    }

    async clearFilters() {
        this.roomId.set("");
        this.dateFrom.set("");
        this.dateTo.set("");
        await this.loadData();
    }

    openRecords(domain, name, resModel = "rc.exam.consumption") {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: resModel,
            views: [[false, "list"], [false, "form"]],
            domain,
            target: "current",
        });
    }

    openIssue(record) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "rc.issue",
            res_id: record.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openRecent(record) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "rc.exam.consumption",
            res_id: record.id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add(
    "radiology_consumables.dashboard",
    RadiologyConsumablesDashboard
);
