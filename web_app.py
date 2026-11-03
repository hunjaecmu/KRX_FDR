from __future__ import annotations

import os
import html
import re
import subprocess
import sys
import tempfile
import time
import zlib
from datetime import date, timedelta
from random import randint
from typing import Optional

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

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
    MA_BREAK_CSV,
    INDEX_TICKERS,
)
from data_loader import load_daily, load_master, load_monthly, load_weekly
from historical_chart_viewer import LOOKBACK_BARS, build_historical_chart_figure
from webapp import data_status as data_status_module
from webapp import lite_data, storage, thumbnails, tv_chart, user_guide, workflow


CLOUD_EDITION = os.getenv("KRX_APP_EDITION") == "cloud"
LITE_EDITION = CLOUD_EDITION or os.getenv("KRX_APP_EDITION") == "lite"
# 로컬 경량 버전만 이미지 차트를 쓰고, 메인과 서버 버전은 대화형 차트를 쓴다.
INTERACTIVE_CHART = CLOUD_EDITION or not LITE_EDITION

st.set_page_config(
    page_title="KRX FDR Lite" if LITE_EDITION else "KRX FDR Dashboard",
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


def run_data_store_and_collect_logs(data_progress_box, markets: Optional[list[str]] = None) -> tuple[list[str], int]:
    project_root = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(project_root, "data_store.py")
    command = [sys.executable, "-u", script_path, *(markets or [])]
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

    raw_done = 0
    raw_total = 1
    derived_done = 0
    derived_total = 1

    def _update_data_store_progress() -> None:
        raw_part = min(max(raw_done / raw_total, 0.0), 1.0)
        derived_part = min(max(derived_done / derived_total, 0.0), 1.0)
        total_part = min(max((raw_part * 0.5) + (derived_part * 0.5), 0.0), 1.0)

        st.session_state.data_store_progress_value = total_part
        st.session_state.data_store_progress_text = (
            f"전체 {total_part * 100:.2f}% "
            f"(RAW {raw_part * 50:.2f}% + DERIVED {derived_part * 50:.2f}%) "
            f"| RAW {raw_done}/{raw_total} | DERIVED {derived_done}/{derived_total}"
        )
        data_progress_box.progress(
            float(st.session_state.data_store_progress_value),
            text=st.session_state.data_store_progress_text,
        )
    if process.stdout is not None:
        last_render = 0.0
        while True:
            raw_line = process.stdout.readline()
            if not raw_line:
                if process.poll() is not None:
                    break
                time.sleep(0.05)
                continue

            line_text = _decode_log_bytes(raw_line)
            _append_log_text(logs, line_text)
            now = time.monotonic()
            if now - last_render >= 0.5:
                _render_live_log(live, logs)
                last_render = now

            current_line = logs[-1] if logs else ""

            raw_match = re.search(r"\[RAW\s+(\d+)/(\d+)\]", current_line)
            if raw_match:
                raw_done = int(raw_match.group(1))
                raw_total = int(raw_match.group(2)) if int(raw_match.group(2)) > 0 else 1
                _update_data_store_progress()

            derived_match = re.search(r"\[DERIVED\s+(\d+)/(\d+)\]", current_line)
            if derived_match:
                derived_done = int(derived_match.group(1))
                derived_total = int(derived_match.group(2)) if int(derived_match.group(2)) > 0 else 1
                _update_data_store_progress()

    return_code = process.wait()
    if return_code == 0:
        st.session_state.data_store_progress_value = 1.0
        st.session_state.data_store_progress_text = "전체 100.00% (RAW 50.00% + DERIVED 50.00%) | 완료"
        data_progress_box.progress(1.0, text=st.session_state.data_store_progress_text)
    else:
        st.session_state.data_store_progress_text = "데이터 업데이트 실패"
        data_progress_box.progress(
            float(st.session_state.data_store_progress_value),
            text=st.session_state.data_store_progress_text,
        )

    # 실행 완료 후 라이브 로그 placeholder를 비워, 하단 최종 로그 박스와 중복 렌더링되지 않게 한다.
    live.empty()

    return logs, return_code


SCAN_LOG_TAIL_BYTES = 256 * 1024
SCAN_LIVE_LOG_LINES = 24
SCAN_REFRESH_SEC = 1


@st.cache_resource
def _scan_job_registry() -> dict:
    # 서버 프로세스 전체에서 공유: 브라우저 새로고침/세션 변경에도 실행 중인 스캔을 유지한다.
    return {"proc": None, "log_path": None, "log_handle": None}


def is_scan_job_running() -> bool:
    proc = _scan_job_registry()["proc"]
    return proc is not None and proc.poll() is None


def start_scan_job() -> None:
    registry = _scan_job_registry()
    if is_scan_job_running():
        return

    project_root = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(project_root, "scripts", "scan_market.py")
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    log_path = os.path.join(tempfile.gettempdir(), "krx_scan_market.log")
    if registry["log_handle"] is not None:
        registry["log_handle"].close()
    log_handle = open(log_path, "wb")
    registry["log_handle"] = log_handle
    registry["log_path"] = log_path
    registry["proc"] = subprocess.Popen(
        [sys.executable, "-u", script_path],
        cwd=project_root,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=env,
    )


def _read_log_tail_lines(log_path: Optional[str], max_bytes: int = SCAN_LOG_TAIL_BYTES) -> list[str]:
    if not log_path or not os.path.isfile(log_path):
        return []
    with open(log_path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(size - max_bytes, 0))
        data = fh.read()
    lines: list[str] = []
    _append_log_text(lines, _decode_log_bytes(data))
    return lines


def _parse_scan_progress(lines: list[str]) -> tuple[float, str]:
    scan_done, scan_total, chart_done, chart_total = 0, 1, 0, 1
    for line in reversed(lines):
        if scan_total == 1 and scan_done == 0:
            m = re.search(r"\[SCAN\]\s*진행률:\s*(\d+)/(\d+)", line)
            if m:
                scan_done, scan_total = int(m.group(1)), max(int(m.group(2)), 1)
        if chart_total == 1 and chart_done == 0:
            m = re.search(r"\[CHART\]\s*생성중\s*(\d+)/(\d+)", line)
            if m:
                chart_done, chart_total = int(m.group(1)), max(int(m.group(2)), 1)
        if (scan_done or scan_total > 1) and (chart_done or chart_total > 1):
            break
    scan_part = min(max(scan_done / scan_total, 0.0), 1.0)
    chart_part = min(max(chart_done / chart_total, 0.0), 1.0)
    value = min(max(scan_part * 0.5 + chart_part * 0.5, 0.0), 1.0)
    return value, f"SCAN {scan_done}/{scan_total} | CHART {chart_done}/{chart_total}"


def _finalize_scan_job() -> None:
    registry = _scan_job_registry()
    return_code = registry["proc"].poll()
    lines = _read_log_tail_lines(registry["log_path"])
    st.session_state.scan_market_logs = lines
    st.session_state.scan_market_last_returncode = return_code
    if return_code == 0:
        st.session_state.scan_progress_value = 1.0
        st.session_state.scan_progress_text = "SCAN 완료 | CHART 완료"
    else:
        st.session_state.scan_progress_text = "스캔 실패"
    st.session_state.scan_market_latest_dir = get_scan_status(OUTPUT_DIR).get("latest_scan_dir")
    st.session_state.scan_market_running = False
    st.rerun()


def render_scan_job_status() -> None:
    """파일 로그의 마지막 일부와 진행률만 읽어 표시한다. 스캔 자체는 별도 프로세스에서 실행된다."""
    registry = _scan_job_registry()
    lines = _read_log_tail_lines(registry["log_path"])
    value, text = _parse_scan_progress(lines)
    st.session_state.scan_progress_value = value
    st.session_state.scan_progress_text = text
    st.progress(value, text=text)
    _render_live_log(st.empty(), lines, max_lines=SCAN_LIVE_LOG_LINES)

    if not is_scan_job_running():
        _finalize_scan_job()


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

    # 패턴 기록은 왼쪽에 검색, 오른쪽에 저장을 두고 그 아래에 차트를 그린다.
    split_save = save_mode == "record" and not LITE_EDITION
    search_area, save_area = st.columns(2, gap="large") if split_save else (st.container(), None)

    with search_area:
        if split_save:
            st.markdown("#### 종목 검색")

        if split_save:
            mode_slot, input_slot, pick_slot = st.columns(3)
            year_slot, month_day_slot, timeframe_slot = st.columns(3)
            run_slot = st.container()
        else:
            c1, c2 = st.columns([1.2, 1.8])
            mode_slot = input_slot = pick_slot = c1
            year_slot = month_day_slot = timeframe_slot = run_slot = c2

        with mode_slot:
            stock_mode = st.radio(
                "종목 선택 방식",
                options=["종목명 2글자 검색", "코드 직접입력"] if split_save else ["코드 직접입력", "종목명 2글자 검색"],
                horizontal=False,
                key=f"{prefix}_stock_mode",
            )

        # 왼쪽 검색 영역은 선택한 방식의 입력칸만 보여준다.
        stock_code_input = ""
        prefix_input = ""
        with input_slot:
            if not split_save or stock_mode == "코드 직접입력":
                stock_code_input = st.text_input(
                    "종목코드 입력 (예: 005930)",
                    value="",
                    max_chars=6,
                    disabled=(stock_mode != "코드 직접입력"),
                    key=f"{prefix}_stock_code",
                )

            if not split_save or stock_mode == "종목명 2글자 검색":
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

        with pick_slot:
            stock_pick = st.selectbox(
                "추천 종목 리스트",
                options=candidate_labels if candidate_labels else [""],
                index=0,
                disabled=(stock_mode != "종목명 2글자 검색"),
                key=f"{prefix}_stock_pick",
            )

        current_year = date.today().year
        with year_slot:
            year_input = st.number_input(
                "연도 입력 (예: 2026)",
                min_value=1900,
                max_value=2100,
                value=current_year,
                step=1,
                key=f"{prefix}_year",
            )
        with month_day_slot:
            month_day_input = st.text_input(
                "월일 입력 (예: 0315 또는 3-15)",
                value=date.today().strftime("%m%d"),
                key=f"{prefix}_month_day",
            )
        with timeframe_slot:
            timeframe_label = st.radio(
                "봉 타입 선택",
                options=["1: 주봉", "2: 월봉"],
                horizontal=True,
                key=f"{prefix}_timeframe",
            )

        with run_slot:
            run_col1, run_col2, run_col3 = st.columns(3)
            with run_col1:
                run_lookup = st.button("종목 차트 조회", type="primary", width="stretch", key=f"{prefix}_run_lookup")
            with run_col2:
                move_prev = st.button("이전 1봉", width="stretch", key=f"{prefix}_move_prev")
            with run_col3:
                move_next = st.button("다음 1봉", width="stretch", key=f"{prefix}_move_next")

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
            if save_mode == "record":
                # 패턴 기록은 입력 날짜가 속한 주(달)의 봉을 기준봉으로 삼는다.
                target_date = tv_chart.period_end(target_date, timeframe)

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
        if split_save:
            with save_area:
                st.markdown(f"#### {panel_title}")
                st.info("종목 차트를 조회하면 저장할 수 있습니다.")
        return

    try:
        show_chart, anchor_date = _build_stock_chart(
            str(state["code"]), str(state["name"]), str(state["timeframe"]), state["target_date"]
        )
        state["target_date"] = anchor_date.strftime("%Y-%m-%d")
        st.session_state[state_key] = state

        def render_save_form() -> None:
            if not split_save:
                st.markdown("---")
            st.markdown(f"#### {panel_title}")

            save_col1, save_col2 = st.columns([1.1, 1.9])
            with save_col1:
                classification = st.selectbox(
                    "분류",
                    options=["10이평", "120이평", "180이평", "240이평"] + (["해당 없음"] if save_mode == "record" else []),
                    index=0,
                    key=f"{prefix}_classification",
                )
            selected_patterns: list[str] = []
            if save_mode == "record":
                with save_col2:
                    with st.container(key="pattern_checkboxes"):
                        st.caption("패턴 구분 (여러 개 선택 가능)")
                        pattern_cols = st.columns(2)
                        for i, label in enumerate(storage.pattern_labels()):
                            with pattern_cols[i % 2]:
                                if st.checkbox(label, key=f"{prefix}_pattern_{i}"):
                                    selected_patterns.append(label)
                memo_text = st.text_input("메모", value="", key=f"{prefix}_memo")
            else:
                with save_col2:
                    memo_text = st.text_input("메모", value="", key=f"{prefix}_memo")
                    current_watch_path = storage.interest_watch_monthly_path()
                    st.caption(f"관심 저장 파일: {os.path.basename(current_watch_path)}")

            if st.button("현재 차트 데이터 저장", width="stretch", key=f"{prefix}_save"):
                try:
                    if save_mode == "record" and not selected_patterns:
                        raise ValueError("패턴 구분을 하나 이상 선택하세요.")

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

                    if save_mode == "interest":
                        target_file = storage.interest_watch_monthly_path()
                    else:
                        storage.merge_legacy_record_files()
                        target_file = MA_BREAK_CSV
                        row = {storage.PATTERN_COLUMN: storage.PATTERN_SEPARATOR.join(selected_patterns), **row}

                    storage.append_row(target_file, row)
                    st.success(f"저장 완료: {target_file}")
                except Exception as save_e:
                    st.error(f"저장 실패: {save_e}")

        if split_save:
            with save_area:
                render_save_form()

        st.success(
            f"{state['name']} ({state['code']}) | 기준봉 {anchor_date.strftime('%Y-%m-%d')} | "
            f"{'주봉' if state['timeframe'] == 'weekly' else '월봉'} {LOOKBACK_BARS}봉"
        )
        show_chart()

        if not split_save and not LITE_EDITION:
            render_save_form()
    except Exception as e:
        st.error(str(e))


def _render_interest_watch_data() -> None:
    st.caption("tracking 폴더의 월별 관심 종목 CSV 데이터를 조회합니다.")
    tracking_dir = TRACKING_INPUT_DIR
    os.makedirs(tracking_dir, exist_ok=True)

    watch_options = storage.interest_watch_file_options(tracking_dir)
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
            wdf = storage.read_csv(watch_path, dtype=str)
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
                if st.button("이전 10개", width="stretch", key="watch_prev_page"):
                    st.session_state[page_key] = max(0, int(st.session_state[page_key]) - 1)
            with nav2:
                if st.button("다음 10개", width="stretch", key="watch_next_page"):
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
                    width="stretch",
                    on_select="rerun",
                    selection_mode="single-row",
                    key="watch_action_table",
                )
                if table_event is not None and hasattr(table_event, "selection"):
                    selected_rows = list(getattr(table_event.selection, "rows", []) or [])
            except TypeError:
                st.dataframe(styled_action, width="stretch")

            c1, c2 = st.columns([1, 5])
            with c1:
                chart_clicked = st.button("차트", key="watch_action_chart", width="stretch")
            with c2:
                delete_clicked = st.button("삭제", key="watch_action_delete", width="stretch")

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
                    if st.button("예", key="watch_delete_yes", width="stretch"):
                        try:
                            drop_idx = int(pending_idx)
                            if 0 <= drop_idx < len(wdf):
                                updated = wdf.drop(index=drop_idx).reset_index(drop=True)
                                storage.write_csv(watch_path, updated)
                            st.session_state.pop("watch_delete_pending_idx", None)
                            st.session_state.pop("watch_delete_pending_name", None)
                            st.rerun()
                        except Exception as del_e:
                            st.error(f"삭제 실패: {del_e}")
                with confirm_cols[2]:
                    if st.button("아니오", key="watch_delete_no", width="stretch"):
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
                move_prev = st.button("이전 1봉", key="watch_chart_prev", width="stretch")
            with mv2:
                move_home = st.button("처음위치로", key="watch_chart_home", width="stretch")
            with mv3:
                move_next = st.button("다음 1봉", key="watch_chart_next", width="stretch")
            with mv4:
                memo_input = st.text_area(
                    "메모",
                    key=memo_state_key,
                    label_visibility="collapsed",
                    placeholder="메모를 입력하세요",
                    height=68,
                )
            with mv5:
                memo_save_clicked = st.button("메모저장", key="watch_chart_memo_save", width="stretch")

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
                        storage.write_csv(watch_path, wdf)
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
                show_chart, anchor_date = _build_stock_chart(
                    str(state["code"]),
                    str(state["name"]),
                    str(state["timeframe"]),
                    state["target_date"],
                    origin_date_text=str(state.get("origin_target_date", state["target_date"])),
                )
                state["target_date"] = anchor_date.strftime("%Y-%m-%d")
                st.session_state[chart_state_key] = state

                st.success(
                    f"{state['name']} ({state['code']}) | 기준봉 {anchor_date.strftime('%Y-%m-%d')} | "
                    f"{'주봉' if state['timeframe'] == 'weekly' else '월봉'} {LOOKBACK_BARS}봉"
                )
                show_chart()
            except Exception as chart_e:
                st.error(f"차트 생성 실패: {chart_e}")
        except Exception as e:
            st.error(f"관심 파일 조회 실패: {e}")
    else:
        st.info("선택한 관심 파일이 아직 생성되지 않았습니다.")


def _render_saved_pattern_data() -> None:
    selected_record_path = MA_BREAK_CSV
    try:
        merged_rows = storage.merge_legacy_record_files()
    except (storage.CsvReadError, OSError) as merge_e:
        st.error(f"기록 파일 통합 실패: {merge_e}")
        return
    if merged_rows:
        st.success(f"기존 기록 {merged_rows:,}행을 ma_break.csv로 통합했습니다.")

    if os.path.isfile(selected_record_path):
        try:
            rdf = storage.read_csv(selected_record_path, dtype=str)
            st.caption(f"파일: {selected_record_path}")

            if rdf.empty:
                st.info("기록 데이터가 비어 있습니다.")
                return

            rdf = rdf.fillna("").reset_index(drop=True)
            if storage.PATTERN_COLUMN not in rdf.columns:
                rdf[storage.PATTERN_COLUMN] = ""

            row_pattern_lists = rdf[storage.PATTERN_COLUMN].map(storage.row_patterns)
            rdf[storage.PATTERN_COLUMN] = row_pattern_lists.map(storage.PATTERN_SEPARATOR.join)
            pattern_counts = {
                label: int(row_pattern_lists.map(lambda p, label=label: label in p).sum())
                for label in storage.pattern_labels()
            }
            available_patterns = [label for label, count in pattern_counts.items() if count > 0]
            if not available_patterns:
                st.info("패턴 기록이 없습니다.")
                return

            pattern_key = "pattern_view_pattern"
            page_key = "pattern_page_idx"
            if st.session_state.get(pattern_key) not in available_patterns:
                st.session_state[pattern_key] = available_patterns[0]
                st.session_state[page_key] = 0

            # 개수가 0인 패턴은 고를 수 없다.
            pattern_cols = st.columns(len(pattern_counts))
            for i, (label, count) in enumerate(pattern_counts.items()):
                with pattern_cols[i]:
                    st.button(
                        f"{label} :small[({count})]",
                        key=f"pattern_view_button_{i}",
                        type="primary" if label == st.session_state[pattern_key] else "secondary",
                        disabled=count == 0,
                        width="stretch",
                        on_click=lambda label=label: st.session_state.update({pattern_key: label, page_key: 0}),
                    )

            pattern_filter = st.session_state[pattern_key]
            rdf = rdf[row_pattern_lists.map(lambda p: pattern_filter in p)].reset_index(drop=True)

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

            if page_key not in st.session_state:
                st.session_state[page_key] = 0
            st.session_state[page_key] = max(0, min(int(st.session_state[page_key]), total_pages - 1))

            list_col, chart_col = st.columns([1, 2], gap="large")
            with list_col:
                nav1, nav2 = st.columns(2)
                with nav1:
                    if st.button("이전 10개", width="stretch", key="pattern_prev_page"):
                        st.session_state[page_key] = max(0, int(st.session_state[page_key]) - 1)
                with nav2:
                    if st.button("다음 10개", width="stretch", key="pattern_next_page"):
                        st.session_state[page_key] = min(total_pages - 1, int(st.session_state[page_key]) + 1)
                st.caption(f"페이지 {int(st.session_state[page_key]) + 1}/{total_pages} | 총 {total_rows}건")

                start = int(st.session_state[page_key]) * page_size
                end = min(start + page_size, total_rows)

                # 기록 하나를 두 줄로 보여준다: 종목 정보 / 메모
                def record_line(idx: int) -> str:
                    row = rdf.iloc[idx]
                    parts = [
                        f"{str(row.get('종목명', '')).strip()} ({row['종목코드']})",
                        str(row.get("주봉 or 월봉 선택", "")).strip(),
                        str(row.get("분류", "")).strip(),
                        str(row.get("종목의 마지막 봉의 날짜", "")).strip(),
                    ]
                    return " · ".join(p for p in parts if p and p != "nan")

                record_indices = list(range(start, end))
                memos = [str(rdf.iloc[i].get("메모", "")).strip() or "메모 없음" for i in record_indices]
                with st.container(key="pattern_records"):
                    picked_idx = st.radio(
                        "기록 데이터",
                        options=record_indices,
                        format_func=record_line,
                        captions=memos,
                        key=f"pattern_record_{pattern_filter}_{st.session_state[page_key]}",
                        label_visibility="collapsed",
                    )

            chosen = rdf.iloc[int(picked_idx)]
            picked = {
                "code": str(chosen.get("종목코드", "")).strip().zfill(6),
                "name": str(chosen.get("종목명", "")).strip(),
                "date": str(chosen.get("종목의 마지막 봉의 날짜", "")).strip(),
                "timeframe_text": str(chosen.get("주봉 or 월봉 선택", "")).strip(),
            }

            with chart_col:
                timeframe_text = str(picked.get("timeframe_text", "")).strip()
                timeframe = "weekly" if "주" in timeframe_text or timeframe_text.lower().startswith("w") else "monthly"

                target_date_text = str(picked.get("date", "")).strip()
                try:
                    target_date = pd.to_datetime(target_date_text)
                except Exception:
                    target_date = pd.Timestamp(date.today())
                # 기록 날짜가 속한 주(달)의 봉을 기준봉으로 삼는다.
                target_date = tv_chart.period_end(target_date, timeframe)

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
                    move_prev = st.button("이전 1봉", key="pattern_chart_prev", width="stretch")
                with mv2:
                    move_home = st.button("처음위치로", key="pattern_chart_home", width="stretch")
                with mv3:
                    move_next = st.button("다음 1봉", key="pattern_chart_next", width="stretch")

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
                    show_chart, anchor_date = _build_stock_chart(
                        str(state["code"]),
                        str(state["name"]),
                        str(state["timeframe"]),
                        state["target_date"],
                        origin_date_text=str(state.get("origin_target_date", state["target_date"])),
                        # 월봉은 240이평 데이터가 없어도 범례에 NaN으로 보여준다.
                        required_mas=("ma240",) if state["timeframe"] == "monthly" else (),
                        close_trail_bars=10,
                    )
                    state["target_date"] = anchor_date.strftime("%Y-%m-%d")
                    st.session_state[chart_state_key] = state

                    st.success(
                        f"{state['name']} ({state['code']}) | 기준봉 {anchor_date.strftime('%Y-%m-%d')} | "
                        f"{'주봉' if state['timeframe'] == 'weekly' else '월봉'} {LOOKBACK_BARS}봉"
                    )
                    show_chart()
                except Exception as chart_e:
                    st.error(f"차트 생성 실패: {chart_e}")
        except Exception as e:
            st.error(f"기록 파일 조회 실패: {e}")
    else:
        st.info("선택한 기록 파일이 아직 생성되지 않았습니다.")


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
def _latest_timeframe_ma240_metrics(code: str, timeframe: str) -> dict:
    loader = load_weekly if timeframe == "weekly" else load_monthly
    try:
        df = loader(str(code).zfill(6))
    except Exception:
        return {"close": None, "ma240": None, "breakout_rate": None}

    if df is None or df.empty:
        return {"close": None, "ma240": None, "breakout_rate": None}

    work = df.copy()
    work["date"] = pd.to_datetime(work.get("date"), errors="coerce")
    work["close"] = pd.to_numeric(work.get("close"), errors="coerce")
    work["ma240"] = pd.to_numeric(work.get("ma240"), errors="coerce")
    work = work.dropna(subset=["date"]).sort_values("date")
    if work.empty:
        return {"close": None, "ma240": None, "breakout_rate": None}

    recent = work.iloc[-1]
    close_val = pd.to_numeric(recent.get("close"), errors="coerce")
    ma240_val = pd.to_numeric(recent.get("ma240"), errors="coerce")

    if pd.notna(close_val) and pd.notna(ma240_val) and float(ma240_val) != 0.0:
        breakout_rate = (float(close_val) / float(ma240_val)) - 1.0
    else:
        breakout_rate = None

    return {
        "close": float(close_val) if pd.notna(close_val) else None,
        "ma240": float(ma240_val) if pd.notna(ma240_val) else None,
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


def _build_stock_chart(
    code: str,
    name: str,
    timeframe: str,
    target_date_text: str,
    origin_date_text: Optional[str] = None,
    buy_price: Optional[float] = None,
    required_mas: tuple[str, ...] = (),
    close_trail_bars: int = 0,
):
    """차트를 준비해 (표시 함수, 기준봉 날짜)를 돌려준다."""
    target_date = pd.to_datetime(target_date_text)
    if not INTERACTIVE_CHART:
        fig, anchor_date = build_historical_chart_figure(
            code=code, name=name, timeframe=timeframe, target_date=target_date, lookback_bars=LOOKBACK_BARS
        )
        if origin_date_text:
            _add_anchor_guides_to_chart(
                fig=fig,
                code=code,
                timeframe=timeframe,
                current_target_date_text=anchor_date.strftime("%Y-%m-%d"),
                origin_target_date_text=origin_date_text,
            )
        if buy_price is not None and getattr(fig, "axes", None):
            fig.axes[0].axhline(y=buy_price, color="#000000", linestyle="-", linewidth=0.7, alpha=0.95, zorder=10)
        return (lambda: st.pyplot(fig, width="stretch")), anchor_date

    df = load_weekly(code) if timeframe == "weekly" else load_monthly(code)
    price_lines = []
    marker_date = None
    if origin_date_text:
        origin_close = _timeframe_close_at_or_before(
            code=code, timeframe=timeframe, target_date_text=pd.to_datetime(origin_date_text).strftime("%Y-%m-%d")
        )
        if origin_close is not None:
            price_lines.append({"price": float(origin_close), "title": "기준"})
        marker_date = pd.to_datetime(origin_date_text)
    if buy_price is not None:
        price_lines.append({"price": buy_price, "title": "매수가"})

    label = "주봉" if timeframe == "weekly" else "월봉"
    payload = tv_chart.build_payload(
        df,
        target_date,
        f"{name} ({code}) {label}",
        LOOKBACK_BARS,
        price_lines=price_lines,
        marker_date=marker_date,
        required_mas=required_mas,
        close_trail_bars=close_trail_bars,
    )
    chart_html = tv_chart.render_html(payload, theme=tv_chart.DARK_THEME if LITE_EDITION else tv_chart.LIGHT_THEME)
    return (lambda: components.html(chart_html, height=tv_chart.CHART_HEIGHT)), pd.to_datetime(payload["anchor"])


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
    code_col = storage.pick_column(raw_df, storage.HOLDINGS_CODE_CANDIDATES)
    if code_col is None:
        raise ValueError("holdings.csv에 종목코드 컬럼(code/종목코드/티커/ticker)이 없습니다.")

    name_col = storage.pick_column(raw_df, storage.HOLDINGS_NAME_CANDIDATES)
    buy_col = storage.pick_column(raw_df, storage.HOLDINGS_BUY_PRICE_CANDIDATES)
    qty_col = storage.pick_column(raw_df, storage.HOLDINGS_QUANTITY_CANDIDATES)
    memo_col = storage.pick_column(raw_df, storage.HOLDINGS_MEMO_CANDIDATES)

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
        weekly_240 = _latest_timeframe_ma240_metrics(str(row["종목코드"]), timeframe="weekly")
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
                "주봉 240이평": weekly_240.get("ma240"),
                "월봉 10이평": monthly.get("ma10"),
                "이격도(주)": weekly.get("breakout_rate"),
                "이격도(주240)": weekly_240.get("breakout_rate"),
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
        "주봉 240이평",
        "월봉 10이평",
        "이격도(주)",
        "이격도(주240)",
        "이격도(월)",
    ]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    return out


def _render_output_holdings_data() -> None:
    holdings_path = HOLDINGS_CSV
    os.makedirs(os.path.dirname(holdings_path), exist_ok=True)
    master = get_master_table()

    st.markdown("#### 보유 종목 추가")
    add_code_candidates: list[str] = []
    add_name_prefix = st.text_input(
        "종목명 앞 2글자 입력",
        value="",
        max_chars=20,
        key="holdings_add_name_prefix",
    )
    if len(str(add_name_prefix).strip()) >= 2:
        if not master.empty and {"code", "name"}.issubset(set(master.columns)):
            filtered = master[master["name"].astype(str).str.startswith(str(add_name_prefix).strip())].copy()
            if not filtered.empty:
                filtered = filtered.sort_values(["name", "code"])
                add_code_candidates = [
                    f"{str(r['name']).strip()} ({str(r['code']).zfill(6)})"
                    for _, r in filtered.iterrows()
                ]

    add_stock_pick = st.selectbox(
        "추천 종목 리스트",
        options=add_code_candidates if add_code_candidates else [""],
        index=0,
        key="holdings_add_stock_pick",
    )

    selected_code = ""
    selected_name = ""
    picked_text = str(add_stock_pick).strip()
    if picked_text:
        m = re.match(r"^(.*)\((\d{6})\)$", picked_text)
        if m:
            selected_name = str(m.group(1)).strip()
            selected_code = str(m.group(2)).strip().zfill(6)

    if st.session_state.get("holdings_add_code", "") != selected_code:
        st.session_state["holdings_add_code"] = selected_code
    if st.session_state.get("holdings_add_name", "") != selected_name:
        st.session_state["holdings_add_name"] = selected_name

    add_c1, add_c2, add_c3, add_c4, add_c5 = st.columns([1.1, 1.3, 1.0, 0.9, 2.2])
    with add_c1:
        add_code = st.text_input(
            "종목코드",
            value="",
            max_chars=6,
            key="holdings_add_code",
            disabled=True,
        )
    with add_c2:
        add_name = st.text_input(
            "종목명",
            value="",
            key="holdings_add_name",
            disabled=True,
        )
    with add_c3:
        add_buy = st.text_input("매수가", value="", key="holdings_add_buy")
    with add_c4:
        add_qty = st.text_input("수량", value="", key="holdings_add_qty")
    with add_c5:
        add_memo = st.text_input("메모", value="", key="holdings_add_memo")

    if st.button("보유 종목 추가", key="holdings_add_submit", width="stretch"):
        try:
            code = str(add_code).strip().replace(" ", "").zfill(6)
            resolved_name = str(add_name).strip()
            if not re.fullmatch(r"\d{6}", code):
                raise ValueError("추천 종목 리스트에서 종목을 선택하세요.")
            if not resolved_name:
                raise ValueError("추천 종목 리스트에서 종목을 선택하세요.")

            buy_val = pd.to_numeric(str(add_buy).strip().replace(",", ""), errors="coerce")
            qty_val = pd.to_numeric(str(add_qty).strip().replace(",", ""), errors="coerce")
            if pd.isna(buy_val) or float(buy_val) <= 0:
                raise ValueError("매수가는 0보다 큰 숫자로 입력하세요.")
            if pd.isna(qty_val) or float(qty_val) <= 0:
                raise ValueError("수량은 0보다 큰 숫자로 입력하세요.")

            storage.add_holding_row(
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
            hdf = storage.read_csv(holdings_path, dtype=str)
            memo_col_name = storage.pick_column(hdf, storage.HOLDINGS_MEMO_CANDIDATES)
            if memo_col_name is None:
                hdf["메모"] = ""
                storage.write_csv(holdings_path, hdf)
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
                "주봉 240이평",
                "이격도(주240)",
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

            right_align_cols = ["매수가", "현재 종가", "수익률", "이격도(주)", "이격도(주240)", "이격도(월)"]
            center_align_cols = ["종목코드", "종목명", "가격일자"]
            styled_action = (
                action_view.style
                .format(
                    {
                        "매수가": lambda x: "" if pd.isna(x) else f"{x:,.0f}",
                        "현재 종가": lambda x: "" if pd.isna(x) else f"{x:,.0f}",
                        "주봉 10이평": lambda x: "" if pd.isna(x) else f"{x:,.0f}",
                        "주봉 240이평": lambda x: "" if pd.isna(x) else f"{x:,.0f}",
                        "월봉 10이평": lambda x: "" if pd.isna(x) else f"{x:,.0f}",
                        "수익률": lambda x: "" if pd.isna(x) else f"{x:.2f}%",
                        "이격도(주)": lambda x: "" if pd.isna(x) else f"{x:.2f}%",
                        "이격도(주240)": lambda x: "" if pd.isna(x) else f"{x:.2f}%",
                        "이격도(월)": lambda x: "" if pd.isna(x) else f"{x:.2f}%",
                    }
                )
                .set_properties(subset=right_align_cols, **{"text-align": "right"})
                .set_properties(subset=center_align_cols, **{"text-align": "center"})
                .map(_pos_neg_color, subset=["수익률", "이격도(주)", "이격도(주240)", "이격도(월)"])
            )

            holdings_column_config = {
                "메모": st.column_config.TextColumn(width="large"),
            }

            selected_rows = []
            try:
                table_event = st.dataframe(
                    styled_action,
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
                    width=1600,
                    column_config=holdings_column_config,
                )

            btn1, btn2, btn3 = st.columns([1, 1, 4])
            with btn1:
                chart_clicked = st.button("차트", key="holdings_action_chart", width="stretch")
            with btn2:
                delete_clicked = st.button("삭제", key="holdings_action_delete", width="stretch")

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
                    if st.button("예", key="holdings_delete_yes", width="stretch"):
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
                                storage.append_row(storage.interest_watch_monthly_path(), interest_row)

                            if 0 <= raw_idx < len(hdf):
                                updated_hdf = hdf.drop(index=raw_idx).reset_index(drop=True)
                                storage.write_csv(holdings_path, updated_hdf)
                            st.session_state.pop("holdings_delete_pending_raw", None)
                            st.session_state.pop("holdings_delete_pending_name", None)
                            st.session_state.pop("holdings_delete_pending_code", None)
                            st.session_state.pop("holdings_delete_pending_memo", None)
                            st.rerun()
                        except Exception as del_e:
                            st.error(f"삭제 실패: {del_e}")
                with dc3:
                    if st.button("아니오", key="holdings_delete_no", width="stretch"):
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
                        memo_col_name = storage.pick_column(hdf, storage.HOLDINGS_MEMO_CANDIDATES)
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
                    move_prev = st.button("이전 1봉", key="holdings_chart_prev", width="stretch")
                with mv2:
                    move_next = st.button("다음 1봉", key="holdings_chart_next", width="stretch")
                with mv3:
                    memo_input = st.text_area(
                        "메모",
                        key=memo_state_key,
                        label_visibility="collapsed",
                        placeholder="메모를 입력하세요",
                        height=68,
                    )
                with mv4:
                    memo_save_clicked = st.button("메모저장", key="holdings_chart_memo_save", width="stretch")

                if memo_save_clicked:
                    try:
                        memo_col_name = storage.pick_column(hdf, storage.HOLDINGS_MEMO_CANDIDATES) or "메모"
                        if memo_col_name not in hdf.columns:
                            hdf[memo_col_name] = ""

                        if not (isinstance(memo_row_idx, int) and 0 <= int(memo_row_idx) < len(hdf)):
                            st.error("메모 저장 대상 행을 찾지 못했습니다.")
                        else:
                            hdf.loc[int(memo_row_idx), memo_col_name] = str(memo_input)
                            storage.write_csv(holdings_path, hdf)
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
                    buy_price = pd.to_numeric(picked.get("buy_price"), errors="coerce")
                    show_chart, anchor_date = _build_stock_chart(
                        str(state["code"]),
                        str(state["name"]),
                        str(state["timeframe"]),
                        state["target_date"],
                        buy_price=float(buy_price) if pd.notna(buy_price) else None,
                    )
                    state["target_date"] = anchor_date.strftime("%Y-%m-%d")
                    st.session_state[chart_state_key] = state

                    st.success(
                        f"{state['name']} ({state['code']}) | 기준봉 {anchor_date.strftime('%Y-%m-%d')} | "
                        f"{'주봉' if state['timeframe'] == 'weekly' else '월봉'} {LOOKBACK_BARS}봉"
                    )
                    show_chart()
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


@st.cache_data(show_spinner=False, ttl=300)
def get_data_status(data_dir: str) -> dict:
    if CLOUD_EDITION:
        return lite_data.load_manifest(data_dir)["data_status"]
    return data_status_module.compute_data_status(data_dir)


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
            sdf = storage.read_csv(summary_path)
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
        "load_error": None,
    }
    if not scan_dir or not os.path.isdir(scan_dir):
        return empty

    cases: dict = {}
    load_error = None

    all_breakouts_path = os.path.join(scan_dir, "all_breakouts.csv")
    if os.path.isfile(all_breakouts_path):
        try:
            bdf = storage.read_csv(all_breakouts_path, dtype={"code": str})
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
                        "is_final": row.get("is_final"),
                    }
                )
        except Exception as e:
            load_error = f"all_breakouts.csv 읽기 실패: {e}"

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
                        "is_final": row.get("is_final"),
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
        "load_error": load_error,
    }


@st.cache_data(show_spinner=False)
def _dark_thumbnail(image_path: str) -> str:
    return thumbnails.dark_thumbnail_data_uri(image_path)


def _format_pct(value, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):.{digits}f}%"


def _bar_chips_html(bar_date: object, is_final: object) -> str:
    chips = []
    if str(bar_date or "").strip():
        chips.append(f"<span class='chip'>봉 <b>{html.escape(str(bar_date))}</b></span>")
    final_text = str(is_final).strip().lower()
    if final_text == "true":
        chips.append("<span class='chip chip-final'>확정 봉</span>")
    elif final_text == "false":
        chips.append("<span class='chip chip-open'>진행 중 봉</span>")
    return "".join(chips)


def _move_gallery(idx_key: str, delta: int, last_index: int, clicked_key: str, nonce_key: str) -> None:
    st.session_state[idx_key] = min(max(int(st.session_state.get(idx_key, 0)) + delta, 0), last_index)
    # 썸네일 위젯은 마지막 클릭값을 유지해 같은 썸네일을 다시 눌러도 반응하지 않으므로 새로 만든다.
    if st.session_state.pop(clicked_key, False):
        st.session_state[nonce_key] = int(st.session_state.get(nonce_key, 0)) + 1


def _select_major_stock(code: str) -> None:
    st.session_state.major_stock_code = code
    st.session_state.major_timeframe = "주봉"


def _available_major_indexes() -> list[tuple[str, str]]:
    manifest = lite_data.load_manifest(DATA_DIR) or {}
    codes = manifest.get("indices", [])
    return [(code, name) for code, name in INDEX_TICKERS if code in codes]


def _render_index_summaries() -> None:
    summaries = (lite_data.load_manifest(DATA_DIR) or {}).get("index_summaries", [])
    if not summaries:
        return

    for col, item in zip(st.columns(len(summaries)), summaries):
        change = item.get("change_pct")
        if change is None:
            change_text, change_class = "-", ""
        else:
            change_text = f"{float(change):+.2f}%"
            change_class = "index-up" if change > 0 else "index-down" if change < 0 else ""
        with col:
            st.markdown(
                f"<div class='status-card'><div class='status-title'>{html.escape(str(item['name']))} "
                f"| {html.escape(str(item['date']))} {html.escape(str(item.get('price_status', '')))}</div>"
                f"<div class='status-value'>{float(item['close']):,.2f} "
                f"<span class='{change_class}'>{change_text}</span></div></div>",
                unsafe_allow_html=True,
            )


def _render_major_buttons(title: str, items: list[tuple[str, str]], selected_code: Optional[str]) -> None:
    st.markdown(f"<div class='case-grid-title'>{title}</div>", unsafe_allow_html=True)
    for col, (code, name) in zip(st.columns(len(MAJOR_STOCKS)), items):
        with col:
            st.button(
                name,
                key=f"major_stock_{code}",
                width="stretch",
                type="primary" if code == selected_code else "secondary",
                on_click=_select_major_stock,
                args=(code,),
            )


def _render_major_stocks() -> None:
    indexes = _available_major_indexes()
    # 메뉴에 들어오면 첫 지수의 주봉을 바로 보여 준다.
    if "major_stock_code" not in st.session_state and indexes:
        st.session_state.major_stock_code = indexes[0][0]
    selected_code = st.session_state.get("major_stock_code")

    _render_index_summaries()
    if indexes:
        _render_major_buttons("지수", indexes, selected_code)
    _render_major_buttons("종목", MAJOR_STOCKS, selected_code)

    if not selected_code:
        st.caption("버튼을 누르면 주봉 차트가 표시됩니다.")
        return

    name = dict(MAJOR_STOCKS + indexes).get(selected_code)
    if name is None:
        st.warning("선택한 항목의 데이터가 없습니다.")
        return

    timeframe_label = st.radio("봉", ["주봉", "월봉"], horizontal=True, key="major_timeframe", label_visibility="collapsed")
    timeframe = "weekly" if timeframe_label == "주봉" else "monthly"
    try:
        # 진행 중인 봉은 이번 주 금요일이나 이번 달 말일 날짜이므로 기준일을 뒤로 잡아 최신 봉까지 포함한다.
        show_chart, anchor_date = _build_stock_chart(
            selected_code,
            name,
            timeframe,
            (pd.Timestamp(date.today()) + pd.Timedelta(days=40)).strftime("%Y-%m-%d"),
        )
    except Exception as e:
        st.error(f"{name} 차트를 불러오지 못했습니다: {e}")
        return

    st.caption(f"{name} ({selected_code}) | 기준봉 {anchor_date.strftime('%Y-%m-%d')} | {timeframe_label} {LOOKBACK_BARS}봉")
    show_chart()


def _passes_review_filter(item: dict, max_breakout_pct: Optional[float], max_volume_pct: Optional[float]) -> bool:
    # 돌파율이 없는 종목(차트만 있는 스캔)은 최대 필터를 쓸 때만 뺀다.
    pct = item.get("breakout_pct")
    has_pct = pct is not None and not pd.isna(pct)
    if has_pct and float(pct) < MIN_REVIEW_BREAKOUT_PCT:
        return False
    if max_breakout_pct is not None and (not has_pct or float(pct) > float(max_breakout_pct)):
        return False

    vol = item.get("volume_pct")
    if max_volume_pct is not None:
        if vol is None or pd.isna(vol) or float(vol) > float(max_volume_pct):
            return False
    return True


def _breakout_filter_text(max_breakout_pct: Optional[float]) -> str:
    if max_breakout_pct is None:
        return f">= {MIN_REVIEW_BREAKOUT_PCT:.1f}%"
    return f"{MIN_REVIEW_BREAKOUT_PCT:.1f}% ~ {max_breakout_pct:.1f}%"


def _select_review_case(case_key: str) -> None:
    st.session_state.review_selected_case = case_key


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
        # 강도가 큰 종목부터, 강도가 없는 종목은 맨 뒤
        items = sorted(
            items,
            key=lambda x: (
                x.get("breakout_strength") is None or pd.isna(x.get("breakout_strength")),
                0.0 if x.get("breakout_strength") is None or pd.isna(x.get("breakout_strength")) else -float(x.get("breakout_strength")),
                str(x.get("code", "")),
            ),
        )

    filtered_items = [item for item in items if _passes_review_filter(item, max_breakout_pct, max_volume_pct)]

    # Keep gallery navigation/indexing on image-available items only.
    gallery_items = [
        item
        for item in filtered_items
        if item.get("image_path") and os.path.isfile(item["image_path"])
    ]

    breakout_filter_text = _breakout_filter_text(max_breakout_pct)
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
    thumb_state_key = f"thumb_state_{case_key}"
    thumb_clicked_key = f"thumb_clicked_{case_key}"
    thumb_nonce_key = f"thumb_nonce_{case_key}"
    gallery_codes = "|".join(str(item.get("code", "")) for item in gallery_items)
    current_sig = (
        sort_by,
        max_breakout_pct,
        max_volume_pct,
        zlib.crc32(gallery_codes.encode("utf-8")),
    )

    if st.session_state.get(gallery_sig_key) != current_sig:
        st.session_state[idx_key] = 0
        st.session_state[gallery_sig_key] = current_sig
        st.session_state.pop(thumb_clicked_key, None)

    current_idx = min(
        max(int(st.session_state.get(idx_key, 0)), 0),
        len(gallery_items) - 1,
    )
    st.session_state[idx_key] = current_idx
    move_args = (len(gallery_items) - 1, thumb_clicked_key, thumb_nonce_key)

    nav1, nav2, nav3 = st.columns([1, 1, 4])
    with nav1:
        st.button(
            "이전",
            key=f"prev_{case_key}",
            disabled=current_idx == 0,
            on_click=_move_gallery,
            args=(idx_key, -1, *move_args),
        )
    with nav2:
        st.button(
            "다음",
            key=f"next_{case_key}",
            disabled=current_idx == len(gallery_items) - 1,
            on_click=_move_gallery,
            args=(idx_key, 1, *move_args),
        )

    selected = gallery_items[current_idx]
    code_text = str(selected.get("code", "")).strip()
    name_text = str(selected.get("name", "")).strip()
    pct_text = _format_pct(selected.get("breakout_pct"))
    vol_text = f"거래량 {_format_pct(selected.get('volume_pct'), digits=1)}"
    header_text = f"{code_text} | {name_text} | ▲ {pct_text} | {vol_text}"
    st.markdown(
        "<div class='gallery-head'><span>{}</span>{}</div>".format(
            html.escape(header_text),
            _bar_chips_html(selected.get("date"), selected.get("is_final")),
        ),
        unsafe_allow_html=True,
    )
    try:
        if not INTERACTIVE_CHART:
            raise ValueError("로컬 경량 버전은 저장된 차트 이미지를 사용합니다.")
        show_review_chart, _ = _build_stock_chart(
            code_text,
            name_text,
            _infer_timeframe_from_case_key(case_key),
            str(selected.get("date", "")).strip(),
            close_trail_bars=10,
        )
        show_review_chart()
    except (ValueError, KeyError, TypeError, FileNotFoundError):
        st.image(selected["image_path"], width="stretch")
    st.caption(
        f"{current_idx + 1}/{len(gallery_items)} | {selected.get('caption', '')} | "
        f"돌파율 {pct_text} | {vol_text}"
    )

    if not LITE_EDITION:
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
                key=f"review_interest_memo_{case_key}_{code_text}",
            )
            current_watch_path = storage.interest_watch_monthly_path()
            st.caption(f"관심 저장 파일: {os.path.basename(current_watch_path)}")

        can_save = bool(code_text)
        if not can_save:
            st.warning("종목코드가 없어 저장할 수 없습니다.")

        if st.button(
            "현재 확대 종목 관심저장",
            width="stretch",
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
                target_watch_path = storage.interest_watch_monthly_path()
                storage.append_row(target_watch_path, row)
                st.success(f"저장 완료: {target_watch_path}")
            except Exception as save_e:
                st.error(f"저장 실패: {save_e}")

    thumb_items = gallery_items
    if LITE_EDITION:
        thumb_images = [_dark_thumbnail(item["image_path"]) for item in thumb_items]
    else:
        thumb_images = [item["image_path"] for item in thumb_items]
    thumb_captions = []
    for item in thumb_items:
        thumb_code = str(item.get("code", "")).strip()
        thumb_name = str(item.get("name", "")).strip()
        thumb_pct = _format_pct(item.get("breakout_pct"))
        thumb_vol_text = f"거래량 {_format_pct(item.get('volume_pct'), digits=1)}"
        thumb_captions.append(f"{thumb_code} | {thumb_name} | ▲ {thumb_pct} | {thumb_vol_text}")

    if thumb_images:
        # 썸네일 부품은 이미지를 처음 한 번만 그리므로 목록이 바뀌면 새 위젯으로 만든다.
        thumb_widget_key = (
            f"img_pick_{case_key}_{current_sig[-1]}_{int(st.session_state.get(thumb_nonce_key, 0))}"
        )
        if IMAGE_SELECT_AVAILABLE:
            picked_thumb = image_select(
                label="",
                images=thumb_images,
                captions=thumb_captions,
                index=current_idx,
                return_value="index",
                use_container_width=False,
                key=thumb_widget_key,
            )
        else:
            st.info("썸네일 선택 기능을 사용하려면 streamlit-image-select 패키지를 설치하세요.")
            picked_thumb = st.selectbox(
                "종목 선택",
                options=list(range(len(thumb_items))),
                index=current_idx,
                format_func=lambda i: thumb_captions[i],
                key=thumb_widget_key,
            )

        # 위젯은 마지막 클릭값을 계속 돌려주므로 값이 바뀌었을 때만 새 클릭으로 처리한다.
        previous_thumb = st.session_state.get(thumb_state_key)
        st.session_state[thumb_state_key] = (thumb_widget_key, picked_thumb)
        is_new_pick = (
            previous_thumb is not None
            and previous_thumb[0] == thumb_widget_key
            and picked_thumb != previous_thumb[1]
        )
        if is_new_pick and picked_thumb is not None and picked_thumb != current_idx:
            st.session_state[idx_key] = int(picked_thumb)
            st.session_state[thumb_clicked_key] = True
            st.rerun()


START_MENU = "시작화면"
MAJOR_STOCKS_MENU = "주요 종목"
GUIDE_MENU = "사용 가이드"
GUIDE_HEIGHT = 900
MAJOR_STOCKS = [
    ("005930", "삼성전자"),
    ("000660", "SK하이닉스"),
    ("009150", "삼성전기"),
]

FULL_MENU_ITEMS = [
    START_MENU,
    "1. 데이터 저장",
    "2. 이평 돌파 종목 서칭",
    "3. 서칭 데이터 조회",
    "4. 관심종목 서칭",
    "5. 관심종목 조회",
    "6. 패턴 데이터 입력",
    "7. 패턴 데이터 조회",
    "8. 보유 종목 조회",
    MAJOR_STOCKS_MENU,
    GUIDE_MENU,
]

if CLOUD_EDITION:
    MENU_ITEMS = [START_MENU, "3. 서칭 데이터 조회", "4. 관심종목 서칭", MAJOR_STOCKS_MENU, GUIDE_MENU]
elif LITE_EDITION:
    MENU_ITEMS = FULL_MENU_ITEMS[:5] + [GUIDE_MENU]
else:
    MENU_ITEMS = FULL_MENU_ITEMS[:9] + [GUIDE_MENU]

# 서칭 데이터 조회에서 이 돌파율(%) 미만은 보여주지 않는다.
MIN_REVIEW_BREAKOUT_PCT = 0.5

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
        if 0 <= menu_index < len(FULL_MENU_ITEMS) and FULL_MENU_ITEMS[menu_index] in MENU_ITEMS:
            return FULL_MENU_ITEMS[menu_index]
    except Exception:
        pass

    if raw_text in MENU_ITEMS:
        return raw_text
    return START_MENU

def _format_scan_label(label: str) -> str:
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})\d{2}", str(label))
    return f"{m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]}" if m else str(label)


MENU_ICONS = {
    START_MENU: ":material/home:",
    "1. 데이터 저장": ":material/database:",
    "2. 이평 돌파 종목 서칭": ":material/manage_search:",
    "3. 서칭 데이터 조회": ":material/candlestick_chart:",
    "4. 관심종목 서칭": ":material/search:",
    "5. 관심종목 조회": ":material/star:",
    "6. 패턴 데이터 입력": ":material/edit_note:",
    "7. 패턴 데이터 조회": ":material/history:",
    "8. 보유 종목 조회": ":material/account_balance_wallet:",
    MAJOR_STOCKS_MENU: ":material/star:",
    GUIDE_MENU: ":material/menu_book:",
}

MENU_GROUPS = [
    (None, [START_MENU]),
    ("시세·스캔", ["1. 데이터 저장", "2. 이평 돌파 종목 서칭", "3. 서칭 데이터 조회"]),
    ("관심·패턴", ["4. 관심종목 서칭", "5. 관심종목 조회", "6. 패턴 데이터 입력", "7. 패턴 데이터 조회"]),
    ("보유", ["8. 보유 종목 조회"]),
    ("도움말", [GUIDE_MENU]),
]

LITE_MENU_GROUPS = [
    (None, [START_MENU]),
    ("시세·스캔", ["1. 데이터 저장", "2. 이평 돌파 종목 서칭", "3. 서칭 데이터 조회"]),
    ("종목", ["4. 관심종목 서칭"]),
    ("도움말", [GUIDE_MENU]),
]

CLOUD_MENU_GROUPS = [
    (None, [START_MENU]),
    ("조회", ["3. 서칭 데이터 조회", "4. 관심종목 서칭", MAJOR_STOCKS_MENU]),
    ("도움말", [GUIDE_MENU]),
]

# 경량 버전은 저장 기능이 없어 4번 메뉴를 차트 조회로 표시한다.
LITE_MENU_LABELS = {"4. 관심종목 서칭": "4. 종목 차트 조회"}
CLOUD_MENU_LABELS = {"3. 서칭 데이터 조회": "돌파 종목 조회", "4. 관심종목 서칭": "종목 차트 조회"}


def _menu_label(menu: str) -> str:
    if CLOUD_EDITION:
        return CLOUD_MENU_LABELS.get(menu, menu)
    return LITE_MENU_LABELS.get(menu, menu) if LITE_EDITION else menu


FEATURE_HELP = {
    "1. 데이터 저장": "KRX 일봉/주봉/월봉 데이터 적재와 갱신을 실행합니다.",
    "2. 이평 돌파 종목 서칭": "주/월봉 이평선 돌파 종목을 스캔합니다.",
    "3. 서칭 데이터 조회": "최근 스캔 결과와 케이스별 요약을 확인합니다.",
    "4. 관심종목 서칭": "개별 종목 차트를 탐색하고 관심 종목으로 저장합니다.",
    "5. 관심종목 조회": "저장된 관심 종목 데이터를 조회합니다.",
    "6. 패턴 데이터 입력": "개별 종목 조회 후 기록 데이터로 저장합니다.",
    "7. 패턴 데이터 조회": "저장된 패턴(기록) 데이터를 조회합니다.",
    "8. 보유 종목 조회": "보유 종목 데이터를 조회합니다.",
    MAJOR_STOCKS_MENU: "시장 지수의 당일 시세와 주요 종목, 지수의 주봉·월봉 차트를 조회합니다.",
    GUIDE_MENU: "메뉴별 사용법과 데이터의 뜻을 안내합니다. 위쪽 검색창으로 찾을 수 있습니다.",
}
if LITE_EDITION:
    FEATURE_HELP["4. 관심종목 서칭"] = "개별 종목의 주봉/월봉 차트를 조회합니다."

with open(os.path.join(os.path.dirname(storage.__file__), "theme.css"), encoding="utf-8") as _theme_file:
    st.markdown(f"<style>{_theme_file.read()}</style>", unsafe_allow_html=True)
if LITE_EDITION:
    with open(os.path.join(os.path.dirname(storage.__file__), "theme_lite.css"), encoding="utf-8") as _lite_file:
        st.markdown(f"<style>{_lite_file.read()}</style>", unsafe_allow_html=True)


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
if "data_store_target" not in st.session_state:
    st.session_state.data_store_target = ["KOSPI", "KOSDAQ", "ETF"]
if "scan_market_running" not in st.session_state:
    st.session_state.scan_market_running = False
if "scan_market_run_requested" not in st.session_state:
    st.session_state.scan_market_run_requested = False
if "scan_progress_value" not in st.session_state:
    st.session_state.scan_progress_value = 0.0
if "scan_progress_text" not in st.session_state:
    st.session_state.scan_progress_text = "스캔 대기 중"
if "data_store_progress_value" not in st.session_state:
    st.session_state.data_store_progress_value = 0.0
if "data_store_progress_text" not in st.session_state:
    st.session_state.data_store_progress_text = "데이터 업데이트 대기 중"

st.sidebar.markdown("### KRX FDR Lite" if LITE_EDITION else "### KRX FDR")
for group_title, group_menus in (
    CLOUD_MENU_GROUPS if CLOUD_EDITION else LITE_MENU_GROUPS if LITE_EDITION else MENU_GROUPS
):
    if group_title:
        st.sidebar.markdown(f"<div class='menu-group'>{group_title}</div>", unsafe_allow_html=True)
    for menu in group_menus:
        button_type = "primary" if st.session_state.selected_menu == menu else "secondary"
        if st.sidebar.button(
            _menu_label(menu), key=f"menu_btn_{menu}", width="stretch", type=button_type, icon=MENU_ICONS[menu]
        ):
            st.session_state.selected_menu = menu
            st.query_params["menu"] = str(FULL_MENU_ITEMS.index(menu))
            if menu == MAJOR_STOCKS_MENU:
                # 메뉴를 고를 때마다 첫 지수의 주봉부터 보여 준다.
                st.session_state.pop("major_stock_code", None)
                st.session_state.pop("major_timeframe", None)
            st.rerun()

selected_menu = st.session_state.selected_menu
if selected_menu in MENU_ITEMS:
    st.query_params["menu"] = str(FULL_MENU_ITEMS.index(selected_menu))
st.session_state.show_intro = selected_menu == START_MENU

def _cloud_setting(name: str) -> Optional[str]:
    if name in os.environ:
        return os.environ[name]
    try:
        return st.secrets.get(name)
    except Exception:
        return None


@st.cache_resource(ttl=3600, show_spinner="최신 데이터를 확인하는 중입니다...")
def _download_cloud_data() -> bool:
    return lite_data.ensure_data(
        _cloud_setting("KRX_DATA_REPO"),
        _cloud_setting("KRX_DATA_TOKEN"),
        DATA_DIR,
        OUTPUT_DIR,
        api=_cloud_setting("KRX_DATA_API") or lite_data.DEFAULT_API,
    )


def _sync_cloud_data() -> None:
    if not _cloud_setting("KRX_DATA_REPO"):
        st.error("KRX_DATA_REPO 설정이 없습니다. 앱 Secrets를 확인하세요.")
        st.stop()
    try:
        if _download_cloud_data():
            st.cache_data.clear()
    except Exception as e:
        st.error(f"데이터를 내려받지 못했습니다: {e}")
        st.stop()


def _render_open_source_notice() -> None:
    notice_path = os.path.join(os.path.dirname(os.path.dirname(storage.__file__)), "THIRD_PARTY_NOTICES.md")
    with st.expander("오픈소스 및 면책 고지"):
        with open(notice_path, encoding="utf-8") as notice_file:
            st.markdown(notice_file.read())


def _render_data_guide() -> None:
    st.caption("KOSPI, KOSDAQ, 한국 ETF의 시세를 이동평균 기준으로 살펴보는 조회 전용 화면입니다.")
    review_col, chart_col = st.columns(2)
    with review_col:
        with st.container(border=True):
            st.markdown(
                f"**{_menu_label('3. 서칭 데이터 조회')}**\n\n"
                "가장 최근 스캔에서 이동평균선을 상향 돌파한 종목입니다.\n\n"
                "- **기준:** 주봉 10, 240이평과 월봉 10, 120, 180, 240이평\n"
                "- **돌파 조건:** 직전 봉 종가가 이평 이하이고 현재 봉 종가가 이평 초과\n"
                "- **돌파율:** 현재 종가가 이평보다 높은 비율\n"
                "- **볼륨%:** 현재 봉 거래량 ÷ 최근 53봉의 최대 거래량\n"
                "- **제외:** ETN, 스팩, 거래량이 없는 봉, 직전 주·월보다 오래된 돌파"
            )
    with chart_col:
        with st.container(border=True):
            st.markdown(
                f"**{_menu_label('4. 관심종목 서칭')}**\n\n"
                "원하는 종목의 과거 차트를 날짜를 지정해 조회합니다.\n\n"
                "- **대상:** 종목 마스터에 있는 전체 종목\n"
                "- **봉:** 주봉 또는 월봉, 기준일까지 52봉\n"
                "- **이동평균:** 5, 10, 20, 120, 180, 240\n"
                "- **이평 계산:** 거래량이 없는 봉은 제외\n"
                "- **이동:** 이전 1봉, 다음 1봉"
            )
    if CLOUD_EDITION:
        index_names = [name for _, name in _available_major_indexes()]
        major_targets = ", ".join(name for _, name in MAJOR_STOCKS)
        if index_names:
            major_targets = f"{', '.join(index_names)} 지수의 당일 시세와 {major_targets}, 지수"
        st.caption(f"**{MAJOR_STOCKS_MENU}:** {major_targets}의 주봉·월봉 차트를 바로 볼 수 있습니다.")
    st.caption(
        "**데이터의 성격:** 실시간 시세가 아니며, 하루 한 번 수집해 스캔한 결과입니다. 기준 시각은 아래 데이터 현황에서 확인하세요. "
        "진행 중인 주·월의 봉은 이후 값이 달라져 돌파 여부도 바뀔 수 있습니다. "
        "분할·병합 등이 있으면 과거 시세가 재조정되지 않았을 수 있습니다. "
        "참고용 자료이며 투자 권유가 아닙니다."
    )


def _render_workflow_steps(steps: list[dict]) -> None:
    done_count = sum(step["state"] == workflow.DONE for step in steps)
    cards = ""
    for number, step in enumerate(steps, start=1):
        mark = "✓" if step["state"] == workflow.DONE else number
        cards += (
            f"<a class='flow-step flow-{step['state']}' href='?menu={step['menu']}' target='_self'>"
            f"<span class='flow-mark'>{mark}</span>"
            f"<span><span class='flow-title'>{html.escape(step['title'])}</span>"
            f"<span class='flow-detail'>{html.escape(step['detail'])}</span></span></a>"
        )
    st.markdown(
        "<div class='flow-panel'>"
        f"<div class='flow-head'><span>오늘의 작업</span><b>{done_count} / {len(steps)}</b></div>"
        f"<div class='flow-steps'>{cards}</div></div>",
        unsafe_allow_html=True,
    )


if CLOUD_EDITION:
    _sync_cloud_data()

data_status = get_data_status(DATA_DIR)
scan_status = get_scan_status(OUTPUT_DIR)

if st.session_state.show_intro:
    st.title("KRX FDR Lite" if LITE_EDITION else "KRX FDR")
    if not CLOUD_EDITION:
        _render_workflow_steps(workflow.build_steps(data_status, scan_status, date.today()))
    if LITE_EDITION:
        _render_data_guide()
    st.markdown("#### 데이터 현황")
    intro_cards = [
        ("KOSPI 종목 수", f"{data_status['kospi_count']:,}"),
        ("KOSDAQ 종목 수", f"{data_status['kosdaq_count']:,}"),
        ("최신 데이터 일자", data_status["latest_trade_date"] or "-"),
        ("최신 수집 날짜", data_status["latest_collection_date"] or "-"),
    ]
    for card_col, (card_title, card_value) in zip(st.columns(4), intro_cards):
        with card_col:
            st.markdown(
                f"<div class='status-card data-card'><div class='status-title'>{card_title}</div>"
                f"<div class='status-value'>{card_value}</div></div>",
                unsafe_allow_html=True,
            )
else:
    head_left, head_right = st.columns([1, 1.4])
    with head_left:
        st.subheader(_menu_label(selected_menu))
    with head_right:
        st.markdown(
            "<div class='status-strip'>"
            f"<span class='chip'>데이터 <b>{data_status['latest_collection_date'] or '미확인'}</b></span>"
            f"<span class='chip'>파일 <b>{data_status['daily_file_count']:,}개</b></span>"
            f"<span class='chip'>스캔 <b>{_format_scan_label(scan_status['latest_scan_label'])}</b></span>"
            f"<span class='chip'>돌파 <b>{scan_status['total_breakouts']:,}건</b></span>"
            "</div>",
            unsafe_allow_html=True,
        )
    st.caption(FEATURE_HELP[selected_menu])
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
    if selected_menu in ("1. 데이터 저장", "2. 이평 돌파 종목 서칭"):
        market_date_message = workflow.mismatched_market_message(data_status)
        if market_date_message:
            st.warning(market_date_message)
    if selected_menu == "2. 이평 돌파 종목 서칭":
        latest_scan = scan_status.get("latest_scan_label", "")
        today_prefix = date.today().strftime("%Y%m%d")
        if isinstance(latest_scan, str) and latest_scan.startswith(today_prefix):
            st.success("스캔이 완료되었습니다.")
        elif latest_scan and latest_scan != "미실행":
            st.warning("오늘자 스캔 결과가 없습니다. 지금 스캔 실행이 필요합니다.")
        else:
            st.warning("스캔 결과가 없습니다. 지금 스캔 실행이 필요합니다.")

if st.session_state.show_intro:
    if LITE_EDITION:
        case_col = st.container()
    else:
        list_col, case_col = st.columns([1.2, 1], gap="large")
        with list_col:
            st.markdown("#### 다른 기능")
            with st.container(border=True):
                for menu in ["4. 관심종목 서칭", "5. 관심종목 조회", "6. 패턴 데이터 입력", "7. 패턴 데이터 조회", "8. 보유 종목 조회"]:
                    st.markdown(f"{MENU_ICONS[menu]} **{menu}**  \n:gray[{FEATURE_HELP[menu]}]")
    with case_col:
        if scan_status["case_counts"]:
            st.markdown("#### 케이스별 돌파 건수")
            case_df = pd.DataFrame(scan_status["case_counts"])
            st.dataframe(case_df, width="stretch", hide_index=True)
    if LITE_EDITION:
        _render_open_source_notice()

if not st.session_state.show_intro:
    if selected_menu == "1. 데이터 저장":
        st.caption("`data_store.py` 실행 로그를 아래에서 확인합니다.")
        run_status_box = st.empty()
        data_progress_box = st.empty()

        if st.session_state.data_store_run_requested and not st.session_state.data_store_running:
            st.session_state.data_store_run_requested = False
            st.session_state.data_store_running = True
            st.rerun()

        market_labels = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ", "ETF": "ETF"}
        today_text = date.today().strftime("%Y-%m-%d")

        st.markdown("##### 시장별 현황")
        status_cols = st.columns(3, gap="medium")
        for scol, mkey in zip(status_cols, market_labels):
            mstat = data_status["markets"][mkey]
            with scol:
                st.markdown(
                    f"<div class='status-card data-card'><div class='status-title'>{mkey}</div>"
                    f"<div class='status-value'>{mstat['file_count']:,} / {mstat['count']:,}종목</div>"
                    f"<div class='status-title'>저장 일자: {mstat['latest_trade_date'] or '-'}</div>"
                    f"<div class='status-title'>수집: {mstat['latest_collection_date'] or '-'} {mstat['latest_collection_time'] or ''}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        def _is_fresh(mkey: str) -> bool:
            mstat = data_status["markets"][mkey]
            return (
                mstat["latest_collection_date"] == today_text
                and isinstance(mstat["latest_collection_time"], str)
                and mstat["latest_collection_time"] >= "17:00"
            )

        running = st.session_state.data_store_running
        clicked_target = None
        all_label = "전체 업데이트"
        if st.session_state.awaiting_update_confirm == "ALL":
            all_label = "확인: 전체 최신, 다시 눌러 업데이트"
        if running and len(st.session_state.data_store_target) == len(market_labels):
            all_label = "전체 업데이트 실행중..."
        if st.button(all_label, type="primary", width="stretch", key="run_data_store_ALL", disabled=running):
            clicked_target = "ALL"

        single_market_active = st.session_state.awaiting_update_confirm in market_labels or (
            running and len(st.session_state.data_store_target) == 1
        )
        with st.expander("시장별 업데이트", expanded=single_market_active):
            btn_cols = st.columns(3)
            for bcol, (mkey, mlabel) in zip(btn_cols, market_labels.items()):
                label = f"{mlabel} 업데이트"
                if st.session_state.awaiting_update_confirm == mkey:
                    label = f"확인: {mlabel} 최신, 다시 눌러 업데이트"
                if running and st.session_state.data_store_target == [mkey]:
                    label = f"{mlabel} 업데이트 실행중..."
                with bcol:
                    if st.button(label, width="stretch", key=f"run_data_store_{mkey}", disabled=running):
                        clicked_target = mkey

        clear_clicked = False
        if st.session_state.data_store_logs:
            clear_clicked = st.button("로그 지우기", disabled=running)

        if clear_clicked:
            st.session_state.data_store_logs = []
            st.session_state.data_store_last_returncode = None
            st.session_state.awaiting_update_confirm = False
            st.session_state.data_store_progress_value = 0.0
            st.session_state.data_store_progress_text = "데이터 업데이트 대기 중"

        data_progress_box.progress(
            float(st.session_state.data_store_progress_value),
            text=st.session_state.data_store_progress_text,
        )

        if clicked_target:
            targets = list(market_labels) if clicked_target == "ALL" else [clicked_target]
            already_fresh = all(_is_fresh(m) for m in targets)
            if already_fresh and st.session_state.awaiting_update_confirm != clicked_target:
                st.session_state.awaiting_update_confirm = clicked_target
            else:
                st.session_state.awaiting_update_confirm = False
                st.session_state.data_store_target = targets
                st.session_state.data_store_run_requested = True
                st.rerun()

        if st.session_state.awaiting_update_confirm:
            st.warning("데이터가 최신 입니다. 그래도 업데이트 하시겠습니까? 실행 버튼을 한 번 더 누르세요.")

        if st.session_state.data_store_running:
            run_status_box.info(f"data_store.py 실행중입니다. ({', '.join(st.session_state.data_store_target)})")
            st.session_state.data_store_progress_value = 0.0
            st.session_state.data_store_progress_text = "전체 0.00% (RAW 0.00% + DERIVED 0.00%) | 시작"
            data_progress_box.progress(0.0, text=st.session_state.data_store_progress_text)
            logs, return_code = run_data_store_and_collect_logs(
                data_progress_box, st.session_state.data_store_target
            )
            get_data_status.clear()
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
            start_scan_job()
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
                width="stretch",
                key="run_scan_market_button",
                disabled=st.session_state.scan_market_running,
            )
        with col_clear:
            clear_clicked = st.button(
                "로그 지우기",
                width="stretch",
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

        # 다른 세션/새로고침 후에도 실행 중인 백그라운드 스캔에 다시 연결한다.
        if is_scan_job_running():
            st.session_state.scan_market_running = True

        if st.session_state.scan_market_running:
            run_status_box.info("scan_market.py 백그라운드 실행중입니다. 다른 메뉴로 이동해도 계속 진행됩니다.")
            scan_progress_box.empty()
            st.fragment(run_every=SCAN_REFRESH_SEC)(render_scan_job_status)()
        elif st.session_state.scan_market_last_returncode == 0:
            run_status_box.success("스캔이 완료되었습니다.")
        if st.session_state.scan_market_logs and not st.session_state.scan_market_running:
            if st.session_state.scan_market_last_returncode == 0:
                latest_dir = st.session_state.scan_market_latest_dir or scan_status.get("latest_scan_dir")
                if latest_dir:
                    st.caption(f"최신 스캔 결과 폴더: {latest_dir}")
            elif st.session_state.scan_market_last_returncode is not None:
                run_status_box.error(f"스캔 실행 중 오류가 발생했습니다. 종료 코드: {st.session_state.scan_market_last_returncode}")

            render_log_box(st.session_state.scan_market_logs)
    elif selected_menu == "3. 서칭 데이터 조회":
        review_data = load_scan_review_data(scan_status["latest_scan_dir"])
        cases = review_data.get("cases", {})

        if review_data.get("load_error"):
            st.error(review_data["load_error"])

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
                    options=["필터 없음", "최대 1.0%", "최대 2.0%", "최대 3.0%", "최대 5.0%", "최대 10.0%"],
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

            filter_desc_breakout = _breakout_filter_text(max_breakout_pct)
            filter_desc_volume = "필터 없음" if max_volume_pct is None else f"<= {max_volume_pct:.1f}%"

            overview_rows = []
            filtered_counts = {}
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
                filtered = [x for x in items if _passes_review_filter(x, max_breakout_pct, max_volume_pct)]

                total_all += len(items)
                total_filtered += len(filtered)
                filtered_counts[case_key] = len(filtered)
                overview_rows.append(
                    {
                        "구분": REVIEW_CASE_LABELS.get(case_key, payload.get("label", case_key)),
                        "전체 돌파 종목수": len(items),
                        "필터 적용 종목수": len(filtered),
                    }
                )

            with st.expander(f"케이스별 요약 (전체 {total_all:,}건, 필터 적용 {total_filtered:,}건)"):
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
                        label = f"{REVIEW_CASE_LABELS.get(key, key)} ({filtered_counts.get(key, 0):,})"
                        btn_type = "primary" if st.session_state.review_selected_case == key else "secondary"
                        st.button(
                            label,
                            key=f"case_sel_{key}",
                            width="stretch",
                            type=btn_type,
                            on_click=_select_review_case,
                            args=(key,),
                        )

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
    elif selected_menu == MAJOR_STOCKS_MENU:
        _render_major_stocks()
    elif selected_menu == GUIDE_MENU:
        edition = "cloud" if CLOUD_EDITION else "lite" if LITE_EDITION else "full"
        components.html(user_guide.render_html(edition), height=GUIDE_HEIGHT, scrolling=True)
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
        st.line_chart(chart_df, width="stretch", height=470)
