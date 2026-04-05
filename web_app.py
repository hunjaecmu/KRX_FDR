from __future__ import annotations

import os
import html
import re
import subprocess
import sys
from datetime import date, timedelta
from random import randint
from typing import Optional

import pandas as pd
import streamlit as st

try:
    from streamlit_image_select import image_select

    IMAGE_SELECT_AVAILABLE = True
except ModuleNotFoundError:
    image_select = None
    IMAGE_SELECT_AVAILABLE = False

from config import (
    DATA_DIR,
    OUTPUT_DIR,
    TRACKING_INPUT_DIR,
    HOLDINGS_CSV,
    RECORD_FILE_OPTIONS,
)
from data_loader import load_daily, load_master, load_monthly, load_weekly
from historical_chart_viewer import LOOKBACK_BARS, build_historical_chart_figure


st.set_page_config(
    page_title="KRX FDR Dashboard",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _decode_log_bytes(raw_line: bytes) -> str:
    try:
        return raw_line.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw_line.decode("cp949")
        except UnicodeDecodeError:
            return raw_line.decode("utf-8", errors="replace")


def _append_log_text(logs: list[str], text: str) -> None:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    for part in normalized.split("\n"):
        logs.append(part)


def _render_log_html_box(lines: list[str], max_lines: int = 500, css_class: str = "log-box") -> str:
    tail = "\n".join(lines[-max_lines:])
    body = html.escape(tail).replace("\n", "<br>")
    return f"<div class='{css_class}'><div class='log-content'>{body}</div></div>"


def _render_live_log(live_placeholder, logs: list[str], max_lines: int = 24) -> None:
    # Keep live output viewport-sized so the newest line stays at the bottom.
    live_placeholder.markdown(
        _render_log_html_box(logs, max_lines=max_lines, css_class="log-box live-log-box"),
        unsafe_allow_html=True,
    )


def run_data_store_and_collect_logs() -> tuple[list[str], int]:
    project_root = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(project_root, "data_store.py")
    command = [sys.executable, "-u", script_path]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    logs: list[str] = []
    process = subprocess.Popen(
        command,
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=False,
        bufsize=0,
        env=env,
    )

    live = st.empty()
    progress = st.progress(0.0, text="대기 중")
    status = st.empty()

    raw_total = None
    derived_total = None
    if process.stdout is not None:
        while True:
            raw_line = process.stdout.readline()
            if not raw_line:
                if process.poll() is not None:
                    break
                continue

            line_text = _decode_log_bytes(raw_line)
            _append_log_text(logs, line_text)
            _render_live_log(live, logs)

            current_line = logs[-1] if logs else ""

            raw_match = re.search(r"\[RAW\s+(\d+)/(\d+)\]", current_line)
            if raw_match:
                raw_idx = int(raw_match.group(1))
                raw_total = int(raw_match.group(2))
                denom = (raw_total * 2) if raw_total > 0 else 1
                progress_val = min(max(raw_idx / denom, 0.0), 1.0)
                progress.progress(progress_val, text=f"RAW 단계: {raw_idx}/{raw_total}")
                status.info(f"현재 진행: RAW {raw_idx}/{raw_total}")

            derived_match = re.search(r"\[DERIVED\s+(\d+)/(\d+)\]", current_line)
            if derived_match:
                derived_idx = int(derived_match.group(1))
                derived_total = int(derived_match.group(2))
                total = derived_total if derived_total > 0 else 1
                progress_val = min(max((total + derived_idx) / (total * 2), 0.0), 1.0)
                progress.progress(progress_val, text=f"DERIVED 단계: {derived_idx}/{derived_total}")
                status.info(f"현재 진행: DERIVED {derived_idx}/{derived_total}")

    return_code = process.wait()
    if return_code == 0:
        progress.progress(1.0, text="완료")
        status.success("데이터 업데이트가 완료되었습니다.")
    else:
        status.error(f"데이터 업데이트 실패 (종료 코드: {return_code})")

    # 실행 완료 후 라이브 로그 placeholder를 비워, 하단 최종 로그 박스와 중복 렌더링되지 않게 한다.
    live.empty()

    return logs, return_code


def run_scan_market_and_collect_logs(scan_progress_box) -> tuple[list[str], int]:
    project_root = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(project_root, "scripts", "scan_market.py")
    command = [sys.executable, "-u", script_path]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    logs: list[str] = []
    process = subprocess.Popen(
        command,
        cwd=project_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=False,
        bufsize=0,
        env=env,
    )

    live = st.empty()
    scan_done = 0
    scan_total = 1
    chart_done = 0
    chart_total = 1

    if process.stdout is not None:
        while True:
            raw_line = process.stdout.readline()
            if not raw_line:
                if process.poll() is not None:
                    break
                continue

            line_text = _decode_log_bytes(raw_line)
            _append_log_text(logs, line_text)
            _render_live_log(live, logs)

            current_line = next((x for x in reversed(logs) if str(x).strip()), "")

            scan_match = re.search(r"\[SCAN\]\s*진행률:\s*(\d+)/(\d+)", current_line)
            if scan_match:
                scan_done = int(scan_match.group(1))
                scan_total = int(scan_match.group(2)) if int(scan_match.group(2)) > 0 else 1

            chart_match = re.search(r"\[CHART\]\s*생성중\s*(\d+)/(\d+)", current_line)
            if chart_match:
                chart_done = int(chart_match.group(1))
                chart_total = int(chart_match.group(2)) if int(chart_match.group(2)) > 0 else 1

            scan_part = min(max(scan_done / scan_total, 0.0), 1.0)
            chart_part = min(max(chart_done / chart_total, 0.0), 1.0)
            progress_val = min(max((scan_part * 0.5) + (chart_part * 0.5), 0.0), 1.0)
            st.session_state.scan_progress_value = progress_val
            st.session_state.scan_progress_text = f"SCAN {scan_done}/{scan_total} | CHART {chart_done}/{chart_total}"
            scan_progress_box.progress(progress_val, text=st.session_state.scan_progress_text)

    return_code = process.wait()
    if return_code == 0:
        st.session_state.scan_progress_value = 1.0
        st.session_state.scan_progress_text = "SCAN 완료 | CHART 완료"
        scan_progress_box.progress(1.0, text=st.session_state.scan_progress_text)
    else:
        st.session_state.scan_progress_text = "스캔 실패"
        scan_progress_box.progress(float(st.session_state.scan_progress_value), text=st.session_state.scan_progress_text)

    live.empty()
    return logs, return_code


def build_mock_chart_data(days: int = 80) -> pd.DataFrame:
    today = date.today()
    points = []
    base = 100
    for i in range(days):
        dt = today - timedelta(days=(days - i))
        base += randint(-3, 4)
        points.append({"date": dt, "close": max(base, 10)})
    return pd.DataFrame(points).set_index("date")


@st.cache_data(show_spinner=False, ttl=300)
def get_master_table() -> pd.DataFrame:
    try:
        mdf = load_master().copy()
    except Exception:
        return pd.DataFrame(columns=["code", "name", "market"])

    if "code" in mdf.columns:
        mdf["code"] = (
            mdf["code"]
            .astype(str)
            .str.strip()
            .str.replace(r"\.0$", "", regex=True)
            .str.zfill(6)
        )
    if "name" in mdf.columns:
        mdf["name"] = mdf["name"].astype(str).str.strip()
    return mdf


def _parse_month_day_text(month_day_text: str) -> tuple[int, int]:
    s = str(month_day_text).strip().replace(" ", "")
    if not s:
        raise ValueError("월일 입력값이 비어 있습니다.")

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
            raise ValueError("월일 형식이 올바르지 않습니다. 예: 0315 또는 3-15")
        month = int(m.group(1))
        day = int(m.group(2))

    pd.Timestamp(year=2000, month=month, day=day)
    return month, day


def _resolve_stock_by_mode(master: pd.DataFrame, mode: str, code_input: str, prefix_input: str, picked_label: str) -> tuple[str, str]:
    if mode == "코드 직접입력":
        code = str(code_input).strip().zfill(6)
        hit = master[master["code"] == code]
        if hit.empty:
            raise ValueError("해당 코드의 종목이 없습니다.")
        row = hit.iloc[0]
        return str(row["code"]).zfill(6), str(row["name"])

    prefix = str(prefix_input).strip()
    if len(prefix) < 2:
        raise ValueError("종목명 앞 2글자를 입력하세요.")

    candidates = master[master["name"].astype(str).str.startswith(prefix)].copy()
    if candidates.empty:
        raise ValueError("일치하는 종목이 없습니다.")

    label_to_row = {
        f"{str(row['name']).strip()} ({str(row['code']).zfill(6)})": row
        for _, row in candidates.sort_values(["name", "code"]).iterrows()
    }
    if picked_label not in label_to_row:
        raise ValueError("추천 종목 리스트에서 종목을 선택하세요.")

    selected = label_to_row[picked_label]
    return str(selected["code"]).zfill(6), str(selected["name"])


@st.cache_data(show_spinner=False, ttl=300)
def _get_timeframe_dates(code: str, timeframe: str) -> list[pd.Timestamp]:
    if timeframe == "weekly":
        df = load_weekly(code)
    elif timeframe == "monthly":
        df = load_monthly(code)
    else:
        raise ValueError("timeframe must be 'weekly' or 'monthly'")

    if df is None or df.empty or "date" not in df.columns:
        return []

    dates = pd.to_datetime(df["date"], errors="coerce").dropna().sort_values().tolist()
    return [pd.to_datetime(x) for x in dates]


def _shift_anchor_target_date(code: str, timeframe: str, current_target_date: pd.Timestamp, step: int) -> pd.Timestamp:
    dates = _get_timeframe_dates(code, timeframe)
    if not dates:
        raise ValueError("이동할 데이터가 없습니다.")

    cur_ts = pd.to_datetime(current_target_date)
    base_idx = 0
    for i, d in enumerate(dates):
        if d <= cur_ts:
            base_idx = i
        else:
            break

    new_idx = max(0, min(len(dates) - 1, base_idx + int(step)))
    return pd.to_datetime(dates[new_idx])


def _extract_last_bar_snapshot(code: str, timeframe: str, target_date: pd.Timestamp) -> tuple[pd.Timestamp, float]:
    if timeframe == "weekly":
        df = load_weekly(code)
    elif timeframe == "monthly":
        df = load_monthly(code)
    else:
        raise ValueError("timeframe must be 'weekly' or 'monthly'")

    if df is None or df.empty:
        raise ValueError("불러올 데이터가 없습니다.")
    if "date" not in df.columns or "close" not in df.columns:
        raise ValueError("저장에 필요한 date/close 컬럼이 없습니다.")

    work = df.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work = work.dropna(subset=["date", "close"]).sort_values("date")
    if work.empty:
        raise ValueError("저장에 필요한 유효 데이터가 없습니다.")

    valid = work[work["date"] <= pd.to_datetime(target_date)]
    if valid.empty:
        raise ValueError("입력한 날짜 이전 데이터가 없습니다.")

    row = valid.iloc[-1]
    return pd.to_datetime(row["date"]), float(row["close"])


def _append_tracking_row(file_path: str, row: dict) -> None:
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    row_df = pd.DataFrame([row])
    if os.path.isfile(file_path):
        try:
            old_df = pd.read_csv(file_path, dtype=str)
            out_df = pd.concat([old_df, row_df], ignore_index=True)
        except Exception:
            out_df = row_df
    else:
        out_df = row_df

    out_df.to_csv(file_path, index=False, encoding="utf-8-sig")


def _record_display_options() -> list[str]:
    return [f"{label}: {fname.replace('.csv', '')}" for label, fname in RECORD_FILE_OPTIONS]


def _record_label_to_filename(display_label: str) -> str:
    left_label = str(display_label).split(":", 1)[0].strip()
    return dict(RECORD_FILE_OPTIONS).get(left_label, "MA10_W_Break.csv")


def _interest_watch_month_token(ref_date: Optional[date] = None) -> str:
    base = ref_date if ref_date is not None else date.today()
    return f"{base.year:04d}{base.month:02d}"


def _interest_watch_monthly_filename(month_token: str) -> str:
    return f"watch_{str(month_token).strip()}.csv"


def _interest_watch_monthly_path(month_token: Optional[str] = None) -> str:
    token = str(month_token).strip() if month_token else _interest_watch_month_token()
    return os.path.join(TRACKING_INPUT_DIR, _interest_watch_monthly_filename(token))


def _parse_interest_watch_month_from_filename(filename: str) -> Optional[str]:
    name = str(filename).strip()
    m1 = re.match(r"^watch_(\d{6})\.csv$", name)
    if m1:
        return m1.group(1)
    m2 = re.match(r"^(\d{6})\.csv$", name)
    if m2:
        return m2.group(1)
    return None


def _interest_watch_file_options(tracking_dir: str) -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    current_month = _interest_watch_month_token()
    current_path = _interest_watch_monthly_path(current_month)
    options.append((f"{current_month} (현재월)", current_path))

    if not os.path.isdir(tracking_dir):
        return options

    month_map: dict[str, str] = {}
    legacy_path = None
    for fname in os.listdir(tracking_dir):
        full_path = os.path.join(tracking_dir, fname)
        if not os.path.isfile(full_path):
            continue
        if str(fname).lower() == "watch.csv":
            legacy_path = full_path
            continue

        month_token = _parse_interest_watch_month_from_filename(str(fname))
        if month_token:
            month_map[month_token] = full_path

    for month_token in sorted(month_map.keys(), reverse=True):
        display = f"{month_token}"
        if month_token == current_month:
            display = f"{month_token} (현재월)"
        pair = (display, month_map[month_token])
        if pair not in options:
            options.append(pair)

    if legacy_path:
        options.append(("legacy watch.csv", legacy_path))

    return options


def _infer_timeframe_from_case_key(case_key: str) -> str:
    return "weekly" if str(case_key).strip().startswith("weekly_") else "monthly"


def _default_classification_from_case_key(case_key: str) -> str:
    key = str(case_key)
    if "ma10" in key:
        return "10이평"
    if "ma120" in key:
        return "120이평"
    if "ma180" in key:
        return "180이평"
    return "240이평"


def _render_stock_lookup_panel(save_mode: str) -> None:
    # save_mode: "interest" or "record"
    panel_title = "관심종목 저장" if save_mode == "interest" else "기록 데이터 저장"
    st.caption("historical_chart_viewer.py와 동일한 입력 방식으로 차트를 조회합니다.")

    master = get_master_table()
    if master.empty or not {"code", "name"}.issubset(set(master.columns)):
        st.error("종목 마스터 데이터를 불러오지 못했습니다.")
        return

    prefix = "interest" if save_mode == "interest" else "record"
    state_key = f"historical_view_state_{prefix}"

    c1, c2 = st.columns([1.2, 1.8])
    with c1:
        stock_mode = st.radio(
            "종목 선택 방식",
            options=["코드 직접입력", "종목명 2글자 검색"],
            horizontal=False,
            key=f"{prefix}_stock_mode",
        )

        stock_code_input = st.text_input(
            "종목코드 입력 (예: 005930)",
            value="",
            max_chars=6,
            disabled=(stock_mode != "코드 직접입력"),
            key=f"{prefix}_stock_code",
        )

        prefix_input = st.text_input(
            "종목명 앞 2글자 입력",
            value="",
            max_chars=20,
            disabled=(stock_mode != "종목명 2글자 검색"),
            key=f"{prefix}_name_prefix",
        )

        candidate_labels: list[str] = []
        if stock_mode == "종목명 2글자 검색" and len(prefix_input.strip()) >= 2:
            filtered = master[master["name"].astype(str).str.startswith(prefix_input.strip())].copy()
            if not filtered.empty:
                filtered = filtered.sort_values(["name", "code"])
                candidate_labels = [
                    f"{str(r['name']).strip()} ({str(r['code']).zfill(6)})"
                    for _, r in filtered.iterrows()
                ]

        stock_pick = st.selectbox(
            "추천 종목 리스트",
            options=candidate_labels if candidate_labels else [""],
            index=0,
            disabled=(stock_mode != "종목명 2글자 검색"),
            key=f"{prefix}_stock_pick",
        )

    with c2:
        current_year = date.today().year
        year_input = st.number_input(
            "연도 입력 (예: 2026)",
            min_value=1900,
            max_value=2100,
            value=current_year,
            step=1,
            key=f"{prefix}_year",
        )
        month_day_input = st.text_input(
            "월일 입력 (예: 0315 또는 3-15)",
            value=date.today().strftime("%m%d"),
            key=f"{prefix}_month_day",
        )
        timeframe_label = st.radio(
            "봉 타입 선택",
            options=["1: 주봉", "2: 월봉"],
            horizontal=True,
            key=f"{prefix}_timeframe",
        )

        run_col1, run_col2, run_col3 = st.columns(3)
        with run_col1:
            run_lookup = st.button("종목 차트 조회", type="primary", use_container_width=True, key=f"{prefix}_run_lookup")
        with run_col2:
            move_prev = st.button("이전 1봉", use_container_width=True, key=f"{prefix}_move_prev")
        with run_col3:
            move_next = st.button("다음 1봉", use_container_width=True, key=f"{prefix}_move_next")

    trigger_error = None
    if run_lookup:
        try:
            code, name = _resolve_stock_by_mode(
                master=master,
                mode=stock_mode,
                code_input=stock_code_input,
                prefix_input=prefix_input,
                picked_label=stock_pick,
            )

            month, day = _parse_month_day_text(month_day_input)
            target_date = pd.Timestamp(year=int(year_input), month=month, day=day)
            timeframe = "weekly" if timeframe_label.startswith("1") else "monthly"

            st.session_state[state_key] = {
                "code": code,
                "name": name,
                "timeframe": timeframe,
                "target_date": target_date.strftime("%Y-%m-%d"),
            }
        except Exception as e:
            trigger_error = str(e)

    if move_prev or move_next:
        state = st.session_state.get(state_key)
        if state is None:
            trigger_error = "먼저 '종목 차트 조회'를 실행하세요."
        else:
            try:
                step = -1 if move_prev else 1
                shifted_target = _shift_anchor_target_date(
                    code=str(state["code"]),
                    timeframe=str(state["timeframe"]),
                    current_target_date=pd.to_datetime(state["target_date"]),
                    step=step,
                )
                state["target_date"] = shifted_target.strftime("%Y-%m-%d")
                st.session_state[state_key] = state
            except Exception as e:
                trigger_error = str(e)

    if trigger_error:
        st.error(trigger_error)

    state = st.session_state.get(state_key)
    if not state:
        return

    try:
        fig, anchor_date = build_historical_chart_figure(
            code=str(state["code"]),
            name=str(state["name"]),
            timeframe=str(state["timeframe"]),
            target_date=pd.to_datetime(state["target_date"]),
            lookback_bars=LOOKBACK_BARS,
        )

        state["target_date"] = anchor_date.strftime("%Y-%m-%d")
        st.session_state[state_key] = state

        st.success(
            f"{state['name']} ({state['code']}) | 기준봉 {anchor_date.strftime('%Y-%m-%d')} | "
            f"{'주봉' if state['timeframe'] == 'weekly' else '월봉'} {LOOKBACK_BARS}봉"
        )
        st.pyplot(fig, use_container_width=True)

        st.markdown("---")
        st.markdown(f"#### {panel_title}")

        save_col1, save_col2 = st.columns([1.1, 1.9])
        with save_col1:
            classification = st.selectbox(
                "분류",
                options=["10이평", "120이평", "180이평", "240이평"],
                index=0,
                key=f"{prefix}_classification",
            )
        with save_col2:
            memo_text = st.text_input("메모", value="", key=f"{prefix}_memo")
            record_file_label = None
            if save_mode == "record":
                record_file_label = st.selectbox(
                    "기록 파일명",
                    options=_record_display_options(),
                    index=0,
                    key=f"{prefix}_record_file",
                    help="tracking 폴더 아래 고정 파일명 중 하나로 저장됩니다.",
                )
            else:
                current_watch_path = _interest_watch_monthly_path()
                st.caption(f"관심 저장 파일: {os.path.basename(current_watch_path)}")

        if st.button("현재 차트 데이터 저장", use_container_width=True, key=f"{prefix}_save"):
            try:
                snap_date, snap_close = _extract_last_bar_snapshot(
                    code=str(state["code"]),
                    timeframe=str(state["timeframe"]),
                    target_date=pd.to_datetime(state["target_date"]),
                )

                row = {
                    "종목명": str(state["name"]),
                    "종목코드": str(state["code"]),
                    "종목의 마지막 봉의 날짜": snap_date.strftime("%Y-%m-%d"),
                    "주봉 or 월봉 선택": "주봉" if str(state["timeframe"]) == "weekly" else "월봉",
                    "현시점 종가": f"{snap_close:.2f}",
                    "분류": classification,
                    "메모": memo_text,
                }

                tracking_dir = TRACKING_INPUT_DIR
                if save_mode == "interest":
                    target_file = _interest_watch_monthly_path()
                else:
                    target_file = os.path.join(tracking_dir, _record_label_to_filename(str(record_file_label)))

                _append_tracking_row(target_file, row)
                st.success(f"저장 완료: {target_file}")
            except Exception as save_e:
                st.error(f"저장 실패: {save_e}")
    except Exception as e:
        st.error(str(e))


def _render_interest_watch_data() -> None:
    st.caption("tracking 폴더의 월별 관심 종목 CSV 데이터를 조회합니다.")
    tracking_dir = TRACKING_INPUT_DIR
    os.makedirs(tracking_dir, exist_ok=True)

    watch_options = _interest_watch_file_options(tracking_dir)
    watch_option_labels = [x[0] for x in watch_options]
    watch_option_map = {label: path for label, path in watch_options}

    default_label = next((label for label, _ in watch_options if "(현재월)" in label), watch_option_labels[0])
    selected_watch_label = st.selectbox(
        "관심 파일 선택",
        options=watch_option_labels,
        index=watch_option_labels.index(default_label),
        key="watch_file_select",
    )
    watch_path = watch_option_map[selected_watch_label]
    st.markdown("#### 관심 데이터")
    if os.path.isfile(watch_path):
        try:
            wdf = pd.read_csv(watch_path, dtype=str)
            st.caption(f"파일: {watch_path}")

            if wdf.empty:
                st.info("선택한 관심 파일 데이터가 비어 있습니다.")
                return

            # Normalize required fields saved by menu 4.
            wdf = wdf.fillna("")
            wdf = wdf.reset_index(drop=True)
            if "종목코드" not in wdf.columns:
                st.error("선택한 관심 파일에 종목코드 컬럼이 없습니다.")
                return
            if "종목명" not in wdf.columns:
                st.error("선택한 관심 파일에 종목명 컬럼이 없습니다.")
                return

            wdf["종목코드"] = (
                wdf["종목코드"]
                .astype(str)
                .str.strip()
                .str.replace(r"\.0$", "", regex=True)
                .str.zfill(6)
            )
            if "종목의 마지막 봉의 날짜" in wdf.columns:
                wdf["종목의 마지막 봉의 날짜"] = pd.to_datetime(
                    wdf["종목의 마지막 봉의 날짜"], errors="coerce"
                ).dt.strftime("%Y-%m-%d")
            else:
                wdf["종목의 마지막 봉의 날짜"] = ""

            if "주봉 or 월봉 선택" not in wdf.columns:
                wdf["주봉 or 월봉 선택"] = "주봉"

            total_rows = len(wdf)
            page_size = 10
            total_pages = max(1, (total_rows + page_size - 1) // page_size)

            page_key = "watch_page_idx"
            if page_key not in st.session_state:
                st.session_state[page_key] = 0
            st.session_state[page_key] = max(0, min(int(st.session_state[page_key]), total_pages - 1))

            nav1, nav2, nav3 = st.columns([1, 1, 4])
            with nav1:
                if st.button("이전 10개", use_container_width=True, key="watch_prev_page"):
                    st.session_state[page_key] = max(0, int(st.session_state[page_key]) - 1)
            with nav2:
                if st.button("다음 10개", use_container_width=True, key="watch_next_page"):
                    st.session_state[page_key] = min(total_pages - 1, int(st.session_state[page_key]) + 1)
            with nav3:
                st.caption(f"페이지 {int(st.session_state[page_key]) + 1}/{total_pages} | 총 {total_rows}건")

            start = int(st.session_state[page_key]) * page_size
            end = min(start + page_size, total_rows)
            page_df = wdf.iloc[start:end].copy().reset_index(drop=True)

            selected_key = "watch_selected_row"
            selected_idx_key = "watch_selected_table_idx"

            table_rows = []
            for i, row in page_df.iterrows():
                real_idx = start + i
                tf_text = str(row.get("주봉 or 월봉 선택", "")).strip()
                anchor_date_text = str(row.get("종목의 마지막 봉의 날짜", "")).strip()
                timeframe_value = "weekly" if "주" in tf_text or tf_text.lower().startswith("w") else "monthly"
                code_value = str(row.get("종목코드", "")).strip().zfill(6)

                anchor_close = _timeframe_close_at_or_before(code_value, timeframe_value, anchor_date_text)
                latest_metrics = _latest_timeframe_ma10_metrics(code_value, timeframe_value)
                latest_close = latest_metrics.get("close")

                change_pct = None
                if anchor_close is not None and latest_close is not None and float(anchor_close) != 0.0:
                    change_pct = ((float(latest_close) / float(anchor_close)) - 1.0) * 100.0

                table_rows.append(
                    {
                        "종목명": str(row.get("종목명", "")).strip(),
                        "종목코드": code_value,
                        "봉타입": tf_text,
                        "기준봉 날짜": anchor_date_text,
                        "기준봉 종가": anchor_close,
                        "최신 종가": latest_close,
                        "변화율": change_pct,
                        "분류": str(row.get("분류", "")),
                        "메모": str(row.get("메모", "")),
                        "__raw_index": int(real_idx),
                    }
                )

            action_df = pd.DataFrame(table_rows)
            action_view = action_df.drop(columns=["__raw_index"]).copy()
            action_view.index = action_view.index + start + 1
            action_view.index.name = "No"

            def _watch_pos_neg_color(v):
                if pd.isna(v):
                    return ""
                if float(v) > 0:
                    return "color: #d32f2f;"
                if float(v) < 0:
                    return "color: #1565c0;"
                return ""

            styled_action = (
                action_view.style
                .format(
                    {
                        "기준봉 종가": lambda x: "" if pd.isna(x) else f"{x:,.0f}",
                        "최신 종가": lambda x: "" if pd.isna(x) else f"{x:,.0f}",
                        "변화율": lambda x: "" if pd.isna(x) else f"{x:.2f}%",
                    }
                )
                .set_properties(subset=["기준봉 종가", "최신 종가", "변화율"], **{"text-align": "right"})
                .set_properties(subset=["종목코드", "봉타입", "기준봉 날짜"], **{"text-align": "center"})
                .map(_watch_pos_neg_color, subset=["변화율"])
            )

            selected_rows = []
            try:
                table_event = st.dataframe(
                    styled_action,
                    use_container_width=True,
                    on_select="rerun",
                    selection_mode="single-row",
                    key="watch_action_table",
                )
                if table_event is not None and hasattr(table_event, "selection"):
                    selected_rows = list(getattr(table_event.selection, "rows", []) or [])
            except TypeError:
                st.dataframe(styled_action, use_container_width=True)

            c1, c2 = st.columns([1, 5])
            with c1:
                chart_clicked = st.button("차트", key="watch_action_chart", use_container_width=True)
            with c2:
                delete_clicked = st.button("삭제", key="watch_action_delete", use_container_width=True)

            if selected_rows:
                st.session_state[selected_idx_key] = int(start + int(selected_rows[0]))

            selected_global_idx = st.session_state.get(selected_idx_key)
            if selected_global_idx is not None and 0 <= int(selected_global_idx) < len(wdf):
                chosen = wdf.iloc[int(selected_global_idx)]
                chosen_name = str(chosen.get("종목명", "")).strip() or str(chosen.get("종목코드", "")).strip()
                st.caption(f"선택된 종목: {chosen_name} ({str(chosen.get('종목코드', '')).zfill(6)})")

                if chart_clicked:
                    st.session_state[selected_key] = {
                        "code": str(chosen.get("종목코드", "")).strip().zfill(6),
                        "name": str(chosen.get("종목명", "")).strip(),
                        "date": str(chosen.get("종목의 마지막 봉의 날짜", "")).strip(),
                        "timeframe_text": str(chosen.get("주봉 or 월봉 선택", "")).strip(),
                        "memo": str(chosen.get("메모", "")),
                        "row_idx": int(selected_global_idx),
                    }

                if delete_clicked:
                    st.session_state["watch_delete_pending_idx"] = int(selected_global_idx)
                    st.session_state["watch_delete_pending_name"] = chosen_name
            else:
                if chart_clicked or delete_clicked:
                    st.warning("관심종목 데이터 테이블에서 먼저 종목 1개를 선택하세요.")

            pending_idx = st.session_state.get("watch_delete_pending_idx")
            if pending_idx is not None:
                pending_name = st.session_state.get("watch_delete_pending_name", "")
                confirm_cols = st.columns([4, 1, 1])
                with confirm_cols[0]:
                    st.warning(f"삭제하시겠습니까? {'(' + pending_name + ')' if pending_name else ''}")
                with confirm_cols[1]:
                    if st.button("예", key="watch_delete_yes", use_container_width=True):
                        try:
                            drop_idx = int(pending_idx)
                            if 0 <= drop_idx < len(wdf):
                                updated = wdf.drop(index=drop_idx).reset_index(drop=True)
                                updated.to_csv(watch_path, index=False, encoding="utf-8-sig")
                            st.session_state.pop("watch_delete_pending_idx", None)
                            st.session_state.pop("watch_delete_pending_name", None)
                            st.rerun()
                        except Exception as del_e:
                            st.error(f"삭제 실패: {del_e}")
                with confirm_cols[2]:
                    if st.button("아니오", key="watch_delete_no", use_container_width=True):
                        st.session_state.pop("watch_delete_pending_idx", None)
                        st.session_state.pop("watch_delete_pending_name", None)
                        st.rerun()

            st.markdown("---")
            st.markdown("#### 선택 종목 차트")

            picked = st.session_state.get(selected_key)
            if not picked:
                st.info("종목을 선택하고 차트 버튼을 누르세요")
                return

            timeframe_text = str(picked.get("timeframe_text", "")).strip()
            timeframe = "weekly" if "주" in timeframe_text or timeframe_text.lower().startswith("w") else "monthly"

            target_date_text = str(picked.get("date", "")).strip()
            try:
                target_date = pd.to_datetime(target_date_text)
            except Exception:
                target_date = pd.Timestamp(date.today())

            chart_state_key = "watch_chart_state"
            if chart_state_key not in st.session_state:
                st.session_state[chart_state_key] = {
                    "code": str(picked.get("code", "")).zfill(6),
                    "name": str(picked.get("name", "")),
                    "timeframe": timeframe,
                    "target_date": pd.to_datetime(target_date).strftime("%Y-%m-%d"),
                    "origin_target_date": pd.to_datetime(target_date).strftime("%Y-%m-%d"),
                }

            state = st.session_state[chart_state_key]
            if (
                str(state.get("code")) != str(picked.get("code", "")).zfill(6)
                or str(state.get("timeframe")) != timeframe
                or str(state.get("origin_target_date")) != pd.to_datetime(target_date).strftime("%Y-%m-%d")
            ):
                state = {
                    "code": str(picked.get("code", "")).zfill(6),
                    "name": str(picked.get("name", "")),
                    "timeframe": timeframe,
                    "target_date": pd.to_datetime(target_date).strftime("%Y-%m-%d"),
                    "origin_target_date": pd.to_datetime(target_date).strftime("%Y-%m-%d"),
                }
                st.session_state[chart_state_key] = state

            memo_row_idx = picked.get("row_idx")
            memo_state_key = "watch_chart_memo_text"
            memo_row_state_key = "watch_chart_memo_row_idx"
            if (
                memo_state_key not in st.session_state
                or st.session_state.get(memo_row_state_key) != memo_row_idx
            ):
                default_memo = ""
                if isinstance(memo_row_idx, int) and 0 <= int(memo_row_idx) < len(wdf):
                    default_memo = str(wdf.iloc[int(memo_row_idx)].get("메모", ""))
                else:
                    default_memo = str(picked.get("memo", ""))
                st.session_state[memo_state_key] = default_memo
                st.session_state[memo_row_state_key] = memo_row_idx

            mv1, mv2, mv3, mv4, mv5 = st.columns([1, 1, 1, 4, 1])
            with mv1:
                move_prev = st.button("이전 1봉", key="watch_chart_prev", use_container_width=True)
            with mv2:
                move_home = st.button("처음위치로", key="watch_chart_home", use_container_width=True)
            with mv3:
                move_next = st.button("다음 1봉", key="watch_chart_next", use_container_width=True)
            with mv4:
                memo_input = st.text_area(
                    "메모",
                    key=memo_state_key,
                    label_visibility="collapsed",
                    placeholder="메모를 입력하세요",
                    height=68,
                )
            with mv5:
                memo_save_clicked = st.button("메모저장", key="watch_chart_memo_save", use_container_width=True)

            st.markdown(
                """
<style>
div[data-testid="stTextArea"] textarea {
    white-space: pre;
    overflow-x: auto;
    overflow-y: auto;
    overflow-wrap: normal;
    word-break: keep-all;
}
</style>
""",
                unsafe_allow_html=True,
            )

            if memo_save_clicked:
                try:
                    if "메모" not in wdf.columns:
                        wdf["메모"] = ""

                    if not (isinstance(memo_row_idx, int) and 0 <= int(memo_row_idx) < len(wdf)):
                        st.error("메모 저장 대상 행을 찾지 못했습니다.")
                    else:
                        wdf.loc[int(memo_row_idx), "메모"] = str(memo_input)
                        wdf.to_csv(watch_path, index=False, encoding="utf-8-sig")
                        if isinstance(picked, dict):
                            picked["memo"] = str(memo_input)
                            st.session_state[selected_key] = picked
                        st.success("메모 저장 완료")
                except Exception as memo_e:
                    st.error(f"메모 저장 실패: {memo_e}")

            if move_home:
                state["target_date"] = str(state.get("origin_target_date", state.get("target_date")))
                st.session_state[chart_state_key] = state

            if move_prev or move_next:
                try:
                    step = -1 if move_prev else 1
                    shifted = _shift_anchor_target_date(
                        code=str(state["code"]),
                        timeframe=str(state["timeframe"]),
                        current_target_date=pd.to_datetime(state["target_date"]),
                        step=step,
                    )
                    state["target_date"] = shifted.strftime("%Y-%m-%d")
                    st.session_state[chart_state_key] = state
                except Exception as move_e:
                    st.error(f"차트 이동 실패: {move_e}")

            try:
                fig, anchor_date = build_historical_chart_figure(
                    code=str(state["code"]),
                    name=str(state["name"]),
                    timeframe=str(state["timeframe"]),
                    target_date=pd.to_datetime(state["target_date"]),
                    lookback_bars=LOOKBACK_BARS,
                )
                state["target_date"] = anchor_date.strftime("%Y-%m-%d")
                st.session_state[chart_state_key] = state

                _add_anchor_guides_to_chart(
                    fig=fig,
                    code=str(state["code"]),
                    timeframe=str(state["timeframe"]),
                    current_target_date_text=str(state["target_date"]),
                    origin_target_date_text=str(state.get("origin_target_date", state["target_date"])),
                )

                st.success(
                    f"{state['name']} ({state['code']}) | 기준봉 {anchor_date.strftime('%Y-%m-%d')} | "
                    f"{'주봉' if state['timeframe'] == 'weekly' else '월봉'} {LOOKBACK_BARS}봉"
                )
                st.pyplot(fig, use_container_width=True)
            except Exception as chart_e:
                st.error(f"차트 생성 실패: {chart_e}")
        except Exception as e:
            st.error(f"관심 파일 조회 실패: {e}")
    else:
        st.info("선택한 관심 파일이 아직 생성되지 않았습니다.")


def _render_saved_pattern_data() -> None:
    st.caption("tracking 폴더의 기록 CSV 데이터를 조회합니다.")
    tracking_dir = TRACKING_INPUT_DIR
    os.makedirs(tracking_dir, exist_ok=True)

    summary_rows = []
    for label, filename in RECORD_FILE_OPTIONS:
        path = os.path.join(tracking_dir, filename)
        count = 0
        if os.path.isfile(path):
            try:
                count = int(len(pd.read_csv(path)))
            except Exception:
                count = 0
        summary_rows.append({"구분": label, "파일명": filename, "행수": count})

    st.markdown("#### 기록 파일 요약")
    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

    st.markdown("#### 기록 데이터")
    record_file_label = st.selectbox(
        "기록 파일 선택",
        options=_record_display_options(),
        index=0,
        key="pattern_view_record_file",
    )
    selected_record_path = os.path.join(tracking_dir, _record_label_to_filename(record_file_label))
    if os.path.isfile(selected_record_path):
        try:
            rdf = pd.read_csv(selected_record_path, dtype=str)
            st.caption(f"파일: {selected_record_path}")

            if rdf.empty:
                st.info("선택한 기록 파일 데이터가 비어 있습니다.")
                return

            rdf = rdf.fillna("").reset_index(drop=True)
            if "종목코드" not in rdf.columns:
                st.error("기록 데이터에 종목코드 컬럼이 없습니다.")
                return
            if "종목명" not in rdf.columns:
                st.error("기록 데이터에 종목명 컬럼이 없습니다.")
                return

            rdf["종목코드"] = (
                rdf["종목코드"]
                .astype(str)
                .str.strip()
                .str.replace(r"\.0$", "", regex=True)
                .str.zfill(6)
            )
            if "종목의 마지막 봉의 날짜" in rdf.columns:
                rdf["종목의 마지막 봉의 날짜"] = pd.to_datetime(
                    rdf["종목의 마지막 봉의 날짜"], errors="coerce"
                ).dt.strftime("%Y-%m-%d")
            else:
                rdf["종목의 마지막 봉의 날짜"] = ""

            if "주봉 or 월봉 선택" not in rdf.columns:
                rdf["주봉 or 월봉 선택"] = "주봉"

            total_rows = len(rdf)
            page_size = 10
            total_pages = max(1, (total_rows + page_size - 1) // page_size)

            page_key = "pattern_page_idx"
            if page_key not in st.session_state:
                st.session_state[page_key] = 0
            st.session_state[page_key] = max(0, min(int(st.session_state[page_key]), total_pages - 1))

            nav1, nav2, nav3 = st.columns([1, 1, 4])
            with nav1:
                if st.button("이전 10개", use_container_width=True, key="pattern_prev_page"):
                    st.session_state[page_key] = max(0, int(st.session_state[page_key]) - 1)
            with nav2:
                if st.button("다음 10개", use_container_width=True, key="pattern_next_page"):
                    st.session_state[page_key] = min(total_pages - 1, int(st.session_state[page_key]) + 1)
            with nav3:
                st.caption(f"페이지 {int(st.session_state[page_key]) + 1}/{total_pages} | 총 {total_rows}건")

            start = int(st.session_state[page_key]) * page_size
            end = min(start + page_size, total_rows)
            page_df = rdf.iloc[start:end].copy().reset_index(drop=True)

            selected_key = "pattern_selected_row"
            selected_idx_key = "pattern_selected_table_idx"

            table_df = page_df[[
                "종목명",
                "종목코드",
                "주봉 or 월봉 선택",
                "종목의 마지막 봉의 날짜",
                "분류",
                "메모",
            ]].copy()
            table_df.index = table_df.index + start + 1
            table_df.index.name = "No"

            pattern_table_column_config = {
                "종목명": st.column_config.TextColumn(width="small"),
                "종목코드": st.column_config.TextColumn(width="small"),
                "주봉 or 월봉 선택": st.column_config.TextColumn(width="small"),
                "종목의 마지막 봉의 날짜": st.column_config.TextColumn(width="small"),
                "분류": st.column_config.TextColumn(width="small"),
                "메모": st.column_config.TextColumn(width="large"),
            }

            selected_rows = []
            try:
                table_event = st.dataframe(
                    table_df,
                    use_container_width=True,
                    column_config=pattern_table_column_config,
                    on_select="rerun",
                    selection_mode="single-row",
                    key="pattern_action_table",
                )
                if table_event is not None and hasattr(table_event, "selection"):
                    selected_rows = list(getattr(table_event.selection, "rows", []) or [])
            except TypeError:
                st.dataframe(
                    table_df,
                    use_container_width=True,
                    column_config=pattern_table_column_config,
                )

            c1, c2 = st.columns([1, 5])
            with c1:
                chart_clicked = st.button("차트", key="pattern_action_chart", use_container_width=True)

            if selected_rows:
                st.session_state[selected_idx_key] = int(start + int(selected_rows[0]))

            selected_global_idx = st.session_state.get(selected_idx_key)
            if selected_global_idx is not None and 0 <= int(selected_global_idx) < len(rdf):
                chosen = rdf.iloc[int(selected_global_idx)]
                chosen_name = str(chosen.get("종목명", "")).strip() or str(chosen.get("종목코드", "")).strip()
                st.caption(f"선택된 종목: {chosen_name} ({str(chosen.get('종목코드', '')).zfill(6)})")

                if chart_clicked:
                    st.session_state[selected_key] = {
                        "code": str(chosen.get("종목코드", "")).strip().zfill(6),
                        "name": str(chosen.get("종목명", "")).strip(),
                        "date": str(chosen.get("종목의 마지막 봉의 날짜", "")).strip(),
                        "timeframe_text": str(chosen.get("주봉 or 월봉 선택", "")).strip(),
                    }
            else:
                if chart_clicked:
                    st.warning("기록 데이터 테이블에서 먼저 종목 1개를 선택하세요.")

            st.markdown("---")
            st.markdown("#### 선택 기록 차트")

            picked = st.session_state.get(selected_key)
            if not picked:
                st.info("종목을 선택하고 차트 버튼을 누르세요")
                return

            timeframe_text = str(picked.get("timeframe_text", "")).strip()
            timeframe = "weekly" if "주" in timeframe_text or timeframe_text.lower().startswith("w") else "monthly"

            target_date_text = str(picked.get("date", "")).strip()
            try:
                target_date = pd.to_datetime(target_date_text)
            except Exception:
                target_date = pd.Timestamp(date.today())

            chart_state_key = "pattern_chart_state"
            if chart_state_key not in st.session_state:
                st.session_state[chart_state_key] = {
                    "code": str(picked.get("code", "")).zfill(6),
                    "name": str(picked.get("name", "")),
                    "timeframe": timeframe,
                    "target_date": pd.to_datetime(target_date).strftime("%Y-%m-%d"),
                }

            state = st.session_state[chart_state_key]
            if (
                str(state.get("code")) != str(picked.get("code", "")).zfill(6)
                or str(state.get("timeframe")) != timeframe
                or str(state.get("origin_target_date")) != pd.to_datetime(target_date).strftime("%Y-%m-%d")
            ):
                state = {
                    "code": str(picked.get("code", "")).zfill(6),
                    "name": str(picked.get("name", "")),
                    "timeframe": timeframe,
                    "target_date": pd.to_datetime(target_date).strftime("%Y-%m-%d"),
                    "origin_target_date": pd.to_datetime(target_date).strftime("%Y-%m-%d"),
                }
                st.session_state[chart_state_key] = state

            mv1, mv2, mv3, _ = st.columns([1, 1, 1, 3])
            with mv1:
                move_prev = st.button("이전 1봉", key="pattern_chart_prev", use_container_width=True)
            with mv2:
                move_home = st.button("처음위치로", key="pattern_chart_home", use_container_width=True)
            with mv3:
                move_next = st.button("다음 1봉", key="pattern_chart_next", use_container_width=True)

            if move_home:
                state["target_date"] = str(state.get("origin_target_date", state.get("target_date")))
                st.session_state[chart_state_key] = state

            if move_prev or move_next:
                try:
                    step = -1 if move_prev else 1
                    shifted = _shift_anchor_target_date(
                        code=str(state["code"]),
                        timeframe=str(state["timeframe"]),
                        current_target_date=pd.to_datetime(state["target_date"]),
                        step=step,
                    )
                    state["target_date"] = shifted.strftime("%Y-%m-%d")
                    st.session_state[chart_state_key] = state
                except Exception as move_e:
                    st.error(f"차트 이동 실패: {move_e}")

            try:
                fig, anchor_date = build_historical_chart_figure(
                    code=str(state["code"]),
                    name=str(state["name"]),
                    timeframe=str(state["timeframe"]),
                    target_date=pd.to_datetime(state["target_date"]),
                    lookback_bars=LOOKBACK_BARS,
                )
                state["target_date"] = anchor_date.strftime("%Y-%m-%d")
                st.session_state[chart_state_key] = state

                _add_anchor_guides_to_chart(
                    fig=fig,
                    code=str(state["code"]),
                    timeframe=str(state["timeframe"]),
                    current_target_date_text=str(state["target_date"]),
                    origin_target_date_text=str(state.get("origin_target_date", state["target_date"])),
                )

                st.success(
                    f"{state['name']} ({state['code']}) | 기준봉 {anchor_date.strftime('%Y-%m-%d')} | "
                    f"{'주봉' if state['timeframe'] == 'weekly' else '월봉'} {LOOKBACK_BARS}봉"
                )
                st.pyplot(fig, use_container_width=True)
            except Exception as chart_e:
                st.error(f"차트 생성 실패: {chart_e}")
        except Exception as e:
            st.error(f"기록 파일 조회 실패: {e}")
    else:
        st.info("선택한 기록 파일이 아직 생성되지 않았습니다.")


HOLDINGS_CODE_CANDIDATES = ["code", "종목코드", "티커", "ticker"]
HOLDINGS_NAME_CANDIDATES = ["name", "종목명"]
HOLDINGS_BUY_PRICE_CANDIDATES = ["buy_price", "매수가", "매입가"]
HOLDINGS_QUANTITY_CANDIDATES = ["quantity", "보유수량", "수량", "shares"]
HOLDINGS_MEMO_CANDIDATES = ["memo", "메모", "note", "비고"]


def _pick_column(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    lower_map = {str(col).strip().lower(): col for col in df.columns}
    for c in candidates:
        key = str(c).strip().lower()
        if key in lower_map:
            return lower_map[key]
    return None


def _to_number_series(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.strip()
        .str.replace(",", "", regex=False)
        .str.replace("\u20a9", "", regex=False)
        .str.replace("원", "", regex=False)
    )
    cleaned = cleaned.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "N/A": pd.NA})
    return pd.to_numeric(cleaned, errors="coerce")


@st.cache_data(show_spinner=False, ttl=120)
def _latest_daily_close(code: str) -> dict:
    try:
        df = load_daily(str(code).zfill(6))
    except Exception:
        return {"price_date": None, "current_price": None}

    if df is None or df.empty:
        return {"price_date": None, "current_price": None}

    work = df.copy()
    work["date"] = pd.to_datetime(work.get("date"), errors="coerce")
    work["close"] = pd.to_numeric(work.get("close"), errors="coerce")
    work = work.dropna(subset=["date", "close"]).sort_values("date")
    if work.empty:
        return {"price_date": None, "current_price": None}

    recent = work.iloc[-1]
    return {
        "price_date": pd.to_datetime(recent["date"]).strftime("%Y-%m-%d"),
        "current_price": float(recent["close"]),
    }


@st.cache_data(show_spinner=False, ttl=120)
def _latest_timeframe_ma10_metrics(code: str, timeframe: str) -> dict:
    loader = load_weekly if timeframe == "weekly" else load_monthly
    try:
        df = loader(str(code).zfill(6))
    except Exception:
        return {"close": None, "ma10": None, "breakout_rate": None}

    if df is None or df.empty:
        return {"close": None, "ma10": None, "breakout_rate": None}

    work = df.copy()
    work["date"] = pd.to_datetime(work.get("date"), errors="coerce")
    work["close"] = pd.to_numeric(work.get("close"), errors="coerce")
    work["ma10"] = pd.to_numeric(work.get("ma10"), errors="coerce")
    work = work.dropna(subset=["date"]).sort_values("date")
    if work.empty:
        return {"close": None, "ma10": None, "breakout_rate": None}

    recent = work.iloc[-1]
    close_val = pd.to_numeric(recent.get("close"), errors="coerce")
    ma10_val = pd.to_numeric(recent.get("ma10"), errors="coerce")

    if pd.notna(close_val) and pd.notna(ma10_val) and float(ma10_val) != 0.0:
        breakout_rate = (float(close_val) / float(ma10_val)) - 1.0
    else:
        breakout_rate = None

    return {
        "close": float(close_val) if pd.notna(close_val) else None,
        "ma10": float(ma10_val) if pd.notna(ma10_val) else None,
        "breakout_rate": (float(breakout_rate) * 100.0) if breakout_rate is not None else None,
    }


@st.cache_data(show_spinner=False, ttl=120)
def _timeframe_close_at_or_before(code: str, timeframe: str, target_date_text: str) -> Optional[float]:
    loader = load_weekly if timeframe == "weekly" else load_monthly
    try:
        df = loader(str(code).zfill(6))
    except Exception:
        return None

    if df is None or df.empty:
        return None

    target_dt = pd.to_datetime(target_date_text, errors="coerce")
    if pd.isna(target_dt):
        return None

    work = df.copy()
    work["date"] = pd.to_datetime(work.get("date"), errors="coerce")
    work["close"] = pd.to_numeric(work.get("close"), errors="coerce")
    work = work.dropna(subset=["date", "close"]).sort_values("date")
    if work.empty:
        return None

    valid = work[work["date"] <= target_dt]
    if valid.empty:
        return None

    return float(valid.iloc[-1]["close"])


def _add_anchor_guides_to_chart(
    fig,
    code: str,
    timeframe: str,
    current_target_date_text: str,
    origin_target_date_text: str,
) -> None:
    if fig is None or not getattr(fig, "axes", None):
        return

    dates = _get_timeframe_dates(str(code).zfill(6), timeframe)
    if not dates:
        return

    cur_ts = pd.to_datetime(current_target_date_text, errors="coerce")
    origin_ts = pd.to_datetime(origin_target_date_text, errors="coerce")
    if pd.isna(cur_ts) or pd.isna(origin_ts):
        return

    current_idx = 0
    for i, d in enumerate(dates):
        if d <= cur_ts:
            current_idx = i
        else:
            break

    origin_idx = 0
    for i, d in enumerate(dates):
        if d <= origin_ts:
            origin_idx = i
        else:
            break

    window_start = max(0, current_idx - LOOKBACK_BARS + 1)
    window_end = current_idx
    visible_len = max(1, window_end - window_start + 1)
    rightmost_x = float(visible_len - 1)
    if window_start <= origin_idx <= window_end:
        anchor_x = float(origin_idx - window_start) + 0.45
    else:
        anchor_x = None

    anchor_close = _timeframe_close_at_or_before(
        code=str(code).zfill(6),
        timeframe=timeframe,
        target_date_text=pd.to_datetime(origin_ts).strftime("%Y-%m-%d"),
    )
    current_close = _timeframe_close_at_or_before(
        code=str(code).zfill(6),
        timeframe=timeframe,
        target_date_text=pd.to_datetime(cur_ts).strftime("%Y-%m-%d"),
    )

    main_ax = fig.axes[0]
    if anchor_x is not None:
        main_ax.axvline(x=anchor_x, color="#000000", linestyle="-", linewidth=0.8, alpha=0.95, zorder=10)
    if anchor_close is not None:
        main_ax.axhline(y=float(anchor_close), color="#000000", linestyle="-", linewidth=0.8, alpha=0.9, zorder=9)

    if anchor_x is not None and anchor_close is not None:
        main_ax.annotate(
            f"{float(anchor_close):,.0f}",
            xy=(anchor_x, float(anchor_close)),
            xytext=(0, 5),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
            color="#000000",
            bbox=dict(boxstyle="round,pad=0.15", facecolor="white", alpha=0.8, edgecolor="none"),
            zorder=11,
        )

    if current_close is not None:
        main_ax.annotate(
            f"{float(current_close):,.0f}",
            xy=(rightmost_x, float(current_close)),
            xytext=(3, 0),
            textcoords="offset points",
            ha="left",
            va="center",
            fontsize=8,
            color="#000000",
            bbox=dict(boxstyle="round,pad=0.15", facecolor="white", alpha=0.8, edgecolor="none"),
            zorder=11,
        )


def _build_holdings_performance_df(raw_df: pd.DataFrame) -> pd.DataFrame:
    code_col = _pick_column(raw_df, HOLDINGS_CODE_CANDIDATES)
    if code_col is None:
        raise ValueError("holdings.csv에 종목코드 컬럼(code/종목코드/티커/ticker)이 없습니다.")

    name_col = _pick_column(raw_df, HOLDINGS_NAME_CANDIDATES)
    buy_col = _pick_column(raw_df, HOLDINGS_BUY_PRICE_CANDIDATES)
    qty_col = _pick_column(raw_df, HOLDINGS_QUANTITY_CANDIDATES)
    memo_col = _pick_column(raw_df, HOLDINGS_MEMO_CANDIDATES)

    if buy_col is None:
        raise ValueError("holdings.csv에 매수가 컬럼(buy_price/매수가/매입가)이 없습니다.")
    if qty_col is None:
        raise ValueError("holdings.csv에 수량 컬럼(quantity/보유수량/수량/shares)이 없습니다.")

    work = pd.DataFrame()
    work["__raw_index"] = raw_df.index
    work["종목코드"] = raw_df[code_col].astype(str).str.strip().str.replace(r"\.0$", "", regex=True).str.zfill(6)
    work["종목명"] = raw_df[name_col].astype(str).str.strip() if name_col else ""
    work["매수가"] = _to_number_series(raw_df[buy_col])
    work["보유수량"] = _to_number_series(raw_df[qty_col])
    work["메모"] = raw_df[memo_col].astype(str) if memo_col else ""
    work = work[work["종목코드"].str.match(r"^\d{6}$", na=False)].copy()
    work = work.reset_index(drop=True)

    rows = []
    for _, row in work.iterrows():
        latest = _latest_daily_close(str(row["종목코드"]))
        current_price = latest.get("current_price")
        price_date = latest.get("price_date")
        weekly = _latest_timeframe_ma10_metrics(str(row["종목코드"]), timeframe="weekly")
        monthly = _latest_timeframe_ma10_metrics(str(row["종목코드"]), timeframe="monthly")

        buy_price = pd.to_numeric(row["매수가"], errors="coerce")
        quantity = pd.to_numeric(row["보유수량"], errors="coerce")

        buy_amount = float(buy_price) * float(quantity) if pd.notna(buy_price) and pd.notna(quantity) else None
        market_value = float(current_price) * float(quantity) if pd.notna(current_price) and pd.notna(quantity) else None
        profit_amount = (market_value - buy_amount) if (buy_amount is not None and market_value is not None) else None
        profit_rate = (profit_amount / buy_amount) if (profit_amount is not None and buy_amount not in [0, 0.0]) else None

        rows.append(
            {
                "종목코드": str(row["종목코드"]),
                "종목명": str(row["종목명"]),
                "메모": str(row.get("메모", "")),
                "__raw_index": int(row["__raw_index"]),
                "가격일자": price_date,
                "매수가": float(buy_price) if pd.notna(buy_price) else None,
                "현재 종가": float(current_price) if pd.notna(current_price) else None,
                "보유수량": float(quantity) if pd.notna(quantity) else None,
                "매수금액": buy_amount,
                "현재 시가": market_value,
                "수익액": profit_amount,
                "수익률": (float(profit_rate) * 100.0) if profit_rate is not None else None,
                "주봉 10이평": weekly.get("ma10"),
                "월봉 10이평": monthly.get("ma10"),
                "이격도(주)": weekly.get("breakout_rate"),
                "이격도(월)": monthly.get("breakout_rate"),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    for col in [
        "매수가",
        "현재 종가",
        "보유수량",
        "매수금액",
        "현재 시가",
        "수익액",
        "수익률",
        "주봉 10이평",
        "월봉 10이평",
        "이격도(주)",
        "이격도(월)",
    ]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    return out


def _load_holdings_source_df(holdings_path: str) -> pd.DataFrame:
    if os.path.isfile(holdings_path):
        try:
            hdf = pd.read_csv(holdings_path, dtype=str)
            return hdf.fillna("")
        except Exception:
            pass
    return pd.DataFrame(columns=["종목코드", "종목명", "매수가", "보유수량", "메모"])


def _add_holding_row(
    holdings_path: str,
    code: str,
    name: str,
    buy_price_text: str,
    quantity_text: str,
    memo_text: str,
) -> None:
    hdf = _load_holdings_source_df(holdings_path)

    code_col = _pick_column(hdf, HOLDINGS_CODE_CANDIDATES) or "종목코드"
    name_col = _pick_column(hdf, HOLDINGS_NAME_CANDIDATES) or "종목명"
    buy_col = _pick_column(hdf, HOLDINGS_BUY_PRICE_CANDIDATES) or "매수가"
    qty_col = _pick_column(hdf, HOLDINGS_QUANTITY_CANDIDATES) or "보유수량"
    memo_col = _pick_column(hdf, HOLDINGS_MEMO_CANDIDATES) or "메모"

    for col in [code_col, name_col, buy_col, qty_col, memo_col]:
        if col not in hdf.columns:
            hdf[col] = ""

    new_row = {col: "" for col in hdf.columns}
    new_row[code_col] = str(code).strip().zfill(6)
    new_row[name_col] = str(name).strip()
    new_row[buy_col] = str(buy_price_text).strip()
    new_row[qty_col] = str(quantity_text).strip()
    new_row[memo_col] = str(memo_text)

    out_df = pd.concat([hdf, pd.DataFrame([new_row])], ignore_index=True)
    out_df.to_csv(holdings_path, index=False, encoding="utf-8-sig")


def _render_output_holdings_data() -> None:
    st.caption(f"{HOLDINGS_CSV} 데이터를 조회합니다.")
    holdings_path = HOLDINGS_CSV
    os.makedirs(os.path.dirname(holdings_path), exist_ok=True)

    st.markdown("#### 보유 종목 추가")
    add_c1, add_c2, add_c3, add_c4, add_c5 = st.columns([1.1, 1.3, 1.0, 0.9, 2.2])
    with add_c1:
        add_code = st.text_input("종목코드", value="", max_chars=6, key="holdings_add_code")
    with add_c2:
        add_name = st.text_input("종목명", value="", key="holdings_add_name")
    with add_c3:
        add_buy = st.text_input("매수가", value="", key="holdings_add_buy")
    with add_c4:
        add_qty = st.text_input("수량", value="", key="holdings_add_qty")
    with add_c5:
        add_memo = st.text_input("메모", value="", key="holdings_add_memo")

    if st.button("보유 종목 추가", key="holdings_add_submit", use_container_width=True):
        try:
            code = str(add_code).strip().replace(" ", "").zfill(6)
            if not re.fullmatch(r"\d{6}", code):
                raise ValueError("종목코드는 6자리 숫자로 입력하세요.")

            buy_val = pd.to_numeric(str(add_buy).strip().replace(",", ""), errors="coerce")
            qty_val = pd.to_numeric(str(add_qty).strip().replace(",", ""), errors="coerce")
            if pd.isna(buy_val) or float(buy_val) <= 0:
                raise ValueError("매수가는 0보다 큰 숫자로 입력하세요.")
            if pd.isna(qty_val) or float(qty_val) <= 0:
                raise ValueError("수량은 0보다 큰 숫자로 입력하세요.")

            resolved_name = str(add_name).strip()
            if not resolved_name:
                master = get_master_table()
                if not master.empty and {"code", "name"}.issubset(set(master.columns)):
                    hit = master[master["code"].astype(str).str.zfill(6) == code]
                    if not hit.empty:
                        resolved_name = str(hit.iloc[0].get("name", "")).strip()

            _add_holding_row(
                holdings_path=holdings_path,
                code=code,
                name=resolved_name,
                buy_price_text=f"{float(buy_val):.2f}",
                quantity_text=f"{float(qty_val):.4f}",
                memo_text=str(add_memo),
            )
            st.success("보유 종목이 추가되었습니다.")
            st.rerun()
        except Exception as add_e:
            st.error(f"추가 실패: {add_e}")

    st.markdown("#### 보유 종목 데이터")
    if os.path.isfile(holdings_path):
        try:
            hdf = pd.read_csv(holdings_path, dtype=str)
            memo_col_name = _pick_column(hdf, HOLDINGS_MEMO_CANDIDATES)
            if memo_col_name is None:
                hdf["메모"] = ""
                hdf.to_csv(holdings_path, index=False, encoding="utf-8-sig")
            st.caption(f"파일: {holdings_path}")

            perf_df = _build_holdings_performance_df(hdf)
            if perf_df.empty:
                st.warning("보유 종목 데이터가 비어 있거나 유효한 종목코드가 없습니다.")
                return

            weekly_rate = pd.to_numeric(perf_df["이격도(주)"], errors="coerce")
            monthly_rate = pd.to_numeric(perf_df["이격도(월)"], errors="coerce")

            total_count = int(len(perf_df))
            weekly_up_count = int(weekly_rate.ge(0).sum())
            weekly_down_count = int(weekly_rate.lt(0).sum())
            monthly_up_count = int(monthly_rate.ge(0).sum())
            monthly_down_count = int(monthly_rate.lt(0).sum())

            s1, s2, s3, s4, s5 = st.columns(5)
            s1.markdown(
                (
                    "<div class='status-card'>"
                    "<div class='status-title'>전체 종목수</div>"
                    f"<div class='status-value'>{total_count}개</div>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
            s2.markdown(
                (
                    "<div class='status-card'>"
                    "<div class='status-title'>주봉 10이평 이상</div>"
                    f"<div class='status-value' style='color:#d32f2f;'>{weekly_up_count}개</div>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
            s3.markdown(
                (
                    "<div class='status-card'>"
                    "<div class='status-title'>주봉 10이평 이하</div>"
                    f"<div class='status-value' style='color:#1565c0;'>{weekly_down_count}개</div>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
            s4.markdown(
                (
                    "<div class='status-card'>"
                    "<div class='status-title'>월봉 10이평 이상</div>"
                    f"<div class='status-value' style='color:#d32f2f;'>{monthly_up_count}개</div>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
            s5.markdown(
                (
                    "<div class='status-card'>"
                    "<div class='status-title'>월봉 10이평 이하</div>"
                    f"<div class='status-value' style='color:#1565c0;'>{monthly_down_count}개</div>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )

            action_df = perf_df[[
                "종목코드",
                "종목명",
                "가격일자",
                "매수가",
                "현재 종가",
                "수익률",
                "주봉 10이평",
                "이격도(주)",
                "월봉 10이평",
                "이격도(월)",
                "메모",
                "__raw_index",
            ]].copy()
            action_df = action_df.reset_index(drop=True)
            pick_key = "holdings_selected_row"
            selected_idx_key = "holdings_selected_table_idx"

            action_view = action_df.drop(columns=["__raw_index"]).copy()
            action_view.index = action_view.index + 1
            action_view.index.name = "No"

            def _pos_neg_color(v):
                if pd.isna(v):
                    return ""
                if float(v) > 0:
                    return "color: #d32f2f;"
                if float(v) < 0:
                    return "color: #1565c0;"
                return ""

            right_align_cols = ["매수가", "현재 종가", "수익률", "이격도(주)", "이격도(월)"]
            center_align_cols = ["종목코드", "종목명", "가격일자"]
            styled_action = (
                action_view.style
                .format(
                    {
                        "매수가": lambda x: "" if pd.isna(x) else f"{x:,.0f}",
                        "현재 종가": lambda x: "" if pd.isna(x) else f"{x:,.0f}",
                        "주봉 10이평": lambda x: "" if pd.isna(x) else f"{x:,.0f}",
                        "월봉 10이평": lambda x: "" if pd.isna(x) else f"{x:,.0f}",
                        "수익률": lambda x: "" if pd.isna(x) else f"{x:.2f}%",
                        "이격도(주)": lambda x: "" if pd.isna(x) else f"{x:.2f}%",
                        "이격도(월)": lambda x: "" if pd.isna(x) else f"{x:.2f}%",
                    }
                )
                .set_properties(subset=right_align_cols, **{"text-align": "right"})
                .set_properties(subset=center_align_cols, **{"text-align": "center"})
                .map(_pos_neg_color, subset=["수익률", "이격도(주)", "이격도(월)"])
            )

            holdings_column_config = {
                "메모": st.column_config.TextColumn(width="large"),
            }

            selected_rows = []
            try:
                table_event = st.dataframe(
                    styled_action,
                    use_container_width=False,
                    width=1600,
                    column_config=holdings_column_config,
                    on_select="rerun",
                    selection_mode="single-row",
                    key="holdings_action_table",
                )
                if table_event is not None and hasattr(table_event, "selection"):
                    selected_rows = list(getattr(table_event.selection, "rows", []) or [])
            except TypeError:
                st.dataframe(
                    styled_action,
                    use_container_width=False,
                    width=1600,
                    column_config=holdings_column_config,
                )

            btn1, btn2, btn3 = st.columns([1, 1, 4])
            with btn1:
                chart_clicked = st.button("차트", key="holdings_action_chart", use_container_width=True)
            with btn2:
                delete_clicked = st.button("삭제", key="holdings_action_delete", use_container_width=True)

            if selected_rows:
                st.session_state[selected_idx_key] = int(selected_rows[0])

            selected_idx = st.session_state.get(selected_idx_key)
            if selected_idx is not None and 0 <= int(selected_idx) < len(action_df):
                chosen = action_df.iloc[int(selected_idx)]
                chosen_name = str(chosen.get("종목명", "")).strip() or str(chosen.get("종목코드", "")).strip()
                st.caption(f"선택된 종목: {chosen_name} ({str(chosen.get('종목코드', '')).zfill(6)})")

                if chart_clicked:
                    chosen_buy_price = pd.to_numeric(chosen.get("매수가"), errors="coerce")
                    st.session_state[pick_key] = {
                        "code": str(chosen.get("종목코드", "")).strip().zfill(6),
                        "name": chosen_name,
                        "buy_price": float(chosen_buy_price) if pd.notna(chosen_buy_price) else None,
                        "memo": str(chosen.get("메모", "")),
                        "raw_index": int(chosen.get("__raw_index")),
                    }

                if delete_clicked:
                    st.session_state["holdings_delete_pending_raw"] = int(chosen.get("__raw_index"))
                    st.session_state["holdings_delete_pending_name"] = chosen_name
                    st.session_state["holdings_delete_pending_code"] = str(chosen.get("종목코드", "")).strip().zfill(6)
                    st.session_state["holdings_delete_pending_memo"] = str(chosen.get("메모", ""))
            else:
                if chart_clicked or delete_clicked:
                    st.warning("보유종목 데이터 테이블에서 먼저 종목 1개를 선택하세요.")

            pending_raw = st.session_state.get("holdings_delete_pending_raw")
            if pending_raw is not None:
                pending_name = st.session_state.get("holdings_delete_pending_name", "")
                pending_code = str(st.session_state.get("holdings_delete_pending_code", "")).strip().zfill(6)
                pending_memo = str(st.session_state.get("holdings_delete_pending_memo", ""))

                send_cols = st.columns([1.4, 1.1, 1.1, 3.4])
                with send_cols[0]:
                    send_to_interest = st.checkbox(
                        "관심종목으로 보내기",
                        value=True,
                        key="holdings_delete_send_interest",
                    )
                with send_cols[1]:
                    send_timeframe_label = st.selectbox(
                        "봉 타입",
                        options=["주봉", "월봉"],
                        index=0,
                        key="holdings_delete_send_timeframe",
                    )
                with send_cols[2]:
                    send_classification = st.selectbox(
                        "분류",
                        options=["10이평", "120이평", "180이평", "240이평"],
                        index=0,
                        key="holdings_delete_send_classification",
                    )
                with send_cols[3]:
                    send_memo = st.text_input(
                        "관심 메모",
                        value=pending_memo,
                        key="holdings_delete_send_memo",
                    )

                dc1, dc2, dc3 = st.columns([4, 1, 1])
                with dc1:
                    st.warning(f"삭제하시겠습니까? {'(' + pending_name + ')' if pending_name else ''}")
                with dc2:
                    if st.button("예", key="holdings_delete_yes", use_container_width=True):
                        try:
                            raw_idx = int(pending_raw)

                            if send_to_interest:
                                send_timeframe = "weekly" if send_timeframe_label == "주봉" else "monthly"
                                snap_date, snap_close = _extract_last_bar_snapshot(
                                    code=pending_code,
                                    timeframe=send_timeframe,
                                    target_date=pd.Timestamp(date.today()),
                                )
                                interest_row = {
                                    "종목명": pending_name,
                                    "종목코드": pending_code,
                                    "종목의 마지막 봉의 날짜": snap_date.strftime("%Y-%m-%d"),
                                    "주봉 or 월봉 선택": "주봉" if send_timeframe == "weekly" else "월봉",
                                    "현시점 종가": f"{snap_close:.2f}",
                                    "분류": send_classification,
                                    "메모": str(send_memo),
                                }
                                _append_tracking_row(_interest_watch_monthly_path(), interest_row)

                            if 0 <= raw_idx < len(hdf):
                                updated_hdf = hdf.drop(index=raw_idx).reset_index(drop=True)
                                updated_hdf.to_csv(holdings_path, index=False, encoding="utf-8-sig")
                            st.session_state.pop("holdings_delete_pending_raw", None)
                            st.session_state.pop("holdings_delete_pending_name", None)
                            st.session_state.pop("holdings_delete_pending_code", None)
                            st.session_state.pop("holdings_delete_pending_memo", None)
                            st.rerun()
                        except Exception as del_e:
                            st.error(f"삭제 실패: {del_e}")
                with dc3:
                    if st.button("아니오", key="holdings_delete_no", use_container_width=True):
                        st.session_state.pop("holdings_delete_pending_raw", None)
                        st.session_state.pop("holdings_delete_pending_name", None)
                        st.session_state.pop("holdings_delete_pending_code", None)
                        st.session_state.pop("holdings_delete_pending_memo", None)
                        st.rerun()

            st.markdown("---")
            st.markdown("#### 선택 종목 차트")

            picked = st.session_state.get(pick_key)
            if picked:
                chart_timeframe = st.radio(
                    "봉 타입 선택",
                    options=["주봉", "월봉"],
                    horizontal=True,
                    key="holdings_chart_timeframe",
                )
                timeframe_value = "weekly" if chart_timeframe == "주봉" else "monthly"

                chart_state_key = "holdings_chart_state"
                dates = _get_timeframe_dates(str(picked.get("code", "")).zfill(6), timeframe_value)
                initial_target = dates[-1] if dates else pd.Timestamp(date.today())

                if chart_state_key not in st.session_state:
                    st.session_state[chart_state_key] = {
                        "code": str(picked.get("code", "")).zfill(6),
                        "name": str(picked.get("name", "")),
                        "timeframe": timeframe_value,
                        "target_date": pd.to_datetime(initial_target).strftime("%Y-%m-%d"),
                    }

                state = st.session_state[chart_state_key]
                if (
                    str(state.get("code")) != str(picked.get("code", "")).zfill(6)
                    or str(state.get("timeframe")) != timeframe_value
                ):
                    state = {
                        "code": str(picked.get("code", "")).zfill(6),
                        "name": str(picked.get("name", "")),
                        "timeframe": timeframe_value,
                        "target_date": pd.to_datetime(initial_target).strftime("%Y-%m-%d"),
                    }
                    st.session_state[chart_state_key] = state

                memo_row_idx = picked.get("raw_index")
                memo_state_key = "holdings_chart_memo_text"
                memo_row_state_key = "holdings_chart_memo_row_idx"
                if (
                    memo_state_key not in st.session_state
                    or st.session_state.get(memo_row_state_key) != memo_row_idx
                ):
                    default_memo = ""
                    if isinstance(memo_row_idx, int) and 0 <= int(memo_row_idx) < len(hdf):
                        memo_col_name = _pick_column(hdf, HOLDINGS_MEMO_CANDIDATES)
                        if memo_col_name is not None:
                            default_memo = str(hdf.iloc[int(memo_row_idx)].get(memo_col_name, ""))
                        else:
                            default_memo = str(picked.get("memo", ""))
                    else:
                        default_memo = str(picked.get("memo", ""))
                    st.session_state[memo_state_key] = default_memo
                    st.session_state[memo_row_state_key] = memo_row_idx

                mv1, mv2, mv3, mv4 = st.columns([1, 1, 4, 1])
                with mv1:
                    move_prev = st.button("이전 1봉", key="holdings_chart_prev", use_container_width=True)
                with mv2:
                    move_next = st.button("다음 1봉", key="holdings_chart_next", use_container_width=True)
                with mv3:
                    memo_input = st.text_area(
                        "메모",
                        key=memo_state_key,
                        label_visibility="collapsed",
                        placeholder="메모를 입력하세요",
                        height=68,
                    )
                with mv4:
                    memo_save_clicked = st.button("메모저장", key="holdings_chart_memo_save", use_container_width=True)

                if memo_save_clicked:
                    try:
                        memo_col_name = _pick_column(hdf, HOLDINGS_MEMO_CANDIDATES) or "메모"
                        if memo_col_name not in hdf.columns:
                            hdf[memo_col_name] = ""

                        if not (isinstance(memo_row_idx, int) and 0 <= int(memo_row_idx) < len(hdf)):
                            st.error("메모 저장 대상 행을 찾지 못했습니다.")
                        else:
                            hdf.loc[int(memo_row_idx), memo_col_name] = str(memo_input)
                            hdf.to_csv(holdings_path, index=False, encoding="utf-8-sig")
                            if isinstance(picked, dict):
                                picked["memo"] = str(memo_input)
                                st.session_state[pick_key] = picked
                            st.success("메모 저장 완료")
                    except Exception as memo_e:
                        st.error(f"메모 저장 실패: {memo_e}")

                st.markdown(
                    """
<style>
div[data-testid="stTextArea"] textarea {
    white-space: pre;
    overflow-x: auto;
    overflow-y: auto;
    overflow-wrap: normal;
    word-break: keep-all;
}
</style>
""",
                    unsafe_allow_html=True,
                )

                if move_prev or move_next:
                    try:
                        step = -1 if move_prev else 1
                        shifted = _shift_anchor_target_date(
                            code=str(state["code"]),
                            timeframe=str(state["timeframe"]),
                            current_target_date=pd.to_datetime(state["target_date"]),
                            step=step,
                        )
                        state["target_date"] = shifted.strftime("%Y-%m-%d")
                        st.session_state[chart_state_key] = state
                    except Exception as move_e:
                        st.error(f"차트 이동 실패: {move_e}")

                try:
                    fig, anchor_date = build_historical_chart_figure(
                        code=str(state["code"]),
                        name=str(state["name"]),
                        timeframe=str(state["timeframe"]),
                        target_date=pd.to_datetime(state["target_date"]),
                        lookback_bars=LOOKBACK_BARS,
                    )
                    state["target_date"] = anchor_date.strftime("%Y-%m-%d")
                    st.session_state[chart_state_key] = state

                    buy_price = pd.to_numeric(picked.get("buy_price"), errors="coerce")
                    if pd.notna(buy_price) and fig is not None and getattr(fig, "axes", None):
                        fig.axes[0].axhline(
                            y=float(buy_price),
                            color="#000000",
                            linestyle="-",
                            linewidth=0.7,
                            alpha=0.95,
                            zorder=10,
                        )

                    st.success(
                        f"{state['name']} ({state['code']}) | 기준봉 {anchor_date.strftime('%Y-%m-%d')} | "
                        f"{'주봉' if state['timeframe'] == 'weekly' else '월봉'} {LOOKBACK_BARS}봉"
                    )
                    st.pyplot(fig, use_container_width=True)
                except Exception as chart_e:
                    st.error(f"차트 생성 실패: {chart_e}")
            else:
                st.info("종목을 선택하고 차트 버튼을 누르세요")
        except Exception as e:
            st.error(f"holdings.csv 조회 실패: {e}")
    else:
        st.warning(f"파일이 없습니다: {holdings_path}")


def render_log_box(lines: list[str], max_lines: int = 500) -> None:
    st.markdown(_render_log_html_box(lines, max_lines=max_lines), unsafe_allow_html=True)


def _read_last_non_empty_line(file_path: str) -> Optional[str]:
    if not os.path.isfile(file_path):
        return None

    with open(file_path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        if size <= 0:
            return None

        pos = size - 1
        while pos >= 0:
            fh.seek(pos)
            ch = fh.read(1)
            if ch not in (b"\n", b"\r"):
                break
            pos -= 1

        if pos < 0:
            return None

        line = bytearray()
        while pos >= 0:
            fh.seek(pos)
            ch = fh.read(1)
            if ch in (b"\n", b"\r"):
                break
            line.extend(ch)
            pos -= 1

    return line[::-1].decode("utf-8", errors="ignore").strip()


@st.cache_data(show_spinner=False, ttl=300)
def get_data_status(data_dir: str) -> dict:
    status = {
        "kospi_count": 0,
        "kosdaq_count": 0,
        "latest_trade_date": None,
        "latest_collection_date": None,
        "latest_collection_time": None,
        "daily_file_count": 0,
    }

    master_csv = os.path.join(data_dir, "master", "kospi_tickers.csv")
    if os.path.isfile(master_csv):
        try:
            mdf = pd.read_csv(master_csv)
            market_series = mdf.get("market", pd.Series(dtype=str)).fillna("").astype(str).str.upper()
            status["kospi_count"] = int((market_series == "KOSPI").sum())
            status["kosdaq_count"] = int((market_series == "KOSDAQ").sum())
        except Exception:
            pass

    daily_dir = os.path.join(data_dir, "derived", "daily")
    if not os.path.isdir(daily_dir):
        return status

    daily_files = [f for f in os.listdir(daily_dir) if f.lower().endswith(".csv")]
    status["daily_file_count"] = len(daily_files)

    latest_trade = None
    latest_collection = None
    latest_collection_time = None
    latest_collection_key = None
    for file_name in daily_files:
        last_line = _read_last_non_empty_line(os.path.join(daily_dir, file_name))
        if not last_line:
            continue

        cols = [c.strip() for c in last_line.split(",")]
        if cols:
            trade_date = cols[0]
            if trade_date and (latest_trade is None or trade_date > latest_trade):
                latest_trade = trade_date

        if len(cols) >= 14:
            collection_date = cols[13]
            if collection_date and (latest_collection is None or collection_date > latest_collection):
                latest_collection = collection_date

        if len(cols) >= 15:
            collection_date = cols[13]
            collection_time = cols[14]
            if collection_date and collection_time:
                key = f"{collection_date} {collection_time}"
                if latest_collection_key is None or key > latest_collection_key:
                    latest_collection_key = key
                    latest_collection = collection_date
                    latest_collection_time = collection_time

    status["latest_trade_date"] = latest_trade
    status["latest_collection_date"] = latest_collection
    status["latest_collection_time"] = latest_collection_time
    return status


@st.cache_data(show_spinner=False, ttl=120)
def get_scan_status(output_dir: str) -> dict:
    status = {
        "latest_scan_dir": None,
        "latest_scan_label": "미실행",
        "overview_path": None,
        "summary_path": None,
        "all_breakouts_path": None,
        "case_counts": [],
        "total_breakouts": 0,
    }

    if not os.path.isdir(output_dir):
        return status

    scan_dirs = [
        d for d in os.listdir(output_dir)
        if d.startswith("scan_result_") and os.path.isdir(os.path.join(output_dir, d))
    ]
    if not scan_dirs:
        return status

    latest = sorted(scan_dirs)[-1]
    latest_dir = os.path.join(output_dir, latest)
    overview_path = os.path.join(latest_dir, "overview.png")
    summary_path = os.path.join(latest_dir, "summary.csv")
    all_breakouts_path = os.path.join(latest_dir, "all_breakouts.csv")

    status["latest_scan_dir"] = latest_dir
    status["latest_scan_label"] = latest.replace("scan_result_", "")
    if os.path.isfile(overview_path):
        status["overview_path"] = overview_path
    if os.path.isfile(all_breakouts_path):
        status["all_breakouts_path"] = all_breakouts_path
    if os.path.isfile(summary_path):
        status["summary_path"] = summary_path
        try:
            sdf = pd.read_csv(summary_path)
            required_cols = {"scan_label", "count"}
            if required_cols.issubset(set(sdf.columns)):
                sdf["count"] = pd.to_numeric(sdf["count"], errors="coerce").fillna(0).astype(int)
                status["total_breakouts"] = int(sdf["count"].sum())
                status["case_counts"] = [
                    {"케이스": str(r["scan_label"]), "건수": int(r["count"])}
                    for _, r in sdf.iterrows()
                ]
        except Exception:
            pass

    return status


@st.cache_data(show_spinner=False, ttl=120)
def load_scan_review_data(scan_dir: Optional[str]) -> dict:
    empty = {
        "cases": {},
        "scan_time": None,
    }
    if not scan_dir or not os.path.isdir(scan_dir):
        return empty

    cases: dict = {}

    all_breakouts_path = os.path.join(scan_dir, "all_breakouts.csv")
    if os.path.isfile(all_breakouts_path):
        try:
            bdf = pd.read_csv(all_breakouts_path, dtype={"code": str})
            if "code" in bdf.columns:
                bdf["code"] = (
                    bdf["code"]
                    .astype(str)
                    .str.strip()
                    .str.replace(r"\.0$", "", regex=True)
                    .str.zfill(6)
                )
            bdf["breakout_pct"] = pd.to_numeric(bdf.get("breakout_pct"), errors="coerce")
            bdf["breakout_strength"] = pd.to_numeric(bdf.get("breakout_strength"), errors="coerce")
            bdf["volume_pct"] = pd.to_numeric(bdf.get("volume_pct"), errors="coerce")
            for _, row in bdf.iterrows():
                case_key = str(row.get("scan_case", "")).strip()
                if not case_key:
                    continue
                case_label = str(row.get("scan_label", case_key))
                entry = cases.setdefault(case_key, {"label": case_label, "rows": [], "files": []})
                entry["rows"].append(
                    {
                        "code": str(row.get("code", "")).strip().zfill(6),
                        "name": str(row.get("name", "")).strip(),
                        "breakout_pct": row.get("breakout_pct"),
                        "breakout_strength": row.get("breakout_strength"),
                        "volume_pct": row.get("volume_pct"),
                        "date": str(row.get("date", "")).strip(),
                    }
                )
        except Exception:
            pass

    charts_root = os.path.join(scan_dir, "charts")
    if os.path.isdir(charts_root):
        for case_key in sorted(os.listdir(charts_root)):
            case_dir = os.path.join(charts_root, case_key)
            if not os.path.isdir(case_dir):
                continue
            png_files = [
                os.path.join(case_dir, f)
                for f in sorted(os.listdir(case_dir))
                if f.lower().endswith(".png")
            ]
            entry = cases.setdefault(case_key, {"label": case_key, "rows": [], "files": []})
            entry["files"] = png_files

    for case_key, payload in cases.items():
        code_map: dict = {}
        for path in payload["files"]:
            stem = os.path.splitext(os.path.basename(path))[0]
            code = stem.split("_", 1)[0]
            code_map.setdefault(code, []).append(path)

        items = []
        if payload["rows"]:
            for row in payload["rows"]:
                code = row.get("code", "")
                image_path = None
                if code in code_map and code_map[code]:
                    image_path = code_map[code][0]
                items.append(
                    {
                        "caption": f"{code} {row.get('name', '')}".strip(),
                        "code": code,
                        "name": row.get("name", ""),
                        "breakout_pct": row.get("breakout_pct"),
                        "breakout_strength": row.get("breakout_strength"),
                        "volume_pct": row.get("volume_pct"),
                        "date": row.get("date", ""),
                        "image_path": image_path if image_path and os.path.isfile(image_path) else None,
                    }
                )
        else:
            for path in payload["files"]:
                stem = os.path.splitext(os.path.basename(path))[0]
                items.append(
                    {
                        "caption": stem,
                        "code": stem.split("_", 1)[0],
                        "name": "",
                        "breakout_pct": None,
                        "breakout_strength": None,
                        "volume_pct": None,
                        "date": "",
                        "image_path": path,
                    }
                )

        payload["items"] = items

    # Always expose six core cases in menu 3, even when data is absent.
    for case_key in REVIEW_CASE_ORDER:
        payload = cases.setdefault(case_key, {"label": REVIEW_CASE_LABELS.get(case_key, case_key), "rows": [], "files": []})
        if not str(payload.get("label", "")).strip():
            payload["label"] = REVIEW_CASE_LABELS.get(case_key, case_key)
        payload.setdefault("rows", [])
        payload.setdefault("files", [])
        payload.setdefault("items", [])

    return {
        "cases": cases,
        "scan_time": os.path.basename(scan_dir).replace("scan_result_", ""),
    }


def _render_case_gallery(
    case_key: str,
    case_label: str,
    items: list,
    max_breakout_pct: Optional[float],
    max_volume_pct: Optional[float],
    sort_by: str,
) -> None:
    if sort_by == "code":
        items = sorted(items, key=lambda x: (str(x.get("code", "")), str(x.get("name", ""))))
    else:
        items = sorted(
            items,
            key=lambda x: (
                999999 if x.get("breakout_strength") is None or pd.isna(x.get("breakout_strength")) else float(x.get("breakout_strength")),
                str(x.get("code", "")),
            ),
        )

    filtered_items = []
    for item in items:
        pct = item.get("breakout_pct")
        vol = item.get("volume_pct")

        if max_breakout_pct is not None:
            if pct is None or pd.isna(pct):
                continue
            if float(pct) > float(max_breakout_pct):
                continue

        if max_volume_pct is not None:
            if vol is None or pd.isna(vol):
                continue
            if float(vol) > float(max_volume_pct):
                continue

        filtered_items.append(item)

    # Keep gallery navigation/indexing on image-available items only.
    gallery_items = [
        item
        for item in filtered_items
        if item.get("image_path") and os.path.isfile(item["image_path"])
    ]

    breakout_filter_text = "필터 없음" if max_breakout_pct is None else f"<= {max_breakout_pct:.1f}%"
    volume_filter_text = "필터 없음" if max_volume_pct is None else f"<= {max_volume_pct:.1f}%"

    st.markdown(f"#### {case_label}")
    st.caption(
        f"전체 {len(items)}개 / 필터 {len(filtered_items)}개 / 차트 {len(gallery_items)}개 "
        f"(돌파율 {breakout_filter_text}, 볼륨% {volume_filter_text})"
    )

    if not filtered_items:
        st.info("해당 조건의 차트가 없습니다.")
        return

    if not gallery_items:
        st.info("필터 결과는 있으나 표시 가능한 차트 이미지가 없습니다.")
        return

    idx_key = f"gallery_idx_{case_key}"
    gallery_sig_key = f"gallery_sig_{case_key}"
    thumb_selected_key = f"thumb_selected_idx_{case_key}"
    current_sig = (
        sort_by,
        max_breakout_pct,
        max_volume_pct,
        len(gallery_items),
        str(gallery_items[0].get("code", "")) if gallery_items else "",
        str(gallery_items[-1].get("code", "")) if gallery_items else "",
    )

    if st.session_state.get(gallery_sig_key) != current_sig:
        st.session_state[idx_key] = 0
        st.session_state[gallery_sig_key] = current_sig
        st.session_state[thumb_selected_key] = 0

    if idx_key not in st.session_state or st.session_state[idx_key] >= len(gallery_items):
        st.session_state[idx_key] = 0
    if thumb_selected_key not in st.session_state or int(st.session_state[thumb_selected_key]) >= len(gallery_items):
        st.session_state[thumb_selected_key] = int(st.session_state[idx_key])

    nav1, nav2, nav3 = st.columns([1, 1, 4])
    with nav1:
        if st.button("이전", key=f"prev_{case_key}"):
            st.session_state[idx_key] = max(0, st.session_state[idx_key] - 1)
    with nav2:
        if st.button("다음", key=f"next_{case_key}"):
            st.session_state[idx_key] = min(len(gallery_items) - 1, st.session_state[idx_key] + 1)

    selected = gallery_items[st.session_state[idx_key]]
    code_text = str(selected.get("code", "")).strip()
    name_text = str(selected.get("name", "")).strip()
    pct_text = float(selected.get("breakout_pct", 0.0))
    vol_pct = selected.get("volume_pct")
    vol_text = f"거래량 {float(vol_pct):.1f}%" if vol_pct is not None and not pd.isna(vol_pct) else "거래량 N/A"
    header_text = f"{code_text} | {name_text} | ▲ {pct_text:.2f}% | {vol_text}"
    st.markdown(
        "<div style='font-size:0.8rem; color:#5d6a7f; margin:0 0 6px 2px;'>{}</div>".format(
            html.escape(header_text)
        ),
        unsafe_allow_html=True,
    )
    st.image(selected["image_path"], use_container_width=True)
    st.caption(
        f"{st.session_state[idx_key] + 1}/{len(gallery_items)} | {selected.get('caption', '')} | "
        f"돌파율 {float(selected.get('breakout_pct', 0.0)):.2f}% | {vol_text}"
    )

    st.markdown("#### 관심종목 저장")
    save_col1, save_col2 = st.columns([1.1, 1.9])
    classification_options = ["10이평", "120이평", "180이평", "240이평"]
    default_classification = _default_classification_from_case_key(case_key)
    default_classification_idx = (
        classification_options.index(default_classification)
        if default_classification in classification_options
        else 0
    )
    with save_col1:
        classification = st.selectbox(
            "분류",
            options=classification_options,
            index=default_classification_idx,
            key=f"review_interest_classification_{case_key}",
        )
    with save_col2:
        memo_text = st.text_input(
            "메모",
            value="",
            key=f"review_interest_memo_{case_key}",
        )
        current_watch_path = _interest_watch_monthly_path()
        st.caption(f"관심 저장 파일: {os.path.basename(current_watch_path)}")

    can_save = bool(code_text)
    if not can_save:
        st.warning("종목코드가 없어 저장할 수 없습니다.")

    if st.button(
        "현재 확대 종목 관심저장",
        use_container_width=True,
        key=f"review_interest_save_{case_key}",
        disabled=not can_save,
    ):
        try:
            timeframe = _infer_timeframe_from_case_key(case_key)
            target_date_text = str(selected.get("date", "")).strip()
            target_date = pd.to_datetime(target_date_text) if target_date_text else pd.Timestamp(date.today())

            snap_date, snap_close = _extract_last_bar_snapshot(
                code=code_text,
                timeframe=timeframe,
                target_date=target_date,
            )

            row = {
                "종목명": name_text,
                "종목코드": code_text,
                "종목의 마지막 봉의 날짜": snap_date.strftime("%Y-%m-%d"),
                "주봉 or 월봉 선택": "주봉" if timeframe == "weekly" else "월봉",
                "현시점 종가": f"{snap_close:.2f}",
                "분류": classification,
                "메모": memo_text,
            }
            target_watch_path = _interest_watch_monthly_path()
            _append_tracking_row(target_watch_path, row)
            st.success(f"저장 완료: {target_watch_path}")
        except Exception as save_e:
            st.error(f"저장 실패: {save_e}")

    thumb_items = gallery_items
    thumb_images = [item["image_path"] for item in thumb_items]
    thumb_captions = []
    for item in thumb_items:
        thumb_code = str(item.get("code", "")).strip()
        thumb_name = str(item.get("name", "")).strip()
        thumb_pct = float(item.get("breakout_pct", 0.0))
        thumb_vol_pct = item.get("volume_pct")
        thumb_vol_text = f"거래량 {float(thumb_vol_pct):.1f}%" if thumb_vol_pct is not None and not pd.isna(thumb_vol_pct) else "거래량 N/A"
        thumb_captions.append(f"{thumb_code} | {thumb_name} | ▲ {thumb_pct:.2f}% | {thumb_vol_text}")

    if thumb_images:
        current_thumb_index = min(max(int(st.session_state[idx_key]), 0), len(thumb_items) - 1)
        if thumb_selected_key not in st.session_state:
            st.session_state[thumb_selected_key] = current_thumb_index

        if IMAGE_SELECT_AVAILABLE:
            picked_thumb = image_select(
                label="",
                images=thumb_images,
                captions=thumb_captions,
                index=current_thumb_index,
                return_value="index",
                use_container_width=False,
                key=f"img_pick_{case_key}",
            )
            if picked_thumb is not None:
                picked_thumb_index = int(picked_thumb)
                if 0 <= picked_thumb_index < len(thumb_items):
                    last_thumb_index = int(st.session_state.get(thumb_selected_key, current_thumb_index))
                    if picked_thumb_index != last_thumb_index:
                        st.session_state[thumb_selected_key] = picked_thumb_index
                        if picked_thumb_index != st.session_state[idx_key]:
                            st.session_state[idx_key] = picked_thumb_index
                            st.rerun()
                    else:
                        # Keep tracker aligned when navigation buttons moved the main index.
                        st.session_state[thumb_selected_key] = current_thumb_index
        else:
            st.info("썸네일 선택 기능을 사용하려면 streamlit-image-select 패키지를 설치하세요.")
            picked_idx = st.selectbox(
                "종목 선택",
                options=list(range(len(thumb_items))),
                index=current_thumb_index,
                format_func=lambda i: thumb_captions[i],
                key=f"img_pick_fallback_{case_key}",
            )
            last_thumb_index = int(st.session_state.get(thumb_selected_key, current_thumb_index))
            if 0 <= picked_idx < len(gallery_items):
                if int(picked_idx) != last_thumb_index:
                    st.session_state[thumb_selected_key] = int(picked_idx)
                    if int(picked_idx) != st.session_state[idx_key]:
                        st.session_state[idx_key] = int(picked_idx)
                        st.rerun()
                else:
                    st.session_state[thumb_selected_key] = current_thumb_index


START_MENU = "시작화면"

MENU_ITEMS = [
    START_MENU,
    "1. 데이터 저장",
    "2. 이평 돌파 종목 서칭",
    "3. 서칭 데이터 조회",
    "4. 관심종목 서칭",
    "5. 관심종목 조회",
    "6. 패턴 데이터 입력",
    "7. 패턴 데이터 조회",
    "8. 보유 종목 조회",
]

REVIEW_CASE_ORDER = [
    "weekly_ma10_breakout",
    "weekly_ma240_breakout",
    "monthly_ma10_breakout",
    "monthly_ma120_breakout",
    "monthly_ma180_breakout",
    "monthly_ma240_breakout",
]

REVIEW_CASE_LABELS = {
    "monthly_ma10_breakout": "월봉 10이평 돌파",
    "monthly_ma120_breakout": "월봉 120이평 돌파",
    "monthly_ma180_breakout": "월봉 180이평 돌파",
    "monthly_ma240_breakout": "월봉 240이평 돌파",
    "weekly_ma10_breakout": "주봉 10이평 돌파",
    "weekly_ma240_breakout": "주봉 240이평 돌파",
}


def _resolve_menu_from_query() -> str:
    raw_menu = st.query_params.get("menu")
    if raw_menu is None:
        return START_MENU

    raw_text = str(raw_menu)
    try:
        menu_index = int(raw_text)
        if 0 <= menu_index < len(MENU_ITEMS):
            return MENU_ITEMS[menu_index]
    except Exception:
        pass

    if raw_text in MENU_ITEMS:
        return raw_text
    return START_MENU

FEATURE_HELP = {
    "1. 데이터 저장": "KRX 일봉/주봉/월봉 데이터 적재와 갱신을 실행합니다.",
    "2. 이평 돌파 종목 서칭": "주/월봉 이평선 돌파 종목을 스캔합니다.",
    "3. 서칭 데이터 조회": "최근 스캔 결과와 케이스별 요약을 확인합니다.",
    "4. 관심종목 서칭": "개별 종목 차트를 탐색하고 관심 종목으로 저장합니다.",
    "5. 관심종목 조회": "저장된 관심 종목 데이터를 조회합니다.",
    "6. 패턴 데이터 입력": "개별 종목 조회 후 기록 데이터로 저장합니다.",
    "7. 패턴 데이터 조회": "저장된 패턴(기록) 데이터를 조회합니다.",
    "8. 보유 종목 조회": "보유 종목 데이터를 조회합니다.",
}

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;700&family=Montserrat:wght@600;700;800&display=swap');

:root {
  --bg-main: #f3f6fb;
  --panel: #ffffff;
  --panel-2: #f8fbff;
  --ink: #1b2536;
  --muted: #5d6a7f;
  --line: #dbe3ef;
  --accent: #0a7a6c;
  --accent-soft: #dff6f1;
}

.stApp {
  background:
    radial-gradient(80rem 50rem at 120% -10%, #dce8ff 0%, rgba(220, 232, 255, 0) 45%),
    radial-gradient(70rem 40rem at -15% 0%, #eafdf8 0%, rgba(234, 253, 248, 0) 40%),
    var(--bg-main);
  color: var(--ink);
  font-family: 'IBM Plex Sans KR', sans-serif;
}

h1, h2, h3 {
  font-family: 'Montserrat', 'IBM Plex Sans KR', sans-serif;
  letter-spacing: 0.01em;
}

[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #112339 0%, #172f49 55%, #18354f 100%);
  border-right: 1px solid rgba(255, 255, 255, 0.08);
}

section[data-testid="stSidebar"] {
    width: 14rem !important;
    min-width: 14rem !important;
    max-width: 14rem !important;
    flex: 0 0 14rem !important;
}

section[data-testid="stSidebar"] > div:first-child,
section[data-testid="stSidebar"] > div {
    width: 14rem !important;
    min-width: 14rem !important;
    max-width: 14rem !important;
}

section[data-testid="stSidebar"][aria-expanded="false"] {
    margin-left: -14rem !important;
}

[data-testid="stSidebarResizeHandle"],
[data-testid="stSidebarResizer"],
[aria-label="Resize sidebar"],
section[data-testid="stSidebar"] + div [role="separator"],
[role="separator"][aria-orientation="vertical"] {
    display: none !important;
    width: 0 !important;
    min-width: 0 !important;
    max-width: 0 !important;
    pointer-events: none !important;
}

[data-testid="stSidebar"] * {
  color: #e9f0fb;
}

[data-testid="stSidebar"] .stButton > button,
[data-testid="stSidebar"] button[kind="secondary"] {
    background: rgba(233, 240, 251, 0.12) !important;
    color: #e9f0fb !important;
    border: 1px solid rgba(190, 210, 235, 0.45) !important;
    font-weight: 700;
    font-size: 0.9rem;
}

[data-testid="stSidebar"] .stButton > button *,
[data-testid="stSidebar"] button[kind="secondary"] * {
    color: #e9f0fb !important;
    fill: #e9f0fb !important;
}

[data-testid="stSidebar"] .stButton > button:hover,
[data-testid="stSidebar"] button[kind="secondary"]:hover {
    background: rgba(233, 240, 251, 0.24) !important;
    color: #ffffff !important;
    border-color: rgba(200, 220, 245, 0.7) !important;
}

[data-testid="stSidebar"] .stButton > button:hover *,
[data-testid="stSidebar"] button[kind="secondary"]:hover * {
    color: #ffffff !important;
    fill: #ffffff !important;
}

[data-testid="stSidebar"] button[kind="primary"] {
    background: #23b59d !important;
    color: #082b2d !important;
    border: 1px solid #6de5d1 !important;
    font-weight: 800;
    box-shadow: 0 0 0 2px rgba(109, 229, 209, 0.2) !important;
}

[data-testid="stSidebar"] button[kind="primary"] * {
    color: #082b2d !important;
    fill: #082b2d !important;
}

[data-testid="stSidebar"] .stButton > button:focus,
[data-testid="stSidebar"] .stButton > button:focus-visible,
[data-testid="stSidebar"] button[kind="secondary"]:focus,
[data-testid="stSidebar"] button[kind="secondary"]:focus-visible,
[data-testid="stSidebar"] button[kind="primary"]:focus,
[data-testid="stSidebar"] button[kind="primary"]:focus-visible {
    color: #ffffff !important;
    border-color: #7aa6d9 !important;
    box-shadow: 0 0 0 2px rgba(122, 166, 217, 0.35) !important;
}

.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 1rem 1.1rem;
  box-shadow: 0 10px 24px rgba(18, 39, 66, 0.06);
}

.status-card {
  background: var(--panel-2);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 0.85rem 0.9rem;
}

.data-card {
    padding: 1.15rem 1.2rem;
    min-height: 110px;
}

.status-title {
  font-size: 0.78rem;
  color: var(--muted);
  margin-bottom: 0.25rem;
}

.status-value {
  font-size: 1.05rem;
  font-weight: 700;
  color: var(--ink);
}

.data-card .status-title {
    font-size: 0.9rem;
}

.data-card .status-value {
    font-size: 1.5rem;
    margin-top: 0.35rem;
}

.flow-chip {
  display: inline-block;
  background: var(--accent-soft);
  color: var(--accent);
  border: 1px solid #bdece1;
  border-radius: 999px;
  font-size: 0.78rem;
  padding: 0.2rem 0.6rem;
  margin-right: 0.35rem;
  margin-bottom: 0.4rem;
}

.caption {
  color: var(--muted);
  font-size: 0.9rem;
}

.log-box {
    height: 420px;
    overflow-y: auto;
    border: 1px solid var(--line);
    background: #0f1725;
    color: #d7e4ff;
    border-radius: 10px;
    padding: 10px 12px;
}

.log-box .log-content {
    width: 100%;
    writing-mode: horizontal-tb;
    text-orientation: mixed;
    direction: ltr;
    unicode-bidi: plaintext;
    color: #d7e4ff;
    white-space: normal;
    word-break: break-word;
    overflow-wrap: anywhere;
    font-family: Consolas, "Courier New", monospace;
    font-size: 0.85rem;
    line-height: 1.35;
}

.live-log-box {
    overflow-y: hidden;
}

.overview-table-wrap {
    width: 100%;
    overflow-x: auto;
}

.overview-table {
    width: 100%;
    border-collapse: collapse;
    border: none;
    table-layout: fixed;
}

.overview-table th,
.overview-table td {
    border: none !important;
    text-align: center;
    vertical-align: middle;
    padding: 8px 10px;
    font-size: 0.92rem;
}

.overview-table th {
    font-weight: 700;
    color: var(--ink);
}

.overview-table td {
    color: var(--muted);
}

.case-grid-title {
    text-align: center;
    font-weight: 700;
    color: var(--ink);
    margin-bottom: 0.35rem;
}
</style>
""",
    unsafe_allow_html=True,
)


if "show_intro" not in st.session_state:
    st.session_state.show_intro = True
if "selected_menu" not in st.session_state:
    st.session_state.selected_menu = _resolve_menu_from_query()
if "data_store_logs" not in st.session_state:
    st.session_state.data_store_logs = []
if "data_store_last_returncode" not in st.session_state:
    st.session_state.data_store_last_returncode = None
if "awaiting_update_confirm" not in st.session_state:
    st.session_state.awaiting_update_confirm = False
if "scan_market_logs" not in st.session_state:
    st.session_state.scan_market_logs = []
if "scan_market_last_returncode" not in st.session_state:
    st.session_state.scan_market_last_returncode = None
if "awaiting_scan_confirm" not in st.session_state:
    st.session_state.awaiting_scan_confirm = False
if "scan_market_latest_dir" not in st.session_state:
    st.session_state.scan_market_latest_dir = None
if "data_store_running" not in st.session_state:
    st.session_state.data_store_running = False
if "data_store_run_requested" not in st.session_state:
    st.session_state.data_store_run_requested = False
if "scan_market_running" not in st.session_state:
    st.session_state.scan_market_running = False
if "scan_market_run_requested" not in st.session_state:
    st.session_state.scan_market_run_requested = False
if "scan_progress_value" not in st.session_state:
    st.session_state.scan_progress_value = 0.0
if "scan_progress_text" not in st.session_state:
    st.session_state.scan_progress_text = "스캔 대기 중"

st.sidebar.title("KRX FDR")
for menu in MENU_ITEMS:
    button_type = "primary" if st.session_state.selected_menu == menu else "secondary"
    if st.sidebar.button(menu, key=f"menu_btn_{menu}", use_container_width=True, type=button_type):
        st.session_state.selected_menu = menu
        st.query_params["menu"] = str(MENU_ITEMS.index(menu))
        st.rerun()

selected_menu = st.session_state.selected_menu
if selected_menu in MENU_ITEMS:
    st.query_params["menu"] = str(MENU_ITEMS.index(selected_menu))
st.session_state.show_intro = selected_menu == START_MENU

st.sidebar.markdown("---")
st.sidebar.markdown(
    "<div class='caption'>4~8번 메뉴에서 관심/기록/보유 종목 조회 기능을 사용할 수 있습니다.</div>",
    unsafe_allow_html=True,
)

st.title("KRX FDR 웹 대시보드")

data_status = get_data_status(DATA_DIR)
scan_status = get_scan_status(OUTPUT_DIR)

if st.session_state.show_intro:
    top_left = st.container()
    top_right = None
else:
    top_left, top_right = st.columns([1.4, 1.1], gap="large")

with top_left:
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    if st.session_state.show_intro:
        st.markdown(
            """
<span class='flow-chip'>데이터 저장</span>
<span class='flow-chip'>돌파 서칭</span>
<span class='flow-chip'>결과 조회</span>
<span class='flow-chip'>종목별 분석</span>
""",
            unsafe_allow_html=True,
        )
        st.markdown(
            """
1. 데이터 저장으로 최신 시세를 적재합니다.  
2. 이평 돌파 종목 서칭을 실행합니다.  
3. 서칭 데이터 조회에서 케이스별 결과를 검토합니다.  
4. 관심/기록/보유 종목 메뉴에서 데이터를 조회하고 저장합니다.
"""
        )
        st.markdown("#### 데이터 현황")
        d1, d2 = st.columns(2, gap="large")
        with d1:
            st.markdown(
                f"<div class='status-card data-card'><div class='status-title'>KOSPI 종목 수</div><div class='status-value'>{data_status['kospi_count']:,}</div></div>",
                unsafe_allow_html=True,
            )
        with d2:
            st.markdown(
                f"<div class='status-card data-card'><div class='status-title'>KOSDAQ 종목 수</div><div class='status-value'>{data_status['kosdaq_count']:,}</div></div>",
                unsafe_allow_html=True,
            )

        st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

        d3, d4 = st.columns(2, gap="large")
        with d3:
            st.markdown(
                f"<div class='status-card data-card'><div class='status-title'>최신 데이터 일자</div><div class='status-value'>{data_status['latest_trade_date'] or '-'}</div></div>",
                unsafe_allow_html=True,
            )
        with d4:
            st.markdown(
                f"<div class='status-card data-card'><div class='status-title'>최신 수집 날짜</div><div class='status-value'>{data_status['latest_collection_date'] or '-'}</div></div>",
                unsafe_allow_html=True,
            )
    else:
        st.subheader(selected_menu)
        st.write(FEATURE_HELP[selected_menu])
        if selected_menu == "1. 데이터 저장":
            latest_date = data_status.get("latest_trade_date")
            today_text = date.today().strftime("%Y-%m-%d")
            if latest_date:
                if str(latest_date) < today_text:
                    st.warning(
                        f"최신 데이터 일자({latest_date})가 오늘({today_text})보다 이전입니다. 지금 업데이트 버튼 실행이 필요합니다."
                    )
                elif str(latest_date) == today_text:
                    st.success(
                        f"최신 데이터 일자({latest_date})가 오늘({today_text})과 같습니다. 필요 시 수동 업데이트를 실행할 수 있습니다."
                    )
                else:
                    st.info(
                        f"최신 데이터 일자({latest_date})가 오늘({today_text})보다 이후로 기록되어 있습니다."
                    )
            else:
                st.warning("최신 데이터 일자를 찾을 수 없습니다. 지금 업데이트 버튼 실행이 필요합니다.")
        if selected_menu == "2. 이평 돌파 종목 서칭":
            latest_scan = scan_status.get("latest_scan_label", "")
            today_prefix = date.today().strftime("%Y%m%d")
            if isinstance(latest_scan, str) and latest_scan.startswith(today_prefix):
                st.success("스캔이 완료되었습니다.")
            elif latest_scan and latest_scan != "미실행":
                st.warning("오늘자 스캔 결과가 없습니다. 지금 스캔 실행이 필요합니다.")
            else:
                st.warning("스캔 결과가 없습니다. 지금 스캔 실행이 필요합니다.")
        if selected_menu == "5. 관심종목 조회":
            st.info("tracking 폴더의 월별 관심 종목 데이터(예: watch_202604.csv)를 조회합니다.")
        if selected_menu == "6. 패턴 데이터 입력":
            st.info("4번과 동일 조회 화면에서 기록 데이터 저장을 지원합니다.")
        if selected_menu == "7. 패턴 데이터 조회":
            st.info("tracking 폴더의 기록 CSV 데이터를 조회합니다.")
        if selected_menu == "8. 보유 종목 조회":
            st.info("보유 종목 데이터를 조회합니다.")
    st.markdown("</div>", unsafe_allow_html=True)

if top_right is not None:
    with top_right:
        st.markdown("<div class='panel'>", unsafe_allow_html=True)
        st.subheader("전체 현황")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                "<div class='status-card'><div class='status-title'>데이터 최신화</div><div class='status-value'>{}</div></div>".format(
                    data_status["latest_collection_date"] or "미확인"
                ),
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div class='status-card'><div class='status-title'>수집 종목 파일</div><div class='status-value'>{:,}개</div></div>".format(
                    data_status["daily_file_count"]
                ),
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                "<div class='status-card'><div class='status-title'>최근 스캔</div><div class='status-value'>{}</div></div>".format(
                    scan_status["latest_scan_label"]
                ),
                unsafe_allow_html=True,
            )
            st.markdown(
                "<div class='status-card'><div class='status-title'>총 돌파 건수</div><div class='status-value'>{:,}건</div></div>".format(
                    scan_status["total_breakouts"]
                ),
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

if st.session_state.show_intro and scan_status["case_counts"]:
    st.markdown("### 케이스별 돌파 건수")
    case_df = pd.DataFrame(scan_status["case_counts"])
    st.dataframe(case_df, use_container_width=True, hide_index=True)

if not st.session_state.show_intro:
    st.markdown("<div class='panel'>", unsafe_allow_html=True)
    if selected_menu == "1. 데이터 저장":
        st.caption("`data_store.py` 실행 로그를 아래에서 확인합니다.")
        run_status_box = st.empty()

        if st.session_state.data_store_run_requested and not st.session_state.data_store_running:
            st.session_state.data_store_run_requested = False
            st.session_state.data_store_running = True
            st.rerun()

        col_run, col_clear = st.columns([1, 1])
        latest_collection_date = data_status.get("latest_collection_date")
        latest_collection_time = data_status.get("latest_collection_time")
        today_text = date.today().strftime("%Y-%m-%d")
        same_day_after_5 = (
            latest_collection_date == today_text
            and isinstance(latest_collection_time, str)
            and latest_collection_time >= "17:00"
        )

        run_button_label = "데이터 업데이트 실행"
        if st.session_state.awaiting_update_confirm:
            run_button_label = "확인: 데이터 최신, 다시 눌러 업데이트"
        if st.session_state.data_store_running:
            run_button_label = "데이터 업데이트 실행중..."

        with col_run:
            run_clicked = st.button(
                run_button_label,
                type="primary",
                use_container_width=True,
                key="run_data_store_button",
                disabled=st.session_state.data_store_running,
            )
        with col_clear:
            clear_clicked = st.button("로그 지우기", use_container_width=True, disabled=st.session_state.data_store_running)

        if clear_clicked:
            st.session_state.data_store_logs = []
            st.session_state.data_store_last_returncode = None
            st.session_state.awaiting_update_confirm = False

        execute_update = False

        if run_clicked:
            if same_day_after_5 and not st.session_state.awaiting_update_confirm:
                st.session_state.awaiting_update_confirm = True
            else:
                st.session_state.awaiting_update_confirm = False
                st.session_state.data_store_run_requested = True
                st.rerun()

        if st.session_state.awaiting_update_confirm:
            st.warning("데이터가 최신 입니다. 그래도 업데이트 하시겠습니까? 실행 버튼을 한 번 더 누르세요.")

        if st.session_state.data_store_running:
            run_status_box.info("data_store.py 실행중입니다.")
            logs, return_code = run_data_store_and_collect_logs()
            st.session_state.data_store_logs = logs
            st.session_state.data_store_last_returncode = return_code
            st.session_state.data_store_running = False

            if return_code == 0:
                run_status_box.success("데이터 업데이트가 완료되었습니다.")
            else:
                run_status_box.error(f"데이터 업데이트 중 오류가 발생했습니다. 종료 코드: {return_code}")

        if st.session_state.data_store_logs:
            if st.session_state.data_store_last_returncode == 0:
                run_status_box.success("데이터 업데이트가 완료되었습니다.")
            elif st.session_state.data_store_last_returncode is not None:
                run_status_box.error(f"데이터 업데이트 중 오류가 발생했습니다. 종료 코드: {st.session_state.data_store_last_returncode}")

            render_log_box(st.session_state.data_store_logs)
        else:
            run_status_box.info("업데이트 실행 전입니다. 버튼을 눌러 진행상황 로그를 확인하세요.")
    elif selected_menu == "2. 이평 돌파 종목 서칭":
        st.caption("`scripts/scan_market.py` 실행 로그를 아래에서 확인합니다.")
        run_status_box = st.empty()
        scan_progress_box = st.empty()

        if st.session_state.scan_market_run_requested and not st.session_state.scan_market_running:
            st.session_state.scan_market_run_requested = False
            st.session_state.scan_market_running = True
            st.rerun()

        col_run, col_clear = st.columns([1, 1])
        latest_scan = scan_status.get("latest_scan_label", "")
        today_prefix = date.today().strftime("%Y%m%d")
        already_scanned_today = isinstance(latest_scan, str) and latest_scan.startswith(today_prefix)

        run_button_label = "스캔 실행"
        if st.session_state.scan_market_running:
            run_button_label = "스캔 실행중..."
        elif st.session_state.awaiting_scan_confirm:
            run_button_label = "확인: 오늘 스캔 존재, 다시 눌러 실행"
        elif st.session_state.scan_market_last_returncode == 0:
            run_button_label = "스캔 완료"

        with col_run:
            run_clicked = st.button(
                run_button_label,
                type="primary",
                use_container_width=True,
                key="run_scan_market_button",
                disabled=st.session_state.scan_market_running,
            )
        with col_clear:
            clear_clicked = st.button(
                "로그 지우기",
                use_container_width=True,
                key="clear_scan_log",
                disabled=st.session_state.scan_market_running,
            )

        if clear_clicked:
            st.session_state.scan_market_logs = []
            st.session_state.scan_market_last_returncode = None
            st.session_state.awaiting_scan_confirm = False
            st.session_state.scan_market_latest_dir = None
            st.session_state.scan_progress_value = 0.0
            st.session_state.scan_progress_text = "스캔 대기 중"

        scan_progress_box.progress(
            float(st.session_state.scan_progress_value),
            text=st.session_state.scan_progress_text,
        )

        execute_scan = False

        if run_clicked:
            if already_scanned_today and not st.session_state.awaiting_scan_confirm:
                st.session_state.awaiting_scan_confirm = True
            else:
                st.session_state.awaiting_scan_confirm = False
                st.session_state.scan_market_run_requested = True
                st.rerun()

        if st.session_state.awaiting_scan_confirm:
            run_status_box.warning("오늘 스캔 결과가 이미 있습니다. 그래도 스캔 하시겠습니까? 실행 버튼을 한 번 더 누르세요.")
        elif not st.session_state.scan_market_logs and not execute_scan:
            run_status_box.info("스캔 실행 전입니다. 버튼을 눌러 진행상황 로그를 확인하세요.")

        if st.session_state.scan_market_running:
            run_status_box.info("scan_market.py 실행중입니다.")
            st.session_state.scan_progress_value = 0.0
            st.session_state.scan_progress_text = "스캔 시작"
            scan_progress_box.progress(0.0, text=st.session_state.scan_progress_text)
            logs, return_code = run_scan_market_and_collect_logs(scan_progress_box)
            st.session_state.scan_market_logs = logs
            st.session_state.scan_market_last_returncode = return_code
            latest_scan_status = get_scan_status(OUTPUT_DIR)
            st.session_state.scan_market_latest_dir = latest_scan_status.get("latest_scan_dir")
            st.session_state.scan_market_running = False

            scan_progress_box.progress(
                float(st.session_state.scan_progress_value),
                text=st.session_state.scan_progress_text,
            )

            if return_code == 0:
                run_status_box.success("스캔이 완료되었습니다.")
            else:
                run_status_box.error(f"스캔 실행 중 오류가 발생했습니다. 종료 코드: {return_code}")

        if st.session_state.scan_market_logs:
            if st.session_state.scan_market_last_returncode == 0:
                latest_dir = st.session_state.scan_market_latest_dir or scan_status.get("latest_scan_dir")
                if latest_dir:
                    st.caption(f"최신 스캔 결과 폴더: {latest_dir}")
            elif st.session_state.scan_market_last_returncode is not None:
                run_status_box.error(f"스캔 실행 중 오류가 발생했습니다. 종료 코드: {st.session_state.scan_market_last_returncode}")

            render_log_box(st.session_state.scan_market_logs)
    elif selected_menu == "3. 서칭 데이터 조회":
        st.caption("최신 스캔 결과를 웹 앱 내에서 직접 조회합니다.")
        review_data = load_scan_review_data(scan_status["latest_scan_dir"])
        cases = review_data.get("cases", {})

        if not cases:
            st.warning("최신 스캔 결과 데이터(all_breakouts/charts)를 찾지 못했습니다.")
        else:
            ctl1, ctl2, ctl3 = st.columns([2, 3, 3])
            with ctl1:
                sort_label = st.selectbox("정렬", ["강도순", "코드순"], index=0)
                sort_by = "strength" if sort_label == "강도순" else "code"
            with ctl2:
                breakout_filter_opt = st.selectbox(
                    "돌파율 필터",
                    options=["필터 없음", "최대 0.5%", "최대 1.0%", "최대 2.0%", "최대 3.0%", "최대 5.0%", "최대 10.0%"],
                    index=0,
                )
            with ctl3:
                volume_filter_opt = st.selectbox(
                    "볼륨% 필터",
                    options=["필터 없음", "최대 20%", "최대 30%", "최대 40%", "최대 50%", "최대 70%", "최대 100%"],
                    index=0,
                )

            max_breakout_pct = None
            if breakout_filter_opt != "필터 없음":
                max_breakout_pct = float(breakout_filter_opt.replace("최대", "").replace("%", "").strip())

            max_volume_pct = None
            if volume_filter_opt != "필터 없음":
                max_volume_pct = float(volume_filter_opt.replace("최대", "").replace("%", "").strip())

            filter_desc_breakout = "필터 없음" if max_breakout_pct is None else f"<= {max_breakout_pct:.1f}%"
            filter_desc_volume = "필터 없음" if max_volume_pct is None else f"<= {max_volume_pct:.1f}%"

            overview_rows = []
            total_all = 0
            total_filtered = 0
            ordered_case_keys = []
            for case_key in REVIEW_CASE_ORDER:
                if case_key in cases:
                    ordered_case_keys.append(case_key)
            for case_key in sorted(cases.keys()):
                if case_key not in ordered_case_keys:
                    ordered_case_keys.append(case_key)

            sorted_cases = [(case_key, cases[case_key]) for case_key in ordered_case_keys]
            for case_key, payload in sorted_cases:
                items = payload.get("items", [])
                filtered = []
                for x in items:
                    x_pct = x.get("breakout_pct")
                    x_vol = x.get("volume_pct")
                    if max_breakout_pct is not None:
                        if x_pct is None or pd.isna(x_pct) or float(x_pct) > float(max_breakout_pct):
                            continue
                    if max_volume_pct is not None:
                        if x_vol is None or pd.isna(x_vol) or float(x_vol) > float(max_volume_pct):
                            continue
                    filtered.append(x)

                total_all += len(items)
                total_filtered += len(filtered)
                overview_rows.append(
                    {
                        "구분": REVIEW_CASE_LABELS.get(case_key, payload.get("label", case_key)),
                        "전체 돌파 종목수": len(items),
                        "필터 적용 종목수": len(filtered),
                    }
                )

            st.markdown("#### Overview Table")
            st.caption(f"적용 필터: 돌파율 {filter_desc_breakout}, 볼륨% {filter_desc_volume}")

            table_rows_html = "".join(
                [
                    "<tr>"
                    f"<td>{html.escape(str(r.get('구분', '')))}</td>"
                    f"<td>{int(r.get('전체 돌파 종목수', 0)):,}</td>"
                    f"<td>{int(r.get('필터 적용 종목수', 0)):,}</td>"
                    "</tr>"
                    for r in overview_rows
                ]
            )
            st.markdown(
                (
                    "<div class='overview-table-wrap'>"
                    "<table class='overview-table'>"
                    "<thead><tr><th>구분</th><th>전체 돌파 종목수</th><th>필터 적용 종목수</th></tr></thead>"
                    f"<tbody>{table_rows_html}</tbody>"
                    "</table></div>"
                ),
                unsafe_allow_html=True,
            )
            s1, s2 = st.columns(2)
            s1.metric("전체 합계", f"{total_all:,}")
            s2.metric("필터 적용 합계", f"{total_filtered:,}")

            st.markdown("#### 케이스 선택")
            if "review_selected_case" not in st.session_state:
                st.session_state.review_selected_case = "weekly_ma10_breakout"

            case_layout = [
                ["weekly_ma10_breakout", "weekly_ma240_breakout"],
                ["monthly_ma10_breakout", "monthly_ma120_breakout"],
                ["monthly_ma180_breakout", "monthly_ma240_breakout"],
            ]

            case_layout_titles = ["주봉", "월봉(10,120)", "월봉(180,240)"]

            col1, col2, col3 = st.columns(3)
            for col, keys, title in zip([col1, col2, col3], case_layout, case_layout_titles):
                with col:
                    st.markdown(f"<div class='case-grid-title'>{title}</div>", unsafe_allow_html=True)
                    for key in keys:
                        label = REVIEW_CASE_LABELS.get(key, key)
                        btn_type = "primary" if st.session_state.review_selected_case == key else "secondary"
                        if st.button(label, key=f"case_sel_{key}", use_container_width=True, type=btn_type):
                            st.session_state.review_selected_case = key

            selected_key = st.session_state.review_selected_case
            if selected_key not in cases:
                selected_key = "weekly_ma10_breakout"
                st.session_state.review_selected_case = selected_key
            selected_payload = cases[selected_key]

            _render_case_gallery(
                case_key=selected_key,
                case_label=REVIEW_CASE_LABELS.get(selected_key, selected_payload.get("label", selected_key)),
                items=selected_payload.get("items", []),
                max_breakout_pct=max_breakout_pct,
                max_volume_pct=max_volume_pct,
                sort_by=sort_by,
            )
    elif selected_menu == "4. 관심종목 서칭":
        _render_stock_lookup_panel(save_mode="interest")
    elif selected_menu == "5. 관심종목 조회":
        _render_interest_watch_data()
    elif selected_menu == "6. 패턴 데이터 입력":
        _render_stock_lookup_panel(save_mode="record")
    elif selected_menu == "7. 패턴 데이터 조회":
        _render_saved_pattern_data()
    elif selected_menu == "8. 보유 종목 조회":
        _render_output_holdings_data()
    else:
        st.caption("하단의 넓은 영역은 실제 종목/스캔 결과 차트가 표시될 자리입니다.")
        chart_df = build_mock_chart_data()
        st.line_chart(chart_df, use_container_width=True, height=470)
    st.markdown("</div>", unsafe_allow_html=True)
