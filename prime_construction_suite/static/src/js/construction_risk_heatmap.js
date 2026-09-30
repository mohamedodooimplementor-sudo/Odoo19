/** @odoo-module **/
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onMounted, useState } from "@odoo/owl";

const PROB_ORDER = ["low", "medium", "high"];
const IMPACT_ORDER = ["high", "medium", "low"]; // top row = high impact
const WEIGHT = { low: 1, medium: 2, high: 3 };
const LABELS = { low: "Low", medium: "Medium", high: "High" };

class ConstructionRiskHeatmap extends Component {
    static template = "prime_construction_suite.RiskHeatmap";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, cells: {}, risks: [] });
        onMounted(() => this._loadData());
    }

    async _loadData() {
        this.state.loading = true;
        const risks = await this.orm.searchRead(
            "construction.risk",
            [["status", "=", "open"]],
            ["name", "project_id", "probability", "impact", "risk_score", "owner_id"],
            { limit: 500 }
        );
        const cells = {};
        for (const p of PROB_ORDER) {
            for (const i of IMPACT_ORDER) {
                cells[`${p}_${i}`] = [];
            }
        }
        for (const r of risks) {
            const key = `${r.probability}_${r.impact}`;
            if (cells[key]) cells[key].push(r);
        }
        this.state.cells = cells;
        this.state.risks = risks;
        this.state.loading = false;
    }

    cellColor(prob, impact) {
        const score = WEIGHT[prob] * WEIGHT[impact];
        if (score >= 6) return "#dc2626";
        if (score >= 3) return "#f59e0b";
        return "#22c55e";
    }

    cellRisks(prob, impact) {
        return this.state.cells[`${prob}_${impact}`] || [];
    }

    probLabel(p) { return LABELS[p]; }
    impactLabel(i) { return LABELS[i]; }
    get probOrder() { return PROB_ORDER; }
    get impactOrder() { return IMPACT_ORDER; }

    openCell(prob, impact) {
        const risks = this.cellRisks(prob, impact);
        this.action.doAction({
            type: "ir.actions.act_window",
            name: `Risks — ${this.probLabel(prob)} Probability / ${this.impactLabel(impact)} Impact`,
            res_model: "construction.risk",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [["id", "in", risks.map((r) => r.id)]],
        });
    }

    openRisk(riskId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "construction.risk",
            res_id: riskId,
            views: [[false, "form"]],
        });
    }
}

registry.category("actions").add("prime_construction_suite.risk_heatmap", ConstructionRiskHeatmap);

export default ConstructionRiskHeatmap;
