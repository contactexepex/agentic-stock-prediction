"use client";
// Page 08, Track record (B16; design/mockups/08-track-record): the forecaster's calls scored per basis (never pooled),
// calibration, ranges held, accuracy over time (the weekly series per basis), the signal model's back-test and the
// historical replay, read from GET /api/v1/markets/{market}/track-record (B13's rm.track_record). Paper records only.
import { useState } from "react";
import { PageFooter, PageHead } from "../../../../../components/blocks/page-head.tsx";
import { Segmented } from "../../../../../components/ui/controls.tsx";
import { HelpTip, Icon } from "../../../../../components/ui/icon.tsx";
import { Card, CardHead, Delta, Kpi, KpiRow, Label, PaperTag, Quiet } from "../../../../../components/ui/primitives.tsx";
import { PageState } from "../../../../../components/ui/states.tsx";
import type { Market } from "../../../../../lib/data/constants.ts";
import { PAPER_LABEL } from "../../../../../lib/ui/constants.ts";
import { DASH, fmtDate, fmtDateYear, fmtLocal, pct, signed } from "../../../../../lib/ui/format.ts";
import type { PageBase } from "../../../../../lib/ui/types.ts";
import { usePage } from "../../../../../lib/ui/use-api.ts";
import {
  BASELINE, BASIS_WORDS, calibrationLayout, groupByKey, horizonRows, intervalClass, keyWords, selectedBasis,
  symmetricSpan, tooFew, verdictKind, weeklyOf,
} from "../../../../../lib/strategy-pages/track-record.ts";
import type { BacktestScore, CallBasisBlock, ReliabilityBand, TrackRecordPayload } from "../../../../../lib/strategy-pages/track-record-types.ts";
import { CiBar, useWidth } from "../../_b16/parts.tsx";
import "./track-record.css";

type Payload = PageBase & TrackRecordPayload;

const f3 = (x: number | null | undefined) => (x === null || x === undefined ? DASH : (Math.round(x * 1000) / 1000).toFixed(3));
const f4 = (x: number | null | undefined) => (x === null || x === undefined ? DASH : (Math.round(x * 10000) / 10000).toFixed(4));
const skill = (x: number | null | undefined) => (x === null || x === undefined ? DASH : (x > 0 ? "+" : x < 0 ? "−" : "") + f4(Math.abs(x)));
const tone = (x: number | null | undefined) => (x === null || x === undefined ? "" : x > 0 ? "up" : x < 0 ? "down" : "");
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function FewTag({ min }: { min: number }) {
  return <Label tone="neutral" tip={`Fewer than ${min} calls scored: the numbers are shown but mean little yet.`}>not enough history yet</Label>;
}

export function TrackRecordPage({ market }: { market: Market }) {
  const res = usePage<Payload>(market, "track-record");
  return (
    <div className="p-track">
      <PageState result={res}>{(p) => <TrackRecord p={p} />}</PageState>
    </div>
  );
}

function TrackRecord({ p }: { p: Payload }) {
  const [basisKey, setBasisKey] = useState<string | null>(null);
  const t = p.track;
  const basis = selectedBasis(t.calls, basisKey);
  return (
    <>
      <PageHead page={p} title="Track record" subtitle={`${p.name} · the forecaster’s calls scored per basis, never pooled · as of ${fmtDate(t.as_of, false)} · research only`} />
      <SkillBand p={p} />
      <Kpis p={p} />
      <BasisCard p={p} basis={basis} onBasis={setBasisKey} />
      <div className="grid">
        <CalibrationCard basis={basis} />
        <div className="col">
          <RangesCard p={p} />
          <OverTimeCard p={p} basis={basis} />
        </div>
      </div>
      <BacktestCard p={p} />
      <ReplayCard p={p} />
      <div className="legend2" aria-label="Legend">
        <span><PaperTag label={p.status.paper_label || PAPER_LABEL} /> every call and range is a paper record</span>
        <span><b>Wilson 95% interval</b> where the true hit rate most likely lies given this few calls</span>
        <span><b>Brier</b> 0 perfect, 0.25 coin flip, lower is better</span>
        <span><b>not enough history yet</b> fewer than {t.min_sample} calls</span>
        <span><b>legacy</b> an old scoring window, never pooled with N+k</span>
      </div>
      <PageFooter page={p} endpoint="track-record" />
    </>
  );
}

function SkillBand({ p }: { p: Payload }) {
  const s = p.track.skill, shown = s.state === "shown";
  const review = s.review;
  return (
    <section className={`mb-alert band ${shown ? "success" : "paper"}`} aria-label="Signal model skill">
      <Icon name={shown ? "check" : "info"} />
      <div>
        <b className="t">{s.label}</b>
        <div className="s">
          {review
            ? `From the weekly review ${review.id}, computed ${fmtLocal(review.computed_at, p.market, p.status.session.local_time, true)}; the back-test below says why. Nothing here is advice.`
            : "No weekly review stored by the cut-off. Nothing here is advice."}
        </div>
      </div>
      <HelpTip tip={s.rule} />
    </section>
  );
}

function Kpis({ p }: { p: Payload }) {
  const t = p.track, c = t.calls[0] ?? null, a = c ? c.all : null, min = t.min_sample, shown = t.skill.state === "shown";
  return (
    <KpiRow>
      <Kpi icon="verified_user" tone={shown ? "success" : "paper"} label="Signal model" value={shown ? "Skill shown" : "No proven skill"} tip={t.skill.rule}
        sub={<span className="labs"><PaperTag label={p.status.paper_label || PAPER_LABEL} />{t.skill.review ? ` review ${t.skill.review.id}` : " no review yet"}</span>} />
      <Kpi icon="history" tone="info" label={c ? `Calls scored · ${c.label}` : "Calls scored"} value={a ? String(a.n) : "0"}
        tip={a ? `${a.n} direction calls scored on the ${c!.label} basis, all horizons; ${a.hits} came true. The range ${pct(a.wilson_lo)}–${pct(a.wilson_hi)} is the Wilson 95% interval of the hit rate${tooFew(a.n, min) ? ": with this few calls it is wide" : ""}.` : "No call has been scored yet."}
        sub={a ? <span className="labs">{`${plural(a.hits, "hit")} · ${pct(a.share)} `}{tooFew(a.n, min) ? <FewTag min={min} /> : <Label tone="neutral">{`${pct(a.wilson_lo)}–${pct(a.wilson_hi)}`}</Label>}</span> : "no call scored yet"} />
      <Kpi icon="trending_flat" tone={a && !tooFew(a.n, min) && (a.edge ?? 0) > 0 ? "success" : "neutral"} label="Against always-up"
        value={a && a.edge !== null ? <Delta value={a.edge * 100} decimals={1} unit=" pts" /> : DASH}
        sub={a ? `always-up would have hit ${pct(a.always_up)}` : "no call scored yet"}
        tip="The hit rate minus the share of calls whose stock simply went up (the always-up baseline). Positive means the calls beat a coin that always says up." />
      <Kpi icon="query_stats" tone={a && !tooFew(a.n, min) && (a.scores.brier_skill ?? 0) > 0 ? "success" : "neutral"} label="Brier score"
        value={a ? f3(a.scores.brier) : DASH}
        sub={a ? <span className="labs">{`skill ${skill(a.scores.brier_skill)} vs the base rate · log loss ${f3(a.scores.log_loss)}`}</span> : "no call scored yet"}
        tip="The Brier score is the mean squared error of the stated confidence (0 is perfect, 0.25 is a coin flip). Brier skill compares it with always predicting the base rate: positive is better than the base rate." />
    </KpiRow>
  );
}

function BasisCard({ p, basis, onBasis }: { p: Payload; basis: CallBasisBlock | null; onBasis: (key: string) => void }) {
  const t = p.track, min = t.min_sample;
  const end = t.calls.length > 1
    ? <Segmented label="Scoring basis" value={basis?.key ?? ""} onChange={onBasis} dense={false} light={false} options={t.calls.map((x) => ({ value: x.key, label: x.label }))} />
    : basis ? <span className="muted">{`${basis.label} only: no call on another basis yet`}</span> : undefined;
  return (
    <Card label="Calls by scoring basis">
      <CardHead title="Calls by scoring basis" end={end}
        help={`A direction call is scored on one basis and the bases are never pooled: close→close ${BASIS_WORDS.close_to_close}; open→close ${BASIS_WORDS.open_to_close}. An old window is its own row (legacy) and is never pooled with N+k.`} />
      {t.example_parts.includes("calls") ? (
        <div className="chips2"><span className="ex"><Icon name="info" />example: no call is scored in the stored data yet, so this block is computed from the forecaster’s example calls by the same code</span></div>
      ) : null}
      {!basis ? <Quiet>No direction call has been scored yet.</Quiet> : (
        <>
          <div className="md-table-wrap">
            <table className="md-table tbl x">
              <thead>
                <tr>
                  <th>Horizon</th><th className="num">Calls</th>
                  <th className="num">Hit rate <HelpTip tip="Hits over calls, with its Wilson 95% interval (the thick line); the orange tick is the always-up baseline." /></th>
                  <th className="num c2">Always-up</th>
                  <th className="num c2">Edge <HelpTip tip="Hit rate minus always-up, in points." /></th>
                  <th className="num c3">Mean confidence</th>
                  <th className="num">Brier <HelpTip tip="0 is perfect, 0.25 a coin flip; lower is better." /></th>
                  <th className="num c3">Log loss</th>
                  <th className="num c2">Brier skill <HelpTip tip="Against always predicting the base rate; positive is better." /></th>
                </tr>
              </thead>
              <tbody>
                {horizonRows(basis).map(({ name, legacy, stats: b }) => (
                  <tr key={name} className={tooFew(b.n, min) ? "few" : ""}>
                    <td>
                      <b>{name}</b>
                      {legacy ? <span style={{ marginLeft: 6 }}><Label tone="neutral" tip="An old close-to-close window; never pooled with N+k.">legacy</Label></span> : null}
                      {tooFew(b.n, min) ? <div><FewTag min={min} /></div> : null}
                    </td>
                    <td className="num">{b.n}<small className="muted" style={{ display: "block" }}>{plural(b.hits, "hit")}</small></td>
                    <td className="num"><CiBar lo={b.wilson_lo} hi={b.wilson_hi} point={b.share} mid={0.5} base={b.always_up} text={pct(b.share)}
                      tip={`${b.hits} of ${b.n} came true (${pct(b.share)}); Wilson 95% interval ${pct(b.wilson_lo)}–${pct(b.wilson_hi)}; always-up ${pct(b.always_up)}.`} /></td>
                    <td className="num c2">{pct(b.always_up)}</td>
                    <td className="num c2">{b.edge === null ? DASH : <Delta value={b.edge * 100} decimals={1} unit=" pts" />}</td>
                    <td className="num c3">{pct(b.mean_confidence, 1)}</td>
                    <td className="num">{f3(b.scores.brier)}</td>
                    <td className="num c3">{f3(b.scores.log_loss)}</td>
                    <td className="num c2"><span className={`mb-delta ${tone(b.scores.brier_skill)}`}>{skill(b.scores.brier_skill)}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="note" style={{ marginTop: 10 }}>{`Below ${min} calls a row says "not enough history yet". Scoring basis: ${basis.label}, ${BASIS_WORDS[basis.basis] ?? basis.basis}.`}</p>
        </>
      )}
    </Card>
  );
}

function CalibrationCard({ basis }: { basis: CallBasisBlock | null }) {
  return (
    <Card label="Calibration">
      <CardHead title="Calibration" end={basis ? <span className="muted">{`${basis.label} · all horizons`}</span> : undefined}
        help="Calls are grouped by the confidence they were made with. A well-calibrated forecaster’s dots sit on the dashed diagonal: calls made with 60% confidence come true about 60% of the time. The vertical line is the Wilson 95% interval of each band’s hit rate." />
      {!basis ? <Quiet>No call scored yet, so no calibration.</Quiet> : (
        <>
          <CalibrationChart bands={basis.all.reliability} />
          <div className="md-table-wrap" style={{ marginTop: 10 }}>
            <table className="md-table tbl x">
              <thead><tr><th>Confidence band</th><th className="num">Calls</th><th className="num c2">Mean confidence</th><th className="num">Hit rate <HelpTip tip="With its Wilson 95% interval." /></th></tr></thead>
              <tbody>
                {basis.all.reliability.map((r) => (
                  <tr key={r.bin} className={r.n === 0 ? "few" : ""}>
                    <td><b>{r.bin.replace("-", "–")}</b></td>
                    <td className="num">{r.n}</td>
                    <td className="num c2">{r.n ? pct(r.mean_conf, 1) : DASH}</td>
                    <td className="num">{r.n ? <CiBar lo={r.wilson_lo} hi={r.wilson_hi} point={r.hit_rate} mid={0.5} text={pct(r.hit_rate)}
                      tip={`${plural(r.n, "call")} made with ${r.bin} confidence: hit rate ${pct(r.hit_rate)}, Wilson 95% interval ${pct(r.wilson_lo)}–${pct(r.wilson_hi)}.`} /> : <span className="muted">no calls</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Card>
  );
}

function CalibrationChart({ bands }: { bands: ReliabilityBand[] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  if (!bands.length) return null;
  const f = calibrationLayout(bands, width ?? 480);
  return (
    <div className="cal" ref={ref}>
      <svg viewBox={`0 0 ${f.width} ${f.height}`} width={f.width} height={f.height} role="img" aria-label="Calibration: hit rate per confidence band against the stated confidence">
        <line className="diag" x1={f.x(bands[0].lo)} y1={f.y(bands[0].lo)} x2={f.x(bands[bands.length - 1].hi)} y2={f.y(bands[bands.length - 1].hi)} />
        {bands.map((b) => {
          const cx = b.n && b.mean_conf !== null ? f.x(b.mean_conf) : f.x((b.lo + b.hi) / 2);
          const tip = b.n ? `${b.bin} confidence: ${plural(b.n, "call")}, mean confidence ${pct(b.mean_conf, 1)}, hit rate ${pct(b.hit_rate)} (Wilson ${pct(b.wilson_lo)}–${pct(b.wilson_hi)}).` : `${b.bin} confidence: no calls in this band yet.`;
          return (
            <g key={b.bin}>
              {b.n && b.hit_rate !== null ? (
                <>
                  {b.wilson_lo !== null && b.wilson_hi !== null ? <line className="wil" x1={cx} x2={cx} y1={f.y(b.wilson_lo)} y2={f.y(b.wilson_hi)} /> : null}
                  <circle className="pt" cx={cx} cy={f.y(b.hit_rate)} r={6} />
                  <text className="n" x={cx + 10} y={f.y(b.hit_rate) + 4}>{b.n}</text>
                </>
              ) : <circle className="pt empty" cx={cx} cy={f.y(0)} r={5} />}
              <rect className="hit" x={f.x(b.lo)} y={f.top} width={f.x(b.hi) - f.x(b.lo)} height={f.height - f.top - f.bottom} tabIndex={0} data-tip={tip} aria-label={tip} />
            </g>
          );
        })}
        <g className="grid">{[0, 0.25, 0.5, 0.75, 1].map((v) => <line key={v} x1={f.left} x2={f.width - f.right} y1={f.y(v)} y2={f.y(v)} />)}</g>
        <g className="axis">
          {[0, 0.25, 0.5, 0.75, 1].map((v) => <text key={v} x={f.left - 6} y={f.y(v) + 4} textAnchor="end">{pct(v)}</text>)}
          {bands.map((b) => <text key={b.bin} x={f.x((b.lo + b.hi) / 2)} y={f.height - f.bottom + 16} textAnchor="middle">{b.bin.replace("-", "–")}</text>)}
          <text className="ttl" x={(f.left + f.width - f.right) / 2} y={f.height - 4} textAnchor="middle">stated confidence (band) → share that came true</text>
        </g>
      </svg>
    </div>
  );
}

function RangesCard({ p }: { p: Payload }) {
  const ranges = p.track.ranges;
  return (
    <Card label="Ranges held">
      <CardHead title="Ranges held" help="How often the close at the horizon landed inside the published 50% and 80% ranges, per horizon, with Wilson intervals. A range is scored at its exit session." />
      {!ranges.length ? <Quiet>No range is scored yet: the first published range settles at its exit session. Until then the page shows no range figure.</Quiet> : (
        <div className="md-table-wrap">
          <table className="md-table tbl x">
            <thead><tr><th>Horizon</th><th className="num">Ranges</th><th className="num">Inside 50%</th><th className="num">Inside 80%</th></tr></thead>
            <tbody>
              {ranges.map((r, i) => (
                <tr key={r.key ?? r.name ?? i}>
                  <td><b>{r.name ?? r.key}</b></td>
                  <td className="num">{r.n}</td>
                  <td className="num">{r.hit50 ? <CiBar lo={r.hit50.wilson_lo} hi={r.hit50.wilson_hi} point={r.hit50.share} mid={0.5} text={pct(r.hit50.share)} /> : DASH}</td>
                  <td className="num">{r.hit80 ? <CiBar lo={r.hit80.wilson_lo} hi={r.hit80.wilson_hi} point={r.hit80.share} mid={0.8} text={pct(r.hit80.share)} /> : DASH}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/** The weekly series of the selected basis (B13's `weekly`, one series per basis key, never pooled). */
function OverTimeCard({ p, basis }: { p: Payload; basis: CallBasisBlock | null }) {
  const series = weeklyOf(p.weekly, basis?.key ?? null);
  const min = p.track.min_sample;
  return (
    <Card label="Accuracy over time">
      <CardHead title="Accuracy over time" end={series ? <span className="muted">{series.label}</span> : undefined}
        help="The hit rate and Brier score per ISO week of the calls’ target date, on the selected basis only (bases are never pooled), so a change in the forecaster shows as a change from week to week. A week with few calls has a wide interval." />
      {!series || !series.weeks.length ? (
        <Quiet>{basis ? `No week of ${basis.label} calls scored yet.` : "No call scored yet, so no weekly series."}</Quiet>
      ) : (
        <div className="md-table-wrap">
          <table className="md-table tbl x wk">
            <thead><tr><th>Week</th><th className="num">Calls</th><th className="num">Hit rate</th><th className="num">Brier</th><th className="num c2">Log loss</th></tr></thead>
            <tbody>
              {series.weeks.map((w) => (
                <tr key={w.week} className={tooFew(w.n, min) ? "few" : ""}>
                  <td><b>{w.week}</b></td>
                  <td className="num">{w.n}<small className="muted" style={{ display: "block" }}>{plural(w.hits, "hit")}</small></td>
                  <td className="num"><CiBar lo={w.wilson_lo} hi={w.wilson_hi} point={w.share} mid={0.5} text={pct(w.share)}
                    tip={`${w.week}: ${w.hits} of ${w.n} came true (${pct(w.share)}); Wilson 95% interval ${pct(w.wilson_lo)}–${pct(w.wilson_hi)}.`} /></td>
                  <td className="num">{f3(w.brier)}</td>
                  <td className="num c2">{f3(w.log_loss)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function SkillTag({ r }: { r: BacktestScore }) {
  return <Label tone={r.skill ? "success" : "neutral"} icon={r.skill ? "check" : "close"}>{r.skill ? "skill shown" : "no skill shown"}</Label>;
}

function BacktestCard({ p }: { p: Payload }) {
  const b = p.track.backtest, lt = p.status.session.local_time;
  const head = (
    <CardHead title="Signal model back-test" end={b ? <span className="muted">{`computed ${fmtLocal(b.computed_at, p.market, lt, true)}`}</span> : undefined}
      help="The weekly review’s walk-forward test of the signal model on the stored history: each month’s model is fitted on the past and scored on the next month, never on what it saw. Not live, and not a paper trade." />
  );
  if (!b) return <Card label="Signal model back-test">{head}<Quiet>No back-test of the signal model stored by the cut-off.</Quiet></Card>;
  const d = b.data;
  return (
    <Card label="Signal model back-test">
      {head}
      <p className="verd"><b>Verdict. </b>{b.verdict}</p>
      <div className="kv">
        <div><div className="l">Companies</div><div className="v">{d.tickers}</div></div>
        <div><div className="l">Bars from</div><div className="v">{fmtDateYear(d.first_bar)}</div></div>
        <div><div className="l">Scored days</div><div className="v">{`${fmtDateYear(d.first_panel_date)} – ${fmtDateYear(d.last_panel_date)}`}</div></div>
        <div><div className="l">Rows</div><div className="v">{d.panel_rows.toLocaleString("en-US")}</div></div>
        <div data-tip="The round-trip (buy and sell) cost in percent at a price of 100, taken off every back-test position."><div className="l">Round-trip cost</div><div className="v">{`${d.round_trip_cost_pct_at_100}%`}</div></div>
      </div>
      <h3 className="sub2">Scores</h3>
      <div className="md-table-wrap">
        <table className="md-table tbl x">
          <thead>
            <tr>
              <th>Horizon · basis</th>
              <th className="num c2">Rows <HelpTip tip="Company-days scored, and the number of days." /></th>
              <th className="num">Brier <HelpTip tip="Against the Brier of always predicting the base rate (its own column on wide screens, in each row’s tooltip otherwise); skill = the gap, positive is better." /></th>
              <th className="num c3">Base rate</th><th className="num">Skill</th>
              <th className="num">AUC <HelpTip tip="Area under the curve: 0.5 is no ranking ability, 1 is perfect. The line is its 95% interval; skill needs the whole interval above 0.5." /></th>
              <th className="cw">Skill shown</th>
            </tr>
          </thead>
          <tbody>
            {b.scores.map((r) => (
              <tr key={r.key}>
                <td><b>{keyWords(r.key)}</b><small className="ph"><SkillTag r={r} /></small></td>
                <td className="num c2">{r.n.toLocaleString("en-US")}<small className="muted" style={{ display: "block" }}>{`${r.dates} days`}</small></td>
                <td className="num" data-tip={`Brier ${f4(r.brier)} against ${f4(r.brier_base_rate)} for always predicting the base rate, on ${r.n.toLocaleString("en-US")} rows over ${r.dates} days.`}>{f4(r.brier)}</td>
                <td className="num c3">{f4(r.brier_base_rate)}</td>
                <td className="num"><span className={`mb-delta ${tone(r.brier_skill)}`}>{skill(r.brier_skill)}</span></td>
                <td className="num"><CiBar lo={r.auc95[0]} hi={r.auc95[1]} point={r.auc} min={0.4} max={0.6} mid={0.5} text={f3(r.auc)} cls={intervalClass(r.auc95[0], r.auc95[1], 0.5)}
                  tip={`AUC ${f4(r.auc)}, 95% interval ${f4(r.auc95[0])}–${f4(r.auc95[1])} (axis 0.40–0.60).`} /></td>
                <td className="cw"><SkillTag r={r} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3 className="sub2" style={{ marginTop: 12 }}>Paper long against the baselines</h3>
      <div className="md-table-wrap" style={{ marginTop: 12 }}>
        <table className="md-table tbl x">
          <thead>
            <tr>
              <th>Baseline</th><th className="num c2">Bar</th><th className="num c2">Positions</th><th className="num c3">Days</th>
              <th className="num">Mean per entry date <HelpTip tip="The model’s paper long minus the baseline: the return over the whole window (1 or 5 sessions), averaged per entry date, in percent, with its 95% interval; the dashed tick is zero." /></th>
              <th className="cw">Verdict</th>
            </tr>
          </thead>
          <tbody>
            {groupByKey(b.strategy).map(([key, rows]) => [
              <tr key={key} className="grp"><td colSpan={6}><b>{keyWords(key)}</b><small> · the model’s paper long (buy when the chance clears the bar) against each baseline</small></td></tr>,
              ...rows.map((r, i) => {
                const lo = r.ci95_pct ? r.ci95_pct[0] : null, hi = r.ci95_pct ? r.ci95_pct[1] : null, span = symmetricSpan(lo, hi, r.mean_pct);
                const verdict = <Label tone={verdictKind(r.verdict)}>{r.verdict}</Label>;
                const bar = pct(Number(r.threshold));
                return (
                  <tr key={`${key}-${i}`} className={r.positions ? "" : "few"}>
                    <td><b>{BASELINE[r.baseline] ?? r.baseline}</b><small className="ph">{`bar ${bar} · `}{verdict}</small></td>
                    <td className="num c2">{bar}</td>
                    <td className="num c2">{r.positions}</td>
                    <td className="num c3">{r.dates}</td>
                    <td className="num">{r.mean_pct === null ? DASH : <CiBar lo={lo} hi={hi} point={r.mean_pct} min={-span} max={span} mid={0} text={signed(r.mean_pct)} cls={intervalClass(lo, hi, 0)}
                      tip={lo !== null ? `Mean ${signed(r.mean_pct)} per entry date over the window, 95% interval ${signed(lo)} to ${signed(hi)}.` : `Mean ${signed(r.mean_pct)} per entry date over the window; no interval.`} />}</td>
                    <td className="cw">{verdict}</td>
                  </tr>
                );
              }),
            ])}
          </tbody>
        </table>
      </div>
      <p className="note" style={{ marginTop: 10 }}>{`Reliability of the back-test: ${b.reliability && Object.keys(b.reliability).length ? "stored with the run" : "no bands stored in this run"}. Source file of the run: ${b.json}.`}</p>
    </Card>
  );
}

function ReplayCard({ p }: { p: Payload }) {
  return (
    <Card label="Historical replay">
      <CardHead title="Historical replay" end={<Label tone="neutral">not live</Label>}
        help="A rule-only replay re-runs the range formula and the direction baselines on past days (no AI). It is a test, never a live record, and is shown apart." />
      <Quiet>{p.track.replay ? "A replay is stored; its headline numbers are kept apart from the live record." : "No rule-only replay stored by the cut-off."}</Quiet>
    </Card>
  );
}

