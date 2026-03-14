# chart_viewer.py

from __future__ import annotations

import os
import re
from typing import Optional

import pandas as pd
import mplfinance as mpf
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import font_manager

from config import (
    OUTPUT_DIR,
    CHART_LOOKBACK_WEEKLY,
    CHART_LOOKBACK_MONTHLY,
    SHOW_CHART,
    SAVE_CHART,
)
from data_loader import load_weekly, load_monthly


_FONT_CONFIGURED = False
_SELECTED_FONT: Optional[str] = None

DEFAULT_MA_COLS = ["ma5", "ma10", "ma20", "ma120", "ma240"]
LOOKBACK_RATIO = 2 / 3

BASE_MA_WIDTH = 1.2
HIGHLIGHT_MULTIPLIER = 1.5

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


def _build_addplots(plot_df: pd.DataFrame, highlight_ma_cols: list[str]) -> list:
    addplots = []
    highlight_set = set(highlight_ma_cols or [])

    for ma_col in DEFAULT_MA_COLS:
        if ma_col not in plot_df.columns:
            continue

        series = pd.to_numeric(plot_df[ma_col], errors="coerce")
        if series.notna().sum() == 0:
            continue

        width = BASE_MA_WIDTH
        if ma_col in highlight_set:
            width = BASE_MA_WIDTH * HIGHLIGHT_MULTIPLIER

        addplots.append(
            mpf.make_addplot(
                series,
                panel=0,
                label=ma_col.upper(),
                width=width,
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


def _add_last_bar_info_box(main_ax, plot_df: pd.DataFrame) -> None:
    if plot_df.empty:
        return

    last_row = plot_df.iloc[-1]
    lines = []

    close_val = _format_value(last_row.get("close"))
    if close_val is not None:
        lines.append(f"종가   {close_val}")

    ma10_val = _format_value(last_row.get("ma10"))
    if ma10_val is not None:
        lines.append(f"10이평 {ma10_val}")

    ma120_val = _format_value(last_row.get("ma120"))
    if ma120_val is not None:
        lines.append(f"120이평 {ma120_val}")

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

    addplots = _build_addplots(plot_df, highlight_ma_cols=ma_cols)

    fig, axes = mpf.plot(
        mpf_df,
        type="candle",
        style=chart_style,
        volume=True,
        axtitle=title,
        figratio=(14, 8),
        figscale=1.1,
        tight_layout=True,
        addplot=addplots if addplots else None,
        update_width_config=dict(
            candle_width=0.75,
            candle_linewidth=0.8,
            volume_width=0.75,
        ),
        returnfig=True,
    )

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

        _add_last_bar_info_box(main_ax, plot_df)

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
    for case_key, meta in CASE_META.items():
        items = results.get(case_key, [])
        print(f"\n=== {meta['label']} 차트 ({len(items)}개) ===")

        case_save_dir = None
        if save_root:
            case_save_dir = os.path.join(save_root, "charts", case_key)

        for item in items:
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