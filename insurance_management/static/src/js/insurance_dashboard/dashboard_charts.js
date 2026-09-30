/** @odoo-module **/

// Small, dependency-free Canvas 2D chart renderers used by the Insurance
// Dashboard (no external chart library, zero extra JS payload).
//
// Every draw function takes two optional trailing arguments:
//   progress   0..1  entrance animation (bars grow, donuts sweep, lines draw)
//   hoverIndex >= 0  highlights one bar / slice / point (driven by the mouse)
// and every chart has a matching hit-test helper that maps a mouse position
// back to a data index, used for tooltips and click-through. The padding
// constants below are shared between drawing and hit-testing so both agree.

const FONT = "Roboto, Arial, sans-serif";

function setupCanvas(canvas) {
    const ratio = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(rect.width, 50);
    const height = Math.max(rect.height, 50);
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    return { ctx, width, height };
}

function theme(darkMode) {
    return darkMode
        ? { grid: "#334155", text: "#CBD5E1", subtext: "#94A3B8", axis: "#475569", hover: "rgba(148,163,184,0.12)" }
        : { grid: "#E2E8F0", text: "#334155", subtext: "#64748B", axis: "#CBD5E1", hover: "rgba(100,116,139,0.10)" };
}

function niceMax(value) {
    if (value <= 0) {
        return 10;
    }
    const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
    const residual = value / magnitude;
    let niceResidual;
    if (residual > 5) {
        niceResidual = 10;
    } else if (residual > 2) {
        niceResidual = 5;
    } else if (residual > 1) {
        niceResidual = 2;
    } else {
        niceResidual = 1;
    }
    return niceResidual * magnitude;
}

function truncate(ctx, text, maxWidth) {
    let shown = String(text);
    if (ctx.measureText(shown).width <= maxWidth) {
        return shown;
    }
    while (shown.length > 1 && ctx.measureText(shown + "…").width > maxWidth) {
        shown = shown.slice(0, -1);
    }
    return shown + "…";
}

function emptyMessage(ctx, width, height, t, message = "No data for this period") {
    ctx.fillStyle = t.subtext;
    ctx.font = `12px ${FONT}`;
    ctx.textAlign = "center";
    ctx.fillText(message, width / 2, height / 2);
}

const LINE_PADDING = { top: 16, right: 16, bottom: 28, left: 56 };
const HBAR_PADDING = { top: 10, right: 60, bottom: 10, left: 130 };
const COLUMN_PADDING = { top: 22, right: 12, bottom: 32, left: 12 };

// ----------------------------------------------------------------------
// Line chart
// ----------------------------------------------------------------------
/**
 * Multi-series line chart with soft area fill under the first series.
 */
export function drawLineChart(canvas, labels, series, darkMode, formatValue, progress = 1, hoverIndex = -1) {
    const { ctx, width, height } = setupCanvas(canvas);
    const t = theme(darkMode);
    const padding = LINE_PADDING;
    const plotW = width - padding.left - padding.right;
    const plotH = height - padding.top - padding.bottom;

    const allValues = series.flatMap((s) => s.data);
    const maxValue = niceMax(Math.max(...allValues, 1));
    const steps = 4;

    ctx.font = `11px ${FONT}`;
    ctx.fillStyle = t.subtext;
    ctx.strokeStyle = t.grid;
    ctx.lineWidth = 1;

    for (let i = 0; i <= steps; i++) {
        const y = padding.top + plotH - (plotH * i) / steps;
        ctx.beginPath();
        ctx.moveTo(padding.left, y);
        ctx.lineTo(padding.left + plotW, y);
        ctx.stroke();
        ctx.textAlign = "right";
        ctx.fillText(formatValue((maxValue * i) / steps, true), padding.left - 8, y + 3);
    }

    const n = labels.length;
    const skip = n > 8 ? Math.ceil(n / 8) : 1;
    ctx.textAlign = "center";
    labels.forEach((label, i) => {
        if (i % skip !== 0 && i !== n - 1) {
            return;
        }
        const x = padding.left + (plotW * i) / Math.max(n - 1, 1);
        ctx.fillText(label, x, height - 8);
    });

    const xFor = (i) => padding.left + (plotW * i) / Math.max(n - 1, 1);
    const yFor = (v) => padding.top + plotH - (plotH * v) / maxValue;

    // Hover guide line + highlighted column behind the series.
    if (hoverIndex >= 0 && hoverIndex < n) {
        ctx.fillStyle = t.hover;
        const slot = plotW / Math.max(n - 1, 1);
        ctx.fillRect(xFor(hoverIndex) - slot / 2, padding.top, slot, plotH);
        ctx.strokeStyle = t.axis;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(xFor(hoverIndex), padding.top);
        ctx.lineTo(xFor(hoverIndex), padding.top + plotH);
        ctx.stroke();
        ctx.setLineDash([]);
    }

    // Draw-in animation: reveal the plot from left to right.
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, padding.left + plotW * progress + 6, height);
    ctx.clip();

    series.forEach((s, sIdx) => {
        if (sIdx === 0) {
            ctx.beginPath();
            s.data.forEach((v, i) => {
                if (i === 0) ctx.moveTo(xFor(i), yFor(v));
                else ctx.lineTo(xFor(i), yFor(v));
            });
            ctx.lineTo(xFor(n - 1), padding.top + plotH);
            ctx.lineTo(xFor(0), padding.top + plotH);
            ctx.closePath();
            ctx.fillStyle = s.color + "22";
            ctx.fill();
        }

        ctx.beginPath();
        s.data.forEach((v, i) => {
            if (i === 0) ctx.moveTo(xFor(i), yFor(v));
            else ctx.lineTo(xFor(i), yFor(v));
        });
        ctx.strokeStyle = s.color;
        ctx.lineWidth = 2.5;
        ctx.lineJoin = "round";
        ctx.stroke();

        s.data.forEach((v, i) => {
            ctx.beginPath();
            ctx.arc(xFor(i), yFor(v), i === hoverIndex ? 5 : 3, 0, Math.PI * 2);
            ctx.fillStyle = s.color;
            ctx.fill();
            if (i === hoverIndex) {
                ctx.lineWidth = 2;
                ctx.strokeStyle = darkMode ? "#1E293B" : "#FFFFFF";
                ctx.stroke();
            }
        });
    });
    ctx.restore();
}

export function hitTestLine(canvas, pointCount, clientX) {
    if (!pointCount) {
        return -1;
    }
    const rect = canvas.getBoundingClientRect();
    const plotW = rect.width - LINE_PADDING.left - LINE_PADDING.right;
    const x = clientX - rect.left - LINE_PADDING.left;
    if (x < -12 || x > plotW + 12) {
        return -1;
    }
    const step = plotW / Math.max(pointCount - 1, 1);
    return Math.max(0, Math.min(pointCount - 1, Math.round(x / (step || 1))));
}

// ----------------------------------------------------------------------
// Donut chart
// ----------------------------------------------------------------------
/**
 * Donut chart with a centered total label. The hovered slice grows a little.
 */
export function drawDonutChart(canvas, values, colors, darkMode, centerLabel, centerValue, progress = 1, hoverIndex = -1) {
    const { ctx, width, height } = setupCanvas(canvas);
    const t = theme(darkMode);
    const total = values.reduce((a, b) => a + b, 0);
    const cx = width / 2;
    const cy = height / 2;
    const radius = Math.min(width, height) / 2 - 8;
    const innerRadius = radius * 0.62;

    if (total <= 0) {
        ctx.beginPath();
        ctx.arc(cx, cy, radius, 0, Math.PI * 2);
        ctx.fillStyle = t.grid;
        ctx.fill();
    } else {
        let start = -Math.PI / 2;
        values.forEach((v, i) => {
            const angle = (v / total) * Math.PI * 2 * progress;
            const r = i === hoverIndex ? radius + 5 : radius;
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.arc(cx, cy, r, start, start + angle);
            ctx.closePath();
            ctx.fillStyle = colors[i];
            ctx.fill();
            // thin gap between slices
            ctx.strokeStyle = darkMode ? "#1E293B" : "#FFFFFF";
            ctx.lineWidth = 2;
            ctx.stroke();
            start += angle;
        });
    }

    ctx.globalCompositeOperation = "destination-out";
    ctx.beginPath();
    ctx.arc(cx, cy, innerRadius, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalCompositeOperation = "source-over";

    if (centerLabel) {
        ctx.textAlign = "center";
        ctx.fillStyle = t.text;
        ctx.font = `bold 16px ${FONT}`;
        ctx.fillText(centerValue || "", cx, cy - 2);
        ctx.font = `11px ${FONT}`;
        ctx.fillStyle = t.subtext;
        ctx.fillText(centerLabel, cx, cy + 16);
    }
}

export function hitTestDonut(canvas, values, clientX, clientY) {
    const total = values.reduce((a, b) => a + b, 0);
    if (total <= 0) {
        return -1;
    }
    const rect = canvas.getBoundingClientRect();
    const cx = rect.width / 2;
    const cy = rect.height / 2;
    const radius = Math.min(rect.width, rect.height) / 2 - 8;
    const dx = clientX - rect.left - cx;
    const dy = clientY - rect.top - cy;
    const distance = Math.hypot(dx, dy);
    if (distance < radius * 0.62 || distance > radius + 6) {
        return -1;
    }
    // angle measured clockwise from 12 o'clock, like the drawing
    let angle = Math.atan2(dy, dx) + Math.PI / 2;
    if (angle < 0) {
        angle += Math.PI * 2;
    }
    let acc = 0;
    for (let i = 0; i < values.length; i++) {
        acc += (values[i] / total) * Math.PI * 2;
        if (angle <= acc) {
            return i;
        }
    }
    return values.length - 1;
}

// ----------------------------------------------------------------------
// Horizontal bars (long partner / plan / product names)
// ----------------------------------------------------------------------
export function drawHBarChart(canvas, labels, values, darkMode, formatValue, barColor, progress = 1, hoverIndex = -1) {
    const { ctx, width, height } = setupCanvas(canvas);
    const t = theme(darkMode);
    const n = labels.length;
    if (!n) {
        emptyMessage(ctx, width, height, t);
        return;
    }
    const padding = HBAR_PADDING;
    const plotW = width - padding.left - padding.right;
    const rowH = (height - padding.top - padding.bottom) / n;
    const barH = Math.min(20, rowH * 0.6);
    const maxValue = niceMax(Math.max(...values, 1));

    ctx.font = `11px ${FONT}`;
    labels.forEach((label, i) => {
        const y = padding.top + rowH * i + rowH / 2;
        const barW = ((plotW * values[i]) / maxValue) * progress;

        if (i === hoverIndex) {
            ctx.fillStyle = t.hover;
            ctx.fillRect(0, y - rowH / 2, width, rowH);
        }

        ctx.textAlign = "right";
        ctx.fillStyle = t.text;
        ctx.fillText(truncate(ctx, label, padding.left - 12), padding.left - 10, y + 4);

        ctx.fillStyle = t.grid;
        ctx.fillRect(padding.left, y - barH / 2, plotW, barH);

        ctx.fillStyle = barColor;
        ctx.globalAlpha = hoverIndex >= 0 && i !== hoverIndex ? 0.55 : 1;
        ctx.fillRect(padding.left, y - barH / 2, Math.max(barW, 2), barH);
        ctx.globalAlpha = 1;

        ctx.textAlign = "left";
        ctx.fillStyle = t.subtext;
        ctx.fillText(formatValue(values[i]), padding.left + barW + 8, y + 4);
    });
}

/**
 * Row index under the mouse for drawHBarChart (or -1).
 */
export function hitTestHBarRow(canvas, rowCount, clientY) {
    if (!rowCount) {
        return -1;
    }
    const rect = canvas.getBoundingClientRect();
    const plotH = rect.height - HBAR_PADDING.top - HBAR_PADDING.bottom;
    const rowH = plotH / rowCount;
    const y = clientY - rect.top - HBAR_PADDING.top;
    if (y < 0 || y > plotH) {
        return -1;
    }
    return Math.min(rowCount - 1, Math.floor(y / rowH));
}

// ----------------------------------------------------------------------
// Column chart (aging buckets, collection funnel)
// ----------------------------------------------------------------------
export function drawColumnChart(canvas, labels, values, colors, darkMode, formatValue, progress = 1, hoverIndex = -1) {
    const { ctx, width, height } = setupCanvas(canvas);
    const t = theme(darkMode);
    const n = labels.length;
    if (!n || !values.some((v) => v > 0)) {
        emptyMessage(ctx, width, height, t);
        return;
    }
    const padding = COLUMN_PADDING;
    const plotW = width - padding.left - padding.right;
    const plotH = height - padding.top - padding.bottom;
    const slot = plotW / n;
    const barW = Math.min(64, slot * 0.62);
    const maxValue = Math.max(...values, 1);

    // baseline
    ctx.strokeStyle = t.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padding.left, padding.top + plotH + 0.5);
    ctx.lineTo(padding.left + plotW, padding.top + plotH + 0.5);
    ctx.stroke();

    labels.forEach((label, i) => {
        const cx = padding.left + slot * i + slot / 2;
        const h = ((plotH * values[i]) / maxValue) * progress;
        const x = cx - barW / 2;
        const y = padding.top + plotH - h;

        if (i === hoverIndex) {
            ctx.fillStyle = t.hover;
            ctx.fillRect(padding.left + slot * i, padding.top - 8, slot, plotH + 8);
        }

        ctx.globalAlpha = hoverIndex >= 0 && i !== hoverIndex ? 0.55 : 1;
        ctx.fillStyle = colors[i % colors.length];
        // rounded top corners
        const r = Math.max(0, Math.min(6, barW / 2, h));
        ctx.beginPath();
        ctx.moveTo(x, y + h);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.lineTo(x + barW - r, y);
        ctx.quadraticCurveTo(x + barW, y, x + barW, y + r);
        ctx.lineTo(x + barW, y + h);
        ctx.closePath();
        ctx.fill();
        ctx.globalAlpha = 1;

        ctx.textAlign = "center";
        ctx.font = `bold 11px ${FONT}`;
        ctx.fillStyle = t.text;
        if (values[i] > 0 && progress > 0.6) {
            ctx.fillText(formatValue(values[i]), cx, y - 6);
        }
        ctx.font = `11px ${FONT}`;
        ctx.fillStyle = t.subtext;
        ctx.fillText(truncate(ctx, label, slot - 6), cx, height - 10);
    });
}

export function hitTestColumn(canvas, count, clientX) {
    if (!count) {
        return -1;
    }
    const rect = canvas.getBoundingClientRect();
    const plotW = rect.width - COLUMN_PADDING.left - COLUMN_PADDING.right;
    const x = clientX - rect.left - COLUMN_PADDING.left;
    if (x < 0 || x > plotW) {
        return -1;
    }
    return Math.min(count - 1, Math.floor(x / (plotW / count)));
}

// ----------------------------------------------------------------------
// Sparkline used inside KPI cards
// ----------------------------------------------------------------------
export function drawSparkline(canvas, data, color) {
    const { ctx, width, height } = setupCanvas(canvas);
    if (!data || data.length < 2) {
        return;
    }
    const padding = 3;
    const plotW = width - padding * 2;
    const plotH = height - padding * 2;
    const maxValue = Math.max(...data, 0.0001);
    const minValue = Math.min(...data, 0);
    const range = maxValue - minValue || 1;
    const n = data.length;

    const xFor = (i) => padding + (plotW * i) / (n - 1);
    const yFor = (v) => padding + plotH - ((v - minValue) / range) * plotH;

    ctx.beginPath();
    data.forEach((v, i) => {
        if (i === 0) ctx.moveTo(xFor(i), yFor(v));
        else ctx.lineTo(xFor(i), yFor(v));
    });
    ctx.lineTo(xFor(n - 1), padding + plotH);
    ctx.lineTo(xFor(0), padding + plotH);
    ctx.closePath();
    ctx.fillStyle = color + "26";
    ctx.fill();

    ctx.beginPath();
    data.forEach((v, i) => {
        if (i === 0) ctx.moveTo(xFor(i), yFor(v));
        else ctx.lineTo(xFor(i), yFor(v));
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.75;
    ctx.lineJoin = "round";
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(xFor(n - 1), yFor(data[n - 1]), 2.5, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
}
