import { registry } from "@web/core/registry";
import { Component, useState, useRef, useEffect, onWillStart, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class SalesRepDashboard extends Component {
    static template = "mo_sales_rep_portal.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.canvasRef = useRef("canvas");
        this.trendRef = useRef("trend");
        this.bars = [];
        this.points = [];
        this.state = useState({ data: null, loading: true, dateFrom: "", dateTo: "", repId: "", teamId: "", routeId: "", partnerName: "",
                                t: 1, live: true, updated: "" });
        onWillStart(() => this.load());
        onMounted(() => {
            // live: refresh every minute while the tab is visible
            this.timer = setInterval(() => {
                if (this.state.live && document.visibilityState === "visible") { this.load(true); }
            }, 60000);
        });
        onWillUnmount(() => { clearInterval(this.timer); cancelAnimationFrame(this.raf); });
        useEffect(() => { this.draw(); this.drawTrend(); }, () => [this.state.data]);
    }

    // numbers and bars count / grow up on every refresh
    animate() {
        cancelAnimationFrame(this.raf);
        if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) { this.state.t = 1; return; }
        const t0 = performance.now();
        this.state.t = 0;
        const step = (now) => {
            const p = Math.min(1, (now - t0) / 900);
            this.state.t = 1 - Math.pow(1 - p, 3);
            this.draw();
            this.drawTrend();
            if (p < 1) { this.raf = requestAnimationFrame(step); }
        };
        this.raf = requestAnimationFrame(step);
    }

    // quick period presets (week starts on Sunday, like the server side)
    setPeriod(kind) {
        const iso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
        const today = new Date();
        let from = new Date(today);
        if (kind === "week") { from.setDate(today.getDate() - today.getDay()); }
        else if (kind === "month") { from = new Date(today.getFullYear(), today.getMonth(), 1); }
        this.state.dateFrom = iso(from);
        this.state.dateTo = iso(today);
        this.load();
    }

    toggleLive() { this.state.live = !this.state.live; }

    // ---- geometry for the SVG widgets ------------------------------------------------------------------
    sparkPoints(key) {
        const pts = (this.state.data && this.state.data.trend || []).map((p) => p[key]);
        if (pts.length < 2 || !Math.max(...pts)) { return ""; }
        const max = Math.max(...pts), min = Math.min(...pts), span = (max - min) || 1;
        return pts.map((v, i) => (100 * i / (pts.length - 1)).toFixed(1) + "," + (30 - 26 * (v - min) / span).toFixed(1)).join(" ");
    }

    donutSegments() {
        const t = this.state.data.totals;
        const items = [
            { label: "Completed", value: t.completed, color: "#2fb59b" },
            { label: "Planned", value: t.planned, color: "#f2a900" },
            { label: "Missed", value: t.missed, color: "#c8372d" },
        ];
        const total = items.reduce((a, i) => a + i.value, 0);
        const C = 2 * Math.PI * 52;
        let acc = 0;
        return { total, items: items.map((i) => {
            const len = total ? (C * i.value / total) * this.state.t : 0;
            const seg = { ...i, dash: `${len} ${C}`, offset: -acc };
            acc += total ? C * i.value / total : 0;
            return seg;
        }) };
    }

    agingSegments() {
        const ag = this.state.data.aging || {};
        const defs = [["current", "Current", "#2fb59b"], ["d30", "1-30 days", "#8ac26b"], ["d60", "31-60 days", "#f2a900"],
                      ["d90", "61-90 days", "#e8743b"], ["d90p", "90+ days", "#c8372d"]];
        const total = defs.reduce((a, d) => a + Math.max(0, ag[d[0]] || 0), 0);
        return { total, items: defs.map((d) => ({ label: d[1], color: d[2], value: ag[d[0]] || 0,
                                                  pct: total ? 100 * Math.max(0, ag[d[0]] || 0) / total : 0 })) };
    }

    ringDash(pct) {
        const C = 2 * Math.PI * 36;
        return `${C * Math.min(100, pct || 0) / 100 * this.state.t} ${C}`;
    }

    isSel(id, current) { return String(id) === String(current); }

    initial(name) { return (name || "?").trim().charAt(0).toUpperCase(); }

    barPct(value, key) {
        const max = Math.max(1, ...this.state.data.rows.map((r) => r[key]));
        return Math.max(2, 100 * (value || 0) / max) * this.state.t;
    }

    async load(silent = false) {
        if (!silent) { this.state.loading = true; }
        const data = await this.orm.call("mo.sales.rep", "get_dashboard_data", [
            this.state.dateFrom || false,
            this.state.dateTo || false,
            this.state.repId || false,
            this.state.teamId || false,
            this.state.routeId || false,
            this.state.partnerName || false,
        ]);
        this.state.dateFrom = data.date_from;
        this.state.dateTo = data.date_to;
        this.state.data = data;
        this.state.loading = false;
        this.state.updated = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        this.animate();
    }

    fmt(value) {
        // scaled by the animation progress so money figures count up
        return ((value || 0) * this.state.t).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
    }

    cnt(value) {
        return Math.round((value || 0) * this.state.t).toLocaleString();
    }

    onDate(ev, key) {
        this.state[key] = ev.target.value;
    }

    onFilter(ev, key) {
        this.state[key] = ev.target.value;
        if (key !== "partnerName") { this.load(); }
    }

    onSearchKey(ev) {
        if (ev.key === "Enter") { this.load(); }
    }

    // ------------------------------------------------------------------ drill-down
    openList(model, name, domain) {
        this.action.doAction({
            type: "ir.actions.act_window",
            name,
            res_model: model,
            views: [[false, "list"], [false, "form"]],
            domain,
        });
    }

    ordersDomain(row, from, to) {
        const d = this.state.data;
        const dom = [
            ["state", "in", ["sale", "done"]],
            ["date_order", ">=", (from || d.date_from) + " 00:00:00"],
            ["date_order", "<=", (to || d.date_to) + " 23:59:59"],
        ];
        if (row) {
            dom.push("|", ["mo_rep_id", "=", row.id], ["user_id", "=", row.user_id]);
        } else {
            dom.push("|", ["mo_rep_id", "!=", false], ["user_id", "in", d.rep_user_ids]);
        }
        return dom;
    }

    visitsDomain(row, states) {
        const d = this.state.data;
        const dom = [["visit_date", ">=", d.date_from], ["visit_date", "<=", d.date_to]];
        if (row) { dom.push(["rep_id", "=", row.id]); }
        if (states) { dom.push(["state", "in", states]); }
        return dom;
    }

    paymentsDomain(row, method, from, to) {
        const d = this.state.data;
        const dom = [
            ["payment_type", "=", "inbound"],
            ["state", "not in", ["draft", "canceled", "rejected"]],
            ["date", ">=", from || d.date_from],
            ["date", "<=", to || d.date_to],
        ];
        dom.push(row ? ["mo_rep_id", "=", row.id] : ["mo_rep_id", "!=", false]);
        if (method) { dom.push(["mo_method_id.method_type", "=", method]); }
        return dom;
    }

    openOrders(row = null, from = null, to = null) {
        this.openList("sale.order", "Sales Orders", this.ordersDomain(row, from, to));
    }
    openVisits(row = null, states = null) {
        this.openList("mo.sales.visit", "Visits", this.visitsDomain(row, states));
    }
    openPayments(row = null, method = null, from = null, to = null) {
        this.openList("account.payment", "Payments", this.paymentsDomain(row, method, from, to));
    }
    openInvoices(overdueOnly) {
        const d = this.state.data;
        const dom = [["move_type", "=", "out_invoice"], ["state", "=", "posted"], ["amount_residual", ">", 0],
                     ["mo_rep_id", "in", d.rep_ids]];
        if (overdueOnly) { dom.push(["invoice_date_due", "<", d.today]); }
        this.openList("account.move", overdueOnly ? "Overdue Invoices" : "Outstanding Invoices", dom);
    }
    openExpenses(row = null) {
        const d = this.state.data;
        const dom = [["date", ">=", d.date_from], ["date", "<=", d.date_to], ["state", "in", ["submitted", "approved"]]];
        dom.push(row ? ["rep_id", "=", row.id] : ["rep_id", "in", d.rep_ids]);
        this.openList("mo.sales.expense", "Expenses", dom);
    }
    openReturns(row = null) {
        const d = this.state.data;
        const dom = [["mo_operation", "=", "customer_return"], ["create_date", ">=", d.date_from + " 00:00:00"],
                     ["create_date", "<=", d.date_to + " 23:59:59"]];
        dom.push(row ? ["mo_rep_id", "=", row.id] : ["mo_rep_id", "in", d.rep_ids]);
        this.openList("stock.picking", "Customer Returns", dom);
    }
    openNewCustomers(row = null) {
        const d = this.state.data;
        const dom = [["create_date", ">=", d.date_from + " 00:00:00"], ["create_date", "<=", d.date_to + " 23:59:59"]];
        dom.push(row ? ["mo_created_by_rep_id", "=", row.id] : ["mo_created_by_rep_id", "in", d.rep_ids]);
        this.openList("res.partner", "New Customers", dom);
    }
    openTargets() {
        this.openList("mo.sales.target", "Targets", [["rep_id", "in", this.state.data.rep_ids]]);
    }
    openCustomers(ids) {
        this.openList("res.partner", "Customers", [["id", "in", ids]]);
    }
    openSalesPeriod(period) {
        const d = this.state.data;
        const from = period === "today" ? d.today : period === "week" ? d.week_start : d.month_start;
        this.openOrders(null, from, d.today);
    }
    openRep(row) {
        this.action.doAction({
            type: "ir.actions.act_window", res_model: "mo.sales.rep", res_id: row.id,
            views: [[false, "form"]],
        });
    }
    openCustomerOrders(c) {
        const dom = this.ordersDomain(null).concat([["partner_id", "=", c.id]]);
        this.openList("sale.order", c.name, dom);
    }

    // ------------------------------------------------------------------ charts
    palette(canvas) {
        const rgb = (getComputedStyle(canvas).color.match(/\d+/g) || [0, 0, 0]).map(Number);
        const dark = rgb[0] + rgb[1] + rgb[2] > 382;
        return {
            text: dark ? "#aab6c2" : "#5d6b79",
            grid: dark ? "#3a4552" : "#d9e1e8",
            sales: dark ? "#2fb59b" : "#0e6b5c",
            collection: dark ? "#ffc233" : "#f2a900",
        };
    }

    prepare(canvas, height) {
        const dpr = window.devicePixelRatio || 1;
        const width = canvas.clientWidth || 600;
        canvas.width = width * dpr;
        canvas.height = height * dpr;
        const ctx = canvas.getContext("2d");
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, width, height);
        ctx.font = "12px sans-serif";
        return { ctx, width };
    }

    draw() {
        const canvas = this.canvasRef.el;
        const data = this.state.data;
        this.bars = [];
        if (!canvas || !data) { return; }
        const rows = data.rows;
        const height = 220;
        const { ctx, width } = this.prepare(canvas, height);
        if (!rows.length) { return; }
        const pal = this.palette(canvas);
        const max = Math.max(1, ...rows.map((r) => Math.max(r.sales, r.collection)));
        const pad = { l: 8, r: 8, t: 14, b: 38 };
        const group = (width - pad.l - pad.r) / rows.length;
        const barW = Math.min(34, group / 3);
        const base = height - pad.b;
        const scale = (base - pad.t) / max;
        ctx.textAlign = "center";
        rows.forEach((r, i) => {
            const cx = pad.l + group * i + group / 2;
            const k = this.state.t;
            ctx.fillStyle = pal.sales;
            ctx.fillRect(cx - barW - 2, base - r.sales * scale * k, barW, r.sales * scale * k);
            ctx.fillStyle = pal.collection;
            ctx.fillRect(cx + 2, base - r.collection * scale * k, barW, r.collection * scale * k);
            ctx.fillStyle = pal.text;
            const name = r.name.length > 12 ? r.name.slice(0, 11) + "…" : r.name;
            ctx.fillText(name, cx, height - 20);
            this.bars.push({ x: cx - barW - 2, w: barW, top: pad.t, bottom: base, row: r, kind: "sales" });
            this.bars.push({ x: cx + 2, w: barW, top: pad.t, bottom: base, row: r, kind: "collection" });
        });
        ctx.strokeStyle = pal.grid;
        ctx.beginPath();
        ctx.moveTo(pad.l, base + 0.5);
        ctx.lineTo(width - pad.r, base + 0.5);
        ctx.stroke();
    }

    drawTrend() {
        const canvas = this.trendRef.el;
        const data = this.state.data;
        this.points = [];
        if (!canvas || !data || !data.trend.length) { return; }
        const height = 200;
        const { ctx, width } = this.prepare(canvas, height);
        const pal = this.palette(canvas);
        const pts = data.trend;
        const max = Math.max(1, ...pts.map((p) => Math.max(p.sales, p.collection)));
        const pad = { l: 8, r: 12, t: 14, b: 28 };
        const base = height - pad.b;
        const stepX = pts.length > 1 ? (width - pad.l - pad.r) / (pts.length - 1) : 0;
        const y = (v) => base - (v / max) * (base - pad.t);
        const line = (key, color) => {
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.beginPath();
            pts.forEach((p, i) => {
                const x = pad.l + stepX * i;
                if (i === 0) { ctx.moveTo(x, y(p[key])); } else { ctx.lineTo(x, y(p[key])); }
            });
            ctx.stroke();
            ctx.fillStyle = color;
            pts.forEach((p, i) => {
                ctx.beginPath();
                ctx.arc(pad.l + stepX * i, y(p[key]), 3, 0, Math.PI * 2);
                ctx.fill();
            });
        };
        line("sales", pal.sales);
        line("collection", pal.collection);
        ctx.fillStyle = pal.text;
        ctx.textAlign = "center";
        const every = Math.ceil(pts.length / 8);
        pts.forEach((p, i) => {
            const x = pad.l + stepX * i;
            if (i % every === 0) {
                ctx.textAlign = i === 0 ? "left" : (i === pts.length - 1 ? "right" : "center");
                ctx.fillText(p.date, i === 0 ? pad.l : (i === pts.length - 1 ? width - pad.r : x), height - 8);
            }
            this.points.push({ x, ys: y(p.sales), yc: y(p.collection), day: p.full, step: stepX || width });
        });
        ctx.strokeStyle = pal.grid;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pad.l, base + 0.5);
        ctx.lineTo(width - pad.r, base + 0.5);
        ctx.stroke();
    }

    barAt(ev) {
        return this.bars.find((b) => ev.offsetX >= b.x && ev.offsetX <= b.x + b.w && ev.offsetY >= b.top && ev.offsetY <= b.bottom);
    }
    pointAt(ev) {
        const near = this.points.find((p) => Math.abs(ev.offsetX - p.x) <= Math.max(8, p.step / 2));
        if (!near) { return null; }
        const kind = Math.abs(ev.offsetY - near.ys) <= Math.abs(ev.offsetY - near.yc) ? "sales" : "collection";
        return { day: near.day, kind };
    }
    onBarMove(ev) { ev.target.style.cursor = this.barAt(ev) ? "pointer" : "default"; }
    onBarClick(ev) {
        const bar = this.barAt(ev);
        if (!bar) { return; }
        if (bar.kind === "sales") { this.openOrders(bar.row); } else { this.openPayments(bar.row); }
    }
    onTrendMove(ev) { ev.target.style.cursor = this.pointAt(ev) ? "pointer" : "default"; }
    onTrendClick(ev) {
        const hit = this.pointAt(ev);
        if (!hit) { return; }
        if (hit.kind === "sales") { this.openOrders(null, hit.day, hit.day); } else { this.openPayments(null, null, hit.day, hit.day); }
    }
}

registry.category("actions").add("mo_sales_rep_dashboard", SalesRepDashboard);
