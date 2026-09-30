/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, onWillStart, useRef, useState } from "@odoo/owl";

export class ConstructionGanttChart extends Component {
    static template = "prime_construction_suite.GanttChart";

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this.canvasRef = useRef("ganttCanvas");

        this.state = useState({
            projects: [],
            projectId: null,
            activities: [],
            loading: true,
        });

        onWillStart(async () => {
            await this._loadProjects();
        });

        onMounted(() => {
            if (this.state.projectId) this._loadActivities();
        });
    }

    async _loadProjects() {
        const projects = await this.orm.searchRead(
            'construction.project', [], ['name'], {limit: 100, order: 'date_start desc'});
        this.state.projects = projects;
        if (projects.length) {
            this.state.projectId = projects[0].id;
            await this._loadActivities();
        } else {
            this.state.loading = false;
        }
    }

    async onProjectChange(ev) {
        this.state.projectId = parseInt(ev.target.value, 10);
        await this._loadActivities();
    }

    async _loadActivities() {
        this.state.loading = true;
        const activities = await this.orm.searchRead(
            'construction.activity',
            [['project_id', '=', this.state.projectId]],
            ['name', 'date_start', 'date_end', 'progress', 'sequence', 'is_milestone'],
            {order: 'sequence, date_start'});
        this.state.activities = activities;
        this.state.loading = false;
        setTimeout(() => this._draw(), 80);
    }

    openScheduleList() {
        this.action.doAction({
            type: 'ir.actions.act_window',
            name: _t('Schedule Activities'),
            res_model: 'construction.activity',
            view_mode: 'list,form',
            views: [[false, 'list'], [false, 'form']],
            domain: [['project_id', '=', this.state.projectId]],
            context: {default_project_id: this.state.projectId},
        });
    }

    _draw() {
        const canvas = this.canvasRef.el;
        if (!canvas) return;
        const activities = this.state.activities;
        const rowH = 38;
        const labelW = 220;
        const topPad = 40;
        const W = canvas.width  = canvas.offsetWidth || 900;
        const H = canvas.height = Math.max(activities.length * rowH + topPad + 20, 160);
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, W, H);

        if (!activities.length) {
            ctx.fillStyle = '#94a3b8';
            ctx.font = '13px Segoe UI,Arial';
            ctx.textAlign = 'center';
            ctx.fillText(_t('No schedule activities yet for this project'), W/2, H/2);
            return;
        }

        const starts = activities.map(a => new Date(a.date_start));
        const ends   = activities.map(a => new Date(a.date_end));
        const minDate = new Date(Math.min(...starts));
        const maxDate = new Date(Math.max(...ends));
        const totalDays = Math.max((maxDate - minDate) / 86400000, 1);
        const chartW = W - labelW - 20;
        const pxPerDay = chartW / totalDays;

        const xForDate = (d) => labelW + ((d - minDate) / 86400000) * pxPerDay;

        // Month gridlines
        ctx.strokeStyle = '#f1f5f9';
        ctx.fillStyle = '#94a3b8';
        ctx.font = '600 10px Segoe UI,Arial';
        ctx.textAlign = 'left';
        const cursor = new Date(minDate.getFullYear(), minDate.getMonth(), 1);
        while (cursor <= maxDate) {
            const x = xForDate(cursor);
            ctx.beginPath();
            ctx.moveTo(x, topPad - 10);
            ctx.lineTo(x, H - 10);
            ctx.stroke();
            ctx.fillText(cursor.toLocaleString('en', {month:'short', year:'2-digit'}), x + 4, topPad - 16);
            cursor.setMonth(cursor.getMonth() + 1);
        }

        // Today marker
        const today = new Date();
        if (today >= minDate && today <= maxDate) {
            const tx = xForDate(today);
            ctx.strokeStyle = '#dc2626';
            ctx.lineWidth = 1.5;
            ctx.setLineDash([4,3]);
            ctx.beginPath();
            ctx.moveTo(tx, topPad - 10);
            ctx.lineTo(tx, H - 10);
            ctx.stroke();
            ctx.setLineDash([]);
        }

        activities.forEach((a, i) => {
            const y = topPad + i * rowH;
            const x1 = xForDate(new Date(a.date_start));
            const x2 = xForDate(new Date(a.date_end));
            const barW = Math.max(x2 - x1, 6);
            const barH = 18;
            const barY = y + (rowH - barH) / 2;

            // Label
            ctx.fillStyle = '#334155';
            ctx.font = '600 12px Segoe UI,Arial';
            ctx.textAlign = 'left';
            const label = a.name.length > 26 ? a.name.slice(0,24) + '…' : a.name;
            ctx.fillText(label, 8, barY + barH/2 + 4);

            // Bar background
            ctx.save();
            ctx.shadowColor = 'rgba(15,23,42,.10)';
            ctx.shadowBlur = 4;
            const bg = ctx.createLinearGradient(x1, 0, x2, 0);
            bg.addColorStop(0, '#e2e8f0');
            bg.addColorStop(1, '#cbd5e1');
            ctx.fillStyle = bg;
            this._roundRect(ctx, x1, barY, barW, barH, 6);
            ctx.fill();
            ctx.restore();

            // Progress fill
            const prog = Math.max(Math.min(a.progress || 0, 100), 0);
            if (prog > 0) {
                const fillW = barW * (prog/100);
                const isDone = prog >= 100;
                const fg = ctx.createLinearGradient(x1, 0, x1+fillW, 0);
                if (isDone) { fg.addColorStop(0,'#34d399'); fg.addColorStop(1,'#059669'); }
                else        { fg.addColorStop(0,'#818cf8'); fg.addColorStop(1,'#4f46e5'); }
                ctx.fillStyle = fg;
                this._roundRect(ctx, x1, barY, Math.max(fillW,6), barH, 6);
                ctx.fill();
            }

            // Milestone diamond
            if (a.is_milestone) {
                const cx = x2, cy = barY + barH/2;
                ctx.fillStyle = '#f59e0b';
                ctx.beginPath();
                ctx.moveTo(cx, cy-8); ctx.lineTo(cx+8, cy); ctx.lineTo(cx, cy+8); ctx.lineTo(cx-8, cy);
                ctx.closePath(); ctx.fill();
            }

            // % label
            ctx.fillStyle = '#1e293b';
            ctx.font = '700 10px Segoe UI,Arial';
            ctx.textAlign = 'left';
            ctx.fillText(Math.round(prog) + '%', x2 + 10, barY + barH/2 + 3);
        });
    }

    _roundRect(ctx, x, y, w, h, r) {
        if (ctx.roundRect) { ctx.beginPath(); ctx.roundRect(x,y,w,h,r); return; }
        ctx.beginPath();
        ctx.moveTo(x+r, y);
        ctx.arcTo(x+w, y,   x+w, y+h, r);
        ctx.arcTo(x+w, y+h, x,   y+h, r);
        ctx.arcTo(x,   y+h, x,   y,   r);
        ctx.arcTo(x,   y,   x+w, y,   r);
        ctx.closePath();
    }
}

registry.category("actions").add("prime_construction_suite.gantt", ConstructionGanttChart);
