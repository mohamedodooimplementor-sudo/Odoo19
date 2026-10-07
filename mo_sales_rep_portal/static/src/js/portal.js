(function () {
  'use strict';
  var GEO_TIMEOUT = 9000;

  // ---- Optional periodic tracking while a visit is open -----------------
  function bindTracking() {
    var body = document.getElementById('mo-root') || document.body;
    var interval = parseInt(body.dataset.tracking || '0', 10);
    if (!interval || !body.dataset.activeVisit || !navigator.geolocation) { return; }
    var csrf = body.dataset.csrf;
    var send = function () {
      navigator.geolocation.getCurrentPosition(function (pos) {
        var fd = new FormData();
        fd.append('csrf_token', csrf);
        fd.append('lat', pos.coords.latitude);
        fd.append('lng', pos.coords.longitude);
        fetch('/rep/track', { method: 'POST', body: fd, credentials: 'same-origin' });
      }, function () {}, { enableHighAccuracy: false, timeout: GEO_TIMEOUT });
    };
    send();
    setInterval(send, interval * 1000);
  }

  // ---- Product lines editor (orders / invoices / stock) -----------------
  function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  function bindLines() {
    var box = document.getElementById('lines');
    if (!box) { return; }
    var tpl = document.getElementById('line-tpl');
    var mode = box.dataset.mode || 'sale';           // sale | stock
    var op = box.dataset.op || '';
    var cap = parseFloat(box.dataset.cap || '0');
    var partnerSel = document.getElementById('partner_id');
    var MSG = { stock: box.dataset.stock || 'Stock', none: box.dataset.none || 'No products found', loading: box.dataset.loading || 'Loading…',
                more: box.dataset.more || 'Showing the first results, type to narrow the list' };
    var SHOW = 80, CATALOG_LIMIT = 500;
    var catalog = null, loading = false, waiting = [];

    function partnerParam() { return partnerSel && partnerSel.value ? '&partner_id=' + partnerSel.value : ''; }
    function stockParam() { return mode === 'stock' ? '&stock=1&op=' + encodeURIComponent(op) : ''; }

    function recompute() {
      var total = 0;
      box.querySelectorAll('.line').forEach(function (l) {
        var q = parseFloat(l.querySelector('[name=qty]').value) || 0;
        var pEl = l.querySelector('[name=price]');
        var p = pEl ? (parseFloat(pEl.value) || 0) : 0;
        var dEl = l.querySelector('[name=discount]');
        var d = dEl ? (parseFloat(dEl.value) || 0) : 0;
        total += q * p * (1 - d / 100);
      });
      var t = document.getElementById('lines-total');
      if (t) { t.textContent = total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
    }

    // The whole catalogue is loaded once (per customer) and filtered locally while typing.
    function loadCatalog(cb) {
      if (catalog) { cb(); return; }
      waiting.push(cb);
      if (loading) { return; }
      loading = true;
      fetch('/rep/products.json?all=1' + partnerParam() + stockParam(), { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (items) { catalog = items; })
        .catch(function () { catalog = null; })
        .then(function () { loading = false; waiting.splice(0).forEach(function (f) { f(); }); });
    }

    function addLine(data) {
      var node = tpl.firstElementChild.cloneNode(true);
      box.appendChild(node);
      var combo = node.querySelector('.mo-combo');
      var search = node.querySelector('.prod-search');
      var list = node.querySelector('.mo-suggest');
      var caret = node.querySelector('.prod-caret');
      var pid = node.querySelector('[name=product_id]');
      var chosen = '';
      var shown = [], hi = -1, timer;

      function isOpen() { return !list.hidden; }
      function close() {
        list.hidden = true; search.setAttribute('aria-expanded', 'false'); hi = -1;
        search.value = pid.value ? chosen : '';      // never leave typed text without a chosen product
      }
      combo._close = close;

      function hint(text) {
        var d = document.createElement('div'); d.className = 'hint'; d.textContent = text; list.appendChild(d);
      }
      function highlight(i) {
        var rows = list.querySelectorAll('div[data-i]');
        rows.forEach(function (r) { r.classList.remove('on'); });
        hi = i;
        if (rows[i]) { rows[i].classList.add('on'); rows[i].scrollIntoView({ block: 'nearest' }); }
      }
      function paint(items, more) {
        list.innerHTML = '';
        shown = items; hi = -1;
        items.forEach(function (it, i) {
          var row = document.createElement('div');
          row.setAttribute('data-i', i); row.setAttribute('role', 'option');
          var sub = esc(it.uom);
          if (mode === 'stock') { if (it.qty !== undefined) { sub = esc(String(it.qty)) + ' ' + sub; } }
          else {
            if (it.price !== undefined) { sub += ' · ' + Number(it.price).toFixed(2); }
            if (it.disc) { sub += ' (−' + it.disc + '%)'; }
            if (it.stock !== undefined) { sub += ' · ' + esc(MSG.stock) + ': ' + Math.round(it.stock * 100) / 100; }
          }
          row.innerHTML = '<b>' + (it.frequent ? '<span class="mo-badge-frequent">★</span> ' : '') + esc(it.name) + '</b><br><span class="mo-muted">' + sub + '</span>';
          row.addEventListener('click', function () { pick(it); });
          list.appendChild(row);
        });
        if (!items.length) { hint(MSG.none); }
        else if (more) { hint(MSG.more); }
      }
      function render() {
        if (!isOpen()) { return; }
        if (!catalog) { list.innerHTML = ''; hint(loading ? MSG.loading : MSG.none); return; }
        var needle = (pid.value ? '' : search.value).trim().toLowerCase();
        var matches = needle ? catalog.filter(function (c) {
          return c.name.toLowerCase().indexOf(needle) !== -1 || (c.code || '').toLowerCase().indexOf(needle) !== -1 ||
                 (c.barcode || '') === needle;
        }) : catalog;
        paint(matches.slice(0, SHOW), matches.length > SHOW);
        // a very large catalogue is truncated server side: ask the server too when typing
        if (needle.length >= 2 && catalog.length >= CATALOG_LIMIT) {
          clearTimeout(timer);
          timer = setTimeout(function () {
            fetch('/rep/products.json?q=' + encodeURIComponent(needle) + partnerParam() + stockParam(), { credentials: 'same-origin' })
              .then(function (r) { return r.json(); })
              .then(function (items) { if (isOpen() && !pid.value && search.value.trim().toLowerCase() === needle) { paint(items, false); } });
          }, 250);
        }
      }
      function open() {
        document.querySelectorAll('.mo-combo').forEach(function (c) { if (c !== combo && c._close) { c._close(); } });
        list.hidden = false; search.setAttribute('aria-expanded', 'true');
        render();
        loadCatalog(render);
      }
      function pick(it) {
        pid.value = it.id; chosen = it.name; search.value = it.name;
        var price = node.querySelector('[name=price]');
        if (price && it.price !== undefined) { price.value = Number(it.price).toFixed(2); }
        var uom = node.querySelector('.uom');
        if (uom) { uom.textContent = it.uom || ''; }
        close(); recompute();
      }

      search.addEventListener('focus', function () { open(); try { search.select(); } catch (e) { /* ignore */ } });
      search.addEventListener('input', function () { pid.value = ''; if (!isOpen()) { open(); } else { render(); } });
      search.addEventListener('keydown', function (ev) {
        if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
          ev.preventDefault();
          if (!isOpen()) { open(); return; }
          var n = shown.length; if (!n) { return; }
          highlight(ev.key === 'ArrowDown' ? (hi + 1) % n : (hi - 1 + n) % n);
        } else if (ev.key === 'Enter') {
          if (isOpen() && shown.length && (hi >= 0 || shown.length === 1)) { ev.preventDefault(); pick(shown[hi >= 0 ? hi : 0]); }
          else if (isOpen()) { ev.preventDefault(); }
        } else if (ev.key === 'Escape' || ev.key === 'Tab') { close(); }
      });
      caret.addEventListener('click', function () { if (isOpen()) { close(); } else { open(); } });

      if (data) {
        pid.value = data.id; chosen = data.name; search.value = data.name;
        node.querySelector('[name=qty]').value = data.qty;
        var pr = node.querySelector('[name=price]'); if (pr) { pr.value = Number(data.price).toFixed(2); }
        var ds = node.querySelector('[name=discount]'); if (ds) { ds.value = data.discount; }
        var um = node.querySelector('.uom'); if (um) { um.textContent = data.uom || ''; }
      }
      node.querySelectorAll('input[type=number]').forEach(function (i) { i.addEventListener('input', recompute); });
      node.querySelector('.rm').addEventListener('click', function () { node.remove(); recompute(); });
    }

    document.addEventListener('click', function (ev) {
      box.querySelectorAll('.mo-combo').forEach(function (c) { if (!c.contains(ev.target) && c._close) { c._close(); } });
    });
    document.getElementById('add-line').addEventListener('click', function () { addLine(); });
    var initial = [];
    try { initial = JSON.parse(box.dataset.initial || '[]'); } catch (e) { initial = []; }
    if (initial.length) { initial.forEach(function (it) { addLine(it); }); } else { addLine(); }
    recompute();
    var form = box.closest('form');
    form.addEventListener('submit', function (ev) {
      var ok = false;
      box.querySelectorAll('[name=product_id]').forEach(function (p) { if (p.value) { ok = true; } });
      if (!ok) { ev.preventDefault(); alert(box.dataset.empty || 'Add at least one product.'); return; }
      var bad = false;
      box.querySelectorAll('[name=discount]').forEach(function (d) { if (parseFloat(d.value || '0') > cap) { bad = true; } });
      if (bad) { ev.preventDefault(); alert((box.dataset.maxmsg || 'Maximum discount is {cap}%').replace('{cap}', cap)); }
    });
    if (partnerSel) {
      partnerSel.addEventListener('change', function () {
        catalog = null; box.innerHTML = ''; addLine(); recompute();
      });
    }
  }

  // ---- Payment form: load open invoices for the chosen customer ---------
  function bindPayment() {
    var partner = document.getElementById('pay_partner');
    var invoice = document.getElementById('pay_invoice');
    var amount = document.getElementById('pay_amount');
    if (!partner || !invoice) { return; }
    var preset = invoice.dataset.preset || '';
    function load() {
      invoice.innerHTML = '';
      if (!partner.value) { return; }
      fetch('/rep/customer/' + partner.value + '/invoices.json', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); }).then(function (items) {
          items.forEach(function (it) {
            var o = document.createElement('option');
            o.value = it.id; o.dataset.residual = it.residual;
            o.textContent = it.name + ' — ' + it.residual.toFixed(2) + ' / ' + it.total.toFixed(2);
            if (String(it.id) === preset) { o.selected = true; }
            invoice.appendChild(o);
          });
          fill();
        });
    }
    function fill() {
      var o = invoice.options[invoice.selectedIndex];
      if (o && amount && !amount.dataset.touched) { amount.value = o.dataset.residual; }
    }
    if (amount) { amount.addEventListener('input', function () { amount.dataset.touched = '1'; }); }
    invoice.addEventListener('change', function () { if (amount) { delete amount.dataset.touched; } fill(); });
    partner.addEventListener('change', function () { preset = ''; load(); });
    load();
  }

  // ======================================================================================
  // Forms: device id/time, GPS, offline queue
  // ======================================================================================
  var root = function () { return document.getElementById('mo-root') || document.body; };
  var banner = function () { return document.getElementById('mo-offline'); };
  var say = function (key, fallback) { var b = banner(); return (b && b.dataset[key]) || fallback; };
  var QKEY = 'mo_rep_queue', EKEY = 'mo_rep_errors';
  var uid = function () { return root().dataset.uid || '0'; };

  function uuid() {
    if (window.crypto && crypto.randomUUID) { return crypto.randomUUID(); }
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
      var r = Math.random() * 16 | 0; return (c === 'x' ? r : (r & 3 | 8)).toString(16);
    });
  }
  function store(key) { try { return JSON.parse(localStorage.getItem(key) || '[]'); } catch (e) { return []; } }
  function save(key, val) { try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) { /* storage full */ } }
  function mine() { return store(QKEY).filter(function (i) { return i.uid === uid(); }); }

  function stamp(form) {
    form.querySelectorAll('input[name=client_uid]').forEach(function (i) { if (!i.value) { i.value = uuid(); } });
    if (form.dataset.geo === '1' || form.dataset.queue === '1') {
      var t = form.querySelector('input[name=client_time]');
      if (!t) { t = document.createElement('input'); t.type = 'hidden'; t.name = 'client_time'; form.appendChild(t); }
      t.value = new Date().toISOString();
    }
  }

  function withGeo(form, done) {
    if (form.dataset.geo !== '1' || !navigator.geolocation) { done(); return; }
    navigator.geolocation.getCurrentPosition(function (pos) {
      var la = form.querySelector('input[name=lat]'), ln = form.querySelector('input[name=lng]');
      if (la) { la.value = pos.coords.latitude; }
      if (ln) { ln.value = pos.coords.longitude; }
      done();
    }, function () { done(); }, { enableHighAccuracy: true, timeout: 9000, maximumAge: 30000 });
  }

  // ---- connection chip -------------------------------------------------------------------
  function setChip() {
    var chip = document.getElementById('mo-conn');
    if (!chip) { return; }
    var n = mine().length, d = chip.dataset;
    var state = !navigator.onLine ? 'offline' : (chip.dataset.busy === '1' ? 'syncing' : (n ? 'pending' : 'online'));
    chip.dataset.state = state;
    var base = state === 'pending' ? d.online : (d[state] || d.online);
    chip.textContent = n && state !== 'syncing' ? base + ' · ' + n + ' ' + (d.pending || '') : base;
    var b = banner(); if (b) { b.hidden = navigator.onLine; }
  }

  function toast(text, bad) {
    var el = document.createElement('div');
    el.className = 'mo-flash' + (bad ? ' err' : ''); el.textContent = text; el.setAttribute('role', 'status');
    var main = document.querySelector('.mo-main'); if (main) { main.parentNode.insertBefore(el, main); }
    setTimeout(function () { el.remove(); }, 7000);
  }

  function enqueue(form, extra) {
    var fields = [], skipped = false;
    new FormData(form).forEach(function (v, k) {
      if (typeof v === 'string') { fields.push([k, v]); } else if (v && v.name) { skipped = true; }
    });
    if (extra) { fields.push(extra); }
    var q = store(QKEY);
    q.push({ id: uuid(), uid: uid(), url: form.getAttribute('action'), fields: fields, ts: Date.now() });
    save(QKEY, q);
    setChip();
    toast(say('queued', 'Saved on this device.') + (skipped ? ' ' + say('skipped', '') : ''));
    setTimeout(function () { window.location.href = '/rep'; }, 1200);
  }

  var syncing = false;
  function sync() {
    if (syncing || !navigator.onLine || !mine().length) { setChip(); return; }
    syncing = true;
    var chip = document.getElementById('mo-conn'); if (chip) { chip.dataset.busy = '1'; } setChip();
    var failed = [];
    fetch('/rep/csrf', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (t) {
      var items = mine();
      return items.reduce(function (chain, item) {
        return chain.then(function () {
          var fd = new FormData();
          item.fields.forEach(function (kv) { fd.append(kv[0], kv[0] === 'csrf_token' ? t.token : kv[1]); });
          return fetch(item.url, { method: 'POST', body: fd, credentials: 'same-origin' }).then(function (res) {
            var m = /[?&]msg=([^&]*)/.exec(res.url), bad = /[?&]kind=err/.test(res.url);
            if (res.ok && !bad) { save(QKEY, store(QKEY).filter(function (i) { return i.id !== item.id; })); }
            else if (bad || (res.status >= 400 && res.status < 500)) {
              save(QKEY, store(QKEY).filter(function (i) { return i.id !== item.id; }));
              failed.push(m ? decodeURIComponent(m[1].replace(/\+/g, ' ')) : item.url);
            } else { throw new Error('server'); }
          });
        });
      }, Promise.resolve());
    }).catch(function () { /* connection dropped: the rest stays queued */ }).then(function () {
      syncing = false;
      if (chip) { chip.dataset.busy = '0'; }
      setChip();
      failed.forEach(function (msg) { toast(msg + ' — ' + say('failed', 'could not be saved'), true); });
    });
  }

  function onSubmit(ev) {
    var form = ev.target;
    if (!(form instanceof HTMLFormElement) || ev.defaultPrevented) { return; }
    if ((form.method || 'get').toLowerCase() === 'get' || form.dataset.sending === '1') { return; }
    ev.preventDefault();
    var submitter = ev.submitter && ev.submitter.name ? [ev.submitter.name, ev.submitter.value] : null;
    stamp(form);
    var btns = form.querySelectorAll('button[type=submit]');
    btns.forEach(function (b) { b.disabled = true; });
    withGeo(form, function () {
      if (!navigator.onLine) {
        var allow = (form.dataset.queueAllow || '').split(',').filter(Boolean);
        if (form.dataset.queue === '1' && (!allow.length || (submitter && allow.indexOf(submitter[1]) !== -1))) {
          enqueue(form, submitter);
        } else {
          btns.forEach(function (b) { b.disabled = false; });
          alert(say('blocked', 'This action needs an internet connection.'));
        }
        return;
      }
      if (submitter) {
        var h = document.createElement('input'); h.type = 'hidden'; h.name = submitter[0]; h.value = submitter[1]; form.appendChild(h);
      }
      form.dataset.sending = '1';
      form.submit();
    });
  }

  // ---- quick actions sheet ------------------------------------------------------------------
  function bindFab() {
    var fab = document.getElementById('mo-fab'), sheet = document.getElementById('mo-sheet');
    if (!fab || !sheet) { return; }
    var toggle = function (open) { sheet.hidden = !open; fab.setAttribute('aria-expanded', open ? 'true' : 'false'); };
    fab.addEventListener('click', function () { toggle(sheet.hidden); });
    sheet.addEventListener('click', function (ev) { if (ev.target === sheet) { toggle(false); } });
    var close = document.getElementById('mo-sheet-close'); if (close) { close.addEventListener('click', function () { toggle(false); }); }
    document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') { toggle(false); } });
  }

  // ---- service worker, warm-up of the day's pages, sync triggers ------------------------------
  function bindOffline() {
    document.addEventListener('submit', onSubmit);
    window.addEventListener('online', function () { setChip(); sync(); });
    window.addEventListener('offline', setChip);
    var chip = document.getElementById('mo-conn');
    if (chip) { chip.addEventListener('click', function () { if (navigator.onLine) { sync(); } }); }
    setChip();
    if (navigator.onLine) { sync(); }
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/rep/sw.js', { scope: '/rep' }).catch(function () {});
      var logout = document.getElementById('mo-logout');
      if (logout) {
        logout.addEventListener('click', function () {
          if (navigator.serviceWorker.controller) { navigator.serviceWorker.controller.postMessage('clear'); }
          try { localStorage.removeItem('mo_rep_warm'); } catch (e) { /* ignore */ }
        });
      }
      warmUp();
    }
  }

  function warmUp() {
    var last = parseInt(localStorage.getItem('mo_rep_warm') || '0', 10);
    if (!navigator.onLine || Date.now() - last < 30 * 60 * 1000) { return; }
    setTimeout(function () {
      fetch('/rep/offline/manifest.json', { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (m) {
        var urls = m.urls.slice(), run = function () {
          var batch = urls.splice(0, 3);
          if (!batch.length) { try { localStorage.setItem('mo_rep_warm', String(Date.now())); } catch (e) { /* ignore */ } return; }
          Promise.all(batch.map(function (u) {
            return fetch(u, { credentials: 'same-origin', headers: { 'X-Mo-Warm': '1' } }).catch(function () {});
          })).then(run);
        };
        run();
      }).catch(function () {});
    }, 2500);
  }

  // ---- payment form: cheque details only for cheque methods --------------------------------------
  function bindCheque() {
    var sel = document.getElementById('method_id'), box = document.getElementById('cheque-box');
    if (!sel || !box) { return; }
    var req = ['chq_no', 'chq_bank', 'chq_due'].map(function (id) { return document.getElementById(id); });
    function apply() {
      var o = sel.options[sel.selectedIndex], on = !!o && o.dataset.type === 'cheque';
      box.hidden = !on;
      req.forEach(function (i) { if (i) { i.required = on; } });
    }
    sel.addEventListener('change', apply); apply();
  }

  // ---- customer return: customer -> invoice / order -> products, quantity, reason ----------------------
  function bindReturn() {
    var form = document.getElementById('return-form');
    if (!form) { return; }
    var partner = document.getElementById('r_partner'), order = document.getElementById('r_order');
    var lines = document.getElementById('r_lines'), reasons = document.getElementById('r_reasons');
    var docs = [];
    function renderLines() {
      lines.innerHTML = '';
      var doc = docs.filter(function (d) { return String(d.id) === order.value; })[0];
      if (!doc) { return; }
      doc.lines.forEach(function (l) {
        var div = document.createElement('div'); div.className = 'mo-return-line';
        div.innerHTML = '<input type="hidden" name="move_id" value="' + l.move_id + '"/><b>' + esc(l.product) + '</b>' +
          '<div class="mo-muted">' + esc(lines.dataset.max || 'Max') + ': ' + l.max + ' ' + esc(l.uom) + '</div>' +
          '<div class="mo-grid"><div><label>' + esc(lines.dataset.qty || 'Quantity') + '</label>' +
          '<input type="number" name="qty" class="mo-input" min="0" max="' + l.max + '" step="any" value="0" inputmode="decimal"/></div>' +
          '<div><label>' + esc(lines.dataset.reason || 'Reason') + '</label><select name="reason_id" class="mo-input">' +
          reasons.innerHTML + '</select></div></div>';
        lines.appendChild(div);
      });
    }
    function loadOrders() {
      order.innerHTML = ''; lines.innerHTML = ''; docs = [];
      if (!partner.value) { return; }
      fetch('/rep/customer/' + partner.value + '/returnable.json', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); }).then(function (items) {
          docs = items;
          var first = document.createElement('option'); first.value = '';
          first.textContent = items.length ? (order.dataset.choose || 'Choose') : (order.dataset.none || 'Nothing can be returned');
          order.appendChild(first);
          items.forEach(function (d) {
            var o = document.createElement('option'); o.value = d.id;
            o.textContent = d.name + ' · ' + d.date + (d.invoices ? ' · ' + d.invoices : '');
            order.appendChild(o);
          });
        });
    }
    partner.addEventListener('change', loadOrders);
    order.addEventListener('change', renderLines);
    form.addEventListener('submit', function (ev) {
      var any = false;
      lines.querySelectorAll('.mo-return-line').forEach(function (l) {
        var q = parseFloat(l.querySelector('[name=qty]').value || '0'), max = parseFloat(l.querySelector('[name=qty]').max);
        if (q > max) { ev.preventDefault(); alert('> ' + max); }
        if (q > 0) { any = true; }
      });
      if (!any) { ev.preventDefault(); }
    });
    loadOrders();
  }

  // ======================================================================================
  // Dashboard: animated numbers, SVG charts, live refresh (no external library)
  // ======================================================================================
  var NS = 'http://www.w3.org/2000/svg';
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function cssVar(name, fb) { return (getComputedStyle(document.documentElement).getPropertyValue(name) || '').trim() || fb; }
  function el(tag, attrs, parent) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (parent) { parent.appendChild(n); }
    return n;
  }
  function fmt(v, kind) {
    v = Number(v) || 0;
    if (kind === 'int') { return Math.round(v).toLocaleString(); }
    if (kind === 'pct') { return (Math.round(v * 10) / 10).toLocaleString(); }
    return v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function compact(v) {
    var a = Math.abs(v);
    if (a >= 1e6) { return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1) + 'M'; }
    if (a >= 1e3) { return (v / 1e3).toFixed(a >= 1e4 ? 0 : 1) + 'k'; }
    return String(Math.round(v));
  }
  function countTo(node, to, kind, instant) {
    var from = node._v === undefined ? 0 : node._v;
    node._v = to;
    if (instant || reduced || from === to) { node.textContent = fmt(to, kind); return; }
    var t0 = null, dur = 750;
    function step(ts) {
      if (t0 === null) { t0 = ts; }
      var p = Math.min(1, (ts - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      node.textContent = fmt(from + (to - from) * e, kind);
      if (p < 1) { requestAnimationFrame(step); } else { node.textContent = fmt(to, kind); }
    }
    requestAnimationFrame(step);
  }
  function empty(host, text) {
    host.innerHTML = '';
    var d = document.createElement('div'); d.className = 'mo-empty'; d.textContent = text; host.appendChild(d);
  }
  function smoothPath(pts, top, bottom) {
    if (pts.length < 2) { return 'M' + pts[0][0] + ',' + pts[0][1]; }
    var d = 'M' + pts[0][0] + ',' + pts[0][1];
    for (var i = 0; i < pts.length - 1; i++) {
      var p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2, k = 0.18;
      var c1y = Math.max(top, Math.min(bottom, p1[1] + (p2[1] - p0[1]) * k));
      var c2y = Math.max(top, Math.min(bottom, p2[1] - (p3[1] - p1[1]) * k));
      d += ' C' + (p1[0] + (p2[0] - p0[0]) * k) + ',' + c1y + ' ' + (p2[0] - (p3[0] - p1[0]) * k) + ',' + c2y + ' ' + p2[0] + ',' + p2[1];
    }
    return d;
  }

  function lineChart(host, labels, series, L, instant) {
    var all = [].concat.apply([], series.map(function (s) { return s.values; }));
    if (!all.some(function (v) { return v > 0; })) { empty(host, L.none); return; }
    host.innerHTML = '';
    var legend = document.createElement('div'); legend.className = 'legend';
    series.forEach(function (s) { legend.innerHTML += '<span><i style="background:' + s.color + '"></i>' + s.name + '</span>'; });
    host.appendChild(legend);
    var W = 640, H = 230, pad = { l: 46, r: 12, t: 12, b: 26 }, base = H - pad.b;
    var max = Math.max.apply(null, all), step = Math.pow(10, Math.floor(Math.log10(max))), top = Math.ceil(max / step) * step;
    var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img' }, host);
    var defs = el('defs', {}, svg);
    for (var g = 0; g <= 4; g++) {
      var y = pad.t + (base - pad.t) * g / 4;
      el('line', { x1: pad.l, x2: W - pad.r, y1: y, y2: y, stroke: cssVar('--line', '#d9e1e8'), 'stroke-dasharray': g === 4 ? '' : '3 4' }, svg);
      var tx = el('text', { x: pad.l - 6, y: y + 4, 'text-anchor': 'end' }, svg); tx.textContent = compact(top * (4 - g) / 4);
    }
    var n = labels.length, dx = (W - pad.l - pad.r) / Math.max(1, n - 1), every = Math.ceil(n / 7);
    labels.forEach(function (lb, i) {
      if (i % every === 0 || i === n - 1) {
        var t = el('text', { x: pad.l + dx * i, y: H - 7, 'text-anchor': 'middle' }, svg); t.textContent = lb;
      }
    });
    series.forEach(function (s, si) {
      var pts = s.values.map(function (v, i) { return [pad.l + dx * i, base - (v / top) * (base - pad.t)]; });
      var gid = 'mo-grad-' + si + '-' + Math.random().toString(36).slice(2, 7);
      var gr = el('linearGradient', { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
      el('stop', { offset: '0%', 'stop-color': s.color, 'stop-opacity': '.32' }, gr);
      el('stop', { offset: '100%', 'stop-color': s.color, 'stop-opacity': '0' }, gr);
      var line = smoothPath(pts, pad.t, base);
      el('path', { d: line + ' L' + pts[pts.length - 1][0] + ',' + base + ' L' + pts[0][0] + ',' + base + ' Z', fill: 'url(#' + gid + ')' }, svg);
      var path = el('path', { d: line, fill: 'none', stroke: s.color, 'stroke-width': 2.6, 'stroke-linecap': 'round' }, svg);
      if (!instant && !reduced && path.getTotalLength) {
        var len = path.getTotalLength(); path.style.strokeDasharray = len; path.style.strokeDashoffset = len;
        requestAnimationFrame(function () { requestAnimationFrame(function () {
          path.style.transition = 'stroke-dashoffset 1.1s ease'; path.style.strokeDashoffset = 0;
        }); });
      }
      pts.forEach(function (p, i) {
        var c = el('circle', { cx: p[0], cy: p[1], r: i === pts.length - 1 ? 4.5 : 3, fill: s.color, opacity: i === pts.length - 1 ? 1 : 0.0 }, svg);
        var hit = el('circle', { cx: p[0], cy: p[1], r: 11, fill: 'transparent' }, svg);
        hit.addEventListener('mouseenter', function () { c.setAttribute('opacity', 1); });
        hit.addEventListener('mouseleave', function () { c.setAttribute('opacity', i === pts.length - 1 ? 1 : 0); });
        var tt = el('title', {}, hit); tt.textContent = labels[i] + ' · ' + s.name + ': ' + fmt(s.values[i], 'money');
      });
    });
  }

  function donut(host, items, L, instant) {
    var total = items.reduce(function (a, i) { return a + i.value; }, 0);
    if (!total) { empty(host, L.none); return; }
    host.innerHTML = '';
    var wrap = document.createElement('div'); wrap.className = 'mo-donut-wrap'; host.appendChild(wrap);
    var svg = el('svg', { viewBox: '0 0 140 140', role: 'img' }, wrap);
    var R = 52, C = 2 * Math.PI * R, acc = 0;
    el('circle', { cx: 70, cy: 70, r: R, fill: 'none', stroke: 'rgba(128,128,128,.2)', 'stroke-width': 18 }, svg);
    items.forEach(function (it) {
      if (!it.value) { return; }
      var len = C * it.value / total;
      var seg = el('circle', { cx: 70, cy: 70, r: R, fill: 'none', stroke: it.color, 'stroke-width': 18,
        'stroke-dasharray': (instant || reduced ? len : 0) + ' ' + C, 'stroke-dashoffset': -acc, transform: 'rotate(-90 70 70)' }, svg);
      if (!instant && !reduced) {
        seg.style.transition = 'stroke-dasharray .9s ease';
        requestAnimationFrame(function () { requestAnimationFrame(function () { seg.setAttribute('stroke-dasharray', len + ' ' + C); }); });
      }
      acc += len;
    });
    var t1 = el('text', { x: 70, y: 76, 'text-anchor': 'middle', style: 'font-size:26px;font-weight:700;fill:var(--ink)' }, svg); t1.textContent = total;
    var ul = document.createElement('ul');
    items.forEach(function (it) { ul.innerHTML += '<li><span><i style="background:' + it.color + '"></i>' + it.label + '</span><b>' + it.value + '</b></li>'; });
    wrap.appendChild(ul);
  }

  function rings(host, rows, instant) {
    host.innerHTML = '';
    var wrap = document.createElement('div'); wrap.className = 'mo-rings'; host.appendChild(wrap);
    rows.forEach(function (r) {
      var box = document.createElement('div'); box.className = 'mo-ring'; wrap.appendChild(box);
      var svg = el('svg', { viewBox: '0 0 100 100', role: 'img' }, box), R = 40, C = 2 * Math.PI * R;
      var pct = Math.min(100, r.pct), color = r.pct >= 100 ? '#2fb59b' : (r.pct >= 60 ? cssVar('--primary', '#0e6b5c') : cssVar('--accent', '#f2a900'));
      el('circle', { cx: 50, cy: 50, r: R, fill: 'none', stroke: 'rgba(128,128,128,.22)', 'stroke-width': 10 }, svg);
      var arc = el('circle', { cx: 50, cy: 50, r: R, fill: 'none', stroke: color, 'stroke-width': 10, 'stroke-linecap': 'round',
        'stroke-dasharray': (instant || reduced ? C * pct / 100 : 0) + ' ' + C, transform: 'rotate(-90 50 50)' }, svg);
      if (!instant && !reduced) {
        arc.style.transition = 'stroke-dasharray 1s ease';
        requestAnimationFrame(function () { requestAnimationFrame(function () { arc.setAttribute('stroke-dasharray', (C * pct / 100) + ' ' + C); }); });
      }
      var tx = el('text', { x: 50, y: 56, 'text-anchor': 'middle', class: 'big' }, svg); tx.textContent = Math.round(r.pct) + '%';
      var lb = document.createElement('span'); lb.className = 'lbl'; lb.textContent = r.label; box.appendChild(lb);
      var sm = document.createElement('span'); sm.className = 'lbl';
      sm.textContent = (r.money ? compact(r.actual) + ' / ' + compact(r.target) : Math.round(r.actual) + ' / ' + Math.round(r.target)); box.appendChild(sm);
    });
  }

  function hbars(host, rows, L, instant) {
    if (!rows.length) { empty(host, L.none); return; }
    host.innerHTML = '';
    var wrap = document.createElement('div'); wrap.className = 'mo-hbars'; host.appendChild(wrap);
    var max = Math.max.apply(null, rows.map(function (r) { return r.value; })) || 1;
    var palette = [cssVar('--primary', '#0e6b5c'), '#17947d', '#2fb59b', cssVar('--accent', '#f2a900'), '#e8a54b'];
    rows.forEach(function (r, i) {
      var row = document.createElement('div'); row.className = 'row';
      row.innerHTML = '<div class="top"><span></span><b>' + fmt(r.value, 'money') + '</b></div><div class="track"><i></i></div>';
      row.querySelector('.top span').textContent = r.name;
      var bar = row.querySelector('i'); bar.style.background = palette[i % palette.length];
      var w = Math.max(3, 100 * r.value / max);
      if (instant || reduced) { bar.style.width = w + '%'; }
      else {
        bar.style.width = '0'; bar.style.transition = 'width .9s cubic-bezier(.2,.8,.2,1) ' + (i * 0.07) + 's';
        requestAnimationFrame(function () { requestAnimationFrame(function () { bar.style.width = w + '%'; }); });
      }
      wrap.appendChild(row);
    });
  }

  function agingBar(host, ag, L) {
    var keys = ['current', 'd30', 'd60', 'd90', 'd90p'], colors = ['#2fb59b', '#8ac26b', '#f2a900', '#e8743b', '#c8372d'];
    var total = keys.reduce(function (a, k) { return a + Math.max(0, ag[k] || 0); }, 0);
    if (!total) { empty(host, L.none); return; }
    host.innerHTML = '';
    var bar = document.createElement('div'); bar.className = 'mo-stack';
    var lg = document.createElement('div'); lg.className = 'mo-stack-legend';
    keys.forEach(function (k, i) {
      var v = Math.max(0, ag[k] || 0), seg = document.createElement('i');
      seg.style.background = colors[i]; seg.style.flexGrow = 0; seg.title = L[k] + ': ' + fmt(v, 'money');
      bar.appendChild(seg);
      requestAnimationFrame(function () { requestAnimationFrame(function () { seg.style.flexGrow = v; }); });
      lg.innerHTML += '<span><i style="background:' + colors[i] + '"></i>' + L[k] + ' · ' + compact(v) + '</span>';
    });
    host.appendChild(bar); host.appendChild(lg);
  }

  function spark(svg, values) {
    if (!svg) { return; }
    svg.innerHTML = '';
    var max = Math.max.apply(null, values), min = Math.min.apply(null, values);
    if (!(max > 0)) { return; }
    var span = (max - min) || 1, n = values.length;
    var pts = values.map(function (v, i) { return (100 * i / (n - 1)).toFixed(1) + ',' + (30 - 26 * (v - min) / span).toFixed(1); }).join(' ');
    el('polyline', { points: pts, fill: 'none', stroke: 'currentColor', 'stroke-width': 1.8, 'stroke-linecap': 'round',
      'stroke-linejoin': 'round', 'vector-effect': 'non-scaling-stroke' }, svg);
  }

  function delta(node, today, yesterday) {
    if (!node) { return; }
    if (!yesterday || !(today >= 0)) { node.hidden = true; return; }
    var p = 100 * (today - yesterday) / yesterday;
    node.hidden = false; node.className = 'delta ' + (p >= 0 ? 'up' : 'down');
    node.textContent = (p >= 0 ? '▲ ' : '▼ ') + Math.abs(Math.round(p)) + '%';
  }

  function bindDashboard() {
    var host = document.getElementById('mo-dash');
    if (!host) { return; }
    var data;
    try { data = JSON.parse(host.dataset.dash); } catch (e) { return; }
    var live = document.getElementById('mo-live'), updated = document.getElementById('mo-updated');
    var first = true;
    function render(d, instant) {
      var L = d.labels, primary = cssVar('--primary', '#0e6b5c'), accent = cssVar('--accent', '#f2a900');
      host.querySelectorAll('[data-stat]').forEach(function (n) {
        var v = d.stats[n.dataset.stat];
        if (v === null || v === undefined) { return; }
        var changed = n._v !== undefined && n._v !== v;
        countTo(n, v, n.dataset.fmt || 'int', instant);
        if (changed) { n.classList.remove('mo-flash-update'); void n.offsetWidth; n.classList.add('mo-flash-update'); }
      });
      var s = d.series, n = s.sales.length;
      delta(document.getElementById('delta-sales'), s.sales[n - 1], s.sales[n - 2]);
      delta(document.getElementById('delta-coll'), s.collection[n - 1], s.collection[n - 2]);
      spark(document.getElementById('spark-sales'), s.sales);
      spark(document.getElementById('spark-coll'), s.collection);
      var trend = document.getElementById('chart-trend');
      if (trend) { lineChart(trend, s.labels, [{ name: L.sales, values: s.sales, color: primary },
                                               { name: L.collection, values: s.collection, color: accent }], L, instant); }
      var vis = document.getElementById('chart-visits');
      if (vis) { donut(vis, [{ label: L.completed, value: d.visits.completed, color: '#2fb59b' },
                             { label: L.started, value: d.visits.started, color: '#1f5fbf' },
                             { label: L.planned, value: d.visits.planned, color: accent },
                             { label: L.missed, value: d.visits.missed, color: '#c8372d' }], L, instant); }
      var tg = document.getElementById('chart-targets'); if (tg && d.targets.length) { rings(tg, d.targets, instant); }
      var ag = document.getElementById('chart-aging'); if (ag) { agingBar(ag, d.aging, L); }
      var top = document.getElementById('chart-top'); if (top) { hbars(top, d.top, L, instant); }
      if (updated) { var now = new Date(); updated.textContent = L.updated + ' ' + now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
      first = false;
    }
    function setLive() { if (live) { live.dataset.off = navigator.onLine ? '0' : '1'; } }
    function refresh() {
      if (!navigator.onLine || document.visibilityState !== 'visible') { return; }
      fetch('/rep/dashboard.json', { credentials: 'same-origin' }).then(function (r) { return r.json(); })
        .then(function (d) { render(d, true); }).catch(function () {});
    }
    render(data, false);
    setLive();
    window.addEventListener('online', function () { setLive(); refresh(); });
    window.addEventListener('offline', setLive);
    document.addEventListener('visibilitychange', refresh);
    setInterval(refresh, 60000);
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindOffline(); bindFab(); bindDashboard(); bindTracking(); bindLines(); bindPayment(); bindCheque(); bindReturn();
    document.querySelectorAll('input[name=client_uid]').forEach(function (i) { if (!i.value) { i.value = uuid(); } });
    var flash = document.querySelector('.mo-flash');
    if (flash && window.history && history.replaceState) {
      var u = new URL(window.location.href);
      u.searchParams.delete('msg'); u.searchParams.delete('kind');
      history.replaceState(null, '', u.pathname + (u.search || ''));
    }
  });
})();
