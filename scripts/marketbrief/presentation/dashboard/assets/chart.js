/* Price chart of the stock view: TradingView Lightweight Charts candlesticks and volume, span buttons, and the
   published 50%/80% ranges of the next session and 5 days drawn as a fan from the as-of close (edges as line
   series, the bands filled by an SVG overlay that follows the chart's own coordinates). */
(function (MB) {
  'use strict';
  var LW = window.LightweightCharts, C = MB.colours;

  function minusDays(iso, n) {
    var p = iso.split('-').map(Number), t = new Date(Date.UTC(p[0], p[1] - 1, p[2] - n));
    return t.toISOString().slice(0, 10);
  }

  function fanPoints(c, lastDay) {
    var rs = (c.ranges || []).filter(function (r) { return r.target_date > lastDay; }).sort(function (a, b) { return a.h - b.h; });
    if (!rs.length) return null;
    var start = { time: lastDay, base: rs[0].base_close };
    return { late: rs.every(function (r) { return r.late; }), rows: rs, start: start };
  }

  function edgeSeries(chart, fan, key, colour, style) {
    var s = chart.addSeries(LW.LineSeries, { color: colour, lineWidth: 1, lineStyle: style, lastValueVisible: false,
      priceLineVisible: false, crosshairMarkerVisible: false, pointMarkersVisible: true, pointMarkersRadius: 2 });
    s.setData([{ time: fan.start.time, value: fan.start.base }].concat(fan.rows.map(function (r) { return { time: r.target_date, value: r[key] }; })));
    return s;
  }

  function drawFan(svg, chart, series, fan, colour) {
    var w = svg.clientWidth, h = svg.clientHeight, ts = chart.timeScale();
    svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
    function pt(time, price) {
      var x = ts.timeToCoordinate(time), y = series.priceToCoordinate(price);
      return x == null || y == null ? null : [x, y];
    }
    function band(lo, hi, fill) {
      var top = [pt(fan.start.time, fan.start.base)], bottom = [];
      fan.rows.forEach(function (r) { top.push(pt(r.target_date, r[hi])); bottom.unshift(pt(r.target_date, r[lo])); });
      var all = top.concat(bottom);
      if (all.some(function (p) { return !p; })) return '';
      return '<polygon points="' + all.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ') + '" fill="' + fill + '"/>';
    }
    var a80 = fan.late ? 'rgba(137,135,129,.14)' : 'rgba(74,58,167,.10)', a50 = fan.late ? 'rgba(137,135,129,.26)' : 'rgba(74,58,167,.22)';
    var paneWidth = w - (chart.priceScale('right').width() || 0);
    svg.innerHTML = '<defs><clipPath id="pane-clip"><rect x="0" y="0" width="' + Math.max(0, paneWidth) + '" height="' + h + '"/></clipPath></defs><g clip-path="url(#pane-clip)">' +
      band('lo80', 'hi80', a80) + band('lo50', 'hi50', a50) + '</g>';
    svg.style.color = colour;
  }

  MB.mountChart = function (box, c, spanKey, onHover) {
    var old = MB.chart();
    if (old) old.remove();
    box.innerHTML = '<div class="lw"></div><svg class="fan" aria-hidden="true"></svg>';
    var el = box.querySelector('.lw'), svg = box.querySelector('svg.fan');
    var chart = LW.createChart(el, {
      autoSize: true,
      layout: { background: { type: 'solid', color: '#ffffff' }, textColor: '#52514e', fontSize: 11,
        fontFamily: getComputedStyle(document.body).fontFamily },
      grid: { vertLines: { color: '#f1f2f4' }, horzLines: { color: '#f1f2f4' } },
      rightPriceScale: { borderColor: '#c3c2b7' },
      timeScale: { borderColor: '#c3c2b7', rightOffset: 3, fixLeftEdge: false },
      crosshair: { mode: LW.CrosshairMode.Normal },
      localization: { locale: MB.locale, priceFormatter: function (p) { return MB.num(p); } }
    });
    var bars = c.bars.filter(function (b) { return MB.isNum(b[1]) && MB.isNum(b[4]); });
    var lastDay = bars.length ? bars[bars.length - 1][0] : null;
    var targets = (c.ranges || []).map(function (r) { return r.target_date; }).filter(function (d) { return lastDay && d > lastDay; });
    var lastTarget = targets.sort()[targets.length - 1];
    // empty slots for the sessions up to the last target, so the fan spans its real number of sessions
    var future = ((MB.D.plan || {}).sessions || []).filter(function (d) { return lastTarget && d > lastDay && d <= lastTarget; })
      .concat(targets).sort().filter(function (d, i, a) { return a.indexOf(d) === i; });
    var candles = chart.addSeries(LW.CandlestickSeries, { upColor: C.UP, downColor: C.DOWN, borderUpColor: C.UP, borderDownColor: C.DOWN,
      wickUpColor: C.UP, wickDownColor: C.DOWN, priceLineVisible: false });
    candles.setData(bars.map(function (b) { return { time: b[0], open: b[1], high: b[2], low: b[3], close: b[4] }; })
      .concat(future.map(function (d) { return { time: d }; })));
    candles.priceScale().applyOptions({ scaleMargins: { top: 0.06, bottom: 0.24 } });
    var volume = chart.addSeries(LW.HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: 'vol', lastValueVisible: false, priceLineVisible: false });
    volume.setData(bars.filter(function (b) { return MB.isNum(b[5]); }).map(function (b) {
      return { time: b[0], value: b[5], color: b[4] >= b[1] ? 'rgba(42,120,214,.35)' : 'rgba(227,73,72,.35)' };
    }));
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    var fan = lastDay ? fanPoints(c, lastDay) : null, colour = fan && fan.late ? C.LATE : C.BAND;
    if (fan) {
      edgeSeries(chart, fan, 'hi80', colour, 2); edgeSeries(chart, fan, 'lo80', colour, 2);
      edgeSeries(chart, fan, 'hi50', colour, 0); edgeSeries(chart, fan, 'lo50', colour, 0);
    }
    var frame = 0;
    function redraw() {
      if (!fan) { svg.innerHTML = ''; return; }
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(function () { requestAnimationFrame(function () { drawFan(svg, chart, candles, fan, colour); }); });
    }
    chart.timeScale().subscribeVisibleLogicalRangeChange(redraw);
    chart.timeScale().subscribeSizeChange(redraw);
    chart.subscribeCrosshairMove(function (param) {
      var d = param && param.time ? param.seriesData.get(candles) : null;
      onHover(d && MB.isNum(d.open) ? d : null, param && param.time);
    });
    MB.setChart(chart, redraw);
    MB.setSpan(spanKey, lastDay, future);
    return { lastDay: lastDay, fan: fan };
  };

  MB.setSpan = function (spanKey, lastDay, future) {
    var chart = MB.chart();
    if (!chart || !lastDay) return;
    var span = MB.D.spans.filter(function (s) { return s.key === spanKey; })[0] || MB.D.spans[0];
    var end = future && future.length ? future[future.length - 1] : lastDay;
    chart.timeScale().setVisibleRange({ from: minusDays(lastDay, span.days), to: end });
  };
})(window.MB);
