# historical_chart_explorer.py

#지원 기능:
#종목 선택
#코드 직접 입력
#종목명 앞 2글자 검색 후 번호 선택
#
#날짜 입력
#   연도 따로
#   월/일 같이 입력
#주봉 / 월봉 선택
#52개 봉 고정
#← / → 로 이전/다음 봉 이동
#↑ / ↓ 로 10봉 단위 이동
#Home / End 로 처음/끝 이동
#S 로 현재 화면 이미지 저장
#Q / Esc 로 종료
#MA5 / MA10 / MA20 / MA120 / MA180 / MA240 표시
#마지막 봉 기준 정보 박스 표시
#종가
#10이평
#120이평(있으면)
#240이평(있으면)




from __future__ import annotations

import os
import re
import warnings
from typing import Optional

import pandas as pd
import mplfinance as mpf
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import font_manager

from config import OUTPUT_DIR
from data_loader import load_master, load_weekly, load_monthly


LOOKBACK_BARS = 52
DEFAULT_MA_COLS = ["ma5", "ma10", "ma20", "ma120", "ma180", "ma240"]
BASE_MA_WIDTH = 1.2

MA_LINE_COLORS = {
    "ma5": "#f59e0b",
    "ma10": "#ef4444",
    "ma20": "#14b8a6",
    "ma120": "#3b82f6",
    "ma180": "#64748b",
    "ma240": "#22c55e",
}

_FONT_CONFIGURED = False
_SELECTED_FONT: Optional[str] = None


# =========================
# 폰트
# =========================
def _configure_plot_font() -> None:
    global _FONT_CONFIGURED, _SELECTED_FONT

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

    mpl.rcParams["axes.unicode_minus"] = False
    _FONT_CONFIGURED = True


# =========================
# 입력 유틸
# =========================
def _input_nonempty(prompt: str) -> str:
    while True:
        s = input(prompt).strip()
        if s:
            return s
        print("입력이 비어 있습니다. 다시 입력하세요.")


def _parse_year() -> int:
    while True:
        s = _input_nonempty("연도 입력 (예: 2026): ")
        if s.isdigit() and len(s) == 4:
            year = int(s)
            if 1900 <= year <= 2100:
                return year
        print("연도는 4자리 숫자로 입력하세요.")


def _parse_month_day() -> tuple[int, int]:
    while True:
        s = _input_nonempty("월일 입력 (예: 0315 또는 3-15): ").replace(" ", "")

        if re.fullmatch(r"\d{3,4}", s):
            if len(s) == 3:
                month = int(s[0])
                day = int(s[1:])
            else:
                month = int(s[:2])
                day = int(s[2:])
        else:
            m = re.fullmatch(r"(\d{1,2})[-/](\d{1,2})", s)
            if not m:
                print("월일 형식이 올바르지 않습니다.")
                continue
            month = int(m.group(1))
            day = int(m.group(2))

        try:
            pd.Timestamp(year=2000, month=month, day=day)
            return month, day
        except Exception:
            print("유효하지 않은 월/일입니다.")


def _parse_target_date() -> pd.Timestamp:
    year = _parse_year()
    month, day = _parse_month_day()
    return pd.Timestamp(year=year, month=month, day=day)


def _parse_timeframe() -> str:
    while True:
        s = _input_nonempty("봉 타입 선택 (1: 주봉, 2: 월봉): ")
        if s == "1":
            return "weekly"
        if s == "2":
            return "monthly"
        print("1 또는 2를 입력하세요.")


# =========================
# 종목 선택
# =========================
def select_stock() -> tuple[str, str]:
    master = load_master()

    while True:
        mode = _input_nonempty("종목 선택 방식 (1: 코드 직접입력, 2: 종목명 2글자 검색): ")

        if mode == "1":
            code = _input_nonempty("종목코드 입력 (예: 005930): ").zfill(6)
            hit = master[master["code"] == code]
            if hit.empty:
                print("해당 코드의 종목이 없습니다.")
                continue
            row = hit.iloc[0]
            return str(row["code"]).zfill(6), str(row["name"])

        if mode == "2":
            prefix = _input_nonempty("종목명 앞 2글자 입력: ")
            candidates = master[master["name"].astype(str).str.startswith(prefix)].copy()

            if candidates.empty:
                print("일치하는 종목이 없습니다.")
                continue

            candidates = candidates.sort_values(["name", "code"]).reset_index(drop=True)

            print("\n추천 종목 리스트")
            for i, row in enumerate(candidates.itertuples(index=False), start=1):
                print(f"{i:>3}. {row.name} ({row.code})")

            while True:
                sel = _input_nonempty("번호 선택: ")
                if sel.isdigit():
                    idx = int(sel)
                    if 1 <= idx <= len(candidates):
                        row = candidates.iloc[idx - 1]
                        return str(row["code"]).zfill(6), str(row["name"])
                print("올바른 번호를 입력하세요.")

        else:
            print("1 또는 2를 입력하세요.")


# =========================
# 차트 유틸
# =========================
def _load_chart_data(code: str, timeframe: str) -> pd.DataFrame:
    if timeframe == "weekly":
        return load_weekly(code)
    if timeframe == "monthly":
        return load_monthly(code)
    raise ValueError("timeframe must be 'weekly' or 'monthly'")


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


def _build_addplots(plot_df: pd.DataFrame, timeframe: Optional[str] = None) -> list:
    addplots = []

    ma_cols = list(DEFAULT_MA_COLS)

    for ma_col in ma_cols:
        if ma_col not in plot_df.columns:
            continue

        series = pd.to_numeric(plot_df[ma_col], errors="coerce")
        if series.notna().sum() == 0:
            continue

        addplots.append(
            mpf.make_addplot(
                series,
                panel=0,
                label=ma_col.upper(),
                width=BASE_MA_WIDTH,
                color=MA_LINE_COLORS.get(ma_col),
            )
        )

    return addplots


def _format_value(v) -> Optional[str]:
    if v is None or pd.isna(v):
        return None
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)


def _safe_filename(text: str) -> str:
    text = re.sub(r'[\\/:*?"<>|]', "_", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _make_save_path(code: str, name: str, timeframe: str, anchor_date: pd.Timestamp) -> str:
    tf_label = "주봉" if timeframe == "weekly" else "월봉"
    safe_name = _safe_filename(name)
    date_str = pd.to_datetime(anchor_date).strftime("%Y-%m-%d")

    target_dir = os.path.join(OUTPUT_DIR, "historical_charts")
    os.makedirs(target_dir, exist_ok=True)

    return os.path.join(
        target_dir,
        f"{code}_{safe_name}_{tf_label}_{date_str}.png"
    )


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
        0.015,
        0.0,
        text,
        transform=main_ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=9,
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
    )


def _weekday_kr(ts: pd.Timestamp) -> str:
    weekday_map = {0: "월", 1: "화", 2: "수", 3: "목", 4: "금", 5: "토", 6: "일"}
    return weekday_map[pd.to_datetime(ts).weekday()]


def _make_title(code: str, name: str, timeframe: str, anchor_date: pd.Timestamp, start_date: pd.Timestamp) -> str:
    tf_label = "주봉" if timeframe == "weekly" else "월봉"
    anchor_w = _weekday_kr(anchor_date)
    start_w = _weekday_kr(start_date)
    return (
        f"{code} {name} | {tf_label} | "
        f"시작봉 {start_date.strftime('%Y-%m-%d')} ({start_w}) | "
        f"기준봉 {anchor_date.strftime('%Y-%m-%d')} ({anchor_w}) | "
        f"{LOOKBACK_BARS}봉"
    )


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

    # Align each label's left edge to the candle's left-side tick and allow
    # the last full-date label to extend outside the chart area if needed.
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


def build_historical_chart_figure(
    code: str,
    name: str,
    timeframe: str,
    target_date: pd.Timestamp,
    lookback_bars: int = LOOKBACK_BARS,
):
    """Build a static historical chart figure using the same visual rules as explorer mode."""
    _configure_plot_font()

    df = _load_chart_data(code, timeframe).copy()
    if df is None or df.empty:
        raise ValueError("불러올 데이터가 없습니다.")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    valid = df[df["date"] <= pd.to_datetime(target_date)].copy()
    if valid.empty:
        raise ValueError("입력한 날짜 이전 데이터가 없습니다.")

    anchor_idx = int(valid.index.max())
    start_idx = max(0, anchor_idx - int(lookback_bars) + 1)
    plot_df = df.iloc[start_idx:anchor_idx + 1].copy().reset_index(drop=True)
    if plot_df.empty:
        raise ValueError("표시할 데이터가 없습니다.")

    anchor_date = pd.to_datetime(plot_df.iloc[-1]["date"])
    start_date = pd.to_datetime(plot_df.iloc[0]["date"])

    mpf_df = _prepare_ohlcv(plot_df)
    addplots = _build_addplots(plot_df, timeframe=timeframe)

    title = _make_title(
        code=code,
        name=name,
        timeframe=timeframe,
        anchor_date=anchor_date,
        start_date=start_date,
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
    return fig, anchor_date


# =========================
# 탐색기
# =========================
class HistoricalChartExplorer:
    def __init__(self, code: str, name: str, timeframe: str, target_date: pd.Timestamp):
        self.code = code
        self.name = name
        self.timeframe = timeframe
        self.df = _load_chart_data(code, timeframe).copy()

        if self.df is None or self.df.empty:
            raise ValueError("불러올 데이터가 없습니다.")

        self.df["date"] = pd.to_datetime(self.df["date"])
        self.df = self.df.sort_values("date").reset_index(drop=True)

        valid = self.df[self.df["date"] <= target_date].copy()
        if valid.empty:
            raise ValueError("입력한 날짜 이전 데이터가 없습니다.")

        self.anchor_idx = int(valid.index.max())
        self.next_action = "quit"
        self.current_fig = None
        self.current_anchor_date = None

    def _current_slice(self) -> pd.DataFrame:
        start_idx = max(0, self.anchor_idx - LOOKBACK_BARS + 1)
        return self.df.iloc[start_idx:self.anchor_idx + 1].copy().reset_index(drop=True)

    def _save_current(self):
        if self.current_fig is None or self.current_anchor_date is None:
            return

        save_path = _make_save_path(
            code=self.code,
            name=self.name,
            timeframe=self.timeframe,
            anchor_date=self.current_anchor_date,
        )
        self.current_fig.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"\n이미지 저장 완료: {save_path}")

    def _on_key(self, event):
        key = event.key.lower() if event.key else ""

        if key == "left":
            if self.anchor_idx > 0:
                self.anchor_idx -= 1
            self.next_action = "refresh"
            plt.close(event.canvas.figure)
            return

        if key == "right":
            if self.anchor_idx < len(self.df) - 1:
                self.anchor_idx += 1
            self.next_action = "refresh"
            plt.close(event.canvas.figure)
            return

        if key == "up":
            self.anchor_idx = max(0, self.anchor_idx - 10)
            self.next_action = "refresh"
            plt.close(event.canvas.figure)
            return

        if key == "down":
            self.anchor_idx = min(len(self.df) - 1, self.anchor_idx + 10)
            self.next_action = "refresh"
            plt.close(event.canvas.figure)
            return

        if key == "home":
            self.anchor_idx = 0
            self.next_action = "refresh"
            plt.close(event.canvas.figure)
            return

        if key == "end":
            self.anchor_idx = len(self.df) - 1
            self.next_action = "refresh"
            plt.close(event.canvas.figure)
            return

        if key == "s":
            self._save_current()
            return

        if key in {"q", "escape"}:
            self.next_action = "quit"
            plt.close(event.canvas.figure)
            return

    def _draw_once(self):
        plot_df = self._current_slice()
        if plot_df.empty:
            print("표시할 데이터가 없습니다.")
            return

        anchor_date = pd.to_datetime(plot_df.iloc[-1]["date"])
        start_date = pd.to_datetime(plot_df.iloc[0]["date"])
        self.current_anchor_date = anchor_date

        mpf_df = _prepare_ohlcv(plot_df)
        addplots = _build_addplots(plot_df, timeframe=self.timeframe)

        title = _make_title(
            code=self.code,
            name=self.name,
            timeframe=self.timeframe,
            anchor_date=anchor_date,
            start_date=start_date,
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

        self.current_fig = fig

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

            _add_last_bar_info_box(main_ax, plot_df, timeframe=self.timeframe)
            _shrink_candle_side_margins(axes, len(mpf_df), ratio=1 / 3)
            _apply_custom_xaxis_labels(axes, mpf_df.index, timeframe=self.timeframe)

        fig.subplots_adjust(top=0.88, bottom=0.22, left=0.07, right=0.98)

        info_text = (
            "←/→ : 이전/다음 1봉   "
            "↑/↓ : 이전/다음 10봉   "
            "Home/End : 처음/끝   "
            "S : 저장   "
            "Q/Esc : 종료"
        )
        fig.text(
            0.5,
            0.04,
            info_text,
            ha="center",
            va="bottom",
            fontsize=9,
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
        )

        fig.canvas.mpl_connect("key_press_event", self._on_key)

        self.next_action = "quit"
        plt.show()

    def run(self):
        while True:
            self._draw_once()
            if self.next_action != "refresh":
                break


# =========================
# 메인
# =========================
def main():
    _configure_plot_font()

    print("=" * 60)
    print("과거 데이터 차트 탐색기")
    print("=" * 60)

    code, name = select_stock()
    target_date = _parse_target_date()
    timeframe = _parse_timeframe()

    print("\n선택 정보")
    print(f"- 종목: {name} ({code})")
    print(f"- 날짜: {target_date.strftime('%Y-%m-%d')}")
    print(f"- 봉타입: {'주봉' if timeframe == 'weekly' else '월봉'}")
    print(f"- 표시 봉 수: {LOOKBACK_BARS}")
    print("\n조작키")
    print("- ← / → : 이전/다음 1봉")
    print("- ↑ / ↓ : 이전/다음 10봉")
    print("- Home / End : 처음/끝")
    print("- S : 현재 화면 저장")
    print("- Q / Esc : 종료\n")

    explorer = HistoricalChartExplorer(
        code=code,
        name=name,
        timeframe=timeframe,
        target_date=target_date,
    )
    explorer.run()


if __name__ == "__main__":
    main()