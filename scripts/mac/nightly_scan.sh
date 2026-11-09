#!/bin/bash
# 평일 저녁 자동 스캔 (macOS, launchd에서 실행)
#   1) 데이터 업데이트  scripts/update_data.py
#   2) 이평 돌파 스캔   scripts/scan_market.py
#   3) GitHub 묶음 업로드 scripts/publish_lite_data.py
#   4) iCloud 공유       scripts/share_full_data.py export (일일 시세 파일, 주 1회 전체 묶음)
#   5) 텔레그램 알림 (OpenClaw)
# 설정: 프로젝트 폴더의 nightly.env (git 제외). 예시는 scripts/mac/nightly.env.example
# 일정 등록/해제: scripts/mac/install_nightly.sh

set -u
PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_DIR" || exit 1

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

[ -f nightly.env ] && set -a && . ./nightly.env && set +a
KRX_DATA_REPO="${KRX_DATA_REPO:-hunjaecmu/KRX_FDR_data}"
NOTIFY_CHANNEL="${KRX_NOTIFY_CHANNEL:-telegram}"
NOTIFY_TARGET="${KRX_NOTIFY_TARGET:-}"

if [ -x .venv/bin/python ]; then PY="$PROJECT_DIR/.venv/bin/python"; else PY="$(command -v python3)"; fi

LOG_DIR="$PROJECT_DIR/Logs/nightly"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/$(date +%Y%m%d_%H%M%S).log"
exec >>"$LOG" 2>&1
find "$LOG_DIR" -name "*.log" -mtime +60 -delete 2>/dev/null

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

notify() {
    local text="$1"
    log "알림 전송"
    echo "$text"
    if [ -z "$NOTIFY_TARGET" ]; then
        log "KRX_NOTIFY_TARGET이 없어 알림을 건너뜁니다."
        return
    fi
    # iCloud 업로드가 시작되면 회선이 잠시 붐벼 전송이 실패할 수 있어 몇 번 다시 시도한다.
    local attempt
    for attempt in 1 2 3; do
        if openclaw message send --channel "$NOTIFY_CHANNEL" --target "$NOTIFY_TARGET" -m "$text"; then
            return
        fi
        log "알림 전송 실패 ($attempt/3)"
        [ "$attempt" -lt 3 ] && sleep 30
    done
}

# 겹쳐 실행되지 않도록 잠금
LOCK="$PROJECT_DIR/Logs/nightly.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
    if kill -0 "$(cat "$LOCK/pid" 2>/dev/null)" 2>/dev/null; then
        log "이전 자동 스캔이 아직 실행 중이라 종료합니다."
        notify "⚠️ KRX 스캔 건너뜀: 이전 자동 스캔이 아직 실행 중입니다."
        exit 0
    fi
    rm -rf "$LOCK" && mkdir "$LOCK"
fi
echo $$ >"$LOCK/pid"
trap 'rm -rf "$LOCK"' EXIT

# 직접 실행한 업데이트·스캔과 같은 파일을 동시에 쓰지 않도록 확인
if pgrep -f "scripts/(update_data|scan_market)\.py|KRX_FDR/data_store\.py" >/dev/null; then
    log "직접 실행한 업데이트/스캔이 진행 중이라 종료합니다."
    notify "⚠️ KRX 스캔 건너뜀: 직접 실행한 업데이트/스캔이 진행 중입니다."
    exit 0
fi

STARTED=$(date +%s)
UPDATE=skip SCAN=skip PUBLISH=skip SHARE=skip
log "자동 스캔 시작 (python: $PY)"

# 업데이트와 스캔은 자체 업로드를 끄고 실행한 뒤, 업로드는 마지막에 한 번만 한다.
run_step() {
    log "▶ $1"
    env -u KRX_DATA_REPO -u KRX_DATA_TOKEN caffeinate -i "$PY" -u "${@:2}"
}

if run_step "데이터 업데이트" scripts/update_data.py; then UPDATE=ok; else UPDATE=fail; fi

if [ "$UPDATE" = ok ]; then
    if run_step "이평 돌파 스캔" scripts/scan_market.py; then SCAN=ok; else SCAN=fail; fi
fi

if [ "$SCAN" = ok ]; then
    log "▶ GitHub 묶음 업로드"
    TOKEN="$(gh auth token 2>/dev/null)"
    if [ -n "$TOKEN" ] && KRX_DATA_REPO="$KRX_DATA_REPO" KRX_DATA_TOKEN="$TOKEN" \
        caffeinate -i "$PY" -u scripts/publish_lite_data.py; then
        PUBLISH=ok
    else
        [ -z "$TOKEN" ] && log "GitHub 로그인 토큰이 없습니다 (gh auth login 필요)."
        PUBLISH=fail
    fi
    unset TOKEN

    log "▶ iCloud 공유"
    if caffeinate -i "$PY" -u scripts/share_full_data.py export; then SHARE=ok; else SHARE=fail; fi
fi

MESSAGE="$("$PY" scripts/nightly_summary.py --started "$STARTED" \
    --update "$UPDATE" --scan "$SCAN" --publish "$PUBLISH" --share "$SHARE" --log "$LOG")" \
    || MESSAGE="⚠️ KRX 스캔: 알림 문구 생성 실패 (update=$UPDATE scan=$SCAN publish=$PUBLISH share=$SHARE)"
notify "$MESSAGE"
log "자동 스캔 종료"
