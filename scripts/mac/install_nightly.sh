#!/bin/bash
# 평일 저녁 자동 스캔을 launchd에 등록/해제한다.
#   scripts/mac/install_nightly.sh            # 월~금 20:30 등록
#   scripts/mac/install_nightly.sh 21 0       # 월~금 21:00 등록
#   scripts/mac/install_nightly.sh --remove   # 해제
#   launchctl kickstart gui/$(id -u)/com.krxfdr.nightly-scan   # 지금 한 번 실행

set -eu
LABEL="com.krxfdr.nightly-scan"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DOMAIN="gui/$(id -u)"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true

if [ "${1:-}" = "--remove" ]; then
    rm -f "$PLIST"
    echo "해제했습니다: $LABEL"
    exit 0
fi

HOUR="${1:-20}"
MINUTE="${2:-30}"
INTERVALS=""
for day in 1 2 3 4 5; do
    INTERVALS="$INTERVALS
        <dict><key>Weekday</key><integer>$day</integer><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>"
done

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/Logs/nightly"
cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$PROJECT_DIR/scripts/mac/nightly_scan.sh</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>StartCalendarInterval</key>
    <array>$INTERVALS
    </array>
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/Logs/nightly/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/Logs/nightly/launchd.log</string>
</dict>
</plist>
EOF

plutil -lint "$PLIST" >/dev/null
launchctl bootstrap "$DOMAIN" "$PLIST"
printf '등록했습니다: %s (월~금 %02d:%02d)\n' "$LABEL" "$HOUR" "$MINUTE"
