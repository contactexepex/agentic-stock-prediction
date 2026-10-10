/* Market Brief dashboard app. Reads the JSON embedded by scripts/dashboard.py and renders four views
   (overview, stock, track record, how to read). Every number shown is a stored value or a plain ratio
   of stored prices computed by the builder; this script only formats. No network access. */
(function () {
  'use strict';
  var D = JSON.parse(document.getElementById('mb-data').textContent);
  var LOC = D.market === 'india' ? 'en-IN' : 'en-US';
  var UP = '#2a78d6', DOWN = '#e34948', BAND = '#4a3aa7', LATE = '#898781';
  var STATUS = {
    confirmed_primary: ['st-good', '✓', 'Confirmed by filing'],
    corroborated: ['st-good', '✓', 'Corroborated'],
    single_source: ['st-warn', '!', 'Single source'],
    unverified: ['st-neutral', '?', 'Unverified'],
    rumour: ['st-serious', '✕', 'Rumour'],
    promotional: ['st-serious', '✕', 'Promotional'],
    contradicted: ['st-critical', '✕', 'Contradicted']
  };
  var byTicker = {};
  (D.companies || []).forEach(function (c) { byTicker[c.ticker] = c; });
  var state = { view: 'overview', ticker: D.companies && D.companies.length ? D.companies[0].ticker : null,
    span: D.default_span, sort: { key: 'sector', dir: 1 }, q: '', sector: '', heat: '1d' };
  var chart = null, chartRedraw = null;

  // ---------- formatting ----------
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (ch) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
  }
  // plain http(s) with quote and angle-bracket characters percent-encoded, as view_data.safe_url (issue #48)
  function safeUrl(u) {
    if (typeof u !== 'string' || !/^https?:\/\/\S+$/i.test(u.trim())) return null;
    return u.trim().replace(/["'<>`]/g, function (ch) { return '%' + ch.charCodeAt(0).toString(16).toUpperCase(); });
  }
  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  function num(v, d) {
    if (!isNum(v)) return '–';
    d = d == null ? (Math.abs(v) >= 10000 ? 1 : 2) : d;
    return v.toLocaleString(LOC, { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function money(v, d) { return isNum(v) ? D.symbol + num(v, d) : '–'; }
  function pct(v, d, sign) {
    if (!isNum(v)) return '–';
    var s = (v * 100).toFixed(d == null ? 1 : d);
    if (sign !== false && v > 0) s = '+' + s;
    return s.replace('-', '−') + '%';
  }
  function prob(v) { return isNum(v) ? (v * 100).toFixed(1) + '%' : '–'; }
  function cls(v) { return !isNum(v) || v === 0 ? 'flat' : (v > 0 ? 'up' : 'down'); }
  function arrow(v) { return !isNum(v) || v === 0 ? '' : (v > 0 ? '▲ ' : '▼ '); }
  function signed(v, d) { return '<span class="' + cls(v) + '">' + arrow(v) + pct(v, d) + '</span>'; }
  var MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  function day(iso) {
    if (!iso) return '–';
    var p = iso.slice(0, 10).split('-').map(Number), dt = new Date(Date.UTC(p[0], p[1] - 1, p[2]));
    return DAYS[dt.getUTCDay()] + ' ' + p[2] + ' ' + MONTHS[p[1] - 1];
  }
  function stamp(iso) {
    if (!iso) return '–';
    var t = new Date(iso);
    if (isNaN(t)) return iso;
    return t.getUTCDate() + ' ' + MONTHS[t.getUTCMonth()] + ' ' + String(t.getUTCHours()).padStart(2, '0') + ':' +
      String(t.getUTCMinutes()).padStart(2, '0') + ' UTC';
  }
  function badge(status) {
    var s = STATUS[status] || STATUS.unverified;
    return '<span class="badge ' + s[0] + '"><span aria-hidden="true">' + s[1] + '</span>' + esc(s[2]) + '</span>';
  }
  function link(title, url) {
    var u = safeUrl(url);
    return u ? '<a href="' + esc(u) + '" target="_blank" rel="noopener noreferrer">' + esc(title) + '</a>' : esc(title);
  }
  function paperTag() {
    return '<span class="paper' + (D.skill.state === 'shown' ? ' shown' : '') + '"><span aria-hidden="true">' +
      (D.skill.state === 'shown' ? '✓' : '⚠') + '</span>' + esc(D.skill.label) + '</span>';
  }
  function empty(text) { return '<div class="empty">' + esc(text) + '</div>'; }
  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
  function modelOf(c, h) { return (c.model || []).filter(function (m) { return m.h === h; })[0] || null; }
  function rangeOf(c, h) { return (c.ranges || []).filter(function (r) { return r.h === h; })[0] || null; }
  function probBar(p) {
    if (!isNum(p)) return '<span class="muted">–</span>';
    var w = Math.min(50, Math.abs(p - 0.5) * 100 * 4), left = p >= 0.5 ? 50 : 50 - w;
    return '<span class="prob"><span class="tab-num">' + prob(p) + '</span><span class="pbar" aria-hidden="true"><i class="' +
      (p >= 0.5 ? '' : 'dn') + '" style="left:' + left + '%;width:' + w + '%"></i></span></span>';
  }
  function spark(points, w, h) {
    var vals = points.map(function (p) { return p[1]; }).filter(isNum);
    if (vals.length < 2) return '';
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), span = hi - lo || 1;
    var d = vals.map(function (v, i) {
      return (i ? 'L' : 'M') + (i * (w - 2) / (vals.length - 1) + 1).toFixed(1) + ' ' + (h - 1 - (v - lo) / span * (h - 2)).toFixed(1);
    }).join(' ');
    var colour = vals[vals.length - 1] >= vals[0] ? UP : DOWN;
    return '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" aria-hidden="true"><path d="' + d +
      '" fill="none" stroke="' + colour + '" stroke-width="1.5" stroke-linejoin="round"/></svg>';
  }

  // ---------- shell: market switch, tabs, banner, footer ----------
  function shell() {
    // relative: the static reports site is gone (owner, 2026-10-10), so the switch opens the sibling page
    var base = '../';
    document.getElementById('markets').innerHTML = (D.markets || [D.market]).map(function (m) {
      var label = m === 'us' ? 'US' : cap(m);
      return m === D.market ? '<span aria-current="page">' + esc(label) + '</span>' :
        '<a href="' + esc(base + encodeURIComponent(m) + '/dashboard.html') + '">' + esc(label) + '</a>';
    }).join('');
    var b = document.getElementById('banner');
    if (D.skill.state === 'shown') b.classList.add('shown');
    b.innerHTML = '<div class="inner"><strong><span aria-hidden="true">' + (D.skill.state === 'shown' ? '✓ ' : '⚠ ') + '</span>' +
      esc(D.skill.label) + '</strong><span>' + esc(D.disclaimer) + '</span><span class="small hide-sm">' + esc(D.skill.why) + '</span></div>';
    document.getElementById('foot').innerHTML = '<p>' + esc(D.disclaimer) + ' Nothing here places a trade. Data as of the close of ' +
      esc(day(D.as_of)) + '; page built ' + esc(stamp(D.generated_at)) + ' from the stored data of the ' + esc(D.name) +
      ' routine.</p><p>Charts: TradingView Lightweight Charts™ (Apache-2.0), bundled in this file; no network needed.</p>';
    Array.prototype.forEach.call(document.querySelectorAll('#tabs button'), function (btn) {
      btn.addEventListener('click', function () { go(btn.dataset.view, btn.dataset.view === 'stock' ? state.ticker : null); });
      btn.addEventListener('keydown', function (e) {
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
        var tabs = Array.prototype.slice.call(document.querySelectorAll('#tabs button'));
        var i = (tabs.indexOf(btn) + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length;
        tabs[i].focus(); tabs[i].click();
      });
    });
  }

  function go(view, ticker) {
    var hash = view === 'stock' && ticker ? '#stock/' + encodeURIComponent(ticker) : '#' + view;
    if (location.hash !== hash) location.hash = hash; else route();
  }

  function route() {
    var h = decodeURIComponent((location.hash || '#overview').slice(1));
    var view = h.split('/')[0] || 'overview', ticker = h.indexOf('/') > 0 ? h.slice(h.indexOf('/') + 1) : null;
    if (['overview', 'stock', 'track', 'how'].indexOf(view) < 0) view = 'overview';
    if (ticker && byTicker[ticker]) state.ticker = ticker;
    state.view = view;
    Array.prototype.forEach.call(document.querySelectorAll('#tabs button'), function (btn) {
      var on = btn.dataset.view === view;
      btn.setAttribute('aria-selected', on ? 'true' : 'false'); btn.tabIndex = on ? 0 : -1;
    });
    Array.prototype.forEach.call(document.querySelectorAll('.view'), function (v) { v.classList.toggle('active', v.id === 'view-' + view); });
    if (view === 'overview') renderOverview();
    if (view === 'stock') renderStock();
    if (view === 'track') renderTrack();
    if (view === 'how') renderHow();
  }

  window.MB = { D: D, locale: LOC, state: state, go: go, esc: esc, num: num, money: money, pct: pct, prob: prob, day: day, stamp: stamp,
    badge: badge, link: link, paperTag: paperTag, empty: empty, cap: cap, modelOf: modelOf, rangeOf: rangeOf,
    probBar: probBar, spark: spark, signed: signed, cls: cls, isNum: isNum, byTicker: byTicker,
    colours: { UP: UP, DOWN: DOWN, BAND: BAND, LATE: LATE },
    chart: function (c) { return chart; }, setChart: function (c, r) { chart = c; chartRedraw = r; } };
  var renderOverview = function () { window.MB.renderOverview(); };
  var renderStock = function () { window.MB.renderStock(); };
  var renderTrack = function () { window.MB.renderTrack(); };
  var renderHow = function () { window.MB.renderHow(); };
  window.MB.boot = function () { shell(); window.addEventListener('hashchange', route); route(); };
})();
