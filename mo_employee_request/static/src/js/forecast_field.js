/** @odoo-module **/
import { registry } from "@web/core/registry";
import { Component, onMounted, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { usePopover } from "@web/core/popover/popover_hook";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { formatFloat } from "@web/views/fields/formatters";

function relId(value) {
    // many2one values are [id, name] or {id, display_name} depending on the version
    if (!value) {
        return false;
    }
    return Array.isArray(value) ? value[0] : value.id;
}

const STATUS_LABEL = {
    available: "Available",
    partial: "Partially available",
    unavailable: "Not available",
};

// Short-lived cache: clicking the same line again opens instantly.
const CACHE = new Map();
const CACHE_TTL = 15000;

export class StockPopover extends Component {
    static template = "mo_employee_request.StockPopover";
    static props = {
        productId: Number,
        warehouseId: Number,
        qty: Number,
        close: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ data: null, loading: true, tab: null });
        // Open immediately, fill in when the data arrives (no blocking wait).
        onMounted(() => this.load());
    }

    async load() {
        const { productId, warehouseId, qty } = this.props;
        const key = `${productId}-${warehouseId}-${qty}`;
        const hit = CACHE.get(key);
        if (hit && Date.now() - hit.time < CACHE_TTL) {
            this.state.data = hit.data;
            this.state.loading = false;
            return;
        }
        try {
            const data = await this.orm.call(
                "employee.request.line",
                "get_forecast_data",
                [productId, warehouseId, qty]
            );
            CACHE.set(key, { time: Date.now(), data });
            this.state.data = data;
        } finally {
            this.state.loading = false;
        }
    }

    fmt(value) {
        return formatFloat(value || 0);
    }

    get status() {
        return (this.state.data || {}).status || "none";
    }

    get metrics() {
        const d = this.state.data || {};
        return [
            { key: "on_hand", label: "On hand", value: this.fmt(d.on_hand), cls: "" },
            { key: "reserved", label: "Reserved", value: this.fmt(d.reserved), cls: "" },
            { key: "available", label: "Available", value: this.fmt(d.available),
              cls: `er-stock-${this.status}` },
            { key: "incoming", label: "Incoming", value: this.fmt(d.incoming), cls: "" },
            { key: "outgoing", label: "Outgoing", value: this.fmt(d.outgoing), cls: "" },
            { key: "forecast", label: "Forecast", value: this.fmt(d.forecast),
              cls: (d.forecast || 0) < 0 ? "er-stock-unavailable" : "" },
        ];
    }

    get locations() {
        return (this.state.data || {}).locations || [];
    }

    get moves() {
        const d = this.state.data || {};
        return [
            ...(d.incoming_moves || []).map((m) => ({ ...m, dir: "In" })),
            ...(d.outgoing_moves || []).map((m) => ({ ...m, dir: "Out" })),
        ];
    }

    toggle(tab) {
        this.state.tab = this.state.tab === tab ? null : tab;
    }
}

export class StockField extends Component {
    static template = "mo_employee_request.StockField";
    static props = { ...standardFieldProps };

    setup() {
        this.popover = usePopover(StockPopover, {
            position: "bottom-start",
            popoverClass: "er-pop-wrap",
            closeOnClickAway: true,
        });
    }

    get data() {
        return this.props.record.data;
    }

    get hasProduct() {
        return Boolean(relId(this.data.product_id));
    }

    get status() {
        return this.data.stock_status || "none";
    }

    get available() {
        return formatFloat(this.data[this.props.name] || 0);
    }

    get forecast() {
        return formatFloat(this.data.forecast_qty || 0);
    }

    get tooltip() {
        const label = STATUS_LABEL[this.status] || "Stock";
        return `${label} - available ${this.available}, forecast ${this.forecast}. Click for details`;
    }

    onClick(ev) {
        const productId = relId(this.data.product_id);
        const warehouseId = relId(this.data.warehouse_id);
        if (!productId || !warehouseId) {
            return;
        }
        this.popover.open(ev.currentTarget, {
            productId,
            warehouseId,
            qty: this.data.product_uom_qty || 0,
        });
    }
}

const stockField = {
    component: StockField,
    displayName: "Stock (available / forecast / status)",
    supportedTypes: ["float"],
};
registry.category("fields").add("er_stock", stockField);
registry.category("fields").add("er_forecast", stockField); // old name, kept for saved views
