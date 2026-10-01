/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, useState } from "@odoo/owl";

// ─── Tiny bar chart using raw Canvas (no external lib needed) ───────────────
function drawBarChart(canvasId, labels, datasets) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.offsetWidth || 600;
    const H = canvas.offsetHeight || 260;
    canvas.width = W;
    canvas.height = H;

    const PAD = { top: 20, right: 20, bottom: 50, left: 70 };
    const chartW = W - PAD.left - PAD.right;
    const chartH = H - PAD.top - PAD.bottom;

    // max value
    let maxVal = 0;
    datasets.forEach(ds => ds.data.forEach(v => { if (v > maxVal) maxVal = v; }));
    if (maxVal === 0) maxVal = 1;
    const scale = chartH / (maxVal * 1.1);

    const groupW = chartW / labels.length;
    const barW = (groupW * 0.7) / datasets.length;
    const groupGap = groupW * 0.15;

    ctx.clearRect(0, 0, W, H);

    // grid lines
    ctx.strokeStyle = "#e9ecef";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 5; i++) {
        const y = PAD.top + chartH - (chartH / 5) * i;
        ctx.beginPath();
        ctx.moveTo(PAD.left, y);
        ctx.lineTo(PAD.left + chartW, y);
        ctx.stroke();
        // y label
        const val = (maxVal / 5) * i;
        ctx.fillStyle = "#adb5bd";
        ctx.font = "11px sans-serif";
        ctx.textAlign = "right";
        ctx.fillText(val >= 1000 ? (val / 1000).toFixed(1) + "k" : val.toFixed(0), PAD.left - 6, y + 4);
    }

    // bars
    labels.forEach((label, gi) => {
        const gx = PAD.left + groupGap + gi * groupW;
        datasets.forEach((ds, di) => {
            const bx = gx + di * barW;
            const bh = ds.data[gi] * scale;
            const by = PAD.top + chartH - bh;

            // bar
            ctx.fillStyle = ds.color + "CC";
            ctx.beginPath();
            ctx.roundRect(bx, by, barW - 2, bh, [4, 4, 0, 0]);
            ctx.fill();

            // border top
            ctx.strokeStyle = ds.color;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.roundRect(bx, by, barW - 2, bh, [4, 4, 0, 0]);
            ctx.stroke();
        });

        // x label
        ctx.fillStyle = "#6c757d";
        ctx.font = "11px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(label, gx + (groupW * 0.7) / 2, PAD.top + chartH + 18);
    });

    // legend
    const legendY = H - 14;
    let lx = PAD.left;
    datasets.forEach(ds => {
        ctx.fillStyle = ds.color;
        ctx.fillRect(lx, legendY - 8, 12, 10);
        ctx.fillStyle = "#495057";
        ctx.font = "11px sans-serif";
        ctx.textAlign = "left";
        ctx.fillText(ds.label, lx + 16, legendY);
        lx += ctx.measureText(ds.label).width + 36;
    });
}
// ─────────────────────────────────────────────────────────────────────────────

class IntercompanyDashboard extends Component {
    static template = "intercompany_operation_modified.Dashboard";
    static props = ["*"];

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            loaded: false,
            kpi: {},
            amounts: {},
            monthly: [],
            recent: [],
            filters: { company_id: 0, months: 6, companies: [] },
        });
        onMounted(async () => {
            await this._loadData();
        });
    }

    async _loadData(company_id, months) {
        const params = {
            company_id: company_id !== undefined ? company_id : (this.state.filters.company_id || 0),
            months: months !== undefined ? months : (this.state.filters.months ?? 6),
        };
        try {
            const resp = await fetch("/intercompany/dashboard_data", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ jsonrpc: "2.0", method: "call", params }),
            });
            const json = await resp.json();
            const data = json.result;
            Object.assign(this.state, data, { loaded: true });
            setTimeout(() => this._renderChart(), 80);
        } catch (e) {
            console.error("Dashboard load error:", e);
            this.state.loaded = true;
        }
    }

    onCompanyFilterChange(ev) {
        const company_id = parseInt(ev.target.value, 10) || 0;
        this._loadData(company_id, this.state.filters.months);
    }

    onPeriodFilterChange(ev) {
        const months = parseInt(ev.target.value, 10) || 0;
        this._loadData(this.state.filters.company_id, months);
    }

    _renderChart() {
        const monthly = this.state.monthly;
        if (!monthly || !monthly.length) return;

        const months = [...new Set(monthly.map(r => r.month))];
        const types = [
            { key: "sale",         label: "Sales",        color: "#28a745" },
            { key: "purchase",     label: "Purchase",     color: "#875A7B" },
            { key: "landed_cost",  label: "Landed Cost",  color: "#E67E22" },
            { key: "payment",      label: "Payment Ops",  color: "#F06050" },
            { key: "payment_dist", label: "Pay. Dist",    color: "#FF9800" },
            { key: "branches_payment_transfer", label: "Branches Transfer", color: "#e07a5f" },
        ];

        const datasets = types.map(t => ({
            label: t.label,
            color: t.color,
            data: months.map(m => {
                const row = monthly.find(r => r.month === m && r.operation_type === t.key);
                return row ? parseFloat(row.total) : 0;
            }),
        }));

        drawBarChart("ic_monthly_chart", months, datasets);
    }

    openList(type) {
        const xmlids = {
            sale:         "intercompany_operation_modified.action_intercompany_operation_sale",
            purchase:     "intercompany_operation_modified.action_intercompany_operation_purchase",
            payment:      "intercompany_operation_modified.action_intercompany_operation_payment",
            landed_cost:  "intercompany_operation_modified.action_intercompany_operation_landed_cost",
            all:          "intercompany_operation_modified.action_intercompany_operation",
        };
        this.action.doAction(xmlids[type] || xmlids.all);
    }

    openRecord(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "intercompany.operation",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    typeLabel(type) {
        return {
            sale: "Sale", purchase: "Purchase", payment: "Payment", payment_dist: "Dist",
            landed_cost: "LC", sale_return: "Sale Return", purchase_return: "Purchase Return",
            branches_picking_transfer: "Picking Transfer", branches_payment_transfer: "Payment Transfer",
        }[type] || type;
    }

    fmt(val) {
        return Number(val || 0).toLocaleString("en-US", { minimumFractionDigits: 2 });
    }

    openPayDist() {
        this.action.doAction("intercompany_operation_modified.action_intercompany_payment");
    }

    openPayDistByState(state) {
        const domain = [["state", "=", state]];
        if (this.state.filters.company_id) {
            domain.push(["line_ids.company_id", "=", this.state.filters.company_id]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: this.payDistLabel(state) + " — Payment Distributions",
            res_model: "intercompany.payment",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
        });
    }

    openOpsByState(state) {
        const domain = [["state", "=", state]];
        if (this.state.filters.company_id) {
            domain.push(["company_ids", "in", [this.state.filters.company_id]]);
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            name: this.stateLabel(state) + " — Operations",
            res_model: "intercompany.operation",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: domain,
        });
    }

    openReturnList(filterType) {
        let domain = [];
        if (filterType && filterType !== 'all') {
            // if it's a state
            const states = ['draft', 'to_approve', 'approved', 'confirmed', 'returned', 'done', 'cancelled', 'refused'];
            if (states.includes(filterType)) {
                domain.push(['state', '=', filterType]);
            } else {
                domain.push(['return_type', '=', filterType]);
            }
        }
        if (this.state.filters.company_id) {
            domain.push(['company_id', '=', this.state.filters.company_id]);
        }
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Intercompany Returns',
            res_model: 'intercompany.return',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
        });
    }

    openPickingTransferList(state) {
        let domain = [];
        if (state && state !== 'all') {
            domain.push(['state', '=', state]);
        }
        if (this.state.filters.company_id) {
            domain.push('|');
            domain.push(['company_sent_id', '=', this.state.filters.company_id]);
            domain.push(['company_receive_id', '=', this.state.filters.company_id]);
        }
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Branches Picking Transfer',
            res_model: 'intercompany.picking.transfer',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
        });
    }

    openPaymentTransferList(state) {
        let domain = [];
        if (state && state !== 'all') {
            domain.push(['state', '=', state]);
        }
        if (this.state.filters.company_id) {
            domain.push('|');
            domain.push(['company_sent_id', '=', this.state.filters.company_id]);
            domain.push(['company_receive_id', '=', this.state.filters.company_id]);
        }
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: 'Branches Payment Transfer',
            res_model: 'intercompany.payment.transfer',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: domain,
        });
    }

    openPayDistRecord(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "intercompany.payment",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    openReturnRecord(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "intercompany.return",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    openPickingTransferRecord(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "intercompany.picking.transfer",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    openPaymentTransferRecord(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "intercompany.payment.transfer",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    returnLabel(state) {
        return {
            draft: 'Draft', to_approve: 'To Approve', approved: 'Approved',
            confirmed: 'Confirmed', returned: 'Returned', done: 'Done',
            cancelled: 'Cancelled', refused: 'Refused',
        }[state] || state;
    }

    returnBadge(state) {
        return {
            draft:      'ic-badge-draft',
            to_approve: 'ic-badge-to-approve',
            approved:   'ic-badge-approved',
            confirmed:  'ic-badge-confirmed',
            returned:   'ic-badge-pickings',
            done:       'ic-badge-success',
            cancelled:  'ic-badge-muted',
            refused:    'ic-badge-danger',
        }[state] || 'ic-badge-muted';
    }

    pickTransferLabel(state) {
        return {
            draft: 'Draft', to_approve: 'To Approve', approved: 'Approved',
            send_approved: 'Send Approved', received: 'Received', cancelled: 'Cancelled',
        }[state] || state;
    }

    pickTransferBadge(state) {
        return {
            draft:         'ic-badge-draft',
            to_approve:    'ic-badge-to-approve',
            approved:      'ic-badge-approved',
            send_approved: 'ic-badge-confirmed',
            received:      'ic-badge-success',
            cancelled:     'ic-badge-muted',
        }[state] || 'ic-badge-muted';
    }

    payDistLabel(state) {
        return {
            draft: 'Draft',
            to_approve: 'To Approve',
            approved: 'Approved',
            posted: 'Posted',
            cancelled: 'Cancelled',
        }[state] || state;
    }

    payDistBadge(state) {
        return {
            draft:      'ic-badge-draft',
            to_approve: 'ic-badge-to-approve',
            approved:   'ic-badge-approved',
            posted:     'ic-badge-success',
            cancelled:  'ic-badge-muted',
        }[state] || 'ic-badge-muted';
    }

    stateLabel(state) {
        return {
            draft: 'Draft',
            to_approve: 'To Approve',
            approved: 'Approved',
            confirmed: 'In Progress',
            pickings_confirmed: 'Stock Confirmed',
            done: 'Done',
            cancelled: 'Cancelled',
        }[state] || state;
    }

    stateBadge(state) {
        return {
            draft:              'ic-badge-draft',
            to_approve:         'ic-badge-to-approve',
            approved:           'ic-badge-approved',
            confirmed:          'ic-badge-confirmed',
            pickings_confirmed: 'ic-badge-pickings',
            done:               'ic-badge-success',
            cancelled:          'ic-badge-muted',
        }[state] || 'ic-badge-muted';
    }
}

registry.category("actions").add("intercompany_dashboard_action", IntercompanyDashboard);
