/* Theme menu: Auto (follow the phone) / Dark / Light. Loaded on every portal page. */
(function () {
  'use strict';
  var root = document.documentElement;
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
  var ICON = { auto: '\uD83C\uDF13', dark: '\uD83C\uDF19', light: '\u2600\uFE0F' };
  var LABELS = {
    en: { auto: 'Auto (same as phone)', dark: 'Dark', light: 'Light' },
    ar: { auto: '\u062A\u0644\u0642\u0627\u0626\u064A (\u0645\u062B\u0644 \u0627\u0644\u0645\u0648\u0628\u0627\u064A\u0644)', dark: '\u062F\u0627\u0643\u0646', light: '\u0641\u0627\u062A\u062D' }
  };
  var ORDER = ['auto', 'dark', 'light'];

  function isArabic() {
    return (root.lang || '').slice(0, 2) === 'ar' || !!document.querySelector('.mo-app[dir="rtl"]');
  }
  function mode() {
    var t = root.getAttribute('data-theme');
    return (t === 'dark' || t === 'light') ? t : 'auto';
  }
  function apply(m) {
    if (m === 'auto') { root.removeAttribute('data-theme'); } else { root.setAttribute('data-theme', m); }
    try {
      if (m === 'auto') { localStorage.removeItem('mo_theme'); } else { localStorage.setItem('mo_theme', m); }
    } catch (e) { /* private mode: still applies to this page */ }
  }
  function paint(btn) {
    var m = mode(), L = LABELS[isArabic() ? 'ar' : 'en'];
    btn.textContent = ICON[m];
    btn.setAttribute('data-mode', m);
    btn.setAttribute('title', L[m]);
    var dark = m === 'dark' || (m === 'auto' && mq && mq.matches);
    var meta = document.querySelector('meta[name=theme-color]');
    if (meta) { meta.setAttribute('content', dark ? '#0f1820' : '#0e6b5c'); }
  }

  function init() {
    var btn = document.getElementById('mo-theme');
    if (!btn) {  // pages without the header (e.g. "No access"): float the button in the corner
      btn = document.createElement('button');
      btn.type = 'button'; btn.id = 'mo-theme'; btn.className = 'mo-theme float';
      document.body.appendChild(btn);
    }
    btn.setAttribute('aria-haspopup', 'menu');
    var menu = null;

    function close() {
      if (menu) { menu.parentNode.removeChild(menu); menu = null; btn.setAttribute('aria-expanded', 'false'); }
    }
    function open() {
      var L = LABELS[isArabic() ? 'ar' : 'en'], current = mode(), rtl = isArabic();
      menu = document.createElement('div');
      menu.className = 'mo-theme-menu'; menu.setAttribute('role', 'menu');
      if (rtl) { menu.setAttribute('dir', 'rtl'); }
      ORDER.forEach(function (m) {
        var it = document.createElement('button');
        it.type = 'button'; it.setAttribute('role', 'menuitemradio');
        it.setAttribute('aria-checked', m === current ? 'true' : 'false');
        it.className = 'mo-theme-item' + (m === current ? ' on' : '');
        it.innerHTML = '<span class="ic"></span><span class="tx"></span><span class="ck"></span>';
        it.querySelector('.ic').textContent = ICON[m];
        it.querySelector('.tx').textContent = L[m];
        it.querySelector('.ck').textContent = m === current ? '\u2713' : '';
        it.addEventListener('click', function () { apply(m); paint(btn); close(); });
        menu.appendChild(it);
      });
      document.body.appendChild(menu);
      var r = btn.getBoundingClientRect();
      menu.style.top = (r.bottom + 6) + 'px';
      if (rtl) { menu.style.left = Math.max(8, r.left) + 'px'; } else { menu.style.right = Math.max(8, window.innerWidth - r.right) + 'px'; }
      btn.setAttribute('aria-expanded', 'true');
      var first = menu.querySelector('.on') || menu.firstChild;
      if (first) { first.focus(); }
    }

    btn.addEventListener('click', function (ev) { ev.stopPropagation(); if (menu) { close(); } else { open(); } });
    document.addEventListener('click', function (ev) { if (menu && !menu.contains(ev.target)) { close(); } });
    document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape' && menu) { close(); btn.focus(); } });
    window.addEventListener('resize', close);
    if (mq && mq.addEventListener) { mq.addEventListener('change', function () { paint(btn); }); }
    paint(btn);

    // Always-visible selector (More page): Auto / Dark / Light
    var opts = document.querySelectorAll('[data-mo-theme]');
    function markOpts() {
      var cur = mode();
      Array.prototype.forEach.call(opts, function (b) {
        var on = b.getAttribute('data-mo-theme') === cur;
        b.classList.toggle('on', on); b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    }
    Array.prototype.forEach.call(opts, function (b) {
      b.addEventListener('click', function () { apply(b.getAttribute('data-mo-theme')); paint(btn); markOpts(); });
    });
    markOpts();
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
