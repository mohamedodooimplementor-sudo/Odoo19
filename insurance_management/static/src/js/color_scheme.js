/** @odoo-module **/

// Tells the module's stylesheets whether the backend is currently dark.
//
// The claim kanban cards and the summary cards of the claim form must be
// WHITE in the normal (light) theme and BLACK in dark mode. Odoo's dark mode
// is applied in different ways depending on the edition / theme (a swapped
// asset bundle, a data-bs-theme attribute, a third-party theme...), and not
// every colour variable flips with it - so instead of guessing which
// variable to trust, this measures the real background the cards sit on and
// sets `o_ic_dark` on <html> when that background is dark.
//
// It re-checks whenever a claim kanban / summary card appears, so it also
// follows a theme that is toggled without reloading the page.
import { whenReady } from "@odoo/owl";

const PROBE_SELECTOR = ".o_insurance_claim_kanban, .o_ic_summary";
const DARK_CLASS = "o_ic_dark";

/** Relative luminance (0 black .. 1 white) of an [r, g, b] colour. */
export function luminance([r, g, b]) {
    const channel = (value) => {
        const v = value / 255;
        return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function parseColor(text) {
    const match = /rgba?\(([^)]+)\)/.exec(text || "");
    if (!match) {
        return null;
    }
    const [r, g, b, a = 1] = match[1].split(/[ ,\/]+/).filter(Boolean).map(parseFloat);
    return { rgb: [r, g, b], alpha: a };
}

/** First non-transparent background found walking up from ``element``. */
export function effectiveBackground(element, getStyle = (el) => getComputedStyle(el)) {
    for (let node = element; node; node = node.parentElement) {
        const color = parseColor(getStyle(node).backgroundColor);
        if (color && color.alpha > 0.5) {
            return color.rgb;
        }
    }
    return [255, 255, 255];
}

export function isDarkBackground(element, getStyle) {
    return luminance(effectiveBackground(element, getStyle)) < 0.4;
}

function refresh() {
    const probe = document.querySelector(PROBE_SELECTOR);
    if (!probe) {
        return;
    }
    // Measure the surface *behind* the cards, not the (styled) card itself.
    const surface = probe.closest(".o_content, .o_form_sheet_bg, .o_action") || probe.parentElement;
    document.documentElement.classList.toggle(DARK_CLASS, isDarkBackground(surface));
}

let scheduled = false;
function scheduleRefresh() {
    if (scheduled) {
        return;
    }
    scheduled = true;
    requestAnimationFrame(() => {
        scheduled = false;
        refresh();
    });
}

whenReady(() => {
    new MutationObserver(scheduleRefresh).observe(document.body, { childList: true, subtree: true });
    scheduleRefresh();
});
