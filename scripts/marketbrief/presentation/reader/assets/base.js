// The reader's daily report (C2): helpers, header, the 20-second glance, what changed, paper trading, legend.
// Every number comes from the embedded data (view_data + presentation/reader); nothing is computed from prices here
// except positions on a chart. Narrative HTML is escaped server-side (html_report.py).
const D = JSON.parse(document.getElementById('report-data').textContent);
const R = D.reader || {};
const $ = (s, el) => (el || document).querySelector(s);
const NS = 'http://www.w3.org/2000/svg', cur = D.symbol || '';
const pct0 = v => (v == null || /e/i.test(String(v)) ? Math.round(v * 100) : Math.round(+(String(v) + 'e2'))) + '%';  // half up
const fmtMoney = v => v == null ? '–' : cur + Number(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const fmtNum = v => v == null ? '–' : Number(v).toLocaleString('en-US', v >= 1000 ? {maximumFractionDigits: 0} : {minimumFractionDigits: 2, maximumFractionDigits: 2});
const sign = v => v > 0 ? '+' : v < 0 ? '−' : '';
const fmtFrac = (v, d) => v == null ? '–' : sign(+Math.abs(v * 100).toFixed(d == null ? 1 : d) && v) + Math.abs(v * 100).toFixed(d == null ? 1 : d) + '%';
const fmtPctU = (v, d) => v == null ? '–' : sign(+Math.abs(v).toFixed(d == null ? 1 : d) && v) + Math.abs(v).toFixed(d == null ? 1 : d) + '%';  // already in percent
const fmtPts = v => v == null ? '–' : sign(+Math.abs(v * 100).toFixed(1) && v) + Math.abs(v * 100).toFixed(1) + ' pts';
const arrow = v => v > 0 ? '▲ ' : v < 0 ? '▼ ' : '';
const safeUrl = u => (typeof u === 'string' && /^https?:\/\/\S+$/i.test(u.trim())) ? u.trim() : null;
const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'], WD = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];
const fmtDay = (iso, wd) => { const d = new Date(String(iso).slice(0, 10) + 'T00:00:00Z'); return (wd ? WD[d.getUTCDay()] + ' ' : '') + d.getUTCDate() + ' ' + MON[d.getUTCMonth()]; };
const fmtTime = iso => iso ? fmtDay(iso, true) + ', ' + String(iso).slice(11, 16) + ' UTC' : '';
function el(tag, attrs, text){
  const e = document.createElement(tag);
  for (const k in (attrs || {})) { if (k === 'class') e.className = attrs[k]; else e.setAttribute(k, attrs[k]); }
  if (text != null) e.textContent = text;
  return e;
}
function svg(tag, attrs){ const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; }
function sText(x, y, str, attrs){ const t = svg('text', Object.assign({x: x, y: y, fill: 'var(--mb-chart-label)', 'font-size': 11}, attrs || {})); t.textContent = str; return t; }
function icon(name){ const s = svg('svg', {class: 'ms', 'aria-hidden': 'true'}); s.append(svg('use', {href: '#ms-' + name})); return s; }
function htmlBlock(cls, inner){ const d = el('div', {class: cls}); d.innerHTML = inner; return d; }  // escaped server-side
function linkOrText(url, text){ const u = safeUrl(url); return u ? el('a', {href: u, target: '_blank', rel: 'noopener'}, text) : el('span', null, text); }
function tag(cls, text, ic){ const t = el('span', {class: 'tag ' + cls}); if (ic) t.append(icon(ic)); t.append(document.createTextNode(text)); return t; }
const STATUS = {confirmed_primary: ['Confirmed by a filing', 'up'], corroborated: ['Confirmed by 2+ outlets', 'up'],
  single_source: ['Single source', 'none'], unverified: ['Not verified', 'none'], rumour: ['Rumour', 'warn'],
  promotional: ['Promotional', 'warn'], contradicted: ['Contradicted', 'down']};
function statusTag(s){ const x = STATUS[s] || STATUS.unverified; return tag(x[1], x[0]); }
const LEAN_WORD = {up: 'Lean up', down: 'Lean down', none: 'No clear lean'};
function leanText(f){ if (!f || f.prob_up == null) return 'No score';
  return f.lean === 'none' ? 'No clear lean' : (f.strength === 'slight' ? 'Slight lean ' : 'Lean ') + f.lean; }

// ---------- tooltip ----------
const tip = $('#tip');
function showTip(ev, rows){
  tip.replaceChildren();
  rows.forEach((r, i) => { const line = el('div'); if (r[1] != null) { line.append(el('b', null, r[1]), document.createTextNode(' ' + r[0])); } else { line.textContent = r[0]; if (i === 0) line.style.fontWeight = 600; } tip.append(line); });
  tip.hidden = false;
  const x = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8), y = Math.min(ev.clientY + 14, window.innerHeight - tip.offsetHeight - 8);
  tip.style.left = Math.max(8, x) + 'px'; tip.style.top = Math.max(8, y) + 'px';
}
function hideTip(){ tip.hidden = true; }

// ---------- companies: the view's company merged with its reader card (active companies only) ----------
const VIEW = {}; (D.companies || []).forEach(c => { VIEW[c.ticker] = c; });
const COS = (R.companies || []).map(rc => Object.assign({}, VIEW[rc.ticker] || {ticker: rc.ticker, name: rc.ticker}, rc));
const BY = {}; COS.forEach(c => { BY[c.ticker] = c; });
const fc = (c, h) => (c.forecasts || []).find(f => f.h === h) || null;
const HS = R.horizons || [1, 3, 5];
const exitOf = h => { for (const c of COS) { const f = fc(c, h); if (f && f.exit_label) return f; } return null; };
let H = R.default_horizon || HS[0];
const N = D.narrative || {};

// ---------- header ----------
function renderTop(){
  const t = $('#top');
  t.append(el('div', {class: 'micro'}, 'Daily brief · ' + D.name));
  t.append(el('h1', null, D.session_label + ' ' + D.session.slice(0, 4)));
  t.append(el('p', {class: 'muted'}, 'Forecasts for the session of ' + D.session_label + ', made from prices up to the close of ' + D.as_of_label + '.'));
  const row = el('div', {class: 'row'});
  row.append(tag('paper', R.paper_label || 'Paper only — no proven edge yet'), tag('none', 'Research only, not investment advice'));
  t.append(row);
  document.title = D.name + ' brief ' + D.session;
}

// ---------- the day in 20 seconds ----------
function trackLine(){
  const pts = (D.calibration || []).filter(p => p.kind === 'range' && p.stated === 0.8 && /N\+/.test(p.label) && p.actual != null);
  const n = pts.reduce((a, p) => a + p.n, 0), hits = Math.round(pts.reduce((a, p) => a + p.actual * p.n, 0));
  if (!n) return 'No forecast has been checked against the real price yet.';
  if (n < D.min_sample) return 'Only ' + n + ' forecast ranges checked so far: too few to judge.';
  return 'So far the 80% ranges held the real price ' + hits + ' of ' + n + ' times (' + pct0(hits / n) + '; the aim is 80%).';
}
function renderGlance(){
  const g = $('#glance'); g.replaceChildren();
  const head = el('div', {class: 'card-head'}); head.append(el('h2', null, 'The day in 20 seconds')); g.append(head);
  const tiles = el('div', {class: 'tiles'});
  const m = R.mood, b = R.benchmark;
  const t1 = el('div', {class: 'tile'}); t1.append(el('span', {class: 'micro'}, 'Market mood'), el('span', {class: 'big'}, m ? m.word + (m.stress ? ' · stress' : '') : 'Unknown'));
  if (m && m.plain) t1.append(el('span', {class: 'small muted'}, m.plain.replace(/^[^:]+:\s*/, '')));
  const t2 = el('div', {class: 'tile'}); t2.append(el('span', {class: 'micro'}, b ? b.name : 'Benchmark'));
  if (b && b.change_pct != null) {
    t2.append(el('span', {class: 'big ' + (b.change_pct > 0 ? 'up-t' : b.change_pct < 0 ? 'down-t' : '')}, arrow(b.change_pct) + fmtPctU(b.change_pct, 2)));
    t2.append(el('span', {class: 'small muted'}, 'on ' + fmtDay(b.close_date, true) + (b.change_5d_pct != null ? ' · 5 days ' + fmtPctU(b.change_5d_pct, 2) : '')));
  } else t2.append(el('span', {class: 'big'}, '–'));
  tiles.append(t1, t2); g.append(tiles);
  const gl = (R.glance || {})[String(H)] || {up: 0, down: 0, none: 0, no_score: 0, moves: []};
  const ex = exitOf(H), tot = gl.up + gl.down + gl.none + gl.no_score;
  g.append(el('div', {class: 'micro'}, 'Leaning up or down · N+' + H + (ex ? ' (sell at the close of ' + ex.exit_label + ')' : '')));
  const bar = el('div', {class: 'leanbar', role: 'img', 'aria-label': gl.up + ' lean up, ' + gl.none + ' no clear lean, ' + gl.down + ' lean down'});
  [['u', gl.up], ['n', gl.none + gl.no_score], ['d', gl.down]].forEach(x => { if (x[1]) { const s = el('span', {class: x[0]}); s.style.width = (100 * x[1] / Math.max(1, tot)) + '%'; bar.append(s); } });
  g.append(bar);
  const key = el('div', {class: 'leankey'});
  key.append(el('span', {class: 'up-t'}, '▲ ' + gl.up + ' lean up'), el('span', {class: 'muted'}, '● ' + gl.none + ' no clear lean'), el('span', {class: 'down-t'}, '▼ ' + gl.down + ' lean down'));
  if (gl.no_score) key.append(el('span', {class: 'muted'}, gl.no_score + ' without a score'));
  g.append(key);
  if (gl.moves.length) {
    g.append(el('div', {class: 'micro'}, 'Biggest expected moves · N+' + H));
    const ul = el('ul', {class: 'moves'});
    gl.moves.forEach(t => { const c = BY[t], f = fc(c, H); if (!f) return;
      const li = el('li'), btn = el('button', {type: 'button'}, c.name);
      btn.addEventListener('click', () => focusCard(t)); li.append(btn);
      li.append(el('span', {class: 'num ' + (f.move_pct > 0 ? 'up-t' : f.move_pct < 0 ? 'down-t' : '')}, arrow(f.move_pct) + fmtPctU(f.move_pct) + ' to ' + fmtMoney(f.target)));
      ul.append(li); });
    g.append(ul);
  }
  const tr = el('p', {class: 'small'}); tr.append(tag('paper', R.paper_label || 'Paper only — no proven edge yet'), document.createTextNode(' ' + trackLine())); g.append(tr);
  if (N.headline) g.append(htmlBlock('headline prose', N.headline));
  if (N.top3 && N.top3.length) { const ol = el('ol', {class: 'top3'}); N.top3.forEach(x => { const li = el('li'); li.innerHTML = x; ol.append(li); }); g.append(ol); }
}

// ---------- what changed since the previous run ----------
function renderChanges(){
  const s = $('#changes'); s.replaceChildren();
  const C = R.changes || {by_horizon: {}, news: []};
  s.append(el('h2', null, 'What changed since the previous run'));
  if (C.since) s.append(el('p', {class: 'small muted'}, 'Compared with the forecasts of ' + fmtTime(C.since) + '.'));
  const rows = (C.by_horizon || {})[String(H)] || [];
  if (rows.length) {
    const ul = el('ul', {class: 'list plain'});
    rows.forEach(r => { const li = el('li'), c = BY[r.ticker] || {name: r.ticker}, b = el('button', {type: 'button', class: 'linkish'}, c.name);
      b.style.cssText = 'all:unset;cursor:pointer;font-weight:600;color:var(--md-sys-color-primary)'; b.addEventListener('click', () => focusCard(r.ticker));
      const bits = [];
      if (r.target_pct != null) bits.push('expected price ' + fmtPctU(r.target_pct));
      if (r.prob_pts != null && Math.abs(r.prob_pts) >= 0.0005) bits.push('chance of going up ' + fmtPts(r.prob_pts));
      li.append(b, document.createTextNode(': ' + bits.join(' · ')));
      ul.append(li); });
    s.append(ul);
  } else s.append(el('p', {class: 'empty'}, 'No big moves in expected prices or chances at N+' + H + '.'));
  const news = C.news || [];
  s.append(el('div', {class: 'micro'}, 'New news the model counted' + (C.news_total ? ' (' + C.news_total + ')' : '')));
  if (!news.length) { s.append(el('p', {class: 'empty'}, 'No new news counted since the previous run.')); return; }
  const ul = el('ul', {class: 'list plain'});
  news.forEach(n => { const li = el('li'); li.append(linkOrText(n.url, n.title || n.id));
    const meta = el('div', {class: 'small muted'}); meta.append(document.createTextNode((BY[n.ticker] ? BY[n.ticker].name : n.ticker) + ' · ' + (n.source || '') + ' '), statusTag(n.status));
    li.append(meta); ul.append(li); });
  s.append(ul);
  if (C.news_total > news.length) s.append(el('p', {class: 'small muted'}, (C.news_total - news.length) + ' more in the company cards.'));
}

// ---------- paper trading (simulated) ----------
function renderPaper(){
  const s = $('#paper'); s.replaceChildren();
  const P = R.paper || {};
  const head = el('div', {class: 'card-head'}); head.append(el('h2', null, 'Paper trading'), tag('sim', P.label || 'SIMULATED')); s.append(head);
  if (!P.live) { s.append(el('p', null, P.note || 'Paper trading has not started.')); s.append(el('p', {class: 'small muted'}, 'Paper trades are records kept to test the forecasts. Nothing is bought or sold.')); return; }
  const o = P.open || {n: 0};
  s.append(el('p', null, o.n ? o.n + ' open paper trade' + (o.n === 1 ? '' : 's') + (o.avg_pct != null ? ', on average ' + fmtPctU(o.avg_pct, 2) + ' so far' : '') + ' (simulated).' : 'No open paper trades right now.'));
  const words = {}; Object.values(P.tiers || {}).forEach(t => { const w = t[String(H)]; if (w) words[w] = (words[w] || 0) + 1; });
  const keys = Object.keys(words);
  if (keys.length) { const p = el('p', {class: 'small'}); p.append(document.createTextNode('Signal tiers at N+' + H + ' (simulated): ' + keys.map(k => words[k] + ' ' + k.toLowerCase()).join(' · ') + '.')); s.append(p); }
  if ((P.by_strategy || []).length) {
    const d = el('details'); d.append(el('summary', null, 'Open paper trades by strategy'));
    const w = el('div', {class: 'tbl'}), tb = el('table'), hr = el('tr');
    ['Strategy', 'Open', 'Average so far', 'Best', 'Worst'].forEach(h => hr.append(el('th', null, h))); tb.append(hr);
    P.by_strategy.forEach(r => { const tr = el('tr'); [r.name, String(r.n), fmtPctU(r.avg_pct, 2), fmtPctU(r.best, 2), fmtPctU(r.worst, 2)].forEach(x => tr.append(el('td', null, x))); tb.append(tr); });
    w.append(tb); d.append(w); s.append(d);
  }
  s.append(el('p', {class: 'small muted'}, 'Simulated records only: no money is used, nothing is bought or sold, and none of this is advice.'));
}

// ---------- legend ----------
function legendFan(){
  const s = svg('svg', {viewBox: '0 0 220 70', width: 220, height: 70, role: 'img', 'aria-label': 'Example: a price line, then a light 80% band, a darker 50% band and a dot for the expected price'});
  s.append(svg('path', {d: 'M110,35 L200,8 L200,62 Z', fill: 'var(--mb-chart-band-80)'}), svg('path', {d: 'M110,35 L200,22 L200,48 Z', fill: 'var(--mb-chart-band-50)'}));
  s.append(svg('path', {d: 'M8,44 L30,40 L52,46 L74,36 L96,38 L110,35', fill: 'none', stroke: 'var(--mb-chart-ink)', 'stroke-width': 2}));
  s.append(svg('circle', {cx: 200, cy: 33, r: 4, fill: 'var(--md-sys-color-primary)'}));
  return s;
}
function renderLegend(){
  const s = $('#legend'); s.replaceChildren();
  s.append(el('h2', null, 'How to read this page'));
  const row = el('div', {style: 'display:flex;gap:14px;align-items:center;flex-wrap:wrap'});
  row.append(legendFan());
  const k = el('div', {class: 'key', style: 'flex-direction:column;gap:4px'});
  [['var(--mb-chart-ink)', 'Line: the last 20 closing prices'], ['var(--mb-chart-band-80)', 'Light band: 80% range'], ['var(--mb-chart-band-50)', 'Dark band: 50% range'], ['var(--md-sys-color-primary)', 'Dot: expected price on the sell day']].forEach(x => {
    const sp = el('span'); const sw = el('span', {class: 'sw'}); sw.style.background = x[0]; sp.append(sw, document.createTextNode(x[1])); k.append(sp); });
  row.append(k); s.append(row);
  s.append(el('p', null, 'A range is where the price is likely to close on the sell day: inside the 80% range about 8 times in 10, inside the 50% range about half the time.'));
  s.append(el('p', null, 'Chance of going up is the signal model’s estimate that the price at the sell day’s close ends above the next morning’s opening price. 50% is a coin flip; most stocks sit between 45% and 55%.'));
  const lean = R.lean || {slight: 0.02, clear: 0.05};
  const d = el('details'); d.append(el('summary', null, 'All definitions'));
  const dl = el('dl', {class: 'gloss'});
  [['N+1, N+3, N+5', 'Bought at the next opening price, sold at the close of the 1st, 3rd or 5th trading day after that day. Weekends and holidays are skipped.'],
   ['Expected price', 'The middle of the range: the most likely closing price on the sell day. Not a promise.'],
   ['Lean', 'Lean up when the chance of going up is ' + pct0(0.5 + lean.clear) + ' or more, lean down at ' + pct0(0.5 - lean.clear) + ' or less; “slight” between ' + pct0(0.5 + lean.slight) + ' and ' + pct0(0.5 + lean.clear) + ' (or the same distance below 50%). Closer to 50%: no clear lean.'],
   ['Why', 'The model’s strongest reasons in plain words, from its stored scores, news and events.'],
   ['Warnings', 'Results soon (prices can jump), a data problem (no forecast trusted), or news that other sources contradicted.'],
   ['News status', 'Confirmed by a filing or by 2+ independent outlets, single source, not verified, rumour, promotional or contradicted.'],
   ['Paper / SIMULATED', 'Paper trades are records kept to test the forecasts: no money, no orders. “Paper only — no proven edge yet” stays until the weekly review shows the model has real skill.'],
   ['Market mood', 'Calm, trending, event-heavy or unstable, from the volatility index and the index trend. Ranges are wider when the mood is rougher.']].forEach(x => dl.append(el('dt', null, x[0]), el('dd', null, x[1])));
  d.append(dl); s.append(d);
}
