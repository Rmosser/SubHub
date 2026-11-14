from __future__ import annotations

from starlette.requests import Request

from app.i18n import DEFAULT_LOCALE, resolve_locale


def _request(*, accept_language: str = "", cookie: str = "") -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if accept_language:
        headers.append((b"accept-language", accept_language.encode("utf-8")))
    if cookie:
        headers.append((b"cookie", cookie.encode("utf-8")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
    }
    return Request(scope)


def test_resolve_locale_prefers_cookie_over_accept_language() -> None:
    request = _request(accept_language="en-US,en;q=0.9", cookie="subhub_lang=zh-CN")
    assert resolve_locale(request) == "zh-CN"


def test_resolve_locale_falls_back_to_accept_language() -> None:
    request = _request(accept_language="en-US,en;q=0.9")
    assert resolve_locale(request) == "en-US"


def test_resolve_locale_defaults_to_zh_cn() -> None:
    assert resolve_locale(None) == DEFAULT_LOCALE
