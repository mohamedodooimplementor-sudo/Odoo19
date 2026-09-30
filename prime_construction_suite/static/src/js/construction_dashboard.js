/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Component, onMounted, useState, useRef } from "@odoo/owl";

class ConstructionDashboard extends Component {
    static template = "prime_construction_suite.Dashboard";

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this.canvasRef = useRef("chartCanvas");
        this.donutRef  = useRef("donutCanvas");
        this.trendRef  = useRef("trendCanvas");
        this.forecastRef = useRef("forecastCanvas");
        this.profitChartRef = useRef("profitChartCanvas");
        this.costTypeRef = useRef("costTypeCanvas");

        this.state = useState({
            loading: true,
            kpis: {
                total_projects: 0, running_projects: 0,
                total_contract: 0, total_invoiced: 0,
                total_cost: 0, total_subcontract: 0,
                pending_co: 0, collection_rate: 0, profit_margin: 0,
            },
            projects: [],
            profitability: [],
            profit_summary: {profit: 0, loss: 0, neutral: 0},
            currency_symbol: '',
            alerts: {overdueProjects: [], overdueInvoices: [], staleChangeOrders: [], nearCompletionContracts: []},
            forecast: [],
            filters: {dateFrom: '', dateTo: ''},
            extra_kpis: {
                equipment_breakdowns: 0, open_incidents: 0, high_risks: 0,
                open_permits_expiring: 0, delayed_activities: 0,
                retention_outstanding: 0, compliance_expiring: 0,
                linked_po_value: 0, linked_po_count: 0,
                costs_posted_accounting: 0, costs_approved_total: 0,
                overall_physical_completion: 0, delayed_projects: 0, near_completion_contracts: 0,
            },
            cost_breakdown: [],
        });

        onMounted(() => this._loadData());
    }

    async _loadData() {
        try {
            const dateDomain = [];
            if (this.state.filters.dateFrom) dateDomain.push(['date', '>=', this.state.filters.dateFrom]);
            if (this.state.filters.dateTo)   dateDomain.push(['date', '<=', this.state.filters.dateTo]);

            const [projects, contracts, invoices, costs, changeOrdersList, subcontractors, currencies, projectDash,
                   equipmentBreakdowns, openIncidents, highRisks, delayedActivities,
                   expiringGuarantees, expiringInsurance, linkedPurchaseOrders, boqLines] =
                await Promise.all([
                    this.orm.searchRead('construction.project', [],
                        ['name','state','progress_percent','contract_value','client_id','date_end'], {limit:50}),
                    this.orm.searchRead('construction.contract',
                        [['state','not in',['terminated']]],
                        ['name','revised_contract_value','contract_value','remaining_amount','project_id','state','retention_outstanding','date_end'], {limit:200}),
                    this.orm.searchRead('construction.progress.invoice',
                        [['state','in',['approved','invoiced','paid']], ...dateDomain],
                        ['gross_amount','date','name','invoice_due_date','invoice_state','project_id'], {limit:500}),
                    this.orm.searchRead('construction.actual.cost',
                        [...dateDomain], ['amount','date','cost_type','state','move_id'], {limit:1000}),
                    this.orm.searchRead('construction.change.order',
                        [['state','in',['submitted','reviewed']]],
                        ['name','date','project_id'], {limit:100}),
                    this.orm.searchRead('construction.subcontractor', [], ['paid_amount'], {limit:200}),
                    this.orm.searchRead('res.currency',
                        [['active','=',true]], ['name','symbol'], {limit:10}),
                    this.orm.searchRead('construction.project.dashboard', [],
                        ['project_id','invoiced_amount','actual_cost'], {limit:200}),
                    this.orm.searchCount('construction.equipment.breakdown', [['status','!=','resolved']]),
                    this.orm.searchCount('construction.hse.incident', [['status','=','open']]),
                    this.orm.searchCount('construction.risk', [['risk_level','=','high'],['status','=','open']]),
                    this.orm.searchCount('construction.activity', [['delay_days','>',0]]),
                    this.orm.searchCount('construction.guarantee', [['state','=','active'],['days_to_expiry','<=',30]]),
                    this.orm.searchCount('construction.insurance', [['state','=','active'],['days_to_expiry','<=',30]]),
                    this.orm.searchRead('purchase.order',
                        [['construction_project_id','!=',false]],
                        ['amount_total','state'], {limit:500}),
                    this.orm.searchRead('construction.boq.line', [],
                        ['total_price','physical_completion_percent'], {limit:2000}),
                ]);
            const changeOrders = changeOrdersList.length;
            const retentionOutstanding = contracts.reduce((s,c)=>s+(c.retention_outstanding||0),0);
            const complianceExpiring = expiringGuarantees + expiringInsurance;

            const boqValueTotal = boqLines.reduce((s,l)=>s+(l.total_price||0), 0);
            const overallPhysicalCompletion = boqValueTotal > 0
                ? (boqLines.reduce((s,l)=>s+(l.total_price||0)*(l.physical_completion_percent||0), 0) / boqValueTotal)
                : 0;

            const confirmedPOs = linkedPurchaseOrders.filter(po => ['purchase','done'].includes(po.state));
            const linkedPoValue = confirmedPOs.reduce((s,po)=>s+(po.amount_total||0), 0);
            const approvedCosts = costs.filter(c => c.state === 'approved');
            const costsPostedAccounting = approvedCosts.filter(c => c.move_id).length;

            const costTypeLabels = {
                material: 'Materials', labor: 'Labor', equipment: 'Equipment',
                subcontract: 'Subcontractors', overhead: 'Overhead', other: 'Other',
            };
            const costTypeColors = {
                material: '#6366f1', labor: '#f59e0b', equipment: '#ef4444',
                subcontract: '#a855f7', overhead: '#0891b2', other: '#94a3b8',
            };
            const costBreakdown = Object.keys(costTypeLabels)
                .map(type => ({
                    type,
                    label: costTypeLabels[type],
                    color: costTypeColors[type],
                    amount: approvedCosts.filter(c => c.cost_type === type).reduce((s,c)=>s+(c.amount||0),0),
                }))
                .filter(d => d.amount > 0);

            const totalContract = contracts.reduce((s,r)=>s+(r.revised_contract_value||r.contract_value||0),0);
            const totalInvoiced = invoices.reduce((s,r)=>s+(r.gross_amount||0),0);
            const totalCost     = costs.reduce((s,r)=>s+(r.amount||0),0);
            const totalSub      = subcontractors.reduce((s,r)=>s+(r.paid_amount||0),0);
            const companyCur    = currencies.find(c => c.name === 'EGP') || currencies[0] || {};

            this.state.kpis = {
                total_projects:    projects.length,
                running_projects:  projects.filter(p=>p.state==='running').length,
                total_contract:    totalContract,
                total_invoiced:    totalInvoiced,
                total_cost:        totalCost,
                total_subcontract: totalSub,
                pending_co:        changeOrders,
                collection_rate:   totalContract>0 ? (totalInvoiced/totalContract*100).toFixed(1) : 0,
                profit_margin:     totalInvoiced>0 ? ((totalInvoiced-totalCost)/totalInvoiced*100).toFixed(1) : 0,
            };
            this.state.projects        = projects.slice(0,8);
            this.state.currency_symbol = companyCur.symbol || '$';
            this.state.loading         = false;

            const statusOrder = ['draft','confirmed','running','done','cancelled'];
            const statusData = statusOrder
                .map(st => ({state: st, count: projects.filter(p => p.state === st).length}))
                .filter(s => s.count > 0);

            const trend = this._buildTrend(invoices, costs, 6);

            const profitability = projectDash
                .map(r => {
                    const invoiced = r.invoiced_amount || 0;
                    const cost     = r.actual_cost || 0;
                    const profit   = invoiced - cost;
                    let status = 'neutral';
                    if (invoiced > 0 || cost > 0) status = profit >= 0 ? 'profit' : 'loss';
                    return {
                        id:       r.project_id ? r.project_id[0] : r.id,
                        name:     r.project_id ? r.project_id[1] : 'Unknown',
                        invoiced, cost, profit, status,
                    };
                })
                .sort((a,b) => Math.abs(b.profit) - Math.abs(a.profit));

            this.state.profitability  = profitability;
            this.state.profit_summary = {
                profit:  profitability.filter(p => p.status === 'profit').length,
                loss:    profitability.filter(p => p.status === 'loss').length,
                neutral: profitability.filter(p => p.status === 'neutral').length,
            };

            // ── Alerts: overdue projects, overdue invoices, stale change orders ──
            const todayStr = new Date().toISOString().slice(0,10);
            const overdueProjects = projects
                .filter(p => p.state === 'running' && p.date_end && p.date_end < todayStr)
                .map(p => ({id: p.id, name: p.name, date_end: p.date_end}));

            const overdueInvoices = invoices
                .filter(i => i.invoice_due_date && i.invoice_due_date < todayStr
                             && !['paid','reversed'].includes(i.invoice_state))
                .map(i => ({
                    id: i.id, name: i.name,
                    project: i.project_id ? i.project_id[1] : '',
                    amount: i.gross_amount || 0,
                    due_date: i.invoice_due_date,
                }))
                .sort((a,b) => a.due_date < b.due_date ? -1 : 1)
                .slice(0, 5);

            const staleChangeOrders = changeOrdersList.map(c => ({
                id: c.id, name: c.name, project: c.project_id ? c.project_id[1] : '', date: c.date,
            }));

            const in30Days = new Date(); in30Days.setDate(in30Days.getDate()+30);
            const in30DaysStr = in30Days.toISOString().slice(0,10);
            const nearCompletionContracts = contracts
                .filter(c => c.state === 'active' && c.date_end && c.date_end >= todayStr && c.date_end <= in30DaysStr)
                .map(c => ({
                    id: c.id,
                    name: c.project_id ? c.project_id[1] : (c.name || ''),
                    date_end: c.date_end,
                    remaining_amount: c.remaining_amount || 0,
                }))
                .sort((a,b) => a.date_end < b.date_end ? -1 : 1);

            this.state.alerts = {overdueProjects, overdueInvoices, staleChangeOrders, nearCompletionContracts};

            this.state.extra_kpis = {
                equipment_breakdowns: equipmentBreakdowns,
                open_incidents: openIncidents,
                high_risks: highRisks,
                delayed_activities: delayedActivities,
                retention_outstanding: retentionOutstanding,
                compliance_expiring: complianceExpiring,
                linked_po_value: linkedPoValue,
                linked_po_count: confirmedPOs.length,
                costs_posted_accounting: costsPostedAccounting,
                costs_approved_total: approvedCosts.length,
                overall_physical_completion: overallPhysicalCompletion,
                delayed_projects: overdueProjects.length,
                near_completion_contracts: nearCompletionContracts.length,
            };
            this.state.cost_breakdown = costBreakdown;

            // ── Simple cash-flow forecast: amortize each active contract's remaining
            // balance evenly across the months left until its project's planned end date ──
            const projectById = {};
            projects.forEach(p => projectById[p.id] = p);
            const now = new Date();
            const forecastMonths = 6;
            const forecast = Array.from({length: forecastMonths}, (_, i) => {
                const d = new Date(now.getFullYear(), now.getMonth() + i + 1, 1);
                return {label: d.toLocaleString('en', {month:'short'}), amount: 0};
            });
            contracts.forEach(c => {
                const proj = c.project_id ? projectById[c.project_id[0]] : null;
                const remaining = c.remaining_amount || 0;
                if (!proj || !proj.date_end || remaining <= 0 || proj.state !== 'running') return;
                const end = new Date(proj.date_end);
                let monthsLeft = (end.getFullYear()-now.getFullYear())*12 + (end.getMonth()-now.getMonth());
                monthsLeft = Math.max(monthsLeft, 1);
                const monthlyRate = remaining / monthsLeft;
                for (let i = 0; i < Math.min(monthsLeft, forecastMonths); i++) {
                    forecast[i].amount += monthlyRate;
                }
            });
            this.state.forecast = forecast;

            setTimeout(() => {
                this._drawChart(projects);
                this._drawDonut(statusData);
                this._drawCostTypeDonut(costBreakdown);
                this._drawTrend(trend);
                this._drawForecast(forecast);
                this._drawProfitChart(profitability);
            }, 120);
        } catch(e) {
            console.error("Dashboard error:", e);
            this.state.loading = false;
        }
    }

    _chartTheme() {
        const dark = document.documentElement.classList.contains('o_dark_mode');
        return dark ? {
            bg: '#101a30', grid: 'rgba(255,255,255,.08)', axisText: '#94a3b8', catText: '#aab4c8',
            cardBg: '#141b2e', headingText: '#f1f5f9', legendText: '#cbd5e1', mutedText: '#64748b',
            zeroLine: 'rgba(255,255,255,.15)', barLabelText: '#cbd5e1',
        } : {
            bg: '#f8fafc', grid: 'rgba(15,23,42,.08)', axisText: '#64748b', catText: '#475569',
            cardBg: '#ffffff', headingText: '#0f172a', legendText: '#475569', mutedText: '#64748b',
            zeroLine: 'rgba(15,23,42,.15)', barLabelText: '#475569',
        };
    }

    _drawChart(projects) {
        const canvas = this.canvasRef.el;
        if (!canvas) return;
        const theme = this._chartTheme();
        const ctx = canvas.getContext('2d');
        const data = projects.slice(0,6);
        const labels = data.map(p => p.name.length > 12 ? p.name.slice(0,12)+'…' : p.name);
        const cVals  = data.map(p => p.contract_value || 0);
        const eVals  = data.map(p => (p.contract_value||0)*(p.progress_percent||0)/100);

        const W = canvas.width  = canvas.offsetWidth || 500;
        const H = canvas.height = 230;
        const pad = {top:16,right:16,bottom:50,left:60};
        const cW = W-pad.left-pad.right;
        const cH = H-pad.top-pad.bottom;
        const maxV = Math.max(...cVals, 1);
        const n = labels.length || 1;
        const bW = Math.max(Math.floor(cW/n*0.28), 8);
        const slot = cW/n;

        ctx.clearRect(0,0,W,H);
        ctx.fillStyle=theme.bg; ctx.fillRect(0,0,W,H);

        // grid
        for(let i=0;i<=4;i++){
            const y=pad.top+cH-(cH/4*i);
            ctx.strokeStyle=theme.grid; ctx.lineWidth=1;
            ctx.beginPath(); ctx.moveTo(pad.left,y); ctx.lineTo(pad.left+cW,y); ctx.stroke();
            ctx.fillStyle=theme.axisText; ctx.font='10px Segoe UI,Arial'; ctx.textAlign='right';
            ctx.fillText((maxV/4*i/1e6).toFixed(1)+'M', pad.left-6, y+3);
        }

        // bars with vivid gradients + shadow
        data.forEach((d,i)=>{
            const cx   = pad.left + slot*i + slot/2;
            const yBot = pad.top+cH;
            const hC   = Math.max(cVals[i]/maxV*cH,3);
            const hE   = Math.max(eVals[i]/maxV*cH,3);

            ctx.save();
            ctx.shadowColor = 'rgba(99,102,241,.25)';
            ctx.shadowBlur  = 6;
            ctx.shadowOffsetY = 3;
            const gC = ctx.createLinearGradient(0,yBot-hC,0,yBot);
            gC.addColorStop(0,'#818cf8'); gC.addColorStop(1,'#4f46e5');
            ctx.fillStyle=gC;
            ctx.beginPath();
            if(ctx.roundRect) ctx.roundRect(cx-bW-2,yBot-hC,bW,hC,[4,4,0,0]);
            else ctx.rect(cx-bW-2,yBot-hC,bW,hC);
            ctx.fill();
            ctx.restore();

            ctx.save();
            ctx.shadowColor = 'rgba(16,185,129,.25)';
            ctx.shadowBlur  = 6;
            ctx.shadowOffsetY = 3;
            const gE = ctx.createLinearGradient(0,yBot-hE,0,yBot);
            gE.addColorStop(0,'#34d399'); gE.addColorStop(1,'#059669');
            ctx.fillStyle=gE;
            ctx.beginPath();
            if(ctx.roundRect) ctx.roundRect(cx+2,yBot-hE,bW,hE,[4,4,0,0]);
            else ctx.rect(cx+2,yBot-hE,bW,hE);
            ctx.fill();
            ctx.restore();

            ctx.fillStyle=theme.catText; ctx.font='600 10px Segoe UI,Arial'; ctx.textAlign='center';
            ctx.fillText(labels[i], cx, yBot+16);
        });
    }

    _buildTrend(invoices, costs, months) {
        const now = new Date();
        const buckets = [];
        for (let i = months - 1; i >= 0; i--) {
            const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
            buckets.push({
                key: `${d.getFullYear()}-${d.getMonth()}`,
                label: d.toLocaleString('en', {month:'short'}),
                invoiced: 0,
                cost: 0,
            });
        }
        const byKey = {};
        buckets.forEach(b => byKey[b.key] = b);

        invoices.forEach(inv => {
            if (!inv.date) return;
            const d = new Date(inv.date);
            const key = `${d.getFullYear()}-${d.getMonth()}`;
            if (byKey[key]) byKey[key].invoiced += (inv.gross_amount || 0);
        });
        costs.forEach(c => {
            if (!c.date) return;
            const d = new Date(c.date);
            const key = `${d.getFullYear()}-${d.getMonth()}`;
            if (byKey[key]) byKey[key].cost += (c.amount || 0);
        });
        return buckets;
    }

    _drawDonut(statusData) {
        const canvas = this.donutRef.el;
        if (!canvas) return;
        const theme = this._chartTheme();
        const ctx = canvas.getContext('2d');
        const W = canvas.width  = canvas.offsetWidth || 260;
        const H = canvas.height = 220;
        ctx.clearRect(0,0,W,H);

        const total = statusData.reduce((s,d)=>s+d.count,0) || 1;
        const cx = W/2, cy = H/2 - 6;
        const rOuter = Math.min(W,H)/2 - 18;
        const rInner = rOuter * 0.62;

        let start = -Math.PI/2;
        statusData.forEach(d => {
            const slice = (d.count/total) * Math.PI * 2;
            const end = start + slice;
            const grad = ctx.createLinearGradient(
                cx + Math.cos(start)*rOuter, cy + Math.sin(start)*rOuter,
                cx + Math.cos(end)*rOuter,   cy + Math.sin(end)*rOuter
            );
            const base = this._stateColor(d.state);
            grad.addColorStop(0, base);
            grad.addColorStop(1, base);

            ctx.save();
            ctx.shadowColor = 'rgba(15,23,42,.12)';
            ctx.shadowBlur  = 5;
            ctx.beginPath();
            ctx.moveTo(cx,cy);
            ctx.arc(cx,cy,rOuter,start,end);
            ctx.closePath();
            ctx.fillStyle = grad;
            ctx.fill();
            ctx.restore();

            start = end;
        });

        // inner hole (donut cut-out) + center label
        ctx.save();
        ctx.beginPath();
        ctx.arc(cx,cy,rInner,0,Math.PI*2);
        ctx.fillStyle = theme.cardBg;
        ctx.fill();
        ctx.restore();

        ctx.fillStyle=theme.headingText; ctx.font='700 22px Segoe UI,Arial'; ctx.textAlign='center';
        ctx.fillText(total, cx, cy+4);
        ctx.fillStyle=theme.mutedText; ctx.font='600 10px Segoe UI,Arial';
        ctx.fillText(_t('PROJECTS'), cx, cy+20);

        // legend below
        const legendY = H - 6;
        let lx = 12;
        ctx.font = '600 10px Segoe UI,Arial'; ctx.textAlign = 'left';
        statusData.forEach(d => {
            ctx.fillStyle = this._stateColor(d.state);
            ctx.beginPath(); ctx.arc(lx, legendY-3, 4, 0, Math.PI*2); ctx.fill();
            ctx.fillStyle = theme.legendText;
            const label = d.state.charAt(0).toUpperCase()+d.state.slice(1)+' '+d.count;
            ctx.fillText(label, lx+8, legendY);
            lx += ctx.measureText(label).width + 24;
        });
    }

    _drawCostTypeDonut(costData) {
        const canvas = this.costTypeRef.el;
        if (!canvas) return;
        const theme = this._chartTheme();
        const ctx = canvas.getContext('2d');
        const W = canvas.width  = canvas.offsetWidth || 260;
        const H = canvas.height = 220;
        ctx.clearRect(0,0,W,H);

        const total = costData.reduce((s,d)=>s+d.amount,0) || 1;
        const cx = W/2, cy = H/2 - 6;
        const rOuter = Math.min(W,H)/2 - 18;
        const rInner = rOuter * 0.62;

        if (costData.length === 0) {
            ctx.fillStyle = theme.mutedText; ctx.font = '600 12px Segoe UI,Arial'; ctx.textAlign = 'center';
            ctx.fillText(_t('No approved costs yet'), cx, cy);
            return;
        }

        let start = -Math.PI/2;
        costData.forEach(d => {
            const slice = (d.amount/total) * Math.PI * 2;
            const end = start + slice;
            ctx.save();
            ctx.shadowColor = 'rgba(15,23,42,.12)';
            ctx.shadowBlur  = 5;
            ctx.beginPath();
            ctx.moveTo(cx,cy);
            ctx.arc(cx,cy,rOuter,start,end);
            ctx.closePath();
            ctx.fillStyle = d.color;
            ctx.fill();
            ctx.restore();
            start = end;
        });

        ctx.save();
        ctx.beginPath();
        ctx.arc(cx,cy,rInner,0,Math.PI*2);
        ctx.fillStyle = theme.cardBg;
        ctx.fill();
        ctx.restore();

        ctx.fillStyle=theme.headingText; ctx.font='700 15px Segoe UI,Arial'; ctx.textAlign='center';
        ctx.fillText(this._fmt(total), cx, cy+2);
        ctx.fillStyle=theme.mutedText; ctx.font='600 10px Segoe UI,Arial';
        ctx.fillText(_t('APPROVED COSTS'), cx, cy+18);

        // legend below
        const legendY = H - 6;
        let lx = 12, ly = legendY;
        ctx.font = '600 10px Segoe UI,Arial'; ctx.textAlign = 'left';
        costData.forEach(d => {
            const label = d.label;
            const w = ctx.measureText(label).width + 24;
            if (lx + w > W - 10) { lx = 12; ly -= 16; }
            ctx.fillStyle = d.color;
            ctx.beginPath(); ctx.arc(lx, ly-3, 4, 0, Math.PI*2); ctx.fill();
            ctx.fillStyle = theme.legendText;
            ctx.fillText(label, lx+8, ly);
            lx += w;
        });
    }

    _drawTrend(buckets) {
        const canvas = this.trendRef.el;
        if (!canvas) return;
        const theme = this._chartTheme();
        const ctx = canvas.getContext('2d');
        const W = canvas.width  = canvas.offsetWidth || 500;
        const H = canvas.height = 220;
        const pad = {top:16,right:16,bottom:30,left:60};
        const cW = W-pad.left-pad.right;
        const cH = H-pad.top-pad.bottom;
        const maxV = Math.max(...buckets.map(b=>Math.max(b.invoiced,b.cost)), 1);
        const n = buckets.length;
        const slot = cW/(n-1 || 1);

        ctx.clearRect(0,0,W,H);
        ctx.fillStyle=theme.bg; ctx.fillRect(0,0,W,H);

        for(let i=0;i<=4;i++){
            const y=pad.top+cH-(cH/4*i);
            ctx.strokeStyle=theme.grid; ctx.lineWidth=1;
            ctx.beginPath(); ctx.moveTo(pad.left,y); ctx.lineTo(pad.left+cW,y); ctx.stroke();
            ctx.fillStyle=theme.axisText; ctx.font='10px Segoe UI,Arial'; ctx.textAlign='right';
            ctx.fillText((maxV/4*i/1e6).toFixed(1)+'M', pad.left-6, y+3);
        }

        const plot = (key, colorTop, colorBottom, fillTop) => {
            const pts = buckets.map((b,i)=>({
                x: pad.left + slot*i,
                y: pad.top + cH - Math.max(b[key]/maxV*cH, 0),
            }));

            // area fill
            ctx.beginPath();
            ctx.moveTo(pts[0].x, pad.top+cH);
            pts.forEach(p => ctx.lineTo(p.x,p.y));
            ctx.lineTo(pts[pts.length-1].x, pad.top+cH);
            ctx.closePath();
            const areaGrad = ctx.createLinearGradient(0,pad.top,0,pad.top+cH);
            areaGrad.addColorStop(0, fillTop);
            areaGrad.addColorStop(1, 'rgba(255,255,255,0)');
            ctx.fillStyle = areaGrad;
            ctx.fill();

            // line
            ctx.save();
            ctx.shadowColor = 'rgba(15,23,42,.15)';
            ctx.shadowBlur = 4;
            ctx.beginPath();
            pts.forEach((p,i)=> i===0 ? ctx.moveTo(p.x,p.y) : ctx.lineTo(p.x,p.y));
            const lineGrad = ctx.createLinearGradient(pad.left,0,pad.left+cW,0);
            lineGrad.addColorStop(0, colorTop);
            lineGrad.addColorStop(1, colorBottom);
            ctx.strokeStyle = lineGrad;
            ctx.lineWidth = 3;
            ctx.lineJoin = 'round';
            ctx.stroke();
            ctx.restore();

            // dots
            pts.forEach(p => {
                ctx.beginPath();
                ctx.arc(p.x,p.y,3.5,0,Math.PI*2);
                ctx.fillStyle = '#fff';
                ctx.fill();
                ctx.lineWidth = 2;
                ctx.strokeStyle = colorBottom;
                ctx.stroke();
            });
        };

        plot('cost', '#fbbf24', '#ea580c', 'rgba(251,191,36,.22)');
        plot('invoiced', '#34d399', '#059669', 'rgba(52,211,153,.25)');

        ctx.fillStyle=theme.catText; ctx.font='600 10px Segoe UI,Arial'; ctx.textAlign='center';
        buckets.forEach((b,i)=>{
            const x = pad.left + slot*i;
            ctx.fillText(b.label, x, pad.top+cH+18);
        });
    }

    _drawForecast(buckets) {
        const canvas = this.forecastRef.el;
        if (!canvas) return;
        const theme = this._chartTheme();
        const ctx = canvas.getContext('2d');
        const W = canvas.width  = canvas.offsetWidth || 500;
        const H = canvas.height = 200;
        const pad = {top:16,right:16,bottom:30,left:60};
        const cW = W-pad.left-pad.right;
        const cH = H-pad.top-pad.bottom;
        const maxV = Math.max(...buckets.map(b=>b.amount), 1);
        const n = buckets.length || 1;
        const bW = Math.max(Math.floor(cW/n*0.45), 10);
        const slot = cW/n;

        ctx.clearRect(0,0,W,H);
        ctx.fillStyle=theme.bg; ctx.fillRect(0,0,W,H);

        for(let i=0;i<=4;i++){
            const y=pad.top+cH-(cH/4*i);
            ctx.strokeStyle=theme.grid; ctx.lineWidth=1;
            ctx.beginPath(); ctx.moveTo(pad.left,y); ctx.lineTo(pad.left+cW,y); ctx.stroke();
            ctx.fillStyle=theme.axisText; ctx.font='10px Segoe UI,Arial'; ctx.textAlign='right';
            ctx.fillText((maxV/4*i/1e6).toFixed(1)+'M', pad.left-6, y+3);
        }

        buckets.forEach((b,i)=>{
            const cx   = pad.left + slot*i + slot/2;
            const yBot = pad.top+cH;
            const h    = Math.max(b.amount/maxV*cH, 2);

            ctx.save();
            ctx.shadowColor = 'rgba(8,145,178,.25)';
            ctx.shadowBlur  = 6;
            ctx.shadowOffsetY = 3;
            const g = ctx.createLinearGradient(0,yBot-h,0,yBot);
            g.addColorStop(0,'#22d3ee'); g.addColorStop(1,'#0891b2');
            ctx.fillStyle=g;
            ctx.beginPath();
            if(ctx.roundRect) ctx.roundRect(cx-bW/2,yBot-h,bW,h,[5,5,0,0]);
            else ctx.rect(cx-bW/2,yBot-h,bW,h);
            ctx.fill();
            ctx.restore();

            ctx.fillStyle=theme.catText; ctx.font='600 10px Segoe UI,Arial'; ctx.textAlign='center';
            ctx.fillText(b.label, cx, yBot+16);
        });
    }

    _drawProfitChart(profitability) {
        const canvas = this.profitChartRef.el;
        if (!canvas) return;
        const theme = this._chartTheme();
        const items = profitability.slice(0, 12); // keep it readable
        const rowH = 32;
        const pad = {top: 10, bottom: 24, left: 160, right: 70};
        const W = canvas.width  = canvas.offsetWidth || 900;
        const H = canvas.height = items.length * rowH + pad.top + pad.bottom;
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, W, H);

        if (!items.length) return;

        const maxAbs = Math.max(...items.map(p => Math.abs(p.profit)), 1);
        const chartW = W - pad.left - pad.right;
        const midX = pad.left + chartW / 2;
        const scale = (chartW / 2) / maxAbs;

        // center zero-line
        ctx.strokeStyle = theme.zeroLine;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(midX, pad.top - 4);
        ctx.lineTo(midX, H - pad.bottom + 4);
        ctx.stroke();

        items.forEach((p, i) => {
            const y = pad.top + i * rowH;
            const barH = 18;
            const barY = y + (rowH - barH) / 2;
            const barLen = Math.max(Math.abs(p.profit) * scale, 2);
            const isProfit = p.profit >= 0;
            const x1 = isProfit ? midX : midX - barLen;
            const color1 = isProfit ? '#34d399' : '#f87171';
            const color2 = isProfit ? '#059669' : '#dc2626';

            // project label (left side, right-aligned)
            ctx.fillStyle = theme.barLabelText;
            ctx.font = '600 12px Segoe UI,Arial';
            ctx.textAlign = 'right';
            const label = p.name.length > 22 ? p.name.slice(0, 20) + '…' : p.name;
            ctx.fillText(label, pad.left - 12, y + rowH/2 + 4);

            // bar
            ctx.save();
            ctx.shadowColor = 'rgba(15,23,42,.12)';
            ctx.shadowBlur = 4;
            const grad = ctx.createLinearGradient(x1, 0, x1 + barLen, 0);
            if (isProfit) { grad.addColorStop(0, color1); grad.addColorStop(1, color2); }
            else          { grad.addColorStop(0, color2); grad.addColorStop(1, color1); }
            ctx.fillStyle = grad;
            const r = 5;
            if (ctx.roundRect) { ctx.beginPath(); ctx.roundRect(x1, barY, barLen, barH, r); ctx.fill(); }
            else ctx.fillRect(x1, barY, barLen, barH);
            ctx.restore();

            // value label at the outer end of the bar
            ctx.fillStyle = color2;
            ctx.font = '700 11px Segoe UI,Arial';
            ctx.textAlign = isProfit ? 'left' : 'right';
            const valX = isProfit ? (x1 + barLen + 8) : (x1 - 8);
            const sign = isProfit ? '+' : '-';
            ctx.fillText(sign + this._fmt(Math.abs(p.profit)), valX, y + rowH/2 + 4);
        });
    }

    _fmt(val) {
        val = val || 0;
        if(val>=1e9)  return (val/1e9).toFixed(2)+' B';
        if(val>=1e6)  return (val/1e6).toFixed(2)+' M';
        if(val>=1e3)  return (val/1e3).toFixed(1)+' K';
        return val.toFixed(0);
    }

    _stateColor(state) {
        return {draft:'#94a3b8',confirmed:'#818cf8',running:'#34d399',done:'#c084fc',cancelled:'#f87171'}[state]||'#94a3b8';
    }
    _stateBg(state) {
        return {draft:'rgba(148,163,184,.15)',confirmed:'rgba(99,102,241,.15)',running:'rgba(16,185,129,.15)',done:'rgba(168,85,247,.15)',cancelled:'rgba(239,68,68,.15)'}[state]||'rgba(148,163,184,.15)';
    }

    _profitColor(status) {
        return {profit:'#34d399', loss:'#f87171', neutral:'#94a3b8'}[status] || '#94a3b8';
    }
    _profitBg(status) {
        return {profit:'rgba(16,185,129,.15)', loss:'rgba(239,68,68,.15)', neutral:'rgba(148,163,184,.15)'}[status] || 'rgba(148,163,184,.15)';
    }
    _profitIcon(status) {
        return {profit:'fa-arrow-up', loss:'fa-arrow-down', neutral:'fa-minus'}[status] || 'fa-minus';
    }
    _profitLabel(status) {
        return {profit:'Profitable', loss:'At Loss', neutral:'No Data Yet'}[status] || 'No Data Yet';
    }

    openProjects()       { this.action.doAction('prime_construction_suite.action_construction_project'); }
    openProjectForm(id) {
        this.action.doAction({
            type: 'ir.actions.act_window',
            res_model: 'construction.project',
            res_id: id,
            views: [[false, 'form']],
            target: 'current',
        });
    }
    openContracts()      { this.action.doAction('prime_construction_suite.action_construction_contract'); }
    openInvoices()       { this.action.doAction('prime_construction_suite.action_construction_progress_invoice'); }
    openChangeOrders()   { this.action.doAction('prime_construction_suite.action_construction_change_order'); }
    openCosts()          { this.action.doAction('prime_construction_suite.action_construction_actual_cost'); }
    openSubcontractors() { this.action.doAction('prime_construction_suite.action_construction_subcontractor'); }

    openLinkedPurchaseOrders() {
        this.action.doAction({
            type: 'ir.actions.act_window', name: _t('Purchase Orders (Construction Projects)'),
            res_model: 'purchase.order', view_mode: 'list,form',
            views: [[false,'list'],[false,'form']],
            domain: [['construction_project_id', '!=', false]],
        });
    }

    openDelayedProjects() {
        this.action.doAction({
            type: 'ir.actions.act_window', name: _t('Delayed Projects'),
            res_model: 'construction.project', view_mode: 'list,form',
            views: [[false,'list'],[false,'form']],
            domain: [['id', 'in', this.state.alerts.overdueProjects.map(p => p.id)]],
        });
    }

    openNearCompletionContracts() {
        this.action.doAction({
            type: 'ir.actions.act_window', name: _t('Contracts Nearing Completion'),
            res_model: 'construction.contract', view_mode: 'list,form',
            views: [[false,'list'],[false,'form']],
            domain: [['id', 'in', this.state.alerts.nearCompletionContracts.map(c => c.id)]],
        });
    }

    openEquipmentBreakdowns() {
        this.action.doAction({
            type: 'ir.actions.act_window', name: _t('Equipment Breakdowns'),
            res_model: 'construction.equipment.breakdown', view_mode: 'list,form',
            views: [[false,'list'],[false,'form']],
            domain: [['status', '!=', 'resolved']],
        });
    }
    openIncidents() {
        this.action.doAction({
            type: 'ir.actions.act_window', name: _t('Open Site Incidents'),
            res_model: 'construction.hse.incident', view_mode: 'list,form',
            views: [[false,'list'],[false,'form']],
            domain: [['status', '=', 'open']],
        });
    }
    openHighRisks() {
        this.action.doAction({
            type: 'ir.actions.act_window', name: _t('High Risks'),
            res_model: 'construction.risk', view_mode: 'list,form',
            views: [[false,'list'],[false,'form']],
            domain: [['risk_level', '=', 'high'], ['status', '=', 'open']],
        });
    }
    openDelayedActivities() {
        this.action.doAction({
            type: 'ir.actions.act_window', name: _t('Delayed Activities'),
            res_model: 'construction.activity', view_mode: 'list,form',
            views: [[false,'list'],[false,'form']],
            domain: [['delay_days', '>', 0]],
        });
    }
    openRetentionOutstanding() {
        this.action.doAction({
            type: 'ir.actions.act_window', name: _t('Contracts — Retention Outstanding'),
            res_model: 'construction.contract', view_mode: 'list,form',
            views: [[false,'list'],[false,'form']],
            domain: [['retention_outstanding', '>', 0]],
        });
    }
    openComplianceExpiring() {
        this.action.doAction({
            type: 'ir.actions.act_window', name: _t('Guarantees Expiring Soon'),
            res_model: 'construction.guarantee', view_mode: 'list,form',
            views: [[false,'list'],[false,'form']],
            domain: [['state', '=', 'active'], ['days_to_expiry', '<=', 30]],
        });
    }

    setDateFrom(ev) { this.state.filters.dateFrom = ev.target.value; }
    setDateTo(ev)   { this.state.filters.dateTo   = ev.target.value; }
    applyFilters()  { this._loadData(); }
    clearFilters()  {
        this.state.filters.dateFrom = '';
        this.state.filters.dateTo   = '';
        this._loadData();
    }

    exportSnapshot() {
        const ids = this.state.profitability.map(p => p.id).join(',');
        const url = `/prime_construction_suite/report/executive_dashboard${ids ? '?ids=' + ids : ''}`;
        window.open(url, '_blank');
    }
}

registry.category("actions").add("prime_construction_suite.dashboard", ConstructionDashboard);
