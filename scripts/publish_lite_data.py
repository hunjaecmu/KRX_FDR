# scripts/publish_lite_data.py

import argparse
import os
import sys

# Ensure project root is importable when this script is executed directly.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import APP_DATA_DIR, DATA_DIR, OUTPUT_DIR
from webapp import data_status, lite_data


def main() -> None:
    parser = argparse.ArgumentParser(description="서버용 경량 버전 데이터 묶음을 만들어 GitHub Release에 올립니다.")
    parser.add_argument("--build-only", action="store_true", help="묶음만 만들고 업로드하지 않습니다.")
    args = parser.parse_args()

    bundle_path = os.path.join(str(APP_DATA_DIR), "lite_bundle", lite_data.BUNDLE_NAME)

    repo = os.getenv("KRX_DATA_REPO")
    token = os.getenv("KRX_DATA_TOKEN")
    if not args.build_only and not (repo and token):
        raise SystemExit("KRX_DATA_REPO와 KRX_DATA_TOKEN 환경변수를 설정하거나 --build-only를 사용하세요.")

    print("데이터 묶음 생성 시작")
    manifest = lite_data.build_bundle(DATA_DIR, OUTPUT_DIR, data_status.compute_data_status(DATA_DIR), bundle_path)
    size_mb = os.path.getsize(bundle_path) / 1e6
    print(f"묶음 완료: {bundle_path} ({size_mb:.1f}MB, 스캔 {manifest['scan']}, {manifest['price_rows']:,}행)")

    if args.build_only:
        return

    print(f"{repo} 업로드 시작")
    url = lite_data.upload_bundle(bundle_path, repo, token)
    print(f"업로드 완료: {url}")


if __name__ == "__main__":
    main()
