/* Shared script of the design-track mockups: DOM helpers, formatters, the app shell (sidebar, top bar, phone
   drawer and bar), the tooltip, the page head and small visual parts (odds meter, icon tile, family label, range
   bar, buyers-by-horizon bars). A page defines `const D = ...payload...` before this script and calls `shell(...)`
   then builds its sections. Spec constants named once here with their source. */
const $ = (s, el=document) => el.querySelector(s);
const el = (tag, attrs={}, ...kids) => { const n = document.createElement(tag); for (const [k,v] of Object.entries(attrs)) { if (v == null || v === false) continue; if (k==='class') n.className=v; else if (k==='html') n.innerHTML=v; else if (k.startsWith('on')) n.addEventListener(k.slice(2), v); else n.setAttribute(k, v === true ? '' : v);} for (const k of kids) { if (k==null) continue; n.append(k.nodeType? k : document.createTextNode(String(k))); } return n; };
const svgEl = (tag, attrs={}) => { const n = document.createElementNS('http://www.w3.org/2000/svg', tag); for (const [k,v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };
const icon = (id, cls='ms') => { const s = svgEl('svg', {class: cls, 'aria-hidden': 'true'}); const u = svgEl('use'); u.setAttribute('href', '#' + (id.startsWith('ms-') ? id : 'ms-' + id)); s.append(u); return s; };
const help = tip => el('button', {class:'md-help', 'data-tip': tip, 'aria-label':'Explain', type:'button'}, '?');
const LABEL = {india: 'India', us: 'US'};
const ZONE = {india: 'IST', us: 'ET'};                      /* presentation only: the market's local clock label */
const LOCALE = {INR: 'en-IN', USD: 'en-US'}, SYMBOL = {INR: '₹', USD: '$'};
const FAMILY = {rule: ['Rule strategies', 'ms-settings', 'r'], baseline: ['Baselines', 'ms-trending_flat', 'b'], ai: ['AI traders', 'ms-bolt', 'a']};
const FAMILY_SHORT = {rule: 'Rule', baseline: 'Baseline', ai: 'AI'};
const PICK = {best_expected_gain: 'Best expected gain', highest_probability: 'Highest probability'};
const BAND = {below80: ['below the 80% range', 'flag'], below50: ['below the 50% range', ''], inside50: ['inside the 50% range', 'ok'], above50: ['above the 50% range', ''], above80: ['above the 80% range', 'flag']};
const BAND_SHORT = {below80: 'below 80%', below50: 'below 50%', inside50: 'inside 50%', above50: 'above 50%', above80: 'above 80%'};
const FLAG = {outside_range: 'outside its range', far_from_target: 'far from its target', against_prediction: 'against the prediction'};
const FLAG_SHORT = {outside_range: 'outside range', far_from_target: 'far from target', against_prediction: 'against prediction'};
const STATUS = {confirmed_primary: ['confirmed', 'A primary document (exchange filing, company release) confirms it. Can be the main evidence of a call.', 'ms-verified_user'],
  corroborated: ['corroborated', 'Two or more independent outlets reported it on their own. Can be the main evidence of a call.', 'ms-check'],
  single_source: ['single source', 'One independent origin so far. Lowers a call’s confidence; cannot be the main evidence.', 'ms-warning'],
  unverified: ['unverified', 'No vetted outlet read yet. Lowers confidence; cannot be the main evidence.', null],
  rumour: ['rumour', 'Reported as a rumour or from unnamed sources. Never supports a call.', 'ms-close'],
  promotional: ['promotional', 'A paid, promotional or opinion item. Never supports a call.', 'ms-close'],
  contradicted: ['contradicted', 'A checked claim conflicts with a primary document. Can only widen a range.', 'ms-close']};
const CAN_CARRY = ['confirmed_primary', 'corroborated'];
/* Spec constants (not data): docs/SPEC.md F7.2 go-live bar = 2 months of forward paper trading and about 300 settled trades per strategy; section 7 = two intraday checks per session; section 6 = fewer than 20 settled trades is too few to rank; F2.3 = the back-test runs on the 15-year history cache; F7.1 luck test = a 95% percentile bootstrap interval (marketbrief/lab/luck.py, alpha 0.05); F4.2, section 7 and F6 = an AI trader's reason, a deviation note and an EOD reason are at most 60 words; F11 and mcp/tools.yaml (explain) = the assistant's question is at most 500 characters, its budget $0.65 a day under a $20 monthly hard cap, conversations kept 90 days. */
const GO_LIVE_MONTHS = 2, GO_LIVE_TRADES_ABOUT = 300, INTRADAY_CHECKS_PER_SESSION = 2, MIN_TRADES_TO_RANK = 20, BACKTEST_YEARS = 15, LUCK_INTERVAL_PCT = 95, REASON_MAX_WORDS = 60;
const ASSISTANT_QUESTION_MAX_CHARS = 500, ASSISTANT_DAILY_USD = 0.65, ASSISTANT_MONTHLY_USD_CAP = 20, ASSISTANT_LOG_DAYS = 90;
/* News page rules (owner decision 2026-10-08, design/mockups/09-news/rationale.md): at most 10 market movers, 10 stories a page; the 3-day window and the 50-item cap are the build's (data.json `window`). */
const NEWS_MOVERS_MAX = 10, NEWS_PAGE_SIZE = 10;
const DOW = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'], DOWL = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'], MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const dt = iso => new Date(iso.slice(0,10)+'T00:00:00Z');
const fmtD = (iso, dow=true) => { const d = dt(iso); return (dow? DOW[d.getUTCDay()]+' ' : '') + d.getUTCDate() + ' ' + MON[d.getUTCMonth()]; };
const fmtDY = iso => fmtD(iso, false) + ' ' + iso.slice(0,4);
const offsetMin = local => { const m = /([+-])(\d\d):(\d\d)$/.exec(local); return m ? (m[1]==='-'?-1:1) * (60*+m[2] + +m[3]) : 0; };
const fmtLocal = (iso, m, withDate=false) => { if (!iso) return '—'; const t = new Date(new Date(iso).getTime() + offsetMin(P(m).status.session.local_time)*60000); const hm = `${String(t.getUTCHours()).padStart(2,'0')}:${String(t.getUTCMinutes()).padStart(2,'0')}`; return (withDate ? `${t.getUTCDate()} ${MON[t.getUTCMonth()]} ` : '') + `${hm} ${ZONE[m]}`; };
const sgn = (x, dec=2, unit='%') => (x>0?'+':x<0?'−':'') + Math.abs(x).toFixed(dec) + unit;
const pct = (x, dec=0) => x == null ? '—' : (x*100).toFixed(dec) + '%';
const money = (cur, x, dec=0, sign=false) => { if (x == null) return '—'; const s = Math.abs(x).toLocaleString(LOCALE[cur], {minimumFractionDigits: dec, maximumFractionDigits: dec}); return (sign ? (x>0?'+':x<0?'−':'') : (x<0?'−':'')) + SYMBOL[cur] + s; };
const price = (cur, x) => x == null ? '—' : x.toLocaleString(LOCALE[cur], {minimumFractionDigits: 2, maximumFractionDigits: 2});
const delta = (x, dec=2, unit='%') => x == null ? el('span', {class:'muted'}, '—') : el('span', {class:'mb-delta '+(x>0?'up':x<0?'down':'flat')}, sgn(x, dec, unit));
const moneyDelta = (cur, x, dec=0) => x == null ? el('span', {class:'muted'}, '—') : el('span', {class:'mb-delta '+(x>0?'up':x<0?'down':'flat')}, money(cur, x, dec, true));
const dec = cur => cur === 'INR' ? 0 : 2;
const P = m => D.markets[m];
const companyOf = (m, t) => (P(m).companies || []).find(c => c.ticker === t) || {ticker: t, name: t};
const stratOf = (m, id) => (P(m).strategies || {})[id] || {id, name: id, family: '—'};
const PAGES = {home: '../01-home/page.html', watchlist: '../02-watchlist/page.html', company: '../03-company/page.html', strategies: '../04-stock-strategies/page.html', lab: '../05-strategy-lab/page.html', compare: '../06-rule-vs-ai/page.html', portfolios: '../07-paper-portfolios/page.html', track: '../08-track-record/page.html', news: '../09-news/page.html', companies: '../10-companies/page.html', assistant: '../11-assistant/page.html', help: '../12-help/page.html'};
const companyPage = t => `${PAGES.company}#${t}`, strategiesPage = t => `${PAGES.strategies}#${t}`;
const odds = (p, tipText) => { if (p == null) return el('span', {class:'muted'}, '—'); const s = svgEl('svg', {viewBox:'0 0 64 14'}); s.append(svgEl('rect', {class:'track', x:0, y:5, width:64, height:4, rx:2})); s.append(svgEl('line', {class:'mid', x1:32, x2:32, y1:1, y2:13})); const cx = Math.max(4, Math.min(60, (p - 0.30) / 0.40 * 64)); s.append(svgEl('circle', {class:'dot '+(p>0.5?'up':'dn'), cx, cy:7, r:4.5})); return el('span', {class:'mb-odds', 'data-tip': tipText}, s, el('b', {}, pct(p))); };
/* a pick's costs: the market-cost expected gain it was ranked on, and decision 51's viability at the owner's own cost */
const pickCand = k => (k.candidates || []).find(c => c.horizon_days === k.horizon_days) || null;
const yourViable = k => { const cd = pickCand(k); return cd && cd.cost_viable != null ? cd.cost_viable : null; };
function costLabels(cur, k) {
  const mk = k.expected_gain_pct > 0, cd = pickCand(k), out = [];
  out.push(el('span', {class:'mb-label ' + (mk ? 'success' : 'neutral'), 'data-tip': `Expected gain after market costs ${sgn(k.expected_gain_pct)} of ${money(cur, k.amount)}: ${pct(k.prob_up, 1)} × ${sgn(k.move_pct)} − ${pct(1 - k.prob_up, 1)} × ${k.loss_pct}% − ${k.costs_pct}% (brokerage, taxes and fees of config/costs.yaml; strategies are ranked on this view).`}, icon(mk ? 'ms-check' : 'ms-close'), `${sgn(k.expected_gain_pct)} · ${mk ? 'clears market costs' : 'below market costs'}`));
  if (cd && cd.cost_viable != null) out.push(el('span', {class:'mb-label ' + (cd.cost_viable ? 'success' : 'warn'), 'data-tip': `Decision 51, your own costs: with your broker’s extra charges the round trip is ${cd.your_cost_pct}% and the expected gain ${sgn(cd.expected_gain_your_pct)}, so this pick is ${cd.cost_viable ? 'viable' : 'not viable'} at your cost. The flag never blocks a paper trade.`}, icon(cd.cost_viable ? 'ms-check' : 'ms-warning'), cd.cost_viable ? 'viable at your cost' : 'not viable at your cost'));
  return out;
}
const viableLine = (picked) => { const mk = picked.filter(k => k.expected_gain_pct > 0).length, yv = picked.filter(k => yourViable(k) === true).length, known = picked.filter(k => yourViable(k) != null).length; return `${mk ? `${mk} clear${mk === 1 ? 's' : ''} market costs` : 'none clears market costs'} · ${known ? (yv ? `${yv} viable at your cost` : 'none viable at your cost') : 'your-cost view not stored'}`; };
const avatar = (ico, kind='', size='') => el('span', {class:`mb-avatar ${kind} ${size}`, 'aria-hidden':'true'}, icon(ico));
const famLabel = (f, text) => el('span', {class:'mb-label ' + ({rule:'', baseline:'warn', ai:'info'}[f])}, el('i', {class:'sw ' + FAMILY[f][2]}), text);
const statusBadge = st => { const s = STATUS[st] || [st, '', null]; return el('span', {class:'md-badge ' + st, 'data-tip': s[1]}, s[2] ? icon(s[2]) : null, s[0]); };
const sentSquare = v => { const s = v == null ? 'flat' : v > 0.05 ? 'up' : v < -0.05 ? 'dn' : 'flat'; return el('span', {class:'mb-dir ' + s, 'aria-label': 'sentiment ' + (v ?? 'n/a'), 'data-tip': v == null ? 'sentiment not scored' : `sentiment ${v > 0 ? '+' : ''}${v} (−1 very negative to +1 very positive), the news analyst’s score`}, icon(s === 'up' ? 'ms-arrow_upward' : s === 'dn' ? 'ms-arrow_downward' : 'ms-remove')); };
/* range bar: the trade's or prediction's 50% and 80% bands, the entry dotted, the target as a triangle, the last price as the dark line */
function rangeBar(cur, r, last, entry) {
  const lo = Math.min(r.lo80, entry ?? r.lo80, last ?? r.lo80) * 0.997, hi = Math.max(r.hi80, entry ?? r.hi80, last ?? r.hi80, r.target_price) * 1.003, X = v => (v - lo) / (hi - lo) * 96 + 2;
  const s = svgEl('svg', {viewBox:'0 0 100 18', role:'img', 'aria-label':`80% range ${price(cur, r.lo80)} to ${price(cur, r.hi80)}${last != null ? ', last ' + price(cur, last) : ''}`});
  s.append(svgEl('rect', {x: X(r.lo80), y: 5, width: X(r.hi80) - X(r.lo80), height: 8, rx: 4, fill: 'var(--mb-chart-band-80)'}));
  s.append(svgEl('rect', {x: X(r.lo50), y: 5, width: X(r.hi50) - X(r.lo50), height: 8, rx: 4, fill: 'var(--mb-chart-band-50)'}));
  if (entry != null) s.append(svgEl('line', {x1: X(entry), x2: X(entry), y1: 3, y2: 15, stroke: 'var(--md-sys-color-outline)', 'stroke-width': 1.5, 'stroke-dasharray': '2 1.5'}));
  s.append(svgEl('path', {d: `M${X(r.target_price)-3},1 L${X(r.target_price)+3},1 L${X(r.target_price)},5 Z`, fill: 'var(--mb-chart-1)'}));
  if (last != null) s.append(svgEl('line', {x1: X(last), x2: X(last), y1: 2, y2: 16, stroke: 'var(--md-sys-color-on-surface)', 'stroke-width': 2}));
  return el('span', {class:'rng', 'data-tip': `Predicted 50% range ${price(cur, r.lo50)}–${price(cur, r.hi50)}, 80% range ${price(cur, r.lo80)}–${price(cur, r.hi80)}; target ${price(cur, r.target_price)} (the triangle)${entry != null ? `; entry ${price(cur, entry)} (dotted)` : ''}${last != null ? `; last ${price(cur, last)} (the dark line)` : ''}.`}, s);
}
/* buyers by horizon: five small bars, the selected horizon dark */
function horizonBars(m, ticker, horizon) {
  const p = P(m), s = svgEl('svg', {viewBox:'0 0 96 40', role:'img', 'aria-label':'buyers by horizon'});
  const rows = p.horizons.map(k => (p.agreement[String(k)] || []).find(x => x.ticker === ticker));
  const max = Math.max(1, ...rows.map(a => a ? a.of : 0));
  rows.forEach((a, i) => { const x = i * 19 + 1, h = a ? Math.max(2, a.buy / max * 26) : 2, on = p.horizons[i] === horizon;
    s.append(svgEl('rect', {class: on ? 'on' : 'off', x, y: 28 - h, width: 15, height: h, rx: 3}));
    const tx = svgEl('text', {class: on ? 'on' : '', x: x + 7.5, y: 38, 'text-anchor':'middle'}); tx.textContent = a ? a.buy : '–'; s.append(tx); });
  const wrap = el('span', {class:'hzb', 'data-tip': `Buyers at each horizon: ${p.horizons.map(k => { const a = (p.agreement[String(k)] || []).find(x => x.ticker === ticker); return `N+${k} ${a ? a.buy + ' of ' + a.of : 'no prediction'}`; }).join(' · ')}. The strongest other horizon is the one with the most buyers (ties: the shorter).`}, s);
  return wrap;
}
function horizonTabs(horizons, current, onPick) {
  const seg = el('div', {class:'md-segmented dense light', role:'group', 'aria-label':'Horizon'});
  for (const k of horizons) seg.append(el('button', {type:'button', 'aria-pressed': String(k === current), onclick: () => onPick(k)}, `N+${k}`));
  return seg;
}
const horizonWords = k => k === 1 ? 'the next session’s close' : `the close of the ${['','1st','2nd','3rd','4th','5th'][k]} session after the open`;

/* ---------- state: the market from the hash ---------- */
let market = (location.hash.slice(1).split('/')[0] in D.markets) ? location.hash.slice(1).split('/')[0] : 'india';

/* ---------- shell ---------- */
const NAV = [['home','Home',PAGES.home], ['format_list_bulleted','Watchlist',PAGES.watchlist], ['science','Strategy lab',PAGES.lab], ['layers','Rule vs AI',PAGES.compare], ['account_balance_wallet','Paper portfolios',PAGES.portfolios], ['query_stats','Track record',PAGES.track], ['newspaper','News',PAGES.news], ['apartment','Companies',PAGES.companies], ['bolt','Assistant',PAGES.assistant], ['help','Help',PAGES.help]];
let onMarketChange = () => {};
function shell(current, title, opts={}) {
  const navItem = ([ico, label, href]) => el('a', {class:'mb-nav-item', href: href === current ? '#' : href, 'aria-current': href === current ? 'page' : null}, el('span', {class:'mb-nav-ind'}, icon('ms-'+ico)), el('span', {class:'mb-nav-label'}, label));
  const sidebar = $('#sidebar');
  sidebar.append(el('div', {class:'mb-sidebar-brand'}, el('span', {class:'mb-brand-mark', 'aria-hidden':'true'}, 'MB'), el('span', {}, 'Market brief', el('small', {}, 'research cockpit'))), el('div', {class:'mb-sidebar-section'}, 'Pages'), ...NAV.map(navItem), el('div', {class:'mb-sidebar-foot', id:'side-foot'}));
  const menuBtn = $('#menu-btn'), scrim = $('#scrim');
  const toggleMenu = on => { sidebar.classList.toggle('open', on); menuBtn.setAttribute('aria-expanded', String(on)); };
  menuBtn.addEventListener('click', () => toggleMenu(!sidebar.classList.contains('open')));
  scrim.addEventListener('click', () => toggleMenu(false));
  const barItems = (opts.bar || [NAV[0], NAV[1], NAV[2], NAV[3]]).map(navItem);
  $('#navbar').append(...barItems, el('button', {class:'mb-nav-item', type:'button', 'aria-controls':'sidebar', onclick: () => toggleMenu(true)}, el('span', {class:'mb-nav-ind'}, icon('ms-menu')), el('span', {class:'mb-nav-label'}, 'More')));
  window.addEventListener('scroll', () => $('#topbar').classList.toggle('scrolled', window.scrollY > 4), {passive:true});
  /* tooltip (hover, focus, tap; Escape closes) */
  const tip = $('#tip'); let tipPinned = null;
  const showTip = (target, html) => { tip.innerHTML = html; tip.classList.add('on'); const r = target.getBoundingClientRect(); let left = r.left + r.width/2 - tip.offsetWidth/2, top = r.top - tip.offsetHeight - 10; left = Math.max(8, Math.min(window.innerWidth - tip.offsetWidth - 8, left)); if (top < 8) top = r.bottom + 12; tip.style.left = left + 'px'; tip.style.top = top + 'px'; };
  const hideTip = () => { if (tipPinned) return; tip.classList.remove('on'); };
  document.addEventListener('pointerover', e => { const t = e.target.closest('[data-tip]'); if (t && !tipPinned) showTip(t, t.dataset.tip); });
  document.addEventListener('pointerout', e => { if (e.target.closest('[data-tip]')) hideTip(); });
  document.addEventListener('focusin', e => { const t = e.target.closest('[data-tip]'); if (t) showTip(t, t.dataset.tip); });
  document.addEventListener('focusout', e => { if (e.target.closest('[data-tip]')) { tipPinned = null; hideTip(); } });
  document.addEventListener('click', e => { const t = e.target.closest('[data-tip]'); if (t && t.tagName !== 'A' && !t.classList.contains('md-btn') && t.closest('.md-segmented') == null && !t.closest('.md-chip.filter') && !t.closest('th')) { if (tipPinned === t) { tipPinned = null; hideTip(); } else { tipPinned = t; showTip(t, t.dataset.tip); } e.preventDefault(); } else if (tipPinned) { tipPinned = null; hideTip(); } });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { tipPinned = null; hideTip(); toggleMenu(false); } });
  window.addEventListener('hashchange', () => { const h = location.hash.slice(1).split('/')[0]; if (h in D.markets && h !== market) { market = h; onMarketChange(); } });
}
function marketSeg(onPick) { const seg = $('#market-seg'); seg.innerHTML = ''; for (const m of Object.keys(D.markets)) seg.append(el('button', {type:'button', 'aria-pressed': String(m === market), 'data-tip': `Switch to the ${LABEL[m]} ${document.title.split(' · ')[1] || 'page'} (${P(m).name})`, onclick: () => { market = m; history.replaceState(null, '', '#'+m); onPick(m); }}, LABEL[m])); }
function sideFoot(m) { const p = P(m), f = $('#side-foot'); f.innerHTML = ''; f.append(el('b', {}, p.status.paper_label), el('br'), `${LABEL[m]} · data as of ${fmtD(p.as_of, false)}`); }
function makeFocusable(root) { for (const n of root.querySelectorAll('[data-tip]')) if (!n.matches('a[href], button, input, select, [tabindex]')) n.setAttribute('tabindex', '0'); }
function pageHead(m, title, subtitle) {
  const p = P(m), s = p.status.session, open = !!s.in_session, fr = p.status.freshness;
  const h = el('section', {class:'phead', 'aria-label':'Session and freshness'});
  h.append(el('div', {}, el('h1', {}, title), el('div', {class:'sub'}, subtitle)));
  const chips = el('div', {class:'chips'});
  chips.append(el('span', {class:'md-chip', 'data-tip': `Session ${fmtLocal(s.session_open_utc, m)}–${fmtLocal(s.session_close_utc, m)}.`}, el('span', {class:'dot'+(open?' open':'')}), s.trading_day ? (open ? el('b', {}, 'Open now') : (s.late_run ? 'Closed for today' : el('span', {}, 'Opens ', el('b', {}, fmtLocal(s.session_open_utc, m))))) : 'No session today'));
  chips.append(el('span', {class:'md-chip', 'data-tip':'Market mood stored by the daily run: CALM / TRENDING / EVENT_HEAVY / UNSTABLE. AI traders lower their probability in EVENT_HEAVY and UNSTABLE; rule strategies either filter those days or not.'}, 'Regime ', el('b', {}, p.status.regime)));
  chips.append(el('span', {class:'md-chip', 'data-tip': `Page data built ${fmtLocal(fr.built_at, m, true)} (${fr.age_minutes} min before the cut-off ${fmtLocal(p.cutoff, m, true)}). Nothing stored after the cut-off is used.`}, icon(fr.state === 'fresh' ? 'ms-check' : 'ms-warning'), el('b', {}, fr.state), ` · built ${fmtLocal(fr.built_at, m)}`));
  chips.append(el('span', {class:'mb-tag paper', 'data-tip': p.status.paper_label}, 'paper'));
  h.append(chips);
  return h;
}
function paperBand(m, g, n) {
  const p = P(m);
  if (g && g.proven) return el('section', {class:'mb-alert band success', 'aria-label':'Signals'}, icon('ms-check'), el('div', {}, el('b', {class:'t'}, 'A strategy has met the go-live bar'), el('div', {class:'s'}, `${p.status.paper_label}. Strong signals may now appear on the strategy pages; the rankings still say who agrees, not what to do.`)), el('a', {class:'md-btn text act', href: PAGES.track, style:'color:inherit'}, 'Track record', icon('ms-chevron_right')));
  return el('section', {class:'mb-alert band', 'aria-label':'Signals'}, icon('ms-block'), el('div', {}, el('b', {class:'t'}, 'No proven strong signals today'),
    el('div', {class:'s'}, `${p.status.paper_label}.` + (g ? ` None of the ${n} strategies has met the go-live bar (${g.trades_needed} settled trades, ${g.months_forward} of ${GO_LIVE_MONTHS} months forward so far, beating the best baseline after costs).` : '') + ' Nothing here is advice.')),
    el('a', {class:'md-btn text act', href: PAGES.track, style:'color:inherit'}, 'Track record', icon('ms-chevron_right')));
}
function footer(m, endpoint) { const p = P(m); return el('footer', {}, `Personal research project. Example data from the data catalogue; nothing here is investment advice and nothing trades. as_of ${p.as_of} · cutoff ${p.cutoff} · built_at ${p.built_at} · `, el('code', {}, endpoint.replace('{market}', m))); }
