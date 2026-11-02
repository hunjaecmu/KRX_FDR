"""앱 안에서 보여 주는 사용 가이드를 버전에 맞게 준비한다."""

from __future__ import annotations

import os

GUIDE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_guide.html")
EDITIONS = ("full", "lite", "cloud")


def render_html(edition: str) -> str:
    if edition not in EDITIONS:
        raise ValueError(f"알 수 없는 버전: {edition}")
    with open(GUIDE_PATH, encoding="utf-8") as f:
        return f.read().replace("__EDITION__", edition)
