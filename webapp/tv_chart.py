"""TradingView Lightweight Charts로 대화형 캔들 차트를 만든다. Streamlit에 의존하지 않는다."""

from __future__ import annotations

import json
import os
from typing import Optional

import pandas as pd

VENDOR_JS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "lightweight-charts.standalone.production.js")
CHART_HEIGHT = 640
MA_COLORS = {
    "ma5": "#f59e0b",
    "ma10": "#ef4444",
    "ma20": "#14b8a6",
    "ma120": "#3b82f6",
    "ma180": "#64748b",
    "ma240": "#22c55e",
}
UP_COLOR = "#e53935"
DOWN_COLOR = "#1e63d0"

LIGHT_THEME = {
    "background": "#ffffff",
    "text": "#14213d",
    "grid": "#eeece5",
    "border": "#dddbd2",
    "guide": "#14213d",
    "up": UP_COLOR,
    "down": DOWN_COLOR,
}
DARK_THEME = {
    "background": "#0d1117",
    "text": "#e6edf3",
    "grid": "#21262d",
    "border": "#30363d",
    "guide": "#e6edf3",
    "up": "#f85149",
    "down": "#58a6ff",
}


def build_payload(
    df: pd.DataFrame,
    target_date: pd.Timestamp,
    title: str,
    visible_bars: int,
    price_lines: Optional[list[dict]] = None,
    marker_date: Optional[pd.Timestamp] = None,
) -> dict:
    """기준일까지의 봉만 넣는다. 복기할 때 이후 시세가 보이지 않도록 하기 위함이다."""
    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date")
    work = work[work["date"] <= pd.to_datetime(target_date)].reset_index(drop=True)
    if work.empty:
        raise ValueError("입력한 날짜 이전 데이터가 없습니다.")

    times = work["date"].dt.strftime("%Y-%m-%d")
    candles = [
        {"time": t, "open": float(o), "high": float(h), "low": float(l), "close": float(c)}
        for t, o, h, l, c in zip(times, work["open"], work["high"], work["low"], work["close"])
    ]
    volumes = []
    if "volume" in work.columns:
        volumes = [
            {"time": t, "value": float(v), "rising": bool(c >= o)}
            for t, v, c, o in zip(times, work["volume"].fillna(0), work["close"], work["open"])
        ]
    moving_averages = {}
    for column, color in MA_COLORS.items():
        if column not in work.columns:
            continue
        points = work[[column]].assign(time=times).dropna(subset=[column])
        if not points.empty:
            moving_averages[column.upper()] = {
                "color": color,
                "data": [{"time": t, "value": float(v)} for t, v in zip(points["time"], points[column])],
            }

    markers = []
    if marker_date is not None:
        earlier = work[work["date"] <= pd.to_datetime(marker_date)]
        if not earlier.empty:
            markers.append({"time": earlier["date"].iloc[-1].strftime("%Y-%m-%d"), "text": "기준"})

    return {
        "title": title,
        "anchor": work["date"].iloc[-1].strftime("%Y-%m-%d"),
        "candles": candles,
        "volumes": volumes,
        "moving_averages": moving_averages,
        "visible_bars": int(visible_bars),
        "price_lines": price_lines or [],
        "markers": markers,
    }


def _json_for_script(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def render_html(payload: dict, height: int = CHART_HEIGHT, theme: Optional[dict] = None) -> str:
    theme = theme or LIGHT_THEME
    with open(VENDOR_JS, encoding="utf-8") as f:
        library = f.read()
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>
html, body {{ margin: 0; height: 100%; background: {theme["background"]}; font-family: "Pretendard Variable", "Malgun Gothic", sans-serif; }}
#chart {{ position: relative; width: 100%; height: {height}px; }}
#legend {{ position: absolute; top: 6px; left: 8px; z-index: 3; font-size: 12px; line-height: 1.5; color: {theme["text"]}; pointer-events: none; max-width: calc(100% - 100px); }}
#legend b {{ font-size: 13px; font-weight: 600; }}
#legend span {{ margin-right: 8px; white-space: nowrap; display: inline-block; }}
</style></head><body><div id="chart"><div id="legend"></div></div>
<script>{library}</script>
<script>
const P = {_json_for_script(payload)};
const T = {_json_for_script(theme)};
const L = LightweightCharts;
const container = document.getElementById("chart");
const legend = document.getElementById("legend");
const chart = L.createChart(container, {{
  autoSize: true,
  layout: {{ background: {{ color: T.background }}, textColor: T.text, attributionLogo: true, panes: {{ separatorColor: T.border }} }},
  grid: {{ vertLines: {{ color: T.grid }}, horzLines: {{ color: T.grid }} }},
  crosshair: {{ mode: L.CrosshairMode.Normal }},
  rightPriceScale: {{ borderColor: T.border }},
  timeScale: {{ borderColor: T.border, rightOffset: 3 }},
  localization: {{ priceFormatter: p => p.toLocaleString("ko-KR", {{ maximumFractionDigits: 2 }}) }},
}});
const candles = chart.addSeries(L.CandlestickSeries, {{
  upColor: T.up, downColor: T.down, wickUpColor: T.up, wickDownColor: T.down, borderVisible: false,
}});
candles.setData(P.candles);
const maSeries = {{}};
for (const [name, ma] of Object.entries(P.moving_averages)) {{
  const line = chart.addSeries(L.LineSeries, {{ color: ma.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }});
  line.setData(ma.data);
  maSeries[name] = {{ line, color: ma.color, last: ma.data[ma.data.length - 1] }};
}}
let volumeSeries = null;
if (P.volumes.length) {{
  volumeSeries = chart.addSeries(L.HistogramSeries, {{ priceFormat: {{ type: "volume" }}, priceLineVisible: false, lastValueVisible: false }}, 1);
  volumeSeries.setData(P.volumes.map(v => ({{ time: v.time, value: v.value, color: v.rising ? T.up : T.down }})));
  chart.panes()[0].setStretchFactor(4);
  chart.panes()[1].setStretchFactor(1);
}}
for (const item of P.price_lines) {{
  candles.createPriceLine({{ price: item.price, color: item.color || T.guide, lineWidth: 1, lineStyle: L.LineStyle.Solid, axisLabelVisible: true, title: item.title || "" }});
}}
if (P.markers.length) {{
  L.createSeriesMarkers(candles, P.markers.map(m => ({{ time: m.time, position: "aboveBar", color: T.guide, shape: "arrowDown", text: m.text }})));
}}
const fmt = v => v === undefined || v === null ? "-" : v.toLocaleString("ko-KR", {{ maximumFractionDigits: 2 }});
const addSpan = (text, color) => {{
  const span = document.createElement("span");
  span.textContent = text;
  if (color) span.style.color = color;
  legend.appendChild(span);
}};
function showLegend(bar, volume, maValue) {{
  legend.textContent = "";
  const title = document.createElement("b");
  title.textContent = P.title;
  legend.appendChild(title);
  legend.appendChild(document.createElement("br"));
  if (bar) {{
    const up = bar.close >= bar.open;
    addSpan(String(bar.time));
    addSpan("시 " + fmt(bar.open));
    addSpan("고 " + fmt(bar.high));
    addSpan("저 " + fmt(bar.low));
    addSpan("종 " + fmt(bar.close), up ? T.up : T.down);
    addSpan("거래량 " + fmt(volume));
    legend.appendChild(document.createElement("br"));
  }}
  for (const [name, item] of Object.entries(maSeries)) {{
    addSpan(name + " " + fmt(maValue(name, item)), item.color);
  }}
}}
const lastBar = P.candles[P.candles.length - 1];
const lastVolume = P.volumes.length ? P.volumes[P.volumes.length - 1].value : null;
const showLast = () => showLegend(lastBar, lastVolume, (name, item) => item.last.value);
showLast();
chart.subscribeCrosshairMove(param => {{
  const bar = param.time ? param.seriesData.get(candles) : null;
  if (!bar) {{ showLast(); return; }}
  const vol = volumeSeries ? param.seriesData.get(volumeSeries) : null;
  showLegend(bar, vol ? vol.value : null, (name, item) => {{
    const point = param.seriesData.get(item.line);
    return point ? point.value : null;
  }});
}});
const count = P.candles.length;
// iframe 크기가 잡히기 전에 구간을 지정하면 전체 기간으로 펼쳐지므로, 크기가 잡힌 뒤 처음 한 번만 적용한다.
let rangeApplied = false;
const applyInitialRange = () => {{
  if (rangeApplied || container.clientWidth === 0) return;
  rangeApplied = true;
  requestAnimationFrame(() => chart.timeScale().setVisibleLogicalRange({{ from: Math.max(0, count - P.visible_bars), to: count + 2 }}));
}};
new ResizeObserver(applyInitialRange).observe(container);
applyInitialRange();
</script></body></html>"""
