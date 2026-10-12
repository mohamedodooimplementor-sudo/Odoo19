/** @odoo-module **/
/**
 * Odoo does not add an "o_dark_mode" class. Dark mode is driven by the
 * `color_scheme` cookie (and a dark assets bundle), so we check several
 * signals and finally fall back to the real page background luminance.
 */
export function isOdooDarkMode() {
    try {
        const html = document.documentElement;
        if (/(?:^|;\s*)color_scheme=dark/.test(document.cookie)) return true;
        if (html.classList.contains('o_dark_mode') || html.classList.contains('dark')) return true;
        if (html.getAttribute('data-bs-theme') === 'dark' ||
            html.getAttribute('data-color-scheme') === 'dark') return true;
        const probe = document.querySelector('.o_action_manager') || document.body;
        const m = getComputedStyle(probe).backgroundColor.match(/\d+(\.\d+)?/g);
        if (m && m.length >= 3 && (m[3] === undefined || parseFloat(m[3]) > 0.5)) {
            const [r, g, b] = m.map(Number);
            return (0.299 * r + 0.587 * g + 0.114 * b) < 110;
        }
    } catch (e) { /* ignore */ }
    return false;
}
