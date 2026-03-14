# chart_viewer.py

from __future__ import annotations

import os
import re
from typing import Optional

import pandas as pd
import mplfinance as mpf
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


_FONT_CONFIGURED = False
_SELECTED_FONT: Optional[str] = None


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
    elif timeframe == "monthly":
        return load_monthly(code)
    else:
        raise ValueError("timeframe must be 'weekly' or 'monthly'")


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
    _configure_plot_font()

    df = _load_chart_data(code, timeframe)

    if df is None or df.empty:
        print(f"[CHART][SKIP] 데이터 없음: {code} {name} {timeframe}")
        return

    plot_df = df.tail(min(len(df), lookback)).copy()
    mpf_df = _prepare_ohlcv(plot_df)

    mav_values = []
    for col in ma_cols:
        if isinstance(col, str) and col.startswith("ma"):
            try:
                mav_values.append(int(col.replace("ma", "")))
            except Exception:
                pass

    title_parts = [f"{code} {name}", f"[{timeframe}]"]
    if title_suffix:
        title_parts.append(title_suffix)

    if breakout_strength is not None:
        title_parts.append(f"strength={breakout_strength * 100:.2f}%")

    if is_final is not None:
        title_parts.append(f"final={is_final}")

    title = " | ".join(title_parts)

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

    save_path = None
    if SAVE_CHART:
        target_dir = save_dir if save_dir else OUTPUT_DIR
        _ensure_dir(target_dir)

        safe_name = _safe_filename(name)
        safe_suffix = _safe_filename(title_suffix) if title_suffix else "chart"

        save_path = os.path.join(
            target_dir,
            f"{code}_{safe_name}_{timeframe}_{safe_suffix}.png"
        )

    kwargs = {
        "type": "candle",
        "style": chart_style,
        "volume": True,
        "axtitle": title,
        "figratio": (14, 8),
        "figscale": 1.1,
        "tight_layout": True,
    }

    if mav_values:
        kwargs["mav"] = tuple(mav_values)

    if save_path is not None:
        kwargs["savefig"] = save_path

    if SHOW_CHART:
        mpf.plot(mpf_df, **kwargs)
    else:
        if save_path is None:
            target_dir = save_dir if save_dir else OUTPUT_DIR
            _ensure_dir(target_dir)

            safe_name = _safe_filename(name)
            safe_suffix = _safe_filename(title_suffix) if title_suffix else "chart"
            kwargs["savefig"] = os.path.join(
                target_dir,
                f"{code}_{safe_name}_{timeframe}_{safe_suffix}.png"
            )

        mpf.plot(mpf_df, **kwargs)


def show_breakout_charts(results: dict, save_root: Optional[str] = None):
    case_meta = {
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

    for case_key, meta in case_meta.items():
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