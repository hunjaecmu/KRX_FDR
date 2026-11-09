# 저녁 자동 스캔 (macOS)

Mac이 평일 저녁마다 데이터 업데이트와 스캔을 하고, 결과를 GitHub와 iCloud Drive에 올린 뒤 텔레그램으로 알립니다. Windows PC는 스캔하지 않고 `pull.cmd`로 Mac의 데이터를 받아 씁니다.

```text
[Mac] 월~금 20:30 launchd → scripts/mac/nightly_scan.sh
  1. scripts/update_data.py          데이터 업데이트
  2. scripts/scan_market.py          이평 돌파 스캔
  3. scripts/publish_lite_data.py    GitHub(KRX_FDR_data) 서버용 묶음
  4. scripts/share_full_data.py export   iCloud Drive/KRX_FDR/krx_full_data.zip
  5. OpenClaw → 텔레그램 알림 (scripts/nightly_summary.py가 문구 작성)

[Windows] pull.cmd → scripts/share_full_data.py import
```

앞 단계가 실패하면 뒤 단계는 건너뛰고, 실패한 단계와 로그 위치를 알림으로 보냅니다.

## 처음 설정

1. 설정 파일: `scripts/mac/nightly.env.example`을 프로젝트 폴더의 `nightly.env`로 복사하고 `KRX_NOTIFY_TARGET`(텔레그램 chat id)을 채웁니다. `nightly.env`는 git에 올라가지 않습니다.
2. GitHub 로그인: `gh auth login`. 업로드 토큰은 이 로그인에서 가져옵니다.
3. OpenClaw 게이트웨이가 실행 중이어야 알림이 갑니다.
4. 일정 등록:

```bash
scripts/mac/install_nightly.sh            # 월~금 20:30
scripts/mac/install_nightly.sh 21 0       # 시간 변경 (월~금 21:00)
scripts/mac/install_nightly.sh --remove   # 해제
```

지금 한 번 실행해 보려면:

```bash
launchctl kickstart gui/$(id -u)/com.krxfdr.nightly-scan
```

## 동작 참고

- 로그: `Logs/nightly/YYYYMMDD_HHMMSS.log` (60일 지나면 삭제)
- 이전 자동 스캔이나 직접 실행한 `update_data.py`/`scan_market.py`가 돌고 있으면 건너뛰고 알립니다.
- 실행 중에는 `caffeinate`로 잠자기를 막습니다. 예정 시각에 Mac이 잠들어 있었다면 깨어난 뒤 실행됩니다.
- 업데이트·스캔 단계에서는 자체 업로드를 끄고, 업로드는 마지막에 한 번만 합니다.

# 전체 데이터 공유 (scripts/share_full_data.py)

| 명령 | 실행 위치 | 동작 |
|---|---|---|
| `python scripts/share_full_data.py export` | 스캔한 PC | 전체 데이터를 `krx_full_data.zip`(약 500MB)으로 묶어 공유 폴더에 저장 |
| `pull.cmd` (Windows), `./pull.command` (Mac) | 다른 PC | 묶음을 받아 데이터 폴더에 설치 |

- 묶음 내용: `master`, `raw/daily`, `derived/{daily,weekly,monthly}`, `index`, 최신 스캔 결과 1개
- 설치할 때 위 폴더는 묶음 내용으로 통째로 교체되고, 스캔 결과는 없을 때만 추가됩니다.
- `tracking`(보유·관심·패턴 기록)과 `logs`는 묶지도 덮어쓰지도 않습니다.
- 이미 설치한 묶음이면 건너뜁니다. 다시 설치하려면 `--force`.
- 공유 폴더 기본값: Mac `~/Library/Mobile Documents/com~apple~CloudDocs/KRX_FDR`, Windows `%USERPROFILE%\iCloudDrive\KRX_FDR` (iCloud for Windows). 다른 곳을 쓰려면 `--dir` 또는 환경변수 `KRX_SHARE_DIR`.
- 묶음은 로컬에서 다 만든 뒤 옮기므로, 쓰다 만 파일이 동기화되지 않습니다.
