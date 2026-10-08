/** @odoo-module **/
import { patch } from "@web/core/utils/patch";
import { ProductCatalogOrderLine } from "@product/product_catalog/order_line/order_line";

patch(ProductCatalogOrderLine.prototype, {
    get showPrice() {
        if (this.env.orderResModel === "employee.request") {
            return false;
        }
        return super.showPrice;
    },
});
