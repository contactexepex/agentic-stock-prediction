// The reader's daily report (C2): controls, company cards with the fan chart, track record, notes, footer.

// ---------- fan chart: the last closes, then the N+1/N+3/N+5 ranges (50% and 80%) and expected prices ----------
function fanChart(c, h){
  const W = 340, Ht = 168, L = 6, Rr = 62, T = 10, B = 22;
  const bars = c.bars || [], n = bars.length;
  const fs = (c.forecasts || []).filter(f => f.lo80 != null && f.hi80 != null).sort((a, b) => a.h - b.h);
  const off = f => f.h + 1;   // the exit session is k + 1 sessions after the as-of close (D, then k more)
  const maxOff = fs.length ? Math.max(...fs.map(off)) : 0;
  const base = fs.length ? fs[0].base_close : (n ? bars[n - 1].c : null);
  // history on the left 62% of the plot, the future (up to the farthest exit session) on the right 38%
  const split = L + (W - L - Rr) * (maxOff ? 0.62 : 1), last = n - 1;
  const xs = i => i <= last ? L + (split - L) * i / Math.max(1, last) : split + (W - Rr - split) * (i - last) / Math.max(1, maxOff);
  const vals = bars.map(b => b.c).concat(fs.flatMap(f => [f.lo80, f.hi80])).filter(v => v != null);
  let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo) * 0.06 || hi * 0.01 || 1; lo -= pad; hi += pad;
  const ys = v => T + (Ht - T - B) * (hi - v) / (hi - lo);
  const sel = fs.find(f => f.h === h);
  const s = svg('svg', {class: 'fan', viewBox: `0 0 ${W} ${Ht}`, role: 'img',
    'aria-label': c.name + ': last ' + n + ' closing prices' + (sel ? '; N+' + h + ' expected price ' + fmtMoney(sel.target) + ', 80% range ' + fmtMoney(sel.lo80) + ' to ' + fmtMoney(sel.hi80) : '')});
  if (n) s.append(svg('rect', {x: xs(last), y: T, width: Math.max(0, W - Rr - xs(last)), height: Ht - T - B, fill: 'var(--md-sys-color-surface-container)', opacity: 0.6}));
  [lo + pad, hi - pad].forEach(v => { s.append(svg('line', {x1: L, x2: W - Rr, y1: ys(v), y2: ys(v), stroke: 'var(--mb-chart-grid)', 'stroke-width': 1}));
    s.append(sText(W - Rr + 6, ys(v) + 4, fmtNum(v))); });
  if (fs.length && n && base != null) {
    const pts = [[last, base, base, base, base]].concat(fs.map(f => [last + off(f), f.lo80, f.hi80, f.lo50, f.hi50]));
    const area = (a, b) => 'M' + pts.map(p => xs(p[0]) + ',' + ys(p[b])).join('L') + 'L' + pts.slice().reverse().map(p => xs(p[0]) + ',' + ys(p[a])).join('L') + 'Z';
    s.append(svg('path', {d: area(1, 2), fill: 'var(--mb-chart-band-80)'}));
    if (fs.every(f => f.lo50 != null)) s.append(svg('path', {d: area(3, 4), fill: 'var(--mb-chart-band-50)'}));
    if (sel) s.append(svg('line', {x1: xs(last + off(sel)), x2: xs(last + off(sel)), y1: T, y2: Ht - B, stroke: 'var(--md-sys-color-primary)', 'stroke-width': 1, 'stroke-dasharray': '3 3'}));
    // expected prices: dots joined by a dashed line from the last close (B15's company-page fan)
    const tg = fs.filter(f => f.target != null);
    if (tg.length) s.append(svg('path', {d: 'M' + xs(last) + ',' + ys(base) + tg.map(f => 'L' + xs(last + off(f)) + ',' + ys(f.target)).join(''),
      fill: 'none', stroke: 'var(--mb-chart-1)', 'stroke-width': 1.5, 'stroke-dasharray': '4 3'}));
    tg.forEach(f => { const on = f === sel;
      s.append(svg('circle', {cx: xs(last + off(f)), cy: ys(f.target), r: on ? 5 : 3.5, fill: 'var(--mb-chart-1)', stroke: 'var(--md-sys-color-surface-container-lowest)', 'stroke-width': 1.5})); });
    if (sel && sel.target != null) {   // the selected expected price as a filled tag on the price axis
      const ty = Math.min(Ht - B - 8, Math.max(T + 8, ys(sel.target))), label = fmtNum(sel.target);
      s.append(svg('rect', {x: W - Rr + 2, y: ty - 9, width: Math.min(Rr - 2, 8 + label.length * 6.4), height: 18, rx: 4, fill: 'var(--mb-chart-1)'}));
      s.append(sText(W - Rr + 6, ty + 4, label, {fill: 'var(--md-sys-color-on-primary)', 'font-weight': 700}));
    }
  }
  if (n) {
    s.append(svg('path', {d: bars.map((p, i) => (i ? 'L' : 'M') + xs(i) + ',' + ys(p.c)).join(''), fill: 'none', stroke: 'var(--mb-chart-ink)', 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round'}));
    s.append(svg('circle', {cx: xs(last), cy: ys(bars[last].c), r: 3.5, fill: 'var(--mb-chart-ink)'}));
    s.append(sText(xs(0), Ht - 6, fmtDay(bars[0].d)));
    s.append(sText(xs(last), Ht - 6, fmtDay(bars[last].d), {'text-anchor': 'end'}));
  }
  if (sel) s.append(sText(Math.max(xs(last + off(sel)), xs(last) + 4), Ht - 6, fmtDay(sel.exit_date), {'text-anchor': 'start', fill: 'var(--md-sys-color-primary)'}));
  const hit = svg('rect', {x: 0, y: 0, width: W, height: Ht, fill: 'transparent'}); s.append(hit);
  hit.addEventListener('pointermove', ev => {
    const box = s.getBoundingClientRect(), px = (ev.clientX - box.left) * W / box.width;
    let best = null, bd = 1e9;
    bars.forEach((p, i) => { const d = Math.abs(xs(i) - px); if (d < bd) { bd = d; best = {p: p}; } });
    fs.forEach(f => { const d = Math.abs(xs(last + off(f)) - px); if (d < bd) { bd = d; best = {f: f}; } });
    if (!best) return;
    if (best.p) showTip(ev, [[fmtDay(best.p.d, true)], ['close', fmtMoney(best.p.c)]]);
    else { const f = best.f; showTip(ev, [['N+' + f.h + ' · sell at the close of ' + f.exit_label], ['expected', fmtMoney(f.target)],
      ['to ' + fmtMoney(f.hi50) + ' (50%)', fmtMoney(f.lo50)], ['to ' + fmtMoney(f.hi80) + ' (80%)', fmtMoney(f.lo80)]]); }
  });
  hit.addEventListener('pointerleave', hideTip);
  return s;
}

// ---------- chance of going up ----------
function oddsMeter(f){
  const box = el('div', {class: 'odds'});
  const row = el('div', {class: 'row'});
  row.append(el('span', {class: 'small muted'}, 'Chance of going up by ' + (f && f.exit_label ? f.exit_label : 'the sell day')));
  row.append(el('b', {class: f && f.lean === 'up' ? 'up-t' : f && f.lean === 'down' ? 'down-t' : ''}, f && f.prob_up != null ? pct0(f.prob_up) : 'no score'));
  box.append(row);
  if (f && f.prob_up != null) {
    const m = el('div', {class: 'meter', role: 'img', 'aria-label': 'Chance of going up ' + pct0(f.prob_up) + ' on a scale from 25% to 75%; the middle mark is 50%, a coin flip'});
    const d = el('span', {class: 'dot'}); d.style.left = (100 * Math.max(0, Math.min(1, (f.prob_up - 0.25) / 0.5))) + '%';
    d.style.background = f.lean === 'up' ? 'var(--mb-color-up)' : f.lean === 'down' ? 'var(--mb-color-down)' : 'var(--md-sys-color-outline)';
    m.append(el('span', {class: 'mid'}), d); box.append(m);
    const sc = el('div', {class: 'meter-scale'}); sc.append(el('span', null, '25% · down'), el('span', null, '50% coin flip'), el('span', null, 'up · 75%')); box.append(sc);
  }
  return box;
}

// ---------- the N+1 / N+3 / N+5 table ----------
const rangeText = (a, b) => a == null || b == null ? '–' : fmtNum(a) + '–​' + fmtNum(b);
function horizonTable(c, h){
  const g = el('div', {class: 'hz', role: 'table', 'aria-label': 'Forecast per horizon'});
  const cols = HS.map(x => fc(c, x));
  const cell = (cls, text, on) => el('div', {class: cls + (on ? ' sel' : ''), role: 'cell'}, text);
  g.append(cell('h l', ''), ...HS.map((x, i) => cell('h', 'N+' + x, x === h)));
  [['Sell at close', f => f && f.exit_label ? f.exit_label.replace(/^\w+ /, '') : '–'],
   ['Expected', f => f ? fmtNum(f.target) : '–'],
   ['50% range', f => f ? rangeText(f.lo50, f.hi50) : '–'],
   ['80% range', f => f ? rangeText(f.lo80, f.hi80) : '–'],
   ['Chance up', f => f && f.prob_up != null ? pct0(f.prob_up) : '–']].forEach(r => {
    g.append(cell('l', r[0])); cols.forEach((f, i) => g.append(cell('v', r[1](f), HS[i] === h)));
  });
  return g;
}

// ---------- company card ----------
function card(c){
  const f = fc(c, H);
  const a = el('article', {class: 'card co', id: 'co-' + c.ticker.replace(/[^A-Za-z0-9]/g, '_')});
  const head = el('div', {class: 'co-head'});
  const nm = el('div'); nm.append(el('h3', null, c.name), el('div', {class: 'tk'}, c.ticker + (c.sector ? ' · ' + c.sector : '')));
  const lean = f ? f.lean : 'none';
  head.append(nm, tag(f && f.prob_up != null ? lean : 'none', (lean === 'up' ? '▲ ' : lean === 'down' ? '▼ ' : '● ') + leanText(f)));
  a.append(head);
  const p = el('div', {class: 'co-price'});
  p.append(document.createTextNode('Last close '), el('b', null, fmtMoney(f && f.base_close != null ? f.base_close : c.close)), document.createTextNode(' '));
  if (c.ret_1d != null) p.append(el('span', {class: c.ret_1d > 0 ? 'up-t' : c.ret_1d < 0 ? 'down-t' : ''}, arrow(c.ret_1d) + fmtFrac(c.ret_1d)));
  p.append(document.createTextNode(' on ' + D.as_of_label + (f && f.target != null ? ' · expected ' + fmtMoney(f.target) + ' (' + fmtPctU(f.move_pct) + ') by ' + f.exit_label : '')));
  a.append(p);
  if ((c.forecasts || []).some(x => x.lo80 != null)) a.append(fanChart(c, H));
  else a.append(el('p', {class: 'empty'}, 'No price range today' + (c.quality ? ' (data quality: ' + c.quality + ')' : '') + '.'));
  a.append(oddsMeter(f));
  if ((c.forecasts || []).length) a.append(horizonTable(c, H));
  a.append(el('p', {class: 'why'}, f ? f.why : 'No forecast for this horizon today.'));
  if ((c.flags || []).length) { const fl = el('div', {class: 'flags'}); c.flags.forEach(x => fl.append(tag(x.code === 'blocked' || x.code === 'contradicted' ? 'down' : 'warn', x.text, 'warning'))); a.append(fl); }
  const ch = f && f.change;
  if (ch) {
    const bits = [];
    if (ch.target_pct != null) bits.push('expected price ' + fmtPctU(ch.target_pct));
    if (ch.prob_pts != null && Math.abs(ch.prob_pts) >= 0.0005) bits.push('chance of going up ' + fmtPts(ch.prob_pts));
    if ((ch.news_added || []).length) bits.push(ch.news_added.length + ' new news item' + (ch.news_added.length === 1 ? '' : 's') + ' counted');
    if (bits.length) a.append(el('p', {class: 'chg'}, 'Since the previous run (' + fmtTime(ch.since) + '): ' + bits.join(' · ') + '.'));
  }
  const P = R.paper || {};
  if (P.live) {
    const t = (P.by_ticker || {})[c.ticker], w = ((P.tiers || {})[c.ticker] || {})[String(H)];
    const pl = el('p', {class: 'paperline'}); pl.append(tag('sim', 'SIMULATED'), document.createTextNode(' ' + (t ? t.n + ' open paper trade' + (t.n === 1 ? '' : 's') + (t.avg_pct != null ? ', average ' + fmtPctU(t.avg_pct, 2) : '') : 'No open paper trades') + (w ? ' · signal tier at N+' + H + ': ' + w : '')));
    a.append(pl);
  }
  a.append(moreDetails(c));
  return a;
}

function moreDetails(c){
  const d = el('details'); d.append(el('summary', null, 'News, events and the analysts’ view'));
  const body = el('div', {class: 'more'});
  (c.calls || []).forEach(cl => {
    body.append(el('h4', null, 'AI forecaster, ' + cl.when + ': ' + cl.direction + ' at ' + pct0(cl.confidence) + ' confidence'));
    if (cl.rationale) body.append(el('p', null, cl.rationale));
  });
  if ((c.news || []).length) { body.append(el('h4', null, 'Latest news')); const ul = el('ul');
    c.news.forEach(n => { const li = el('li'); li.append(linkOrText(n.url, n.title));
      const meta = el('div', {class: 'small muted'}); meta.append(document.createTextNode((n.source || '') + (n.ts ? ' · ' + fmtDay(n.ts) : '') + ' '));
      if (n.verification) meta.append(statusTag(n.verification)); li.append(meta); ul.append(li); });
    body.append(ul); }
  const added = ((fc(c, H) || {}).change || {}).news_added || [];
  if ((c.events || []).length) { body.append(el('h4', null, 'Coming up')); const ul = el('ul');
    c.events.forEach(e => ul.append(el('li', null, e.day + ' · ' + e.label + (e.market ? ' (whole market)' : '')))); body.append(ul); }
  const sec = (N.sectors || {})[c.sector];
  if (sec) { body.append(el('h4', null, c.sector + ': analysts’ view')); body.append(htmlBlock('prose', sec)); }
  if (c.record) { const parts = Object.keys(c.record.ranges || {}).map(k => c.record.ranges[k].name + ' 80% ranges: ' + c.record.ranges[k].text);
    body.append(el('h4', null, 'Track record for ' + c.ticker)); body.append(el('p', {class: 'small'}, (parts.length ? parts.join(' ') : 'No ranges checked yet.') + ' Calls: ' + ((c.record.calls || {}).text || 'none checked yet.'))); }
  if (added.length) body.append(el('p', {class: 'small muted'}, added.length + ' news item(s) newly counted by the model since the previous run.'));
  if (!body.childNodes.length) body.append(el('p', {class: 'empty'}, 'No news or events found for this company.'));
  d.append(body);
  return d;
}

// ---------- controls ----------
const fs = $('#f-sector'), fl = $('#f-lean'), fo = $('#f-sort'), fh = $('#f-horizon');
fs.append(el('option', {value: ''}, 'All sectors'));
Array.from(new Set(COS.map(c => c.sector).filter(Boolean))).forEach(x => fs.append(el('option', {value: x}, x)));
HS.forEach(h => { const b = el('button', {type: 'button', 'aria-pressed': String(h === H)}, 'N+' + h);
  b.addEventListener('click', () => { H = h; fh.querySelectorAll('button').forEach(x => x.setAttribute('aria-pressed', String(x === b))); renderAll(); }); fh.append(b); });
function visible(){
  const strength = c => { const f = fc(c, H); return f && f.prob_up != null ? Math.abs(f.prob_up - 0.5) : -1; };
  const move = c => { const f = fc(c, H); return f && f.move_pct != null ? Math.abs(f.move_pct) : -1; };
  const list = COS.filter(c => (!fs.value || c.sector === fs.value) && (!fl.value ||
    (fl.value === 'flag' ? (c.flags || []).length > 0 : (fc(c, H) || {lean: 'none'}).lean === fl.value)));
  const by = fo.value === 'move' ? (a, b) => move(b) - move(a) : fo.value === 'name' ? null : (a, b) => strength(b) - strength(a);
  return list.slice().sort((a, b) => (by ? by(a, b) : 0) || a.name.localeCompare(b.name));
}
function renderCards(){
  const list = visible(), cs = $('#cards');
  cs.replaceChildren(...list.map(card));
  if (!list.length) cs.append(el('p', {class: 'empty'}, 'No company matches. Choose another sector or “All companies”.'));
  $('#f-count').textContent = list.length + ' of ' + COS.length + ' companies';
  const ex = exitOf(H);
  $('#f-hzline').textContent = ex ? 'N+' + H + ': bought at the open of ' + fmtDay(ex.entry_date, true) + ', sold at the close of ' + ex.exit_label + '.' : '';
}
function focusCard(t){
  fs.value = ''; fl.value = ''; renderCards();
  const node = document.getElementById('co-' + t.replace(/[^A-Za-z0-9]/g, '_'));
  if (node) { node.scrollIntoView({behavior: 'smooth', block: 'start'}); $('details', node).open = true; }
}
[fs, fl, fo].forEach(x => x.addEventListener('change', renderCards));

// ---------- track record ----------
function renderTrack(){
  const s = $('#track'); s.replaceChildren();
  const head = el('div', {class: 'card-head'}); head.append(el('h2', null, 'Track record so far'), tag('paper', R.paper_label || 'Paper only — no proven edge yet')); s.append(head);
  const pts = (D.calibration || []).filter(p => p.kind === 'range' && p.actual != null && p.n > 0);
  if (!pts.length) { s.append(el('p', {class: 'empty'}, 'Nothing has been checked yet: forecasts are scored once their sell day has closed.')); return; }
  s.append(el('p', {class: 'small muted'}, 'How often the real closing price ended inside each kind of range (bar) against the aim (black mark). All companies of this market.' + (pts.every(p => p.n < D.min_sample) ? ' Fewer than ' + D.min_sample + ' checks each: too early to judge.' : '')));
  pts.forEach(p => { const r = el('div', {class: 'rec'});
    r.append(el('span', null, p.label), el('span', {class: 'num'}, pct0(p.actual) + ' of ' + p.n + ' · aim ' + pct0(p.stated)));
    const bar = el('div', {class: 'bar'}), fill = el('i'), aim = el('b'); fill.style.width = (100 * p.actual) + '%'; aim.style.left = (100 * p.stated) + '%';
    bar.append(fill, aim); r.append(bar); s.append(r); });
  const cs = D.call_scores || {n: 0};
  s.append(el('p', {class: 'small'}, cs.n ? 'AI up/down calls checked: ' + cs.n + '.' + (cs.basis_note ? ' ' + cs.basis_note : '') : 'No AI up/down call has been checked yet.'));
}

// ---------- notes, data quality, footer ----------
function renderNotes(){
  const s = $('#notes');
  s.append(el('h2', null, 'Analyst notes'));
  [['Yesterday', N.yesterday], ['Calls and abstentions', N.calls], ['This week: risks and events', N.outlook]].forEach(x => {
    if (!x[1] && !x[0].startsWith('This week')) return;
    const d = el('details'); d.append(el('summary', null, x[0]));
    if (x[1]) d.append(htmlBlock('prose', x[1]));
    if (x[0].startsWith('This week') && (D.upcoming || []).length) { const ul = el('ul', {class: 'list'}); D.upcoming.forEach(e => ul.append(el('li', null, e.day + ' · ' + e.label + (e.major ? ' (major)' : '')))); d.append(ul); }
    s.append(d);
  });
  const Q = D.quality || {partial: [], blocked: [], regime_notes: []}, dq = el('details');
  const nWarn = Q.partial.length + Q.blocked.length + Q.regime_notes.length;
  dq.append(el('summary', null, 'Data quality' + (nWarn ? ' (' + nWarn + ' warning' + (nWarn > 1 ? 's' : '') + ')' : '')));
  const b = el('div', {class: 'prose'});
  b.append(el('p', null, 'Indicators: ' + (Q.blocked.length ? 'blocked (no forecast trusted): ' + Q.blocked.join(', ') + '. ' : 'none blocked. ') + (Q.partial.length ? 'Partial data: ' + Q.partial.join(', ') + '.' : 'No partial data.')));
  if (Q.regime_notes.length) b.append(el('p', null, 'Market mood notes: ' + Q.regime_notes.join('; ')));
  if (N.data_quality) b.append(htmlBlock('prose', N.data_quality));
  dq.append(b); s.append(dq);
  const ft = $('#footer');
  ft.append(el('p', null, 'Research log, not investment advice. Numbers come from the stored data as of ' + fmtTime(R.cutoff || D.generated_at) + '; the text is written by research agents, checked by automated validation and sampled weekly by a separate judge agent.'));
  const fl2 = el('p'); fl2.append(document.createTextNode('Built ' + String(D.generated_at).replace('T', ' ').replace('+00:00', ' UTC') + ' · '));
  fl2.append(el('a', {href: D.links.index}, 'All report days'), document.createTextNode(' · '), el('a', {href: D.links.md}, 'Text version')); ft.append(fl2);
}

function renderAll(){ renderGlance(); renderChanges(); renderPaper(); renderCards(); }
renderTop(); renderLegend(); renderTrack(); renderNotes(); renderAll();
const hash = decodeURIComponent(location.hash.slice(1));
if (hash && BY[hash]) focusCard(hash);
