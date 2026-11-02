from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image

THUMBNAIL_WIDTH = 240
THUMBNAIL_JPEG_QUALITY = 75


def dark_thumbnail_data_uri(image_path: str, width: int = THUMBNAIL_WIDTH) -> str:
    """흰 배경 차트를 색상은 유지한 채 어둡게 뒤집은 축소 이미지로 만든다."""
    with Image.open(image_path) as source:
        image = source.convert("RGB")
    height = max(1, round(image.height * width / image.width))
    image = image.resize((width, height), Image.LANCZOS)

    pixels = np.asarray(image, dtype=np.int16)
    inverted = 255 - pixels
    # 밝기만 뒤집기 위해 색상을 180도 되돌린다 (max + min - channel).
    hue_kept = inverted.max(axis=2, keepdims=True) + inverted.min(axis=2, keepdims=True) - inverted
    dimmed = (hue_kept * 0.92).astype(np.uint8)

    buffer = io.BytesIO()
    Image.fromarray(dimmed).save(buffer, format="JPEG", quality=THUMBNAIL_JPEG_QUALITY)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
