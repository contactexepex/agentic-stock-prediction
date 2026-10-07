/* "How to read this": the page in plain language. Dates and labels come from the embedded data. */
(function (MB) {
  'use strict';
  var D = MB.D, esc = MB.esc;

  MB.renderHow = function () {
    var plan = D.plan || {};
    var statuses = ['confirmed_primary', 'corroborated', 'single_source', 'unverified', 'rumour', 'promotional', 'contradicted'];
    var meaning = {
      confirmed_primary: 'an exchange or regulator filing states it.', corroborated: 'at least two independent, vetted outlets report it.',
      single_source: 'one vetted outlet only; lowers any call\'s confidence.', unverified: 'not checked, or no vetted outlet was read.',
      rumour: 'unnamed sources; never supports a call.', promotional: 'paid or self-interested; never supports a call.',
      contradicted: 'a primary source or vetted outlets say otherwise.'
    };
    document.getElementById('view-how').innerHTML = '<div class="card how"><h1>How to read this</h1>' +
      '<p>This page is a research log for short trades on a watchlist of ' + D.companies.length + ' ' + esc(D.name) + ' stocks. ' + esc(D.disclaimer) +
      ' It never places a trade and nothing on it is a recommendation.</p>' +
      '<h2>The questions: horizons N+k</h2><p>Every signal buys at the open of the next session, D' + (plan.entry ? ' (' + esc(MB.day(plan.entry)) + ')' : '') +
      ', and sells at the close of the k-th session after D: N+1 sells at the close of D+1, N+5 at the close of D+5. Weekends and holidays are skipped.</p><ul>' +
      (plan.horizons || []).map(function (k) {
        var exit = (plan.exits || {})[String(k)];
        return '<li><strong>N+' + k + ':</strong> sold at the close of D+' + k + (exit ? ' (' + esc(MB.day(exit)) + ')' : '') + '.</li>';
      }).join('') + '</ul>' +
      '<h2>P(up): the signal model\'s probability</h2><p>For each stock and question, a logistic model turns today\'s indicators into the probability that the trade above ends with a gain (before costs). ' +
      '50% means no view. The <em>base rate</em> is how often such trades gained in the training data; the model starts there and each group of indicators adds or takes away ' +
      '<em>points</em> (percentage points of probability). The groups and the top drivers, in plain words, are listed under every probability; "The formula" shows the exact calculation and the fitted numbers.</p>' +
      '<h2>"' + esc(D.skill.label) + '"</h2><p>Each week the review reruns a walk-forward backtest: the model is fitted only on the past and scored on days it never saw, then compared with ' +
      'the base rate and with simple baselines (always buy, 5-day momentum, RSI mean reversion, the index) after trading costs. ' + esc(D.skill.rule) + ' Until that test is passed, every probability is labelled paper only: ' +
      'it is a hypothesis being tracked, not an edge. Latest verdict: ' + esc(D.skill.why) + '</p>' +
      '<h2>Price ranges on the chart</h2><p>The shaded fan starts at the last close. The darker band is the <strong>50% range</strong> (the close should land inside about half the time), the lighter band with dashed edges the <strong>80% range</strong>. ' +
      'They come from a volatility formula, not from the AI, and are scored every day. Gray ranges were made after the session had already opened: kept for the record, never scored.</p>' +
      '<h2>Risk/reward</h2><p>Upside is the distance from the last close to the top of the 80% range, downside to its bottom. Reward : risk above 1 means the range reaches further up than down. ' +
      'The round-trip cost (buy plus sell, from config/costs.yaml) is shown beside it: a gain smaller than the cost is a loss.</p>' +
      '<h2>Open, close and the gap</h2><p><strong>Overnight gap</strong> = the last session\'s open against the close before it: how much the price jumped before anyone could trade. ' +
      '<strong>Open → close</strong> is the move during the session. The signals buy at the open, so a large gap at the next open changes the trade.</p>' +
      '<h2>Bull vs bear</h2><p>Two research agents argue each side from the stored data and news; the forecaster weighs them and may abstain. Ids in brackets are the cited headlines, listed with their status.</p>' +
      '<h2>News badges</h2><ul>' + statuses.map(function (s) { return '<li>' + MB.badge(s) + ' ' + esc(meaning[s]) + '</li>'; }).join('') + '</ul>' +
      '<h2>Market regime</h2><p>Calm, trending, event-heavy or unstable, from the volatility index, the benchmark\'s recent moves and scheduled events. Event-heavy and unstable regimes widen the ranges and lower confidence.</p>' +
      '<h2>Track record</h2><p>Live results only count calls and ranges made before the market opened. Calls are scored two ways, close to close and open to close, and the two are never added together. ' +
      'Each hit rate has a 95% interval (Wilson): with few scored calls the interval is wide and the rate means little. The always-up baseline shows what buying everything would have scored. ' +
      'The historical replay re-runs the rules on past prices and is shown apart because it is not live.</p></div>';
  };
})(window.MB);
