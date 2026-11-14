from __future__ import annotations

import re

_DEVICE_TRAILER = re.compile(r"\s*[\(（]\s*#?\d+\s*[\)）]\s*$")
_ENTRY_MARKER = re.compile(r"(?:-|/)?\s*(?:「|\[|【)\s*lv\s*\d+", re.I)
_RATE_TRAILER = re.compile(r"\s*倍率\s*[:：]?\s*\d+(?:\.\d+)?\s*$", re.I)
_NON_WORD = re.compile(r"[^0-9a-zA-Z\u4e00-\u9fff]+")


def normalize_device_name(line_name: str) -> str:
    text = str(line_name or "").strip()
    if not text:
        return "Unknown"
    text = _DEVICE_TRAILER.sub("", text).strip()
    text = _RATE_TRAILER.sub("", text).strip()
    if not text:
        return "Unknown"
    marker = _ENTRY_MARKER.search(text)
    if marker and marker.start() > 0:
        prefix = text[: marker.start()].strip().strip("-").strip()
        if prefix:
            return prefix
    # Keep a compact prefix-style name; if there are spaces, first segment is usually stable.
    first = text.split()[0].strip()
    return first or "Unknown"


def build_device_key(device_name: str) -> str:
    cleaned = _NON_WORD.sub("-", device_name.lower()).strip("-")
    return cleaned or "unknown"


def extract_device_group(line_name: str) -> tuple[str, str]:
    name = normalize_device_name(line_name)
    return name, build_device_key(name)
