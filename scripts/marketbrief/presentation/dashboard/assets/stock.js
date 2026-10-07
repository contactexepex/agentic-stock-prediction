/* Stock view: header with the last session's open/close/gap, the chart, the model's P(up) per horizon with its
   reasoning (points per feature group, top drivers, the formula, how it was checked), ranges with risk/reward,
   the forecaster's bull and bear cases, headlines with verification status, and the indicators. */
(function (MB) {
  'use strict';
  var D = MB.D, state = MB.state, esc = MB.esc, C = MB.colours;
  var DECISION = { abstain: 'abstained', up: 'up', down: 'down' };

  function picker(c) {
    var groups = {};
    D.companies.forEach(function (x) { (groups[x.sector] = groups[x.sector] || []).push(x); });
    var opts = Object.keys(groups).map(function (s) {
      return '<optgroup label="' + esc(s) + '">' + groups[s].map(function (x) {
        return '<option value="' + esc(x.ticker) + '"' + (x.ticker === c.ticker ? ' selected' : '') + '>' + esc(x.ticker + ' · ' + x.name) + '</option>';
      }).join('') + '</optgroup>';
    }).join('');
    return '<div class="stock-pick"><button id="st-prev" aria-label="Previous stock">‹</button><label class="small"><span class="muted">Stock </span>' +
      '<select id="st-pick">' + opts + '</select></label><button id="st-next" aria-label="Next stock">›</button></div>';
  }

  function header(c) {
    var l = c.last || {};
    return '<div class="stock-head"><div><div class="sub">' + esc(c.sector) + ' · ' + esc(c.ticker) + '</div><h1>' + esc(c.name) + '</h1>' +
      '<div><span class="price-big">' + MB.money(l.close) + '</span> ' + MB.signed(l.change, 2) + ' <span class="sub">close of ' + esc(MB.day(l.date)) + '</span></div></div>' +
      picker(c) + '</div><div class="session-strip" aria-label="Last session">' +
      [['Open', MB.money(l.open)], ['Close', MB.money(l.close)], ['Previous close', MB.money(l.prev_close)],
        ['Overnight gap', MB.signed(l.gap, 2) + ' <span class="small muted">open vs previous close</span>'],
        ['Open → close', MB.signed(l.open_to_close, 2) + ' <span class="small muted">day range ' + MB.money(l.low) + '–' + MB.money(l.high) + '</span>']]
        .map(function (kv) { return '<div><div class="k">' + kv[0] + '</div><div class="v">' + kv[1] + '</div></div>'; }).join('') + '</div>';
  }

  function chartCard() {
    return '<div class="card chart-card section"><div class="chart-tools"><div class="seg" role="group" aria-label="Chart span">' +
      D.spans.map(function (s) { return '<button data-span="' + s.key + '" aria-pressed="' + (state.span === s.key) + '" title="' + esc(s.label) + '">' + s.key + '</button>'; }).join('') +
      '</div><div class="legend"><span><i class="sw" style="background:' + C.UP + '"></i>Closed higher</span><span><i class="sw" style="background:' + C.DOWN + '"></i>Closed lower</span>' +
      '<span><i class="sw" style="background:rgba(74,58,167,.22)"></i>50% range</span><span><i class="sw" style="background:rgba(74,58,167,.10);border:1px dashed ' + C.BAND + '"></i>80% range</span></div></div>' +
      '<div class="ohlc" id="ohlc" aria-live="polite"></div><div class="chart-box" id="chart-box"></div><p class="small muted" id="fan-note" style="margin-top:6px"></p></div>';
  }

  function fit(m) { return (D.models || []).filter(function (v) { return v.id === m.model_id; })[0] || null; }

  function contributions(m) {
    var rows = [{ group: 'baseline', points: m.baseline_points }].concat(m.groups);
    var max = Math.max.apply(null, rows.map(function (r) { return Math.abs(r.points || 0); }).concat([0.5]));
    return '<div class="contrib" role="table" aria-label="Points per feature group">' + rows.map(function (r) {
      var v = r.points || 0, w = Math.abs(v) / max * 50, left = v >= 0 ? 50 : 50 - w;
      return '<span role="cell">' + esc(MB.cap(r.group)) + '</span><span class="track" aria-hidden="true"><i style="left:' + left + '%;width:' + w + '%;background:' +
        (v >= 0 ? C.UP : C.DOWN) + '"></i></span><span role="cell" class="tab-num ' + MB.cls(v) + '" style="text-align:right">' + (v > 0 ? '+' : '') + MB.num(v, 2) + '</span>';
    }).join('') + '</div>';
  }

  function drivers(list, empty) {
    return list && list.length ? '<ul class="drivers">' + list.map(function (d) { return '<li>' + esc(d.text) + '</li>'; }).join('') + '</ul>' :
      '<p class="small muted">' + esc(empty) + '</p>';
  }

  function formula(m, f) {
    var lines = 'logit(p) = logit(base rate) + baseline + Σ feature items + news\np = 1 / (1 + e^(−logit(p)))';
    var out = '<details><summary>The formula, and how the points are made</summary><div class="formula">' + esc(lines) + '</div><ul class="drivers">' +
      '<li>Model: L2-regularised logistic regression on standardised indicators, refit each month on all earlier labelled stock-days' +
      (f ? ' (this fit: ' + esc(f.id) + ', trained to ' + esc(MB.day(f.trained_until)) + ' on ' + MB.num(f.train_rows, 0) + ' stock-days, ' + f.features + ' features)' : '') + '.</li>' +
      '<li>Calibration (Platt): the raw score s becomes σ(a·s + c)' + (f && MB.isNum(f.platt_slope) ? ', here a = ' + MB.num(f.platt_slope, 3) + ', c = ' + MB.num(f.platt_offset, 3) +
        ', fitted on ' + MB.num(f.platt_rows, 0) + ' past out-of-sample rows' : '') + '.' +
      (f && f.platt_slope === 0 ? ' a = 0 means the calibration found no usable signal in the indicators: every stock gets the same probability apart from news.' : '') + '</li>' +
      '<li>Points: each item\'s share of (p − base rate), in percentage points; baseline + groups add up to p − base rate (' +
      MB.num((m.prob_up - m.base_rate) * 100, 2) + ' points here, before rounding).</li>' +
      '<li>News enters as a fixed prior, not trained yet' + (m.news_items != null ? ' (' + m.news_items + ' verified item(s) in the window)' : '') + '.</li></ul>' +
      '<p class="small">How we know whether it works: the walk-forward backtest on the Track record page (Brier vs base rate, AUC, paper long vs baselines after costs). ' + esc(D.skill.why) + '</p></details>';
    return out;
  }

  function forecastCard(c, h) {
    var m = MB.modelOf(c, h), title = h === 1 ? 'Buy today, sell tomorrow' : 'Buy today, sell within 5 days';
    if (!m) return '<div class="card fc"><h2>' + title + '</h2>' + MB.empty('No model score stored for this stock and day.') + '</div>';
    var p = m.prob_up;
    return '<div class="card fc"><div class="chart-tools"><h2 style="margin:0">' + title + '</h2>' + MB.paperTag() + '</div>' +
      '<div class="when">Buy at the open of ' + esc(MB.day(m.entry)) + ', sell at the close of ' + esc(MB.day(m.exit)) + '.</div>' +
      '<div><span class="big ' + (p >= 0.5 ? 'up' : 'down') + '">' + MB.prob(p) + '</span> <span class="sub">probability of a gain (before costs)</span></div>' +
      '<div><div class="meter" aria-hidden="true"><span class="base" style="left:' + (m.base_rate * 100) + '%"></span><span class="dot" style="left:' + (p * 100) + '%;background:' +
      (p >= 0.5 ? C.UP : C.DOWN) + '"></span></div><div class="meter-scale"><span>0% sure down</span><span>50%</span><span>100% sure up</span></div></div>' +
      '<p class="small sub">Base rate (share of gains in training): ' + MB.prob(m.base_rate) + ' (the tick on the bar). Calibrated: ' + (m.calibrated ? 'yes' : 'no') +
      '. Score made ' + esc(MB.stamp(m.computed_at)) + '.</p><h3>Why: points per feature group</h3>' + contributions(m) +
      '<div class="grid g2"><div><h3>Pushing up</h3>' + drivers(m.up, 'No driver adds 0.1 points or more.') + '</div><div><h3>Pushing down</h3>' +
      drivers(m.down, 'No driver takes away 0.1 points or more.') + '</div></div>' +
      (m.missing && m.missing.length ? '<p class="small muted">Missing inputs (taken as their training mean): ' + esc(m.missing.join(', ')) + '</p>' : '') +
      formula(m, fit(m)) + '</div>';
  }

  function rangesCard(c) {
    if (!c.ranges.length) return '<div class="card section"><h2>Price ranges and risk/reward</h2>' + MB.empty('No ranges published for this stock and day.') + '</div>';
    var rows = c.ranges.map(function (r) {
      return '<tr><td>' + (r.h === 1 ? 'Next session' : '5 sessions') + (r.late ? ' <span class="badge st-neutral" title="Made after this session opened">for the record</span>' : '') +
        '</td><td>' + esc(MB.day(r.target_date)) + '</td><td class="r">' + MB.money(r.lo50) + ' – ' + MB.money(r.hi50) + '</td><td class="r">' + MB.money(r.lo80) + ' – ' + MB.money(r.hi80) +
        '</td><td class="r up">' + MB.pct(r.up80, 1) + '</td><td class="r down">' + MB.pct(r.down80, 1) + '</td><td class="r">' + (MB.isNum(r.reward_risk) ? MB.num(r.reward_risk, 2) + ' : 1' : '–') + '</td></tr>';
    }).join('');
    var late = c.ranges.some(function (r) { return r.late; });
    return '<div class="card section"><h2>Price ranges and risk/reward</h2><p class="sub small">Where the close of the target day is likely to land, from the range formula (not the AI). ' +
      'Upside and downside are from the last close (' + MB.money(c.ranges[0].base_close) + ') to the top and bottom of the 80% range. Round-trip cost at this price: ' +
      MB.pct(c.cost, 2, false) + ' (config/costs.yaml).</p><div class="table-wrap"><table><thead><tr><th>Horizon</th><th>Target close</th><th class="r">50% range</th><th class="r">80% range</th>' +
      '<th class="r">Upside</th><th class="r">Downside</th><th class="r">Reward : risk</th></tr></thead><tbody>' + rows + '</tbody></table></div>' +
      (late ? '<p class="small muted">"For the record": made after that session had opened, so it is not a forecast and is never scored.</p>' : '') +
      (c.ranges.some(function (r) { return r.notes.length; }) ? '<p class="small muted">Range notes: ' + esc(c.ranges.map(function (r) { return r.h + 'd: ' + r.notes.join('; '); }).join(' · ')) + '</p>' : '') + '</div>';
  }

  function linkIds(text, evidence) {
    var out = esc(text || '');
    (evidence || []).forEach(function (e) { out = out.split(esc(e.id)).join('<code class="small" title="' + esc(e.title || '') + '">' + esc(e.id) + '</code>'); });
    return out;
  }

  function casesCard(c) {
    var r = c.reasoning;
    if (!r) return '<div class="card section"><h2>Bull vs bear</h2>' + MB.empty('No forecaster reasoning stored for this stock and day.') + '</div>';
    var calls = c.calls.length ? c.calls.map(function (x) { return x.h + ' day: ' + x.direction + ' at ' + MB.prob(x.confidence) + ' stated confidence'; }).join('; ') : 'no call stored';
    return '<div class="card section"><div class="chart-tools"><h2 style="margin:0">Bull vs bear</h2><span class="small muted">Forecaster ' + esc(r.prompt_version || '') + ' · ' + esc(MB.stamp(r.made_at)) + '</span></div>' +
      '<div class="grid g2"><div class="case bull"><h3>Bull case</h3><p>' + linkIds(r.bull, r.evidence) + '</p></div><div class="case bear"><h3>Bear case</h3><p>' + linkIds(r.bear, r.evidence) + '</p></div></div>' +
      '<div class="section"><h3>Verdict</h3><p>' + linkIds(r.verdict, r.evidence) + '</p><p class="small sub">1 day: ' + esc(DECISION[r.decision_1d] || r.decision_1d || '–') + ' · 5 days: ' +
      esc(DECISION[r.decision_5d] || r.decision_5d || '–') + ' · Stored calls: ' + esc(calls) + '</p></div>' +
      (r.evidence.length ? '<h3>Evidence cited</h3><ul class="news">' + r.evidence.map(function (e) {
        return '<li><span>' + MB.link(e.title, e.url) + '</span><span class="meta">' + MB.badge(e.status) + '<span>' + esc(e.source || '') + '</span><span>' +
          esc(MB.stamp(e.ts)) + '</span><code class="small">' + esc(e.id) + '</code></span></li>';
      }).join('') + '</ul>' : '') + '</div>';
  }

  function newsCard(c) {
    var body = c.news.length ? '<ul class="news">' + c.news.map(function (n) {
      return '<li><span>' + MB.link(n.title, n.url) + '</span><span class="meta">' + MB.badge(n.status) + '<span>' + esc(n.source || '') + '</span><span>' + esc(MB.stamp(n.ts)) + '</span></span></li>';
    }).join('') + '</ul>' : MB.empty('No headlines stored for this stock.');
    return '<div class="card"><h2>News</h2><p class="sub small">Newest headlines; the badge is the verification status as of when this page was built.</p>' + body + '</div>';
  }

  function indicatorsCard(c) {
    var i = c.indicators, rsi = i.rsi_14;
    var rsiText = !MB.isNum(rsi) ? '' : rsi < 30 ? 'Oversold: fell fast relative to its recent swings.' : rsi > 70 ? 'Overbought: rose fast relative to its recent swings.' : 'Neutral zone (30–70).';
    var kv = [['Return, 1 day', MB.signed(i.ret_1d, 2)], ['Return, 5 days', MB.signed(i.ret_5d, 2)], ['Return, 20 days', MB.signed(i.ret_20d, 2)],
      ['Typical daily move (ATR 14)', MB.pct(i.atr_pct, 2, false)], ['Volume vs 20-day average', MB.isNum(i.volume_ratio_20d) ? MB.num(i.volume_ratio_20d, 2) + '×' : '–'],
      ['Close vs 20-day high', MB.isNum(i.price_vs_20d_high) ? MB.pct(i.price_vs_20d_high - 1, 1) : '–'], ['Beta (1 year)', MB.num(i.beta_1y, 2)],
      ['vs sector, 5 days', MB.signed(i.rel_sector_5d, 2)], ['Indicator quality', esc(i.quality || 'no data')],
      ['Next earnings', c.earnings ? esc(MB.day(c.earnings)) + (i.days_to_earnings != null ? ' <span class="muted small">(' + i.days_to_earnings + ' days)</span>' : '') : '<span class="muted">none stored</span>']];
    return '<div class="card"><h2>Indicators</h2><div><div class="small sub">RSI, 14 days</div><div style="font-size:22px;font-weight:650">' + MB.num(rsi, 1) + '</div>' +
      (MB.isNum(rsi) ? '<div class="rsi" aria-hidden="true"><span class="dot" style="left:' + rsi + '%"></span></div><div class="meter-scale"><span>0</span><span>30</span><span>70</span><span>100</span></div>' : '') +
      '<p class="small sub">' + esc(rsiText) + '</p></div><dl class="kv">' + kv.map(function (x) { return '<dt>' + x[0] + '</dt><dd>' + x[1] + '</dd>'; }).join('') + '</dl>' +
      (i.days_to_earnings != null && i.days_to_earnings <= 1 ? '<p class="small"><span class="badge st-warn">! Earnings within 1 day</span> no new call by the rules.</p>' : '') + '</div>';
  }

  function hover(c) {
    var el = document.getElementById('ohlc');
    return function (d, time) {
      var b = d ? d : null, last = c.bars[c.bars.length - 1];
      if (!b && last) b = { open: last[1], high: last[2], low: last[3], close: last[4], time: last[0] };
      if (!b) { el.textContent = ''; return; }
      el.innerHTML = esc(MB.day(String(time || b.time))) + ' · O ' + MB.money(b.open) + ' · H ' + MB.money(b.high) + ' · L ' + MB.money(b.low) + ' · C ' + MB.money(b.close) + (d ? '' : ' (last session)');
    };
  }

  MB.renderStock = function () {
    var el = document.getElementById('view-stock'), c = MB.byTicker[state.ticker];
    if (!c) { el.innerHTML = MB.empty(D.empty || 'No stock data yet.'); return; }
    el.innerHTML = header(c) + chartCard() + '<div class="grid g2 section">' + forecastCard(c, 1) + forecastCard(c, 5) + '</div>' + rangesCard(c) +
      casesCard(c) + '<div class="grid g2 section">' + newsCard(c) + indicatorsCard(c) + '</div>';
    var onHover = hover(c);
    var info = MB.mountChart(document.getElementById('chart-box'), c, state.span, onHover);
    onHover(null);
    var future = (c.ranges || []).map(function (r) { return r.target_date; }).sort();
    document.getElementById('fan-note').textContent = info.fan ? (info.fan.late ? 'Ranges shown in gray were made after the session opened: for the record, not forecasts.' :
      'Shaded fan: the published 50% and 80% ranges for the next close and the close 5 sessions ahead, from the close of ' + MB.day(info.lastDay) + '.') : 'No ranges published for this stock and day.';
    el.querySelectorAll('[data-span]').forEach(function (b) {
      b.addEventListener('click', function () {
        state.span = b.dataset.span;
        el.querySelectorAll('[data-span]').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
        MB.setSpan(state.span, info.lastDay, future.filter(function (d) { return d > info.lastDay; }));
      });
    });
    var tickers = D.companies.map(function (x) { return x.ticker; }), at = tickers.indexOf(c.ticker);
    document.getElementById('st-pick').addEventListener('change', function (e) { MB.go('stock', e.target.value); });
    document.getElementById('st-prev').addEventListener('click', function () { MB.go('stock', tickers[(at + tickers.length - 1) % tickers.length]); });
    document.getElementById('st-next').addEventListener('click', function () { MB.go('stock', tickers[(at + 1) % tickers.length]); });
  };
})(window.MB);
