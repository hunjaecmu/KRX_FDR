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
from streamlit_image_select import image_select

from config import DATA_DIR, OUTPUT_DIR


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

    if idx_key not in st.session_state or st.session_state[idx_key] >= len(gallery_items):
        st.session_state[idx_key] = 0

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
                picked_idx = picked_thumb_index
            else:
                picked_idx = current_thumb_index

            if 0 <= picked_idx < len(gallery_items) and picked_idx != st.session_state[idx_key]:
                st.session_state[idx_key] = picked_idx
                st.rerun()


START_MENU = "시작화면"

MENU_ITEMS = [
    START_MENU,
    "1. 데이터 저장",
    "2. 이평 돌파 종목 서칭",
    "3. 서칭 데이터 조회",
    "4. 종목별 조회",
    "5. 패턴 데이터 입력",
    "6. 패턴 데이터 조회",
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
    "4. 종목별 조회": "개별 종목의 이력과 차트 흐름을 조회합니다.",
    "5. 패턴 데이터 입력": "향후 구현 예정 기능입니다.",
    "6. 패턴 데이터 조회": "향후 구현 예정 기능입니다.",
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
    "<div class='caption'>5번, 6번 메뉴는 현재 UI만 준비되어 있고 기능 구현은 예정입니다.</div>",
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
4. 종목별 조회로 개별 종목을 상세 확인합니다.
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
        if selected_menu in {"5. 패턴 데이터 입력", "6. 패턴 데이터 조회"}:
            st.info("해당 메뉴는 추후 백엔드 로직과 연결될 예정입니다.")
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
    else:
        st.caption("하단의 넓은 영역은 실제 종목/스캔 결과 차트가 표시될 자리입니다.")
        chart_df = build_mock_chart_data()
        st.line_chart(chart_df, use_container_width=True, height=470)
    st.markdown("</div>", unsafe_allow_html=True)
