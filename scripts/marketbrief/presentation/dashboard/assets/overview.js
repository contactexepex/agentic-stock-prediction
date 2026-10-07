/* Overview view: market tiles, cues, sector heatmap and the full watchlist table. */
(function (MB) {
  'use strict';
  var D = MB.D, state = MB.state, esc = MB.esc;

  function tile(label, value, delta, extra) {
    return '<div class="card tile"><div class="label">' + esc(label) + '</div><div class="value">' + value + '</div>' +
      (delta ? '<div class="delta">' + delta + '</div>' : '') + (extra || '') + '</div>';
  }

  function tiles(o) {
    var out = [], b = o.benchmark, v = o.vol_index, r = o.regime;
    if (b && b.last) {
      out.push(tile(b.name + ' · ' + MB.day(b.last.date), MB.num(b.last.close), MB.signed(b.last.change, 2) +
        ' <span class="muted small">gap ' + MB.pct(b.last.gap, 2) + '</span>', '<div style="margin-top:6px">' + MB.spark(b.spark, 160, 32) + '</div>'));
    }
    if (v && v.last) out.push(tile(v.name + ' (fear gauge)', MB.num(v.last.close, 2), MB.signed(v.last.change, 1)));
    if (r) {
      out.push(tile('Market regime · ' + MB.day(r.as_of), esc(r.code.replace('_', ' ').toLowerCase()), '',
        '<p class="small sub" style="margin-top:4px">' + esc(r.plain) + (r.stress ? ' Stress mode is on.' : '') + '</p>'));
    }
    if (D.plan) {
      out.push(tile('Next session plan', esc(MB.day(D.plan.entry)), '',
        '<p class="small sub" style="margin-top:4px">Signals assume a buy at the open of ' + esc(MB.day(D.plan.entry)) + '. ' +
        D.plan.horizons.map(function (k) { return 'N+' + k + ': sell at the close of ' + esc(MB.day(D.plan.exits[String(k)])); }).join('. ') + '.</p>'));
    }
    return '<div class="grid g4 tiles">' + out.join('') + '</div>';
  }

  function cues(o) {
    if (!o.cues.length) return '';
    var rows = o.cues.map(function (q) {
      return '<tr><td>' + esc(q.name) + '</td><td>' + esc(q.role) + '</td><td class="r">' + MB.num(q.price) + '</td><td class="r">' +
        MB.signed(q.change, 2) + '</td><td class="small muted">' + esc(MB.stamp(q.collected_at)) + '</td></tr>';
    }).join('');
    return '<div class="card section"><h2>Overnight cues and global factors</h2><p class="sub small">Newest stored quote per symbol; the change is against the previous close. Times are when the routine stored the quote.</p>' +
      '<div class="table-wrap"><table><thead><tr><th>Symbol</th><th>Role</th><th class="r">Price</th><th class="r">Change</th><th>Stored</th></tr></thead><tbody>' +
      rows + '</tbody></table></div></div>';
  }

  // diverging scale: red (down) - gray - blue (up), clamped at +-3% (1 day) or +-6% (5 days)
  var NEG = [227, 73, 72], MID = [240, 239, 236], POS = [42, 120, 214];
  function heatColour(v, limit) {
    if (!MB.isNum(v)) return ['#f5f6f8', '#6f6d68'];
    var t = Math.max(-1, Math.min(1, v / limit)), end = t < 0 ? NEG : POS, a = Math.abs(t);
    var rgb = MID.map(function (m, i) { return Math.round(m + (end[i] - m) * a); });
    return ['rgb(' + rgb.join(',') + ')', a > 0.7 ? '#ffffff' : '#0b0b0b'];
  }

  function heatmap(o) {
    var key = state.heat === '5d' ? 'ret_5d' : 'ret_1d', limit = state.heat === '5d' ? 0.06 : 0.03;
    var cells = o.sectors.map(function (s) {
      var mean = state.heat === '5d' ? s.move_5d : s.move_1d;
      return '<div class="sector"><h3><span>' + esc(s.sector) + '</span><span class="' + MB.cls(mean) + '">' + MB.pct(mean, 1) + '</span></h3><div class="cells">' +
        s.stocks.map(function (x) {
          var c = heatColour(x[key], limit);
          return '<button class="cell" data-t="' + esc(x.ticker) + '" style="background:' + c[0] + ';color:' + c[1] + '" aria-label="' +
            esc(x.ticker + ' ' + MB.pct(x[key], 1)) + '"><b>' + esc(x.ticker) + '</b><span>' + (x[key] > 0 ? '▲ ' : x[key] < 0 ? '▼ ' : '') + MB.pct(x[key], 1) + '</span></button>';
        }).join('') + '</div></div>';
    }).join('');
    var lo = heatColour(-limit, limit)[0], hi = heatColour(limit, limit)[0];
    return '<div class="card section"><div class="chart-tools"><h2 style="margin:0">Sector heatmap</h2><div class="seg" role="group" aria-label="Heatmap period">' +
      ['1d', '5d'].map(function (k) { return '<button data-heat="' + k + '" aria-pressed="' + (state.heat === k) + '">' + (k === '1d' ? '1 day' : '5 days') + '</button>'; }).join('') +
      '</div></div><p class="sub small">Each cell is one stock\'s close-to-close return; the sector figure is the mean of its stocks. Select a cell to open the stock.</p>' +
      '<div class="heat">' + cells + '</div><div class="scale" style="margin-top:10px"><span>' + MB.pct(-limit, 0) + ' or less</span><span class="bar" style="background:linear-gradient(90deg,' +
      lo + ',rgb(240,239,236),' + hi + ')"></span><span>' + MB.pct(limit, 0) + ' or more</span></div></div>';
  }

  // the table shows P(up) of the shortest and the longest configured horizon (config/strategies.yaml via
  // D.plan.horizons) and the range of the stock's shortest published horizon, with a pill naming any other
  function horizonsShown() { var hs = D.plan.horizons; return { first: hs[0], last: hs[hs.length - 1] }; }
  function columns() {
    var hs = horizonsShown();
    return [
      ['ticker', 'Stock'], ['sector', 'Sector', 'hide-sm'], ['close', 'Close', 'r'], ['change', '1 day', 'r'], ['gap', 'Gap', 'r'],
      ['p1', 'P(up) N+' + hs.first, 'r']].concat(hs.last !== hs.first ? [['p5', 'P(up) N+' + hs.last, 'r']] : []).concat([
      ['range1', '80% range, N+' + hs.first, 'r'], ['rsi', 'RSI', 'r'],
      ['earn', 'Earnings', ''], ['trend', '20 sessions', 'hide-sm'], ['quality', 'Data', '']
    ]);
  }
  function rowValues(c) {
    var hs = horizonsShown(), m1 = MB.modelOf(c, hs.first), m5 = MB.modelOf(c, hs.last), last = c.last || {};
    var r1 = (c.ranges || [])[0] || null;   // ranges come sorted by horizon
    return { ticker: c.ticker, sector: c.sector, close: last.close, change: last.change, gap: last.gap,
      p1: m1 && m1.prob_up, p5: m5 && m5.prob_up, range1: r1 && r1.lo80, rsi: c.indicators.rsi_14,
      earn: c.earnings || '9999', trend: null, quality: c.indicators.quality || '', r: r1 };
  }
  function sorted() {
    var k = state.sort.key, dir = state.sort.dir, q = state.q.toLowerCase();
    var list = D.companies.filter(function (c) {
      return (!state.sector || c.sector === state.sector) && (!q || (c.ticker + ' ' + c.name).toLowerCase().indexOf(q) >= 0);
    });
    if (k === 'sector') return list;
    return list.slice().sort(function (a, b) {
      var x = rowValues(a)[k], y = rowValues(b)[k];
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * dir;
    });
  }
  function table() {
    var head = columns().map(function (col) {
      var sortable = col[0] !== 'trend', on = state.sort.key === col[0];
      return '<th class="' + (col[2] || '') + '"' + (on ? ' aria-sort="' + (state.sort.dir > 0 ? 'ascending' : 'descending') + '"' : '') + '>' +
        (sortable ? '<button class="sort" data-sort="' + col[0] + '">' + esc(col[1]) + '</button>' : esc(col[1])) + '</th>';
    }).join('');
    var body = sorted().map(function (c) {
      var v = rowValues(c), r = v.r;
      var range = r ? (r.late ? '<span class="muted" title="Made after the session opened: for the record only">' : '<span>') +
        MB.money(r.lo80) + ' – ' + MB.money(r.hi80) + (r.h !== horizonsShown().first || r.horizon_label !== 'n_plus_k' ? ' <span class="pill">' + esc(r.name) + '</span>' : '') + '</span>' : '<span class="muted">–</span>';
      return '<tr><td><button class="tick" data-t="' + esc(c.ticker) + '"><b>' + esc(c.ticker) + '</b><span>' + esc(c.name) + '</span></button></td>' +
        '<td class="hide-sm">' + esc(c.sector) + '</td><td class="r">' + MB.money(v.close) + '</td><td class="r">' + MB.signed(v.change, 2) +
        '</td><td class="r">' + MB.signed(v.gap, 2) + '</td><td class="r">' + MB.probBar(v.p1) + '</td>' + (horizonsShown().last !== horizonsShown().first ? '<td class="r">' + MB.probBar(v.p5) + '</td>' : '') + '<td class="r">' +
        '</td><td class="r">' + range + '</td><td class="r">' + MB.num(v.rsi, 1) + '</td><td>' + (c.earnings ? esc(MB.day(c.earnings)) : '<span class="muted">–</span>') +
        '</td><td class="hide-sm">' + MB.spark(c.bars.slice(-20).map(function (b) { return [b[0], b[4]]; }), 80, 22) + '</td><td>' +
        '<span class="pill">' + esc(v.quality || 'no data') + '</span></td></tr>';
    }).join('');
    var sectors = D.overview.sectors.map(function (s) { return '<option' + (state.sector === s.sector ? ' selected' : '') + '>' + esc(s.sector) + '</option>'; }).join('');
    return '<div class="card section"><div class="chart-tools"><h2 style="margin:0">Watchlist</h2>' + MB.paperTag() + '</div>' +
      '<p class="sub small">P(up) is the signal model\'s probability that the stock gains from the next open (' + esc(MB.day(D.plan.entry)) +
      ') to the exit close. Gap = last open vs the close before it. Sort by any column; select a stock for its chart and reasoning.</p>' +
      '<div class="filters"><label class="small">Search <input id="wl-q" type="search" value="' + esc(state.q) + '" placeholder="Ticker or name"></label>' +
      '<label class="small">Sector <select id="wl-sector"><option value="">All sectors</option>' + sectors + '</select></label>' +
      '<span class="small muted" id="wl-count"></span></div><div class="table-wrap"><table><thead><tr>' + head + '</tr></thead><tbody id="wl-body">' + body +
      '</tbody></table></div></div>';
  }

  MB.renderOverview = function () {
    var el = document.getElementById('view-overview');
    if (!D.overview) { el.innerHTML = MB.empty(D.empty || 'No data yet.'); return; }
    var activeId = document.activeElement && document.activeElement.id;
    el.innerHTML = '<h1>' + esc(D.name) + ' — market overview</h1><p class="sub">Close of ' + esc(MB.day(D.as_of)) + ' · built ' +
      esc(MB.stamp(D.generated_at)) + '</p>' + tiles(D.overview) + heatmap(D.overview) + table() + cues(D.overview);
    el.querySelectorAll('[data-t]').forEach(function (b) { b.addEventListener('click', function () { MB.go('stock', b.dataset.t); }); });
    el.querySelectorAll('[data-heat]').forEach(function (b) { b.addEventListener('click', function () { state.heat = b.dataset.heat; MB.renderOverview(); }); });
    el.querySelectorAll('[data-sort]').forEach(function (b) {
      b.addEventListener('click', function () {
        var k = b.dataset.sort;
        state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : (k === 'ticker' || k === 'earn' ? 1 : -1) };
        MB.renderOverview(); var again = el.querySelector('[data-sort="' + k + '"]'); if (again) again.focus();
      });
    });
    var q = document.getElementById('wl-q');
    q.addEventListener('input', function () { state.q = q.value; MB.renderOverview(); var n = document.getElementById('wl-q'); n.focus(); n.setSelectionRange(n.value.length, n.value.length); });
    document.getElementById('wl-sector').addEventListener('change', function (e) { state.sector = e.target.value; MB.renderOverview(); document.getElementById('wl-sector').focus(); });
    document.getElementById('wl-count').textContent = document.querySelectorAll('#wl-body tr').length + ' of ' + D.companies.length + ' stocks';
    if (activeId && document.getElementById(activeId) && activeId !== 'wl-q' && activeId !== 'wl-sector') document.getElementById(activeId).focus();
  };
})(window.MB);
