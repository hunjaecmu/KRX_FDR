# chart_viewer.py

from __future__ import annotations

import os
import re
import warnings
from html import escape
from typing import Optional

import pandas as pd
import matplotlib as mpl
from matplotlib import font_manager

from config import (
    OUTPUT_DIR,
    CHART_LOOKBACK_WEEKLY,
    CHART_LOOKBACK_MONTHLY,
    SHOW_CHART,
    SAVE_CHART,
)
from data_loader import load_weekly, load_monthly

# batch 모드에서는 GUI 백엔드를 쓰지 않아 tkinter 종료 오류를 방지한다.
if not SHOW_CHART:
    mpl.use("Agg")

import matplotlib.pyplot as plt
import mplfinance as mpf


_FONT_CONFIGURED = False
_SELECTED_FONT: Optional[str] = None

DEFAULT_MA_COLS = ["ma5", "ma10", "ma20", "ma120", "ma180", "ma240"]
LOOKBACK_RATIO = 2 / 3

BASE_MA_WIDTH = 1.2
HIGHLIGHT_MULTIPLIER = 1.5
HIGHLIGHT_MULTIPLIER_MA10 = 2.0

MA_LINE_COLORS = {
    "ma5": "#f59e0b",
    "ma10": "#ef4444",
    "ma20": "#14b8a6",
    "ma120": "#3b82f6",
    "ma180": "#64748b",
    "ma240": "#22c55e",
}

CASE_META = {
    "weekly_ma10_breakout": {
        "label": "주봉 10이평 돌파",
        "timeframe": "weekly",
        "ma_cols": ["ma10"],
        "lookback": CHART_LOOKBACK_WEEKLY,
    },
    "weekly_ma240_breakout": {
        "label": "주봉 240이평 돌파",
        "timeframe": "weekly",
        "ma_cols": ["ma240"],
        "lookback": CHART_LOOKBACK_WEEKLY,
    },
    "monthly_ma10_breakout": {
        "label": "월봉 10이평 돌파",
        "timeframe": "monthly",
        "ma_cols": ["ma10"],
        "lookback": CHART_LOOKBACK_MONTHLY,
    },
    "monthly_ma120_breakout": {
        "label": "월봉 120이평 돌파",
        "timeframe": "monthly",
        "ma_cols": ["ma120"],
        "lookback": CHART_LOOKBACK_MONTHLY,
    },
    "monthly_ma180_breakout": {
        "label": "월봉 180이평 돌파",
        "timeframe": "monthly",
        "ma_cols": ["ma180"],
        "lookback": CHART_LOOKBACK_MONTHLY,
    },
    "monthly_ma240_breakout": {
        "label": "월봉 240이평 돌파",
        "timeframe": "monthly",
        "ma_cols": ["ma240"],
        "lookback": CHART_LOOKBACK_MONTHLY,
    },
}


def _configure_plot_font() -> None:
    global _FONT_CONFIGURED
    global _SELECTED_FONT

    if _FONT_CONFIGURED:
        return

    preferred_font_files = [
        r"C:\Windows\Fonts\malgun.ttf",
        r"C:\Windows\Fonts\NanumGothic.ttf",
    ]
    preferred_fonts = [
        "Malgun Gothic",
        "NanumGothic",
        "Noto Sans CJK KR",
        "AppleGothic",
    ]

    for font_path in preferred_font_files:
        if os.path.exists(font_path):
            try:
                font_manager.fontManager.addfont(font_path)
                _SELECTED_FONT = font_manager.FontProperties(fname=font_path).get_name()
                break
            except Exception:
                pass

    available_fonts = {f.name for f in font_manager.fontManager.ttflist}

    if _SELECTED_FONT is None:
        for font_name in preferred_fonts:
            if font_name in available_fonts:
                _SELECTED_FONT = font_name
                break

    if _SELECTED_FONT is not None:
        mpl.rcParams["font.family"] = [_SELECTED_FONT, "DejaVu Sans"]
        mpl.rcParams["font.sans-serif"] = [_SELECTED_FONT, "DejaVu Sans"]
        print(f"[CHART][FONT] using font: {_SELECTED_FONT}")
    else:
        print("[CHART][FONT][WARN] Korean-capable font not found; Hangul may be broken.")

    mpl.rcParams["axes.unicode_minus"] = False
    _FONT_CONFIGURED = True


def _safe_filename(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]', "_", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _validate_ohlcv_columns(df: pd.DataFrame) -> None:
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"차트용 필수 컬럼 누락: {missing}")


def _prepare_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    _validate_ohlcv_columns(df)

    work = df.copy()
    work["date"] = pd.to_datetime(work["date"])
    work = work.sort_values("date").set_index("date")

    work = work.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume",
    })

    return work


def _load_chart_data(code: str, timeframe: str) -> pd.DataFrame:
    if timeframe == "weekly":
        return load_weekly(code)
    if timeframe == "monthly":
        return load_monthly(code)
    raise ValueError("timeframe must be 'weekly' or 'monthly'")


def _effective_lookback(lookback: int, actual_len: int) -> int:
    reduced = max(1, int(lookback * LOOKBACK_RATIO))
    return min(actual_len, reduced)


def _build_addplots(
    plot_df: pd.DataFrame,
    highlight_ma_cols: list[str],
    timeframe: Optional[str] = None,
) -> list:
    addplots = []
    highlight_set = set(highlight_ma_cols or [])

    ma_cols = list(DEFAULT_MA_COLS)

    for ma_col in ma_cols:
        if ma_col not in plot_df.columns:
            continue

        series = pd.to_numeric(plot_df[ma_col], errors="coerce")
        if series.notna().sum() == 0:
            continue

        width = BASE_MA_WIDTH
        if ma_col in highlight_set:
            if ma_col == "ma10":
                width = BASE_MA_WIDTH * HIGHLIGHT_MULTIPLIER_MA10
            else:
                width = BASE_MA_WIDTH * HIGHLIGHT_MULTIPLIER

        line_color = MA_LINE_COLORS.get(ma_col)

        addplots.append(
            mpf.make_addplot(
                series,
                panel=0,
                label=ma_col.upper(),
                width=width,
                color=line_color,
            )
        )

    return addplots


def _make_title(
    code: str,
    name: str,
    timeframe: str,
    title_suffix: str = "",
    breakout_strength: Optional[float] = None,
    latest_data_date: Optional[pd.Timestamp] = None,
    latest_asof_time: Optional[str] = None,
    latest_price_status: Optional[str] = None,
) -> str:
    tf_map = {
        "weekly": "주봉",
        "monthly": "월봉",
    }
    tf_label = tf_map.get(timeframe, timeframe)

    breakout_map = {
        "weekly_ma10_breakout": "10MA 돌파",
        "weekly_ma240_breakout": "240MA 돌파",
        "monthly_ma10_breakout": "10MA 돌파",
        "monthly_ma120_breakout": "120MA 돌파",
        "monthly_ma180_breakout": "180MA 돌파",
        "monthly_ma240_breakout": "240MA 돌파",
    }
    breakout_label = breakout_map.get(title_suffix, "")

    strength_label = ""
    if breakout_strength is not None:
        strength_label = f"▲{breakout_strength * 100:.2f}%"

    date_time_label = ""
    if latest_data_date is not None:
        dt = pd.to_datetime(latest_data_date)
        weekday_map = {
            0: "월",
            1: "화",
            2: "수",
            3: "목",
            4: "금",
            5: "토",
            6: "일",
        }
        weekday = weekday_map[dt.weekday()]

        if latest_asof_time and pd.notna(latest_asof_time):
            date_time_label = dt.strftime(f"%Y-%m-%d ({weekday})") + f" {latest_asof_time}"
        else:
            date_time_label = dt.strftime(f"%Y-%m-%d ({weekday})")

    parts = [f"{code} {name}", tf_label]

    if breakout_label:
        if strength_label:
            parts.append(f"{breakout_label} {strength_label}")
        else:
            parts.append(breakout_label)

    if date_time_label:
        parts.append(date_time_label)

    if latest_price_status and pd.notna(latest_price_status):
        parts.append(str(latest_price_status))

    return " | ".join(parts)


def _make_save_path(
    code: str,
    name: str,
    timeframe: str,
    title_suffix: str = "",
    save_dir: Optional[str] = None,
) -> str:
    target_dir = save_dir if save_dir else OUTPUT_DIR
    _ensure_dir(target_dir)

    safe_name = _safe_filename(name)
    safe_suffix = _safe_filename(title_suffix) if title_suffix else "chart"

    return os.path.join(
        target_dir,
        f"{code}_{safe_name}_{timeframe}_{safe_suffix}.png"
    )


def _format_value(v) -> Optional[str]:
    if v is None or pd.isna(v):
        return None
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)


def _add_last_bar_info_box(main_ax, plot_df: pd.DataFrame, timeframe: Optional[str] = None) -> None:
    if plot_df.empty:
        return

    last_row = plot_df.iloc[-1]
    lines = []

    close_val = _format_value(last_row.get("close"))
    if close_val is not None:
        lines.append(f"종가   {close_val}")

    ma5_val = _format_value(last_row.get("ma5"))
    if ma5_val is not None:
        lines.append(f"5이평  {ma5_val}")

    ma10_val = _format_value(last_row.get("ma10"))
    if ma10_val is not None:
        lines.append(f"10이평 {ma10_val}")

    ma20_val = _format_value(last_row.get("ma20"))
    if ma20_val is not None:
        lines.append(f"20이평 {ma20_val}")

    ma120_val = _format_value(last_row.get("ma120"))
    if ma120_val is not None:
        lines.append(f"120이평 {ma120_val}")

    ma180_val = _format_value(last_row.get("ma180"))
    if ma180_val is not None:
        lines.append(f"180이평 {ma180_val}")

    ma240_val = _format_value(last_row.get("ma240"))
    if ma240_val is not None:
        lines.append(f"240이평 {ma240_val}")

    if not lines:
        return

    text = "\n".join(lines)

    main_ax.text(
        0.985,
        0.985,
        text,
        transform=main_ax.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
    )


def _calc_visible_volume_pct(plot_df: pd.DataFrame) -> Optional[float]:
    if plot_df is None or plot_df.empty or "volume" not in plot_df.columns:
        return None

    volume = pd.to_numeric(plot_df["volume"], errors="coerce").fillna(0)
    if volume.empty:
        return None

    max_volume = float(volume.max())
    if max_volume <= 0:
        return None

    last_volume = float(volume.iloc[-1])
    return (last_volume / max_volume) * 100.0


def _apply_custom_xaxis_labels(axes, dates: pd.Index, timeframe: Optional[str] = None) -> None:
    if not axes or dates is None or len(dates) == 0:
        return

    bottom_ax = axes[-1]
    ticks: list[float] = []
    labels: list[str] = []

    prev_year = None
    prev_month = None
    monthly_tick_months = {1, 3, 6, 9}

    for i, dt in enumerate(pd.to_datetime(dates)):
        year = int(dt.year)
        month = int(dt.month)

        if prev_year is None or year != prev_year:
            ticks.append(float(i))
            labels.append(str(year))
        elif prev_month is None or month != prev_month:
            if timeframe == "monthly":
                if month in monthly_tick_months:
                    ticks.append(float(i))
                    labels.append(f"{month:02d}")
            else:
                ticks.append(float(i))
                labels.append(f"{month:02d}")

        prev_year = year
        prev_month = month

    last_i = float(len(dates) - 1)
    last_label = pd.to_datetime(dates[-1]).strftime("%Y-%m-%d")

    try:
        idx = ticks.index(last_i)
        labels[idx] = last_label
    except ValueError:
        ticks.append(last_i)
        labels.append(last_label)

    last_dt = pd.to_datetime(dates[-1])
    filtered_ticks: list[float] = []
    filtered_labels: list[str] = []
    for t, lbl in zip(ticks, labels):
        tick_dt = pd.to_datetime(dates[int(round(t))])
        is_month_label = bool(re.fullmatch(r"\d{2}", str(lbl)))
        in_last_label_month = (
            tick_dt.year == last_dt.year and tick_dt.month == last_dt.month
        )
        if is_month_label and in_last_label_month:
            continue
        filtered_ticks.append(t)
        filtered_labels.append(lbl)

    bottom_ax.set_xticks(filtered_ticks)
    bottom_ax.set_xticklabels(filtered_labels, fontsize=4, rotation=0, ha="left")
    bottom_ax.tick_params(axis="x", labelrotation=0)

    for label in bottom_ax.get_xticklabels():
        label.set_ha("left")
        label.set_rotation(0)
        label.set_rotation_mode("anchor")
        label.set_clip_on(False)


def _shrink_candle_side_margins(axes, data_len: int, ratio: float = 1 / 3) -> None:
    if not axes or data_len <= 0:
        return

    ratio = max(0.0, min(1.0, float(ratio)))
    left_edge = 0.0
    right_edge = float(data_len - 1)

    base_ax = axes[-1]
    cur_left, cur_right = base_ax.get_xlim()

    left_pad = max(0.0, left_edge - cur_left)
    right_pad = max(0.0, cur_right - right_edge)

    new_left = left_edge - (left_pad * ratio)
    new_right = right_edge + (right_pad * ratio)

    for ax in axes:
        ax.set_xlim(new_left, new_right)


def _build_chart_figure(
    code: str,
    name: str,
    timeframe: str,
    ma_cols: list[str],
    lookback: int,
    title_suffix: str = "",
    breakout_strength: Optional[float] = None,
):
    _configure_plot_font()

    df = _load_chart_data(code, timeframe)

    if df is None or df.empty:
        print(f"[CHART][SKIP] 데이터 없음: {code} {name} {timeframe}")
        return None, None, None

    effective_lookback = _effective_lookback(lookback, len(df))
    plot_df = df.tail(effective_lookback).copy()

    if plot_df.empty:
        print(f"[CHART][SKIP] 표시할 데이터 없음: {code} {name} {timeframe}")
        return None, None, None

    mpf_df = _prepare_ohlcv(plot_df)

    latest_row = plot_df.iloc[-1]
    title = _make_title(
        code=code,
        name=name,
        timeframe=timeframe,
        title_suffix=title_suffix,
        breakout_strength=breakout_strength,
        latest_data_date=latest_row.get("date"),
        latest_asof_time=latest_row.get("asof_time"),
        latest_price_status=latest_row.get("price_status"),
    )

    market_colors = mpf.make_marketcolors(
        up="red",
        down="blue",
        edge="inherit",
        wick="inherit",
        volume="inherit",
    )
    chart_style = mpf.make_mpf_style(
        base_mpf_style="default",
        marketcolors=market_colors,
        facecolor="white",
        figcolor="white",
        rc={
            "font.family": [_SELECTED_FONT, "DejaVu Sans"] if _SELECTED_FONT else ["DejaVu Sans"],
            "font.sans-serif": [_SELECTED_FONT, "DejaVu Sans"] if _SELECTED_FONT else ["DejaVu Sans"],
            "axes.unicode_minus": False,
        },
    )

    addplots = _build_addplots(plot_df, highlight_ma_cols=ma_cols, timeframe=timeframe)

    plot_kwargs = dict(
        type="candle",
        style=chart_style,
        volume=True,
        axtitle=title,
        xrotation=0,
        figratio=(14, 8),
        figscale=1.1,
        tight_layout=False,
        update_width_config=dict(
            candle_width=0.75,
            candle_linewidth=0.8,
            volume_width=0.75,
            volume_linewidth=0.0,
        ),
        returnfig=True,
    )
    if addplots:
        plot_kwargs["addplot"] = addplots

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"Attempting to set identical low and high ylims makes transformation singular; automatically expanding\\.",
            category=UserWarning,
        )
        fig, axes = mpf.plot(mpf_df, **plot_kwargs)

    if axes:
        main_ax = axes[0]
        handles, labels = main_ax.get_legend_handles_labels()
        if handles and labels:
            main_ax.legend(
                handles,
                labels,
                loc="upper left",
                fontsize=9,
                frameon=True,
            )

        _add_last_bar_info_box(main_ax, plot_df, timeframe=timeframe)
        _shrink_candle_side_margins(axes, len(mpf_df), ratio=1 / 3)
        _apply_custom_xaxis_labels(axes, mpf_df.index, timeframe=timeframe)

    fig.subplots_adjust(top=0.88, bottom=0.22, left=0.07, right=0.98)

    return fig, axes, plot_df


def show_candle_chart(
    code: str,
    name: str,
    timeframe: str,
    ma_cols: list[str],
    lookback: int,
    title_suffix: str = "",
    save_dir: Optional[str] = None,
    breakout_strength: Optional[float] = None,
    is_final: Optional[bool] = None,
):
    fig, _, _ = _build_chart_figure(
        code=code,
        name=name,
        timeframe=timeframe,
        ma_cols=ma_cols,
        lookback=lookback,
        title_suffix=title_suffix,
        breakout_strength=breakout_strength,
    )
    if fig is None:
        return

    if SAVE_CHART:
        save_path = _make_save_path(
            code=code,
            name=name,
            timeframe=timeframe,
            title_suffix=title_suffix,
            save_dir=save_dir,
        )
        fig.savefig(save_path, dpi=150, bbox_inches="tight")

    if SHOW_CHART:
        plt.show()
    else:
        plt.close(fig)


def _filter_results_by_breakout_pct(
    results: dict[str, list[dict]],
    min_pct: float = 0.5,
    max_pct: float = 5.0,
) -> dict[str, list[dict]]:
    filtered: dict[str, list[dict]] = {}

    for case_key, items in results.items():
        filtered_items = []
        for item in items:
            pct = item.get("breakout_pct")
            if pct is None:
                continue
            if min_pct <= pct <= max_pct:
                filtered_items.append(item)
        filtered[case_key] = filtered_items

    return filtered


def create_overview_image(
    results: dict[str, list[dict]],
    save_root: Optional[str] = None,
    min_pct: float = 0.5,
    max_pct: float = 5.0,
    show_first_page: bool = True,
    pause_sec: float = 3.0,
) -> str:
    target_dir = save_root if save_root else OUTPUT_DIR
    _ensure_dir(target_dir)

    filtered = _filter_results_by_breakout_pct(results, min_pct=min_pct, max_pct=max_pct)

    rows = []
    total_all = 0
    total_filtered = 0

    for case_key, meta in CASE_META.items():
        total_count = len(results.get(case_key, []))
        filtered_count = len(filtered.get(case_key, []))
        total_all += total_count
        total_filtered += filtered_count

        rows.append({
            "구분": meta["label"],
            "전체 돌파 종목수": total_count,
            f"{min_pct:.1f}%~{max_pct:.1f}% 종목수": filtered_count,
        })

    df = pd.DataFrame(rows)

    _configure_plot_font()
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.axis("off")

    title = "돌파 스캔 오버뷰"
    subtitle = f"자동 슬라이드 대상: 돌파강도 {min_pct:.1f}% ~ {max_pct:.1f}%"
    footer = f"전체 {total_all}개 / 슬라이드 대상 {total_filtered}개"

    ax.text(0.5, 0.93, title, ha="center", va="center", fontsize=18, fontweight="bold")
    ax.text(0.5, 0.86, subtitle, ha="center", va="center", fontsize=11)
    ax.text(0.5, 0.18, footer, ha="center", va="center", fontsize=11)

    table = ax.table(
        cellText=df.values,
        colLabels=df.columns,
        loc="center",
        cellLoc="center",
        colLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.2, 1.8)

    overview_path = os.path.join(target_dir, "overview.png")
    fig.savefig(overview_path, dpi=150, bbox_inches="tight")

    if SHOW_CHART and show_first_page:
        plt.show(block=False)
        plt.pause(pause_sec)
        plt.close(fig)
    else:
        plt.close(fig)

    return overview_path


def auto_slide_breakout_charts(
    results: dict[str, list[dict]],
    save_root: Optional[str] = None,
    min_pct: float = 0.5,
    max_pct: float = 5.0,
    pause_sec: float = 2.0,
    max_per_case: int = 5,
):
    filtered = _filter_results_by_breakout_pct(results, min_pct=min_pct, max_pct=max_pct)

    for case_key, meta in CASE_META.items():
        items = filtered.get(case_key, [])

        if max_per_case is not None and max_per_case > 0:
            items = items[:max_per_case]

        print(f"\n=== {meta['label']} 자동 슬라이드 ({len(items)}개 / 최대 {max_per_case}개) ===")

        case_save_dir = None
        if save_root:
            case_save_dir = os.path.join(save_root, "charts", case_key)

        for item in items:
            fig, _, _ = _build_chart_figure(
                code=item["code"],
                name=item["name"],
                timeframe=meta["timeframe"],
                ma_cols=meta["ma_cols"],
                lookback=meta["lookback"],
                title_suffix=case_key,
                breakout_strength=item.get("breakout_strength"),
            )
            if fig is None:
                continue

            if SAVE_CHART:
                save_path = _make_save_path(
                    code=item["code"],
                    name=item["name"],
                    timeframe=meta["timeframe"],
                    title_suffix=case_key,
                    save_dir=case_save_dir,
                )
                fig.savefig(save_path, dpi=150, bbox_inches="tight")

            if SHOW_CHART:
                plt.show(block=False)
                plt.pause(pause_sec)
                plt.close(fig)
            else:
                plt.close(fig)

def show_breakout_charts(results: dict, save_root: Optional[str] = None):
    total_charts = sum(len(results.get(case_key, [])) for case_key in CASE_META.keys())
    built_count = 0

    for case_key, meta in CASE_META.items():
        items = results.get(case_key, [])
        print(f"\n=== {meta['label']} 차트 ({len(items)}개) ===")

        case_save_dir = None
        if save_root:
            case_save_dir = os.path.join(save_root, "charts", case_key)

        for idx, item in enumerate(items, start=1):
            built_count += 1
            print(
                f"[CHART] 생성중 {built_count}/{total_charts} "
                f"(케이스 {idx}/{len(items)}) | "
                f"{item['code']} {item['name']} | {meta['label']}"
            )
            show_candle_chart(
                code=item["code"],
                name=item["name"],
                timeframe=meta["timeframe"],
                ma_cols=meta["ma_cols"],
                lookback=meta["lookback"],
                title_suffix=case_key,
                save_dir=case_save_dir,
                breakout_strength=item.get("breakout_strength"),
                is_final=item.get("is_final"),
            )


def create_scan_overview_html(
    results: dict[str, list[dict]],
    save_root: str,
    html_filename: Optional[str] = None,
    timestamp: Optional[str] = None,
    sort_by: str = "strength",
) -> str:
    """
    scan_result 폴더 내 차트 PNG와 overview.png를 한 번에 확인할 수 있는 HTML 생성.
    """
    _ensure_dir(save_root)

    if html_filename is None:
        if timestamp:
            html_filename = f"scan_overview_{timestamp}.html"
        else:
            html_filename = "scan_overview.html"

    html_path = os.path.join(save_root, html_filename)
    sort_key = "strength" if sort_by not in {"strength", "code"} else sort_by

    if timestamp:
        try:
            scan_dt = pd.to_datetime(timestamp, format="%Y%m%d_%H%M%S")
            scan_time_text = scan_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            scan_time_text = str(timestamp)
    else:
        scan_time_text = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

    filtered = _filter_results_by_breakout_pct(results, min_pct=0.5, max_pct=5.0)

    sections = []
    for case_key, meta in CASE_META.items():
        case_dir = os.path.join(save_root, "charts", case_key)
        image_tags = []

        items = list(results.get(case_key, []))
        if sort_key == "code":
            items.sort(key=lambda x: str(x.get("code", "")))
        else:
            items.sort(
                key=lambda x: (
                    999999 if x.get("breakout_strength") is None else float(x.get("breakout_strength")),
                    str(x.get("code", "")),
                )
            )

        for idx, item in enumerate(items):
            image_path = _make_save_path(
                code=item["code"],
                name=item["name"],
                timeframe=meta["timeframe"],
                title_suffix=case_key,
                save_dir=case_dir,
            )
            if not os.path.exists(image_path):
                continue

            rel_path = os.path.relpath(image_path, save_root).replace("\\", "/")
            caption = f"{item['code']} {item['name']}"
            image_tags.append(
                "<figure class=\"card\">"
                f"<img class=\"zoomable\" src=\"{escape(rel_path)}\" loading=\"lazy\" alt=\"{escape(caption)}\" data-caption=\"{escape(caption)}\" data-group=\"{escape(case_key)}\" data-index=\"{idx}\">"
                f"<figcaption>{escape(caption)}</figcaption>"
                "</figure>"
            )

        if not image_tags and os.path.isdir(case_dir):
            for idx, filename in enumerate(sorted(os.listdir(case_dir))):
                if not filename.lower().endswith(".png"):
                    continue

                image_path = os.path.join(case_dir, filename)
                rel_path = os.path.relpath(image_path, save_root).replace("\\", "/")
                image_tags.append(
                    "<figure class=\"card\">"
                    f"<img class=\"zoomable\" src=\"{escape(rel_path)}\" loading=\"lazy\" alt=\"{escape(filename)}\" data-caption=\"{escape(filename)}\" data-group=\"{escape(case_key)}\" data-index=\"{idx}\">"
                    f"<figcaption>{escape(filename)}</figcaption>"
                    "</figure>"
                )

        section_html = (
            f"<section id=\"section-{escape(case_key)}\"><h2>{escape(meta['label'])} ({len(image_tags)}개)</h2>"
            f"<div class=\"grid\">{''.join(image_tags) if image_tags else '<p class=\"empty\">저장된 차트가 없습니다.</p>'}</div>"
            "</section>"
        )
        sections.append(section_html)

    overview_table_rows = []
    total_all = 0
    total_filtered = 0
    for case_key, meta in CASE_META.items():
        total_count = len(results.get(case_key, []))
        filtered_count = len(filtered.get(case_key, []))
        total_all += total_count
        total_filtered += filtered_count
        label_link = f"<a href=\"#section-{escape(case_key)}\">{escape(meta['label'])}</a>"
        overview_table_rows.append(
            "<tr>"
            f"<td>{label_link}</td>"
            f"<td>{total_count}</td>"
            f"<td>{filtered_count}</td>"
            "</tr>"
        )

    overview_table_block = (
        "<section>"
        "<h2>Overview Table</h2>"
        "<div class=\"table-wrap\">"
        "<table class=\"summary\">"
        "<thead><tr><th>구분</th><th>전체 돌파 종목수</th><th>0.5%~5.0% 종목수</th></tr></thead>"
        f"<tbody>{''.join(overview_table_rows)}</tbody>"
        f"<tfoot><tr><td>합계</td><td>{total_all}</td><td>{total_filtered}</td></tr></tfoot>"
        "</table>"
        "</div>"
        "</section>"
    )

    html = f"""<!doctype html>
<html lang=\"ko\">
<head>
    <meta charset=\"utf-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
    <title>스캔 결과 뷰어</title>
    <style>
        :root {{
            --bg: #f6f8fb;
            --surface: #ffffff;
            --text: #18212f;
            --muted: #5f6b7a;
            --line: #dde4ed;
            --brand: #0f6bff;
        }}
        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            font-family: "Segoe UI", "Malgun Gothic", sans-serif;
            color: var(--text);
            background: radial-gradient(circle at top left, #eef3ff 0%, var(--bg) 45%);
        }}
        .wrap {{ max-width: 1440px; margin: 0 auto; padding: 24px; }}
        h1 {{ margin: 0 0 6px; font-size: 28px; }}
        .desc {{ margin: 0 0 24px; color: var(--muted); }}
        .scan-time {{ margin: 0 0 18px; color: #3f4c5e; font-size: 14px; }}
        section {{
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 14px;
            padding: 16px;
            margin-bottom: 18px;
            box-shadow: 0 10px 24px rgba(16, 31, 64, 0.05);
        }}
        h2 {{ margin: 0 0 12px; font-size: 20px; color: #0b4ea2; }}
        .overview img {{ width: 100%; max-width: 1200px; border-radius: 10px; border: 1px solid var(--line); }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 14px; }}
        .table-wrap {{ overflow-x: auto; }}
        table.summary {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
        table.summary th, table.summary td {{ border: 1px solid var(--line); padding: 8px 10px; text-align: center; }}
        table.summary th {{ background: #eef4ff; color: #103f86; }}
        table.summary tbody tr:nth-child(odd) {{ background: #fafcff; }}
        table.summary tfoot td {{ background: #f1f6ff; font-weight: 700; }}
        table.summary a {{ color: #0f59d1; text-decoration: none; font-weight: 600; }}
        table.summary a:hover {{ text-decoration: underline; }}
        .card {{ margin: 0; border: 1px solid var(--line); border-radius: 12px; overflow: hidden; background: #fff; }}
        .card img {{ width: 100%; display: block; }}
        .zoomable {{ cursor: zoom-in; }}
        .card figcaption {{ padding: 8px 10px; font-size: 13px; color: var(--muted); }}
        .empty {{ color: var(--muted); margin: 0; }}
        .lightbox {{
            position: fixed;
            inset: 0;
            display: none;
            align-items: center;
            justify-content: center;
            background: rgba(8, 15, 26, 0.84);
            z-index: 9999;
            padding: 24px;
        }}
        .lightbox.open {{ display: flex; }}
        .lightbox img {{
            max-width: min(95vw, 1800px);
            max-height: 86vh;
            width: auto;
            height: auto;
            border-radius: 10px;
            box-shadow: 0 18px 48px rgba(0, 0, 0, 0.45);
            background: #fff;
        }}
        .lightbox-caption {{
            position: absolute;
            left: 50%;
            bottom: 18px;
            transform: translateX(-50%);
            color: #e8edf5;
            background: rgba(0, 0, 0, 0.35);
            padding: 8px 12px;
            border-radius: 8px;
            font-size: 13px;
        }}
        .lightbox-close {{
            position: absolute;
            top: 14px;
            right: 16px;
            border: 0;
            background: rgba(255, 255, 255, 0.2);
            color: #fff;
            width: 36px;
            height: 36px;
            border-radius: 999px;
            font-size: 22px;
            line-height: 1;
            cursor: pointer;
        }}
        .lightbox-nav {{
            position: absolute;
            top: 50%;
            transform: translateY(-50%);
            border: 0;
            background: rgba(255, 255, 255, 0.22);
            color: #fff;
            width: 44px;
            height: 64px;
            border-radius: 12px;
            font-size: 28px;
            line-height: 1;
            cursor: pointer;
        }}
        .lightbox-nav:disabled {{
            opacity: 0.35;
            cursor: not-allowed;
        }}
        .lightbox-prev {{ left: 18px; }}
        .lightbox-next {{ right: 18px; }}
        @media (max-width: 768px) {{
            .wrap {{ padding: 14px; }}
            .grid {{ grid-template-columns: 1fr; }}
            h1 {{ font-size: 24px; }}
            .lightbox-nav {{ width: 38px; height: 54px; font-size: 22px; }}
        }}
    </style>
</head>
<body>
    <main class=\"wrap\">
        <h1>스캔 결과 이미지 모음</h1>
        <p class=\"desc\">이동평균 케이스별 저장 차트를 한 화면에서 확인합니다. 정렬 기준: {escape(sort_key)}</p>
        <p class="scan-time">스캔 시각: {escape(scan_time_text)}</p>
        {overview_table_block}
        {''.join(sections)}
    </main>
    <div class=\"lightbox\" id=\"lightbox\" aria-hidden=\"true\">
        <button class=\"lightbox-nav lightbox-prev\" id=\"lightbox-prev\" type=\"button\" aria-label=\"이전 차트\" disabled>‹</button>
        <button class=\"lightbox-nav lightbox-next\" id=\"lightbox-next\" type=\"button\" aria-label=\"다음 차트\" disabled>›</button>
        <button class=\"lightbox-close\" id=\"lightbox-close\" type=\"button\" aria-label=\"닫기\">×</button>
        <img id=\"lightbox-image\" src=\"\" alt=\"확대 이미지\">
        <div class=\"lightbox-caption\" id=\"lightbox-caption\"></div>
    </div>
    <script>
        const lightbox = document.getElementById("lightbox");
        const lightboxImage = document.getElementById("lightbox-image");
        const lightboxCaption = document.getElementById("lightbox-caption");
        const lightboxClose = document.getElementById("lightbox-close");
        const lightboxPrev = document.getElementById("lightbox-prev");
        const lightboxNext = document.getElementById("lightbox-next");
        const zoomableImages = Array.from(document.querySelectorAll("img.zoomable"));

        let currentImage = null;
        let currentGroupImages = [];
        let currentGroupPos = -1;

        function updateNavButtons() {{
            const canNavigate = currentGroupImages.length > 1;
            lightboxPrev.disabled = !canNavigate || currentGroupPos <= 0;
            lightboxNext.disabled = !canNavigate || currentGroupPos >= currentGroupImages.length - 1;
        }}

        function updateCaption() {{
            if (!currentImage) {{
                lightboxCaption.textContent = "";
                return;
            }}

            const baseCaption = currentImage.dataset.caption || currentImage.alt || "";
            if (currentGroupImages.length > 0 && currentGroupPos >= 0) {{
                lightboxCaption.textContent = `${{baseCaption}} (${{currentGroupPos + 1}}/${{currentGroupImages.length}})`;
            }} else {{
                lightboxCaption.textContent = baseCaption;
            }}
        }}

        function openLightboxByImage(img) {{
            if (!img) {{
                return;
            }}

            currentImage = img;
            lightboxImage.src = img.src;
            lightbox.classList.add("open");
            lightbox.setAttribute("aria-hidden", "false");

            const group = img.dataset.group || "";
            if (group) {{
                currentGroupImages = zoomableImages.filter((node) => node.dataset.group === group);
                currentGroupPos = currentGroupImages.indexOf(img);
            }} else {{
                currentGroupImages = [];
                currentGroupPos = -1;
            }}

            updateCaption();
            updateNavButtons();
        }}

        function moveGroup(step) {{
            if (currentGroupImages.length <= 1 || currentGroupPos < 0) {{
                return;
            }}

            let nextPos = currentGroupPos + step;
            if (nextPos < 0 || nextPos >= currentGroupImages.length) {{
                return;
            }}

            openLightboxByImage(currentGroupImages[nextPos]);
        }}

        function closeLightbox() {{
            lightbox.classList.remove("open");
            lightbox.setAttribute("aria-hidden", "true");
            lightboxImage.src = "";
            lightboxCaption.textContent = "";
            currentImage = null;
            currentGroupImages = [];
            currentGroupPos = -1;
            updateNavButtons();
        }}

        zoomableImages.forEach((img) => {{
            img.addEventListener("click", () => {{
                openLightboxByImage(img);
            }});
        }});

        lightboxClose.addEventListener("click", closeLightbox);
        lightboxPrev.addEventListener("click", (event) => {{
            event.stopPropagation();
            moveGroup(-1);
        }});
        lightboxNext.addEventListener("click", (event) => {{
            event.stopPropagation();
            moveGroup(1);
        }});

        lightbox.addEventListener("click", (event) => {{
            if (event.target === lightbox) {{
                closeLightbox();
            }}
        }});

        document.addEventListener("keydown", (event) => {{
            if (!lightbox.classList.contains("open")) {{
                return;
            }}
            if (event.key === "Escape") {{
                closeLightbox();
            }}
            if (event.key === "ArrowLeft") {{
                moveGroup(-1);
            }}
            if (event.key === "ArrowRight") {{
                moveGroup(1);
            }}
        }});
    </script>
</body>
</html>
"""

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    return html_path