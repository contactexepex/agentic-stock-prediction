/* Track record view: the skill verdict, live calls per scoring basis (never pooled) against the always-up
   baseline, ranges held with Wilson 95% intervals, the model backtest (scores and the paper long after costs),
   the model fits, and the historical replay shown apart as not live. */
(function (MB) {
  'use strict';
  var D = MB.D, esc = MB.esc;

  function ci(x) {
    return x && x.n ? MB.pct(x.share, 1, false) + ' <span class="small muted">(' + x.hits + ' of ' + x.n + '; 95%: ' + MB.pct(x.wilson_lo, 0, false) + '–' + MB.pct(x.wilson_hi, 0, false) + ')</span>' : '–';
  }
  function fixed(v, d) { return MB.isNum(v) ? MB.num(v, d == null ? 3 : d) : '–'; }
  function sample(n) { return n < D.track.min_sample ? ' <span class="badge st-warn">! fewer than ' + D.track.min_sample + ' scored</span>' : ''; }

  function skillCard() {
    var s = D.skill;
    return '<div class="card"><div class="chart-tools"><h2 style="margin:0">Does the model show skill?</h2>' + MB.paperTag() + '</div><p>' + esc(s.why) + '</p><p class="small sub">' + esc(s.rule) +
      (s.review ? ' Weekly review ' + esc(s.review.id) + ', computed ' + esc(MB.stamp(s.review.computed_at)) + '.' : '') + '</p></div>';
  }

  function reliabilityTable(rows, title) {
    var used = (rows || []).filter(function (r) { return r.n; });
    if (!used.length) return '';
    return '<div class="table-wrap section"><table><caption class="small sub" style="text-align:left;padding:4px 0">' + esc(title) + '</caption><thead><tr><th>Stated band</th><th class="r">n</th><th class="r">Mean stated</th><th class="r">Actual</th><th class="r">95% interval</th></tr></thead><tbody>' +
      used.map(function (r) {
        var lo = r.wilson_lo, hi = r.wilson_hi, stated = r.mean_conf, actual = r.hit_rate;
        return '<tr><td>' + esc(r.bin) + '</td><td class="r">' + r.n + '</td><td class="r">' + MB.pct(stated, 1, false) + '</td><td class="r">' + MB.pct(actual, 1, false) +
          '</td><td class="r">' + (MB.isNum(lo) ? MB.pct(lo, 0, false) + '–' + MB.pct(hi, 0, false) : '–') + '</td></tr>';
      }).join('') + '</tbody></table></div>';
  }

  function callsSection() {
    var t = D.track.calls;
    if (!t.length) return '<div class="card section"><h2>Live calls</h2>' + MB.empty('No live calls scored yet. Scores appear here once calls reach their target day.') + '</div>';
    return t.map(function (b) {
      var rows = [['All horizons', b.all]].concat(Object.keys(b.by_horizon).map(function (k) { return [k === '1d' ? '1 day' : '5 days', b.by_horizon[k]]; }));
      return '<div class="card section"><h2>Live calls, scored ' + esc(b.label) + '</h2><p class="sub small">Each scoring basis is shown on its own; they are never added together.</p>' +
        '<div class="table-wrap"><table><thead><tr><th>Horizon</th><th class="r">Calls right</th><th class="r">Always-up baseline</th><th class="r">Edge</th><th class="r">Mean stated</th><th class="r">Brier</th><th class="r">Log loss</th></tr></thead><tbody>' +
        rows.map(function (r) {
          var x = r[1];
          return '<tr><td>' + r[0] + sample(x.n) + '</td><td class="r">' + ci(x) + '</td><td class="r">' + MB.pct(x.always_up, 1, false) + '</td><td class="r">' + MB.signed(x.edge, 1) +
            '</td><td class="r">' + MB.pct(x.mean_confidence, 1, false) + '</td><td class="r">' + fixed(x.scores.brier) + '</td><td class="r">' + fixed(x.scores.log_loss) + '</td></tr>';
        }).join('') + '</tbody></table></div><p class="small muted">Always-up baseline: the share of these same calls whose stock went up. Brier: 0.25 is a coin flip; lower is better.</p>' +
        reliabilityTable(b.all.reliability, 'Calibration: stated confidence vs how often the calls were right') + '</div>';
    }).join('');
  }

  function rangesSection() {
    var r = D.track.ranges;
    var body = r.length ? '<div class="table-wrap"><table><thead><tr><th>Horizon</th><th class="r">Inside 50% range (target 50%)</th><th class="r">Inside 80% range (target 80%)</th><th class="r">Mean 80% width</th></tr></thead><tbody>' +
      r.map(function (x) {
        return '<tr><td>' + (x.h === 1 ? 'Next session' : x.h + ' sessions') + sample(x.inside80.n) + '</td><td class="r">' + ci(x.inside50) + '</td><td class="r">' + ci(x.inside80) +
          '</td><td class="r">' + (MB.isNum(x.scores.width80_pct) ? MB.num(x.scores.width80_pct, 2) + '%' : '–') + '</td></tr>';
      }).join('') + '</tbody></table></div>' : MB.empty('No live ranges scored yet.');
    return '<div class="card section"><h2>Live ranges held</h2><p class="sub small">How often the actual close landed inside the published range. A well-sized 80% range holds about 80% of the time.</p>' + body + '</div>';
  }

  function backtestSection() {
    var b = D.backtest;
    if (!b) return '<div class="card section"><h2>Model backtest</h2>' + MB.empty('Model backtest: ' + D.not_available + ' (no weekly review stored).') + '</div>';
    if (b.error) return '<div class="card section"><h2>Model backtest</h2>' + MB.empty('Model backtest: ' + D.not_available + ' (' + b.error + ').') + '</div>';
    var d = b.data || {};
    var scores = '<div class="table-wrap"><table><thead><tr><th>Horizon · label</th><th class="r">Rows</th><th class="r">Brier</th><th class="r">Base-rate Brier</th><th class="r">Brier skill</th><th class="r">AUC</th><th class="r">AUC 95%</th><th>Skill</th></tr></thead><tbody>' +
      b.scores.map(function (s) {
        if (!MB.isNum(s.brier)) return '<tr><td>' + esc(s.key) + '</td><td colspan="7" class="muted">' + esc(s.skipped || '–') + '</td></tr>';
        return '<tr><td>' + esc(s.key) + '</td><td class="r">' + MB.num(s.n, 0) + '</td><td class="r">' + fixed(s.brier, 4) + '</td><td class="r">' + fixed(s.brier_base_rate, 4) + '</td><td class="r">' +
          fixed(s.brier_skill, 4) + '</td><td class="r">' + fixed(s.auc, 3) + '</td><td class="r">' + fixed((s.auc95 || [])[0], 3) + '–' + fixed((s.auc95 || [])[1], 3) + '</td><td>' +
          (s.skill ? '<span class="badge st-good">✓ yes</span>' : '<span class="badge st-neutral">✕ no</span>') + '</td></tr>';
      }).join('') + '</tbody></table></div>';
    var strategy = (b.strategy || []).length ? '<div class="table-wrap section"><table><thead><tr><th>Horizon</th><th>Threshold</th><th class="r">Positions</th><th>Baseline</th><th class="r">Dates</th><th class="r">Model − baseline, mean %</th><th class="r">95%</th><th>Verdict</th></tr></thead><tbody>' +
      b.strategy.map(function (s) {
        return '<tr><td>' + esc(s.key) + '</td><td>p ≥ ' + esc(s.threshold) + '</td><td class="r">' + MB.num(s.positions, 0) + '</td><td>' + esc(String(s.baseline).replace(/_/g, ' ')) + '</td><td class="r">' + s.dates +
          '</td><td class="r">' + fixed(s.mean_pct, 2) + '</td><td class="r">' + fixed(s.ci95_pct[0], 2) + ' to ' + fixed(s.ci95_pct[1], 2) + '</td><td>' + esc(s.verdict) + '</td></tr>';
      }).join('') + '</tbody></table></div>' : '';
    var rel = Object.keys(b.reliability || {});
    var relHtml = rel.length ? rel.map(function (k) { return reliabilityTable(b.reliability[k], 'Backtest calibration, ' + k + ': predicted P(up) vs actual share up'); }).join('') :
      '<p class="small muted">Backtest calibration table: ' + esc(D.not_available) + ' (the backtest JSON ' + esc(b.json || '') + ' is not in this checkout; the weekly review writes it to work/).</p>';
    return '<div class="card section"><h2>Model backtest (walk-forward, out of sample)</h2><p class="sub small">Rerun by the weekly review on ' + esc(MB.stamp(b.computed_at)) + '. Panel ' +
      esc(d.first_panel_date || '–') + ' to ' + esc(d.last_panel_date || '–') + ', ' + esc(d.tickers || '–') + ' stocks, ' + MB.num(d.panel_rows, 0) + ' stock-days; round-trip cost ' +
      (MB.isNum(d.round_trip_cost_pct_at_100) ? MB.num(d.round_trip_cost_pct_at_100, 4) + '% at a price of 100' : '–') + '. Brier skill above 0 means better than always saying the base rate; AUC 0.5 is chance.</p>' +
      scores + '<h3 class="section">Paper long strategy after costs, against each baseline</h3><p class="small sub">Buy at the open, sell at the exit close, net of the round-trip cost; "beats" only when the whole 95% interval is above 0.</p>' +
      strategy + relHtml + '<p class="small"><strong>' + esc(b.verdict || '') + '</strong></p></div>';
  }

  function fitsSection() {
    if (!(D.models || []).length) return '';
    return '<div class="card section"><h2>Model fits used today</h2><div class="table-wrap"><table><thead><tr><th>Fit</th><th class="r">Training stock-days</th><th class="r">Base rate</th><th class="r">Platt a</th><th class="r">Platt c</th><th class="r">Platt rows</th><th>Weight by group (Σ|coef|)</th></tr></thead><tbody>' +
      D.models.map(function (f) {
        return '<tr><td>' + esc(f.id) + '</td><td class="r">' + MB.num(f.train_rows, 0) + '</td><td class="r">' + MB.pct(f.base_rate, 1, false) + '</td><td class="r">' + fixed(f.platt_slope) + '</td><td class="r">' +
          fixed(f.platt_offset) + '</td><td class="r">' + MB.num(f.platt_rows, 0) + '</td><td class="small">' + esc(Object.keys(f.group_weight).map(function (g) { return g + ' ' + f.group_weight[g]; }).join(', ')) + '</td></tr>';
      }).join('') + '</tbody></table></div></div>';
  }

  function replaySection() {
    var r = D.track.replay;
    var body = r ? '<div class="table-wrap"><table><thead><tr><th>Horizon</th><th class="r">Inside 50%</th><th class="r">Inside 80%</th><th class="r">80% score</th><th class="r">Naive 80% score</th><th class="r">Always up</th></tr></thead><tbody>' +
      [1, 5].map(function (h) {
        return '<tr><td>' + h + ' day</td><td class="r">' + MB.pct(r['cover50_' + h + 'd'], 1, false) + '</td><td class="r">' + MB.pct(r['cover80_' + h + 'd'], 1, false) + '</td><td class="r">' + fixed(r['score80_' + h + 'd'], 2) +
          '</td><td class="r">' + fixed(r['naive_score80_' + h + 'd'], 2) + '</td><td class="r">' + MB.pct(r['always_up_' + h + 'd'], 1, false) + '</td></tr>';
      }).join('') + '</tbody></table></div><p class="small muted">' + esc(r.start_date) + ' to ' + esc(r.end_date) + ', ' + MB.num(r.n_days, 0) + ' days, ' + MB.num(r.n_ranges, 0) + ' ranges; computed ' + esc(MB.stamp(r.computed_at)) + '.</p>' :
      MB.empty('No historical replay stored yet (scripts/replay.py).');
    return '<div class="card section"><h2>Historical replay — not live</h2><p class="sub small">The rule-based parts (ranges, regime, simple baselines) replayed on past prices. No AI and no live decisions: kept apart from the live record above.</p>' + body + '</div>';
  }

  MB.renderTrack = function () {
    document.getElementById('view-track').innerHTML = '<h1>Track record</h1><p class="sub">Everything scored by ' + esc(MB.stamp(D.generated_at)) + '.</p>' + skillCard() + callsSection() +
      rangesSection() + backtestSection() + fitsSection() + replaySection();
  };
})(window.MB);
