from __future__ import annotations

from io import BytesIO


def decode_qr_url(content: bytes) -> str:
    if not content:
        return ""

    try:
        from PIL import Image, UnidentifiedImageError
    except Exception:
        return ""

    try:
        image = Image.open(BytesIO(content))
        image.load()
    except (OSError, UnidentifiedImageError):
        return ""

    return _decode_with_zxingcpp(image)


def _decode_with_zxingcpp(image) -> str:
    try:
        import zxingcpp
    except Exception:
        return ""

    try:
        result = zxingcpp.read_barcode(image)
    except Exception:
        return ""
    if not result or not getattr(result, "text", ""):
        return ""
    return str(result.text).strip()
