from __future__ import annotations

import asyncio
import base64
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from time import perf_counter
from urllib.parse import quote, unquote

import httpx
import pytest

from app.config import Settings
from app.models import (
    STANDARD_SOURCE_PULL_NETWORK_DIRECT_ONLY,
    STANDARD_SOURCE_PULL_NETWORK_DIRECT_THEN_PROXY,
    STANDARD_SOURCE_PULL_NETWORK_PROXY_THEN_DIRECT,
    NodeRecord,
    QUALITY_MEDIUM,
    StandardSource,
)
from app.services.source_diagnostics import (
    extract_source_secrets, known_source_secrets,
    public_runtime, public_source_status, redact_source_url, sanitize_source_error,
    source_error_detail, source_error_signal, summarize_pull_errors, unsupported_protocol_reason,
)
from app.services.source_fetcher import FetchPayload, SourceFetcher, SourcePullAttempt, SourcePullResult


def test_known_secrets_extraction_and_reserved_words() -> None:
    url = ("https://user:pass@a1B2c3D4e5.example/api/client_subscribe_v2/abc123def456.yaml"
           "/%2561%2562%2563%2531%2532%2533%2564%2565%2566%2534%2535%2536"
           "?token=ordinary-secret&api_key=secret2&password=clash&other=another123&small=sub#frag")
    values = extract_source_secrets(url, "https://sub:clash@h/sub?token=short&x=clash", "")
    # Host labels also appear lowercased; the double-encoded segment decodes
    # once to an encoded form, which is no token on its own.
    assert values == frozenset({"user", "pass", "a1B2c3D4e5", "a1b2c3d4e5", "abc123def456.yaml", "abc123def456",
                                "ordinary-secret", "secret2", "another123", "frag"})
    matcher = known_source_secrets([StandardSource(id="s", name="Source", clash_url=url)])
    assert sanitize_source_error("sub clash api client_subscribe_v2 short", matcher) == "sub clash api client_subscribe_v2 short"
    assert extract_source_secrets("https://h/api/v1/client/subscribe/link/clash.yaml") == frozenset()
    # Every existing sensitive-query key spelling uses the same table.
    for key in ["access_token", "access-token", "accesstoken", "api_key", "api-key", "apikey",
                "authorization", "cookie", "password", "secret", "token", "webhook_secret", "webhook-secret"]:
        assert extract_source_secrets(f"https://h/sub?{key}=special") == frozenset({"special"})
    assert extract_source_secrets("https://h/sub?nottoken=special") == frozenset()


@pytest.mark.parametrize("punctuation", [",", ";", "'", '"'])
def test_known_secrets_hide_nested_urls_independently_of_boundaries(punctuation) -> None:
    token = "aBc123dEf456"
    source = StandardSource(id="s", name="Source", clash_url=f"https://outer/api/https://inner{punctuation}//{token}")
    matcher = known_source_secrets([source])
    encoded = token  # the configured spelling, as the pull code prints it
    shapes = [
        f"https://h/a{punctuation}//{encoded}/sub",
        f"https://outer/api/https://inner{punctuation}//{encoded}",
        f"https://outer/api/https://inner/https://third{punctuation}//{encoded}?q=extra#frag",
        f"prefix{punctuation}{encoded}?x=y#f", f"?q=first#{encoded}",
        f"{encoded}https://next/sub", f"left[{encoded}]right",
    ]
    for raw in shapes:
        for clean in (sanitize_source_error, redact_source_url, summarize_pull_errors):
            public = clean(raw, matcher)
            assert token.casefold() not in unquote(unquote(public)).casefold()
            assert clean(public, matcher) == public
        attempt = SourcePullAttempt("clash", False, 0, error=raw, url=raw, skip_reasons=[raw])
        pull = SourcePullResult(ok=False, error=raw, attempts=[attempt])
        for value in [attempt.to_dict(matcher), pull.to_dict(known_secrets=matcher),
                      source_error_detail(RuntimeError(raw), "phase", "id", matcher),
                      public_runtime({"last_error": raw, "source_status": {"aggregate": {"errors": [raw]}}}, matcher)]:
            assert token.casefold() not in unquote(unquote(json.dumps(value))).casefold()


@pytest.mark.parametrize("levels", range(1, 17))
def test_unstable_nested_kv_is_hidden_at_all_public_entries(levels) -> None:
    raw = "?token=x" + "}#password=x" * levels + "}403"
    cleaners = [sanitize_source_error, redact_source_url, summarize_pull_errors,
                lambda x: public_source_status({"error": x})["error"],
                lambda x: public_runtime({"last_error": x})["last_error"],
                lambda x: SourcePullAttempt("clash", False, 0, error=x).to_dict()["error"],
                lambda x: SourcePullResult(ok=False, error=x).to_dict()["error"],
                lambda x: source_error_detail(RuntimeError(x), "phase", "id")["message"]]
    for clean in cleaners:
        first = clean(raw)
        assert clean(first) == first
        assert source_error_signal(first) == source_error_signal(clean(first))
    if levels >= 3:
        assert sanitize_source_error("before " + raw + " after") == "before <redacted> after"


@pytest.mark.parametrize("authority", ["h.example:", "localhost:", "[2001:db8::1]:", "10.0.0.1:",
                                        "h.example;parse", "h.example,x", "h.example)tail", "h.example]tail",
                                        "h.example'tail", 'h.example"tail'])
def test_bare_authority_empty_ports_and_glued_punctuation(authority) -> None:
    raw = "reviewuser:reviewpass@" + authority
    for clean in (sanitize_source_error, redact_source_url, summarize_pull_errors):
        first = clean(raw)
        assert "reviewpass" not in first and "reviewuser" not in first
        assert clean(first) == first


@pytest.mark.parametrize("punctuation", [",", ";", "'", '"'])
@pytest.mark.parametrize("token", [
    "abc123def456", "abcdefabcdefabcdef", "aB_cD-eF_gH-iJ_kL",
    "550e8400-e29b-41d4-a716-446655440000", "abc123def456.yaml",
])
def test_ambiguous_relative_path_uses_both_interpretations(punctuation, token) -> None:
    raw = f"https://h/a{punctuation}//{token}/sub"
    expected = f"https://h/a{punctuation}//<redacted>/sub"
    for clean in (sanitize_source_error, redact_source_url, summarize_pull_errors):
        assert clean(raw) == expected
        assert clean(expected) == expected
    attempt = SourcePullAttempt("clash", False, 0, url=raw, error=raw).to_dict()
    pull = SourcePullResult(ok=False, error=f"clash: {raw}", attempts=[
        SourcePullAttempt("clash", False, 0, url=raw, error=raw),
    ]).to_dict()
    runtime = public_runtime({"last_error": f"clash: {raw}", "source_status": {
        "standard": {"s": {"error": f"clash: {raw}", "attempts": [attempt]}},
        "aggregate": {"errors": [f"clash: {raw}"]},
    }})
    assert attempt["url"] == attempt["error"] == expected
    assert pull["error"] == runtime["last_error"] == f"clash: {expected}"
    assert token.casefold() not in json.dumps([pull, runtime]).casefold()
    assert public_runtime(runtime) == runtime


@pytest.mark.parametrize("punctuation", [",", ";", "'", '"'])
def test_ambiguous_relative_path_also_hides_second_url_userinfo(punctuation) -> None:
    raw = f"https://a/x{punctuation}//u:p@h/link/abc123def456"
    # Under the path interpretation, the whole u:p@h segment is sensitive.
    expected = f"https://a/x{punctuation}//<redacted>/link/<redacted>"
    assert redact_source_url(raw) == sanitize_source_error(raw) == expected
    assert sanitize_source_error(expected) == expected
    # No path context: this remains a separate relative URL with a normal host.
    assert sanitize_source_error(f"https://a{punctuation}//u:p@h/sub") == f"https://a{punctuation}//h/sub"


@pytest.mark.parametrize("punctuation", [",", ";", "'", '"'])
def test_ambiguous_relative_path_context_survives_adjacent_boundaries(punctuation) -> None:
    raw = f"https://h/a{punctuation}//abc123def456{punctuation}//def456ghi789"
    expected = f"https://h/a{punctuation}//<redacted>{punctuation}//<redacted>"
    assert sanitize_source_error(raw) == redact_source_url(raw) == expected
    assert sanitize_source_error(expected) == expected


@pytest.mark.parametrize("raw, expected, signal", [
    ("[ABC123DEF456&token=abctoken=abc%2F=#@;parse)//shadowrocket: https://h/403/expired/parse",
     "[//;parse)//shadowrocket: https://h/403/expired/parse", "[<redacted> <redacted>"),
    # Remove @ to isolate KV/URL convergence from the new bare-authority rule.
    ("[ABC123DEF456&token=abctoken=abc%2F=#;parse)//shadowrocket: https://h/403/expired/parse",
     "[ABC123DEF456&token=<redacted> https://h/403/expired/parse",
     "[abc123def456&token=<redacted> <redacted>"),
])
def test_error_sanitizer_settles_fable_fixed_point_in_one_public_call(monkeypatch, raw, expected, signal) -> None:
    import app.services.source_diagnostics as diagnostics

    original = diagnostics._rewrite_urls
    calls = []

    def observed(text, **kwargs):
        calls.append(text)
        return original(text, **kwargs)

    monkeypatch.setattr(diagnostics, "_rewrite_urls", observed)
    for clean in (sanitize_source_error, redact_source_url):
        calls.clear()
        assert clean(raw) == expected
        assert len(calls) <= 6  # At most three complete URL/KV/URL passes.
        assert clean(expected) == expected
    assert source_error_signal(expected) == signal


@pytest.mark.parametrize("raw", [
    "ratio 3:1@peak", "retry at 12:30@server", "see docs/README@v2",
    "npm pkg @scope/name@1.2.3", "code:403@upstream", "admin@example.com",
])
def test_bare_authority_decision_preserves_prose_and_email(raw) -> None:
    assert sanitize_source_error(raw) == raw
    assert redact_source_url(raw) == raw
    assert source_error_signal(raw) == raw.lower()


@pytest.mark.parametrize("raw, expected", [
    ("expired:token@host/x", "//host/x"),
    ("status=403/forbidden@gateway/1", "//gateway/1"),
    ("u:p@h.example", "//h.example"),
    ("user:pass@10.0.0.1:8080", "//10.0.0.1:8080"),
    ("user:pass@[2001:db8::1]:8080", "//[2001:db8::1]:8080"),
    ("user:pass@2001:db8::1", "//2001:db8::1"),
    ("user:pass@localhost:8080", "//localhost:8080"),
    ("user@h.example/link/abc123def456", "//h.example/link/<redacted>"),
    ("a/b@c/abc123def456", "//c/<redacted>"),
    ("@u:p@h/x", "//h/x"), ("u:p@@h/x", "//h/x"), ("u:p@h/x@y", "//y"),
    ("u:p@", "//"), ("%25/path/u:p@h", "//h"),
    ("u:p@h//abc123def456", "//h//<redacted>"),
    ("u@h//abc123def456", "//h//<redacted>"),
    ("u:p@=///host", "//=///host"),
    ("git@github.com:org/repo.git", "//github.com:org/repo.git"),
])
def test_bare_authority_decision_keeps_credential_shapes_hidden(raw, expected) -> None:
    for clean in (sanitize_source_error, redact_source_url):
        assert clean(raw) == expected
        assert clean(expected) == expected
    assert source_error_signal(expected) == ("//" if expected == "//" else "<redacted>")


# Fable round 3 unit3.py: 7 original + 44 review examples. Expected values
# were captured from the accepted round 3 snapshot, including documented N7 limits.
@pytest.mark.parametrize("raw, expected", [
    ('x ///u:p@h.example/s/abc123def456', 'x ///h.example/s/<redacted>'),
    ('1://u:p@h.example/x', '1://h.example/x'),
    ("'://u:p@h.example/x'", "'://h.example/x'"),
    ('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa://u:p@h.example/link/0123456789abcdef0123?q=1', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa://h.example/link/<redacted>'),
    ('/u:p@h.example/x', '//h.example/x'),
    ('see /path/u:p@h.example', 'see //h.example'),
    ('u@h.example/link/0123456789abcdef0123', '//h.example/link/<redacted>'),
    ('X ////U:P@H.example/S/ABC123DEF456', 'X ////H.example/S/<redacted>'),
    ('9a+b.c://U:P@h.example/Link/0123456789ABCDEF0123', '9a+b.c://h.example/Link/<redacted>'),
    ('"://u:p@h.example/x"', '"://h.example/x"'),
    ('(://u:p@h.example/x)', '(://h.example/x)'),
    ('[1://u:p@h.example/x]', '[1://h.example/x]'),
    ('-://u:p@h.example/x', '-://h.example/x'),
    ('+a://u:p@h.example/x', '+a://h.example/x'),
    ('.://u:p@h.example/x', '.://h.example/x'),
    ('_s://u:p@h.example/x', '_s://h.example/x'),
    ('é://u:p@h.example/x', 'é://h.example/x'),
    ('HTTPS://U:P@H.example/Link/0123456789ABCDEF0123?X=SECRETQ', 'HTTPS://H.example/Link/<redacted>'),
    ('hTtP://u:p@h/x', 'hTtP://h/x'),
    ('url:u:p@h.example/x', '//h.example/x'),
    ('to=u:p@h.example', '//h.example'),
    ('err,u:p@h.example/x;next', '//h.example/x;<redacted>'),
    ('{u:p@h.example}', '{//h.example}'),
    ('u:p@h.example:8443', '//h.example:8443'),
    ('u@h.example', 'u@h.example'),
    ('u@h.example/x', '//h.example/x'),
    ('user@h.example/link/abc123def456', '//h.example/link/<redacted>'),
    ('\\\\u:p@h.example\\share', '\\\\//h.example\\share'),
    ('file:///u:p@h/x', 'file:///<redacted>/x'),
    ('///u:p@h.example', '///h.example'),
    ('/x/y/u:p@h.example/z', '//h.example/z'),
    ('a/b@c/0123456789abcdef0123', '//c/<redacted>'),
    ('https://h.example/a/u:p@h2.example/x', 'https://h.example/a/<redacted>/x'),
    ('https://h.example?next=//u:p@h2.example/x', 'https://h.example'),
    ('https://h.example#//u:p@h2.example/x', 'https://h.example'),
    ('x=1&u:p@h.example/x', '//h.example/x'),
    ('u:p@[2001:db8::1]:80/x', '//[2001:db8::1]:80/x'),
    ('u%3Ap%40h.example/x', 'u%3Ap%40h.example/x'),
    ('u:p%40h.example/link/0123456789abcdef0123', 'u:p%40h.example/link/0123456789abcdef0123'),
    ('u:p＠h.example/x', 'u:p＠h.example/x'),
    ('0123456789ABCDEF0123https://h/x', '0123456789ABCDEF0123https://h/x'),
    ('abc123def456HTTPS://h/x', 'abc123def456HTTPS://h/x'),
    ('https://h/abc123def456https://h2/x', 'https://h/<redacted>https://h2/x'),
    ('pw-secret://h/x', 'pw-secret:<redacted>'),
    ('u:p@', '//'),
    ('@u:p@h/x', '//h/x'),
    ('u:p@@h/x', '//h/x'),
    ('u:p@h/x@y', '//y'),
    ('a b u:p@h.example\tx', 'a b //h.example\tx'),
    ('u:p@h.example\n/link/0123456789abcdef0123', '//h.example\n/link/0123456789abcdef0123'),
    ('line1\nu:p@h.example/x\nline3', 'line1\n//h.example/x\nline3'),
])
def test_round3_review_examples_remain_compatible(raw, expected) -> None:
    assert sanitize_source_error(raw) == expected
    assert redact_source_url(raw) == expected.strip()
    assert sanitize_source_error(expected) == expected


@pytest.mark.parametrize("token", ["abc123def456", "abcdefabcdefabcdef", "1234567890123456"])
@pytest.mark.parametrize("slashes", ["//", "///"])
def test_empty_url_path_segments_preserve_slashes_and_redact_on_first_read(token, slashes) -> None:
    raw = f"HTTPS://Host.test/a{slashes}{token}"
    expected = f"HTTPS://Host.test/a{slashes}<redacted>"
    for clean in (redact_source_url, sanitize_source_error):
        assert clean(raw) == expected
        assert clean(expected) == expected
    attempt = SourcePullAttempt("clash", False, 0, url=raw, error=raw).to_dict()
    assert attempt["url"] == attempt["error"] == expected


@pytest.mark.parametrize("raw, expected", [
    ("///u:p@h/link/abc123def456", "///h/link/<redacted>"),
    ("1://u:p@h/link/abc123def456", "1://h/link/<redacted>"),
    ("'://u:p@h/link/abc123def456", "'://h/link/<redacted>"),
    ("Z" * 90 + "://u:p@h/link/abc123def456", "Z" * 90 + "://h/link/<redacted>"),
    ("/u:p@h/x", "//h/x"),
    ("/path/u:p@h", "//h"),
    ("u@h/link/abc123def456", "//h/link/<redacted>"),
])
def test_malformed_and_username_only_authorities_are_sanitized(raw, expected) -> None:
    assert sanitize_source_error(f"failed {raw} end") == f"failed {expected} end"
    assert redact_source_url(raw) == expected
    assert redact_source_url(expected) == sanitize_source_error(expected) == expected


@pytest.mark.parametrize("token", ["AAparseAAAAAAAAAAAAA", "AAexpiredAAAAAAAAAAA"])
def test_token_glued_to_next_scheme_is_never_preserved_as_a_scheme(token) -> None:
    raw = f"HTTPS://Host/link/{token}https://Other/Path"
    expected = "HTTPS://Host/link/<redacted>https://Other/Path"
    actual = redact_source_url(raw)
    assert token.casefold() not in actual.casefold()
    assert actual == sanitize_source_error(raw) == expected
    assert sanitize_source_error(expected) == expected
    assert token.casefold() not in expected.casefold()
    node, reason = SourceFetcher(_settings())._node_from_clash_proxy_with_reason(
        {"name": "N", "type": raw, "server": "node.test", "port": 443}, StandardSource(id="s", name="S"),
    )
    assert node is None
    assert reason == f"unsupported protocol {expected}"


@pytest.mark.parametrize("raw, expected", [
    ("https://h/link/abc123def4561://u:p@h/sub", "https://h/link/<redacted>://h/sub"),
    ("https://h/link/abcdefabcdefabcdefexpiredhttps://x", "https://h/link/<redacted>https://x"),
    ("https://h/link/xexpiredhttp://]http://[", "https://h/link/xexpired<redacted>"),
])
def test_random_boundary_regressions_remain_stable(raw, expected) -> None:
    for clean in (redact_source_url, sanitize_source_error, summarize_pull_errors):
        assert clean(raw) == expected
        assert clean(expected) == expected


@pytest.mark.parametrize("path, expected", [
    ("1.2.3", "1.2.3"), ("foo.bar.baz", "foo.bar.baz"), ("a.b.c", "a.b.c"),
    ("eyJfoo.bar.baz", "<redacted>"),
    ("abcdefghij.klmnopqrst.uvwxyzABCD", "<redacted>"),
])
def test_jwt_detection_preserves_versions_and_ordinary_dotted_names(path, expected) -> None:
    raw = f"https://Host/Path/{path}"
    public = f"https://Host/Path/{expected}"
    assert redact_source_url(raw) == sanitize_source_error(raw) == public
    assert redact_source_url(public) == public


def test_protocol_name_limit_applies_only_to_new_diagnostics() -> None:
    old = {"attempts": [{"skip_reasons": ["unsupported protocol " + "z" * 200]}]}
    assert public_source_status(old) == old
    assert unsupported_protocol_reason("z" * 200) == "unsupported protocol " + "z" * 64 + "…"
    section = (Path(__file__).resolve().parents[1] / "docs/api/http-api.md").read_text().split(
        "`last_pull_error` 失败摘要约定：", 1,
    )[1].split("当标准源设置为", 1)[0]
    assert "新生成的未知协议名" in section
    assert "历史 skip_reasons" in section


# Acceptance examples come from B2/B3 of brief-backend-round-2.md, not from
# the implementation's character classes or its computed return values.
@pytest.mark.parametrize("path, expected", [
    ("0123456789abcdef0123456789abcdef.yaml", "<redacted>"),
    ("0123456789abcdef0123456789abcdef.txt", "<redacted>"),
    ("0123456789abcdef0123456789abcdef.conf", "<redacted>"),
    ("QUJDREVGR0hJSktMTU5PUA==", "<redacted>"),
    ("QUJDREVGR0hJSktMTU5PUA%3D%3D", "<redacted>"),
    ("AbCdEfGhIjKlMnOp==", "<redacted>"),
    ("0123456789abcdef+foo", "<redacted>"),
    ("aB3~dE5fG7hI9jK1", "<redacted>"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature1234567890", "<redacted>"),
    ("abc123def456", "<redacted>"),
    ("a1B2c3D4e5", "<redacted>"),
    ("%2561B3dE5fG7hI9jK1m", "<redacted>"),
    ("sub;token=abcdef0123456789", "sub;<redacted>"),
    ("sub%253Btoken%253Dabcdef0123456789", "sub;<redacted>"),
    ("s%75b;token=abcdef0123456789", "s%75b;<redacted>"),
    ("550e8400-e29b-41d4-a716-446655440000", "<redacted>"),
    ("aB_cD-eF_gH-iJ_kL", "<redacted>"),
    ("AAexpiredAAAAAAAAAAA", "<redacted>"),
    ("AAparseAAAAAAAAAAAAA", "<redacted>"),
    ("private-user@private-host", "<redacted>"),
])
def test_acceptance_token_forms_are_hidden_in_every_diagnostic_alias(path, expected) -> None:
    url = f"https://private-user:private-pass@sub.example:8443/link/{path}?q=query-secret#fragment-secret"
    safe = f"https://sub.example:8443/link/{expected}"
    error = f"clash: HTTP 404 ({url})"
    attempt = SourcePullAttempt(method="clash", ok=False, node_count=0, url=url, error=error, skip_reasons=[error])
    result = SourcePullResult(ok=False, error=f"{error}; {error}", attempts=[attempt]).to_dict()
    runtime = public_runtime({"last_error": f"{error}; {error}", "source_status": {
        "standard": {"s": {"error": error, "attempts": [attempt.to_dict()]}},
        "aggregate": {"errors": [f"{error}; {error}"]},
    }})
    expected_error = f"clash: HTTP 404 ({safe})"
    assert result["error"] == summarize_pull_errors(error) == runtime["last_error"] == expected_error
    assert result["attempts"][0]["url"] == safe
    assert result["attempts"][0]["error"] == expected_error
    assert result["attempts"][0]["skip_reasons"] == [expected_error]
    text = json.dumps([result, runtime])
    for secret in (path, "private-user", "private-pass", "query-secret", "fragment-secret"):
        assert secret not in text


@pytest.mark.parametrize("path", [
    "api", "v1", "v2", "client", "subscribe", "link", "sub", "s", "clash.yaml", "surge.conf",
    "shadowrocket.conf", "subscription-userinfo", "client_subscribe_v2", "shadowrocket-config",
    "clash-meta-config", "getSubscribeContent", "subscription-configurations", "client-configurations",
    "internationalization", "download", "config.yaml",
])
def test_acceptance_ordinary_paths_are_preserved(path) -> None:
    url = f"https://sub.example/{path}"
    assert SourceFetcher._redact_url(url + "?secret=q#f") == url
    assert summarize_pull_errors(f"clash: failed {url}") == f"clash: failed {url}"


@pytest.mark.parametrize("host, expected", [
    ("0123456789abcdef0123.sub.example.test:8443", "<redacted>.sub.example.test:8443"),
    ("[2001:db8::1]:8443", "[2001:db8::1]:8443"),
    ("例子.测试:8443", "例子.测试:8443"),
    ("xn--abcdefghijklmnop123.test:8443", "xn--abcdefghijklmnop123.test:8443"),
    ("subscription-configurations.example:8443", "subscription-configurations.example:8443"),
])
def test_acceptance_host_labels_preserve_ports_ipv6_and_idn(host, expected) -> None:
    url = f"https://private-user:private-pass@{host}/sub?q=query-secret#fragment-secret"
    safe = f"https://{expected}/sub"
    attempt = SourcePullAttempt(method="clash", ok=False, node_count=0, url=url, error=url).to_dict()
    error = f"clash: HTTP 404 ({url})"
    runtime = public_runtime({"last_error": error, "source_status": {"aggregate": {"errors": [error]}}})
    assert attempt["url"] == attempt["error"] == safe
    assert runtime["last_error"] == summarize_pull_errors(error) == f"clash: HTTP 404 ({safe})"
    assert public_runtime(runtime) == runtime


@pytest.mark.parametrize("raw, expected", [
    ("//user:pass@host.test/link/abc123def456?q=secret#fragment", "//host.test/link/<redacted>"),
    ("//host.test/link/abc123def456?q=secret#fragment", "//host.test/link/<redacted>"),
    ("user:pass@host.test/link/abc123def456?q=secret#fragment", "//host.test/link/<redacted>"),
    ("'user:pass@host.test/link/abc123def456?q=secret#fragment'", "'//host.test/link/<redacted>'"),
    ("u" * 256 + ":" + "p" * 256 + "@host.test/link/abc123def456?q=secret#fragment", "//host.test/link/<redacted>"),
    ("https://a.example/x,https://u:p@b.example/link/0123456789abcdef0123?k=v",
     "https://a.example/x,https://b.example/link/<redacted>"),
    ("'https://a.example/x','https://u:p@b.example/y'", "'https://a.example/x','https://b.example/y'"),
    ("https://a.example/x;https://u:p@b.example/y", "https://a.example/x;https://b.example/y"),
    ("https://a.example/x;//u:p@b.example/link/abc123def456?q=s#f",
     "https://a.example/x;//<redacted>/link/<redacted>"),
    ("https://ghproxy.example/https://u:p@raw.example/link/0123456789abcdef0123?q=s#f",
     "https://ghproxy.example/https://raw.example/link/<redacted>"),
    ("https://u:p@h/a<b/0123456789abcdef0123?x=1", "https://h/<redacted>/<redacted>"),
    ("https://h/link/AAexpiredAAAAAAAAAAAparse.clash:", "https://h/link/<redacted>"),
    ("https://h/link/AAparseAAAAAAAAAAAAA)''HTTP", "https://h/link/<redacted>"),
])
def test_adjacent_nested_relative_and_bare_urls(raw, expected) -> None:
    text = f"failed {raw} end"
    result = sanitize_source_error(text)
    assert result == f"failed {expected} end"
    assert sanitize_source_error(result) == result


@pytest.mark.parametrize("protocol, expected", [
    ("//user:pass@example.test/s/0123456789abcdef?ordinary=private#fragment",
     "unsupported protocol //example.test/s/<redacted>"),
    ("https://user:pass@example.test/s/0123456789abcdef?ordinary=private#fragment",
     "unsupported protocol https://example.test/s/<redacted>"),
    ("z" * 200, "unsupported protocol " + "z" * 64 + "…"),
    ("https://h/AAparseAAAAAAAAAAAAAhttps://x", "unsupported protocol https://h/<redacted>https://x"),
])
def test_real_http_yaml_parser_sanitizes_and_limits_unknown_protocol(protocol, expected) -> None:
    # Real TCP + httpcore: the *requested* URL is absolute. The relative URL
    # is upstream data in valid YAML, never an invalid MockTransport request.
    body = json.dumps({"proxies": [{"name": "Unknown", "type": protocol, "server": "node.test", "port": 443}]}).encode()
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.headers.get("User-Agent"))
            self.send_response(200)
            self.send_header("Content-Type", "application/yaml")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        worker.start()
        try:
            source = StandardSource(
                id="real-http", name="Real HTTP", clash_url=f"http://127.0.0.1:{server.server_port}/sub",
                pull_network_mode=STANDARD_SOURCE_PULL_NETWORK_DIRECT_ONLY,
            )
            result = asyncio.run(SourceFetcher(_settings()).fetch_source(source))
        finally:
            server.shutdown()
            worker.join()
    assert len(requests) == 3
    assert len([attempt for attempt in result.attempts if attempt.method == "clash"]) == 3
    assert not result.ok
    assert expected in result.error
    for attempt in result.to_dict()["attempts"]:
        if attempt["method"] == "clash":
            assert any(expected in reason for reason in attempt["skip_reasons"])
    for secret in ("user:pass", "0123456789abcdef", "ordinary=private", "#fragment"):
        assert secret not in json.dumps(result.to_dict())
    assert "AAparseAAAAAAAAAAAAA".casefold() not in json.dumps(result.to_dict()).casefold()


@pytest.mark.parametrize("parser", ["clash", "uri", "shadowrocket", "surge"])
def test_all_protocol_reason_generation_sites_limit_the_name(parser) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(id="s", name="S")
    protocol = "z" * 200
    if parser == "clash":
        node, reason = fetcher._node_from_clash_proxy_with_reason(
            {"name": "N", "type": protocol, "server": "node.test", "port": 443}, source,
        )
    elif parser == "uri":
        node, reason = fetcher._node_from_generic_uri(f"{protocol}://node.test:443", source)
    else:
        node, reason = getattr(fetcher, f"_node_from_{parser}_line_with_reason")(
            f"N = {protocol}, node.test, 443", source,
        )
    assert node is None
    assert reason == "unsupported protocol " + "z" * 64 + "…"


@pytest.mark.parametrize("kind", [
    "dots", "pluses", "closing_parens", "different_urls", "hub_summary", "dense_slashes", "short_segments",
    "long_scheme", "scheme_near_miss",
])
def test_pull_summary_linear_scan_budget(kind) -> None:
    cases = {
        "dots": "a." * 32768,
        "pluses": "a+" * 32768,
        "closing_parens": "http://h/" + ")" * 32000,
        "different_urls": "; ".join(
            f"clash: https://u:p@h.example.test/{i}/0123456789abcdef0123?q=x#f" for i in range(1000)
        ),
        "hub_summary": "; ".join(f"clash: {i} " + "error " * 15 for i in range(1000)),
        "dense_slashes": "//a" * (65536 // 3),
        "short_segments": "http://h/" + "a/" * ((65536 - 9) // 2),
        "long_scheme": "Z" * 65000 + "://u:p@h/sub",
        "scheme_near_miss": "a+." * 21845 + ":/",
    }
    started = perf_counter()
    output = summarize_pull_errors(cases[kind])
    elapsed = perf_counter() - started
    # The slowest linear case takes about 0.1 s on CI; a quadratic regression on
    # these 64 KiB inputs takes seconds.
    assert elapsed < 0.5, (kind, elapsed)
    if kind in {"different_urls", "hub_summary"}:
        assert output.count("clash: ") == 1000  # No truncation to meet the budget.
    elif kind == "long_scheme":
        assert output == "Z" * 65000 + "://h/sub"
    else:
        assert output == cases[kind]


@pytest.mark.parametrize("original, expected", [
    ("", "all methods failed"),
    ("   ", "all methods failed"),
    ("clash: HTTP 404; clash: HTTP 404; surge: HTTP 403; clash: HTTP 403; surge: HTTP 403",
     "clash: HTTP 404; surge: HTTP 403; clash: HTTP 403"),
    ("clash: 0 valid nodes parsed; reason1; reason1; reason2; surge: HTTP 404; "
     "clash: 0 valid nodes parsed; reason1; reason1; reason2; shadowrocket: HTTP 404",
     "clash: 0 valid nodes parsed; reason1; reason1; reason2; surge: HTTP 404; shadowrocket: HTTP 404"),
    ("clash: error; reason1; clash: error; reason2", "clash: error; reason1; clash: error; reason2"),
    ("legacy: failure; legacy: failure", "legacy: failure; legacy: failure"),
])
def test_pull_error_summary_preserves_complete_entries(original, expected) -> None:
    assert summarize_pull_errors(original) == expected
    assert summarize_pull_errors(expected) == expected


@pytest.mark.parametrize("path, expected", [
    ("/api/v1/client/subscribe/link/clash.yaml", "/api/v1/client/subscribe/link/clash.yaml"),
    ("/link/aB3dE5fG7hI9jK1m", "/link/<redacted>"),
    ("/s/0123456789abcdef0123456789abcdef", "/s/<redacted>"),
    ("/api/v1/client/subscribe/550e8400-e29b-41d4-a716-446655440000", "/api/v1/client/subscribe/<redacted>"),
    ("/link/aB_cD-eF_gH-iJ_kL", "/link/<redacted>"),
    ("/link/abcdefghijklmnop", "/link/<redacted>"),
    ("/link/1234567890123456", "/link/<redacted>"),
    ("/link/%61B3dE5fG7hI9jK1m", "/link/<redacted>"),
    ("/link/part%2FaB3dE5fG7hI9jK1m", "/link/<redacted>"),
    ("/link/<redacted>/clash.yaml", "/link/<redacted>/clash.yaml"),
])
def test_redact_source_url_strips_credentials_and_token_segments(path, expected) -> None:
    url = f"https://user:private-pass@sub.example:8443{path}?token=query-secret&format=clash#fragment-secret"
    safe = f"https://sub.example:8443{expected}"
    assert SourceFetcher._redact_url(url) == safe
    assert SourceFetcher._redact_url(safe) == safe
    error = f"request failed ({url}); retry '{url}'"
    expected_error = f"request failed ({safe}); retry '{safe}'"
    assert sanitize_source_error(error) == expected_error
    assert sanitize_source_error(expected_error) == expected_error


def test_redact_source_url_preserves_ipv6_and_handles_invalid_authority() -> None:
    assert SourceFetcher._redact_url(
        "http://user%40example:p%3Ass@[2001:db8::1]:8080/api/v1?x=secret#private"
    ) == "http://[2001:db8::1]:8080/api/v1"
    assert SourceFetcher._redact_url("https://user:secret@[invalid/link/private") == "<redacted>"
    assert SourceFetcher._redact_url("") == ""


@pytest.mark.parametrize("quote", ["", "'", '"'])
def test_error_url_quotes_do_not_expose_userinfo_or_query(quote) -> None:
    url = "https://user:pri'vate@sub.example/link/0123456789abcdef?other='private-query'#private-fragment"
    assert sanitize_source_error(f"failed at {quote}{url}{quote}") == (
        f"failed at {quote}https://sub.example/link/<redacted>{quote}"
    )


@pytest.mark.parametrize("exception_type", [ValueError, RuntimeError, httpx.ReadTimeout, httpx.ConnectError])
def test_fetch_error_sanitizes_exception_urls_and_sensitive_values(exception_type) -> None:
    url = "https://private-user:private-pass@sub.example:8443/link/aB3dE5fG7hI9jK1m?foo=query-secret#fragment-secret"
    message = f"failed at {url}; password=private-kv"
    error = SourceFetcher._sanitize_fetch_error("surge", url, exception_type(message))
    assert "surge" in error
    for secret in ("private-user", "private-pass", "aB3dE5fG7hI9jK1m", "query-secret", "fragment-secret", "private-kv"):
        assert secret not in error
    assert "https://sub.example:8443/link/<redacted>" in error


def test_fetch_source_summarizes_multiple_uas_and_network_paths(monkeypatch) -> None:
    url = "https://private-user:private-pass@sub.example:8443/link/aB3dE5fG7hI9jK1m?foo=query-secret#fragment-secret"
    safe_url = "https://sub.example:8443/link/<redacted>"
    calls = []

    def build_client(_settings, *, trust_env):
        def handle(request):
            ua = request.headers["User-Agent"]
            calls.append((trust_env, ua))
            return httpx.Response(403 if ua.startswith("mihomo") else 404, request=request)

        return httpx.AsyncClient(transport=httpx.MockTransport(handle), trust_env=False)

    monkeypatch.setattr("app.services.source_fetcher.build_async_http_client", build_client)
    source = StandardSource(id="multi", name="Multi", clash_url=url, surge_url=url, shadowrocket_url=url)
    result = asyncio.run(SourceFetcher(_settings()).fetch_source(source))
    assert result.ok is False
    assert len(calls) == len(result.attempts) == 10
    assert [item.network_path for item in result.attempts] == ["direct"] * 3 + ["proxy"] * 3 + ["direct", "proxy"] * 2
    assert result.error == (
        "clash: HTTP 404; clash: HTTP 403; "
        f"surge: HTTP 404 (surge, {safe_url}); shadowrocket: HTTP 404 (shadowrocket, {safe_url})"
    )
    for item in result.attempts:
        assert item.url == safe_url
        assert item.to_dict()["url"] == safe_url
        for secret in ("private-user", "private-pass", "aB3dE5fG7hI9jK1m", "query-secret", "fragment-secret"):
            assert secret not in item.error
            assert secret not in result.error
    assert summarize_pull_errors(result.error) == result.error


def test_clash_internal_exceptions_and_contextual_attempts_are_sanitized(monkeypatch) -> None:
    raw_url = "https://user:secret@sub.example/s/0123456789abcdef?other=private#private"
    safe_url = "https://sub.example/s/<redacted>"

    def fail(request):
        raise RuntimeError(f"upstream rejected {raw_url}")

    monkeypatch.setattr("app.services.source_fetcher.build_async_http_client", lambda *_a, **_kw: httpx.AsyncClient(
        transport=httpx.MockTransport(fail), trust_env=False,
    ))
    fetcher = SourceFetcher(_settings())
    payload = asyncio.run(fetcher._fetch_clash(StandardSource(id="s", name="S", clash_url=raw_url)))
    assert len(payload.attempts) == 3
    assert all(item.error == f"upstream rejected {safe_url}" for item in payload.attempts)

    raw = SourcePullAttempt(method="", ok=False, node_count=0, url=raw_url, error=f"parse failed {raw_url}")
    copied = fetcher._contextualize_attempts([raw], method="clash", safe_url=safe_url, network_path="direct")[0]
    assert copied.url == safe_url
    assert copied.error == f"parse failed {safe_url}"
    assert raw.url == raw_url  # The contextual copy does not mutate its input.
    assert raw.to_dict()["url"] == safe_url
    assert raw.to_dict()["error"] == copied.error


def test_fetch_source_keeps_zero_node_reasons_together(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())

    async def empty(_source, *, trust_env):
        return FetchPayload(nodes=[], skip_reasons=["reason1", "reason1", "reason2"])

    for method in ("clash", "surge", "shadowrocket"):
        monkeypatch.setattr(fetcher, f"_fetch_{method}", empty)
    result = asyncio.run(fetcher.fetch_source(StandardSource(
        id="s", name="S", clash_url="https://example.test/clash.yaml",
        surge_url="https://example.test/surge", shadowrocket_url="https://example.test/sr",
    )))
    assert len(result.attempts) == 6
    assert result.error == "; ".join(
        f"{method}: 0 valid nodes parsed; reason1; reason1; reason2" for method in ("clash", "surge", "shadowrocket")
    )


def test_pull_summary_redacts_before_deduplication_without_truncating() -> None:
    raw_url = "https://user:secret@sub.example/link/0123456789abcdef?x=private#private"
    entry = f"clash: rejected {raw_url}"
    distinct = "shadowrocket: " + "reason " * 400 + "HTTP 401"
    result = summarize_pull_errors(f"{entry}; {entry}; {distinct}")
    assert result == f"clash: rejected https://sub.example/link/<redacted>; {distinct}"
    assert summarize_pull_errors(result) == result


@pytest.mark.parametrize("bad_line", [
    "trojan://synthetic-secret@bad.example:bad",
    "ss://YWVzLTEyOC1nY206c2VjcmV0@bad.example:99999",
    "vless://uuid@[invalid:443",
    "vmess://uuid@bad.example:not-a-port",
])
def test_manual_import_keeps_valid_nodes_when_another_uri_is_malformed(bad_line) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="mixed", name="Mixed", ingest_kind="manual_nodes",
        manual_nodes_text="trojan://password@good.example:443#Good\n" + bad_line,
    )
    result = fetcher.parse_manual_nodes(source)
    assert result.ok is True
    assert result.node_count == 1
    assert result.nodes[0].host == "good.example"
    assert "invalid uri" in str(result.attempts[0].skip_reasons)
    assert "synthetic-secret" not in str(result.attempts[0].skip_reasons)
    assert result.warnings[0].code == "source-parse-rejected"
    assert "synthetic-secret" not in result.warnings[0].message


def test_uri_parser_preserves_tls_websocket_and_connection_identity() -> None:
    fetcher = SourceFetcher(_settings())
    prefix = "vless://ed3fe100-9247-4eac-a7d9-646aac14b979@same.example:443?type=ws&security=tls&host=front.example&sni=tls.example&alpn=h2%2Chttp%2F1.1&path="
    source = StandardSource(
        id="ws", name="WS", ingest_kind="manual_nodes",
        manual_nodes_text="\n".join([
            prefix + "%2Fa#One", prefix + "%2Fb#Two", prefix + "%2Fa#Duplicate",
            "trojan://secret-one@same.example:443#First",
            "trojan://secret-two@same.example:443#Second",
        ]),
    )
    result = fetcher.parse_manual_nodes(source)
    assert result.node_count == 4
    first = result.nodes[0]
    assert first.raw["tls"] is True
    assert first.raw["network"] == "ws"
    assert first.raw["sni"] == "tls.example"
    assert first.raw["alpn"] == ["h2", "http/1.1"]
    assert first.raw["ws-opts"] == {"path": "/a", "headers": {"Host": "front.example"}}
    assert result.nodes[1].raw["ws-opts"]["path"] == "/b"
    assert all("secret" not in node.dedupe_key() for node in result.nodes)


def test_legacy_vmess_json_keeps_transport_tls_and_cipher() -> None:
    payload = {
        "add": "vmess.example", "port": 443, "id": "uuid", "aid": "3", "scy": "aes-128-gcm",
        "net": "ws", "path": "/websocket", "host": "front.example", "tls": "tls", "sni": "tls.example",
    }
    line = "vmess://" + base64.b64encode(json.dumps(payload).encode()).decode()
    node, reason = SourceFetcher(_settings())._node_from_uri_line(line, StandardSource(id="vm", name="VM"))
    assert reason == ""
    assert node is not None
    assert node.raw["cipher"] == "aes-128-gcm"
    assert node.raw["alterId"] == 3
    assert node.raw["tls"] is True
    assert node.raw["ws-opts"] == {"path": "/websocket", "headers": {"Host": "front.example"}}


@pytest.mark.parametrize("query, reason", [
    ("type=grpc&serviceName=service", "unsupported uri transport"),
    ("type=ws&security=xtls", "unsupported uri security"),
    ("security=tls&ech=encoded", "unsupported uri security extension"),
    ("type=tcp&type=ws", "duplicate uri query field"),
    ("encryption=mlkem-custom", "unsupported vless encryption"),
    ("security=reality", "missing vless reality public key"),
])
def test_unrepresentable_uri_fields_are_diagnosed_instead_of_dropped(query, reason) -> None:
    node, actual_reason = SourceFetcher(_settings())._node_from_uri_line(
        "vless://uuid@server.example:443?" + query, StandardSource(id="s", name="Source"),
    )
    assert node is None
    assert actual_reason == reason


@pytest.mark.parametrize("uri, reason", [
    ("vmess://uuid@server.example:443?security=reality&pbk=abc&sid=00", "unsupported uri reality protocol"),
    ("trojan://password@server.example:443?security=none", "unsupported trojan security"),
])
def test_protocol_security_mismatches_are_rejected(uri, reason) -> None:
    node, actual_reason = SourceFetcher(_settings())._node_from_uri_line(uri, StandardSource(id="s", name="Source"))
    assert node is None
    assert actual_reason == reason


def test_sip002_plugin_parameters_are_preserved_and_unknown_plugins_rejected() -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(id="ss", name="SS")
    node, reason = fetcher._node_from_uri_line(
        "ss://YWVzLTEyOC1nY206c2VjcmV0@ss.example:443/?plugin=obfs-local%3Bobfs%3Dhttp%3Bobfs-host%3Dfront.example#SS", source,
    )
    assert reason == ""
    assert node.raw["plugin"] == "obfs"
    assert node.raw["plugin-opts"] == {"mode": "http", "host": "front.example"}
    refused, reason = fetcher._node_from_uri_line(
        "ss://YWVzLTEyOC1nY206c2VjcmV0@ss.example:443/?plugin=unknown-plugin", source,
    )
    assert refused is None
    assert reason == "unsupported ss plugin"


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _CaptureClient:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.calls: list[dict[str, object]] = []

    async def __aenter__(self) -> "_CaptureClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(
        self,
        url: str,
        timeout: int | float | None = None,
        headers: dict[str, str] | None = None,
    ) -> _FakeResponse:
        self.calls.append(
            {
                "url": url,
                "timeout": timeout,
                "headers": dict(headers or {}),
            }
        )
        return _FakeResponse(self.response_text)


class _VariantCaptureClient:
    def __init__(self, response_by_ua: dict[str, str]) -> None:
        self.response_by_ua = response_by_ua
        self.calls: list[dict[str, object]] = []

    async def __aenter__(self) -> "_VariantCaptureClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(
        self,
        url: str,
        timeout: int | float | None = None,
        headers: dict[str, str] | None = None,
    ) -> _FakeResponse:
        call = {
            "url": url,
            "timeout": timeout,
            "headers": dict(headers or {}),
        }
        self.calls.append(call)
        ua = str((headers or {}).get("User-Agent", "")).strip()
        return _FakeResponse(self.response_by_ua.get(ua, "proxies: []\n"))


def _settings() -> Settings:
    return Settings(
        app_name="SubHub",
        app_base_url="",
        storage_root="./var",
        refresh_interval_minutes=30,
        request_timeout_seconds=20,
        verify_tls=True,
        github_api_base="https://api.github.com/repos/blackmatrix7/ios_rule_script",
        github_raw_base="https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master",
        rule_catalog_refresh_hours=24,
        manage_api_require_login=False,
        max_snapshots_per_account=20,
        account_crawl_parallelism=2,
    )


def test_parse_clash_node_with_prefix() -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="",
        shadowrocket_url="",
        quality_group=QUALITY_MEDIUM,
    )
    node = fetcher._node_from_clash_proxy(
        {
            "name": "Tokyo-01",
            "server": "tokyo.example.com",
            "port": 443,
            "type": "trojan",
            "password": "x",
        },
        source,
    )
    assert node is not None
    assert node.name.startswith("[机场A]")
    assert node.protocol == "trojan"


def test_parse_clash_vless_preserves_mihomo_extensions() -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="",
        shadowrocket_url="",
        quality_group=QUALITY_MEDIUM,
    )
    node = fetcher._node_from_clash_proxy(
        {
            "name": "vless-1",
            "server": "vless.example.com",
            "port": 443,
            "type": "vless",
            "uuid": "uuid-1",
            "flow": "xtls-rprx-vision",
            "packet-encoding": "packetaddr",
            "reality-opts": {
                "public-key": "pub-key",
                "short-id": "short",
            },
        },
        source,
    )
    assert node is not None
    assert node.protocol == "vless"
    assert node.raw.get("flow") == "xtls-rprx-vision"
    assert node.raw.get("packet_encoding") == "packetaddr"
    assert node.raw.get("reality_opts") == {
        "public-key": "pub-key",
        "short-id": "short",
    }


def test_parse_clash_payload_filters_technical_nodes() -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="",
        shadowrocket_url="",
        quality_group=QUALITY_MEDIUM,
    )
    payload = fetcher._parse_clash_payload(
        (
            "proxies:\n"
            "  - name: 'Traffic: 2.29 GB | 20 GB'\n"
            "    server: traffic.example.com\n"
            "    port: 443\n"
            "    type: trojan\n"
            "    password: p1\n"
            "  - name: 'Tokyo-01'\n"
            "    server: tokyo.example.com\n"
            "    port: 443\n"
            "    type: trojan\n"
            "    password: p2\n"
        ),
        source,
    )
    assert len(payload.nodes) == 1
    assert payload.nodes[0].name.endswith("Tokyo-01")
    assert payload.filtered_technical_count == 1
    assert payload.filtered_technical_examples == ["[机场A] Traffic: 2.29 GB | 20 GB"]
    assert any("filtered technical node" in item for item in payload.skip_reasons())


def test_parse_clash_payload_keeps_keyword_only_name() -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="",
        shadowrocket_url="",
        quality_group=QUALITY_MEDIUM,
    )
    payload = fetcher._parse_clash_payload(
        (
            "proxies:\n"
            "  - name: 'Traffic Relay Tokyo 01'\n"
            "    server: tokyo.example.com\n"
            "    port: 443\n"
            "    type: trojan\n"
            "    password: p1\n"
        ),
        source,
    )
    assert len(payload.nodes) == 1
    assert payload.filtered_technical_count == 0
    assert payload.filtered_technical_examples == []


def test_parse_clash_payload_keeps_structure_without_keyword() -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="",
        shadowrocket_url="",
        quality_group=QUALITY_MEDIUM,
    )
    payload = fetcher._parse_clash_payload(
        (
            "proxies:\n"
            "  - name: '2.29 GB | 20 GB'\n"
            "    server: quota.example.com\n"
            "    port: 443\n"
            "    type: trojan\n"
            "    password: p1\n"
        ),
        source,
    )
    assert len(payload.nodes) == 1
    assert payload.filtered_technical_count == 0
    assert payload.filtered_technical_examples == []


def test_parse_surge_node_with_prefix() -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="",
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    node = fetcher._node_from_surge_line(
        "Tokyo-02 = vmess, vmess.example.com, 443, username=uuid-1",
        source,
    )
    assert node is not None
    assert node.name.startswith("[机场A]")
    assert node.protocol == "vmess"
    assert node.raw.get("uuid") == "uuid-1"


def test_parse_surge_vless_returns_none() -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="",
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    node = fetcher._node_from_surge_line(
        "vless-1 = vless, vless.example.com, 443, username=uuid-1",
        source,
    )
    assert node is None


def test_fetch_source_prefers_clash_then_surge(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="https://example.com/clash.yaml",
        shadowrocket_url="https://example.com/sr.conf",
        surge_url="https://example.com/surge.conf",
        quality_group=QUALITY_MEDIUM,
    )

    called = {"surge": False, "shadowrocket": False}
    clash_node = NodeRecord(
        name="[机场A] c1",
        host="c1.example.com",
        port=443,
        protocol="http",
        quality_group=QUALITY_MEDIUM,
        source_id="s1",
        source_type="standard",
    )

    async def _fake_clash(_source: StandardSource) -> list[NodeRecord]:
        return [clash_node]

    async def _fake_surge(_source: StandardSource) -> list[NodeRecord]:
        called["surge"] = True
        return []

    async def _fake_shadowrocket(_source: StandardSource) -> list[NodeRecord]:
        called["shadowrocket"] = True
        return []

    monkeypatch.setattr(fetcher, "_fetch_clash", _fake_clash)
    monkeypatch.setattr(fetcher, "_fetch_surge", _fake_surge)
    monkeypatch.setattr(fetcher, "_fetch_shadowrocket", _fake_shadowrocket)

    result = asyncio.run(fetcher.fetch_source(source))
    assert result.ok is True
    assert result.method == "clash"
    assert result.node_count == 1
    assert result.nodes == [clash_node]
    assert called["surge"] is False
    assert called["shadowrocket"] is False


def test_fetch_source_uses_surge_when_clash_empty(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="https://example.com/clash.yaml",
        shadowrocket_url="https://example.com/sr.conf",
        surge_url="https://example.com/surge.conf",
        quality_group=QUALITY_MEDIUM,
    )

    called = {"shadowrocket": False}
    surge_node = NodeRecord(
        name="[机场A] s1",
        host="s1.example.com",
        port=443,
        protocol="http",
        quality_group=QUALITY_MEDIUM,
        source_id="s1",
        source_type="standard",
    )

    async def _fake_clash(_source: StandardSource) -> list[NodeRecord]:
        return []

    async def _fake_surge(_source: StandardSource) -> list[NodeRecord]:
        return [surge_node]

    async def _fake_shadowrocket(_source: StandardSource) -> list[NodeRecord]:
        called["shadowrocket"] = True
        return []

    monkeypatch.setattr(fetcher, "_fetch_clash", _fake_clash)
    monkeypatch.setattr(fetcher, "_fetch_surge", _fake_surge)
    monkeypatch.setattr(fetcher, "_fetch_shadowrocket", _fake_shadowrocket)

    result = asyncio.run(fetcher.fetch_source(source))
    assert result.ok is True
    assert result.method == "surge"
    assert result.node_count == 1
    assert result.nodes == [surge_node]
    assert called["shadowrocket"] is False


def test_fetch_source_returns_error_when_all_methods_fail(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="https://example.com/clash.yaml?token=abc",
        shadowrocket_url="https://example.com/sr.conf?token=def",
        surge_url="https://example.com/surge.conf?token=xyz",
        quality_group=QUALITY_MEDIUM,
    )

    async def _fake_clash(_source: StandardSource) -> list[NodeRecord]:
        raise ValueError("bad clash payload")

    async def _fake_surge(_source: StandardSource) -> list[NodeRecord]:
        return []

    async def _fake_shadowrocket(_source: StandardSource) -> list[NodeRecord]:
        raise RuntimeError("network down")

    monkeypatch.setattr(fetcher, "_fetch_clash", _fake_clash)
    monkeypatch.setattr(fetcher, "_fetch_surge", _fake_surge)
    monkeypatch.setattr(fetcher, "_fetch_shadowrocket", _fake_shadowrocket)

    result = asyncio.run(fetcher.fetch_source(source))
    assert result.ok is False
    assert result.method == ""
    assert result.node_count == 0
    assert len(result.attempts) == 6
    assert result.attempts[0].ok is False
    assert "bad clash payload" in result.attempts[0].error
    assert any(item.error == "0 valid nodes parsed" for item in result.attempts)
    assert "network down" in result.error
    # Error payload should not leak original query params.
    assert "?token=" not in result.error


def test_fetch_source_direct_then_proxy_fallback(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="https://example.com/clash.yaml",
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
        pull_network_mode=STANDARD_SOURCE_PULL_NETWORK_DIRECT_THEN_PROXY,
    )

    called: list[bool] = []
    node = NodeRecord(
        name="[机场A] c1",
        host="c1.example.com",
        port=443,
        protocol="http",
        quality_group=QUALITY_MEDIUM,
        source_id="s1",
        source_type="standard",
    )

    async def _fake_clash(_source: StandardSource, *, trust_env: bool = True) -> list[NodeRecord]:
        called.append(trust_env)
        if not trust_env:
            raise ValueError("direct blocked")
        return [node]

    monkeypatch.setattr(fetcher, "_fetch_clash", _fake_clash)

    result = asyncio.run(fetcher.fetch_source(source))
    assert result.ok is True
    assert result.method == "clash"
    assert called == [False, True]
    assert result.attempts[0].network_path == "direct"
    assert result.attempts[1].network_path == "proxy"
    assert result.attempts[1].ok is True


def test_fetch_source_direct_only_no_proxy_fallback(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="https://example.com/clash.yaml",
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
        pull_network_mode=STANDARD_SOURCE_PULL_NETWORK_DIRECT_ONLY,
    )

    called: list[bool] = []

    async def _fake_clash(_source: StandardSource, *, trust_env: bool = True) -> list[NodeRecord]:
        called.append(trust_env)
        raise ValueError("direct blocked")

    monkeypatch.setattr(fetcher, "_fetch_clash", _fake_clash)

    result = asyncio.run(fetcher.fetch_source(source))
    assert result.ok is False
    assert called == [False]
    assert len(result.attempts) == 3
    assert result.attempts[0].network_path == "direct"


def test_fetch_source_proxy_then_direct_fallback(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="https://example.com/clash.yaml",
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
        pull_network_mode=STANDARD_SOURCE_PULL_NETWORK_PROXY_THEN_DIRECT,
    )

    called: list[bool] = []
    node = NodeRecord(
        name="[机场A] c1",
        host="c1.example.com",
        port=443,
        protocol="http",
        quality_group=QUALITY_MEDIUM,
        source_id="s1",
        source_type="standard",
    )

    async def _fake_clash(_source: StandardSource, *, trust_env: bool = True) -> list[NodeRecord]:
        called.append(trust_env)
        if trust_env:
            raise ValueError("proxy blocked")
        return [node]

    monkeypatch.setattr(fetcher, "_fetch_clash", _fake_clash)

    result = asyncio.run(fetcher.fetch_source(source))
    assert result.ok is True
    assert called == [True, False]
    assert result.attempts[0].network_path == "proxy"
    assert result.attempts[1].network_path == "direct"


def test_fetch_clash_sets_clash_user_agent_header(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="https://example.com/clash.yaml",
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    client = _CaptureClient("proxies: []\n")

    monkeypatch.setattr(
        "app.services.source_fetcher.build_async_http_client",
        lambda *_args, **_kwargs: client,
    )

    result = asyncio.run(fetcher._fetch_clash(source, trust_env=False))
    assert len(result) == 0
    assert len(client.calls) == 3
    uas = [str((call.get("headers") or {}).get("User-Agent", "")) for call in client.calls]
    assert uas == [
        "ClashforWindows/0.20.39",
        "clash-verge/2.0",
        "mihomo/1.19.0",
    ]


def test_fetch_clash_direct_path_ignores_proxy_env(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="https://example.com/clash.yaml",
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    client = _CaptureClient("proxies: []\n")
    seen_kwargs: list[dict[str, object]] = []

    monkeypatch.setenv("HTTP_PROXY", "http://172.18.0.1:17890")
    monkeypatch.setenv("HTTPS_PROXY", "http://172.18.0.1:17890")

    def _fake_build_client(*_args, **kwargs):
        seen_kwargs.append(dict(kwargs))
        return client

    monkeypatch.setattr("app.services.source_fetcher.build_async_http_client", _fake_build_client)

    result = asyncio.run(fetcher._fetch_clash(source, trust_env=False))

    assert len(result) == 0
    assert seen_kwargs
    assert all(item.get("trust_env") is False for item in seen_kwargs)
    assert os.environ["HTTP_PROXY"] == "http://172.18.0.1:17890"


def test_fetch_clash_uses_best_ua_variant(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="https://example.com/clash.yaml",
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    client = _VariantCaptureClient(
        {
            "ClashforWindows/0.20.39": "proxies: []\n",
            "clash-verge/2.0": (
                "proxies:\n"
                "  - name: n1\n"
                "    server: n1.example.com\n"
                "    port: 443\n"
                "    type: anytls\n"
                "    password: p1\n"
                "    sni: n1.example.com\n"
            ),
            "mihomo/1.19.0": "proxies: []\n",
        }
    )

    monkeypatch.setattr(
        "app.services.source_fetcher.build_async_http_client",
        lambda *_args, **_kwargs: client,
    )

    result = asyncio.run(fetcher.fetch_source(source))
    assert result.ok is True
    assert result.method == "clash"
    assert result.node_count == 1
    assert result.nodes[0].protocol == "anytls"
    assert any(item.request_variant == "ua:clash-verge/2.0" and item.ok for item in result.attempts)


def test_fetch_clash_preserves_explicit_udp_setting(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="https://example.com/clash.yaml",
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    client = _VariantCaptureClient(
        {
            "ClashforWindows/0.20.39": "proxies: []\n",
            "clash-verge/2.0": (
                "proxies:\n"
                "  - name: n1\n"
                "    server: n1.example.com\n"
                "    port: 443\n"
                "    type: ss\n"
                "    cipher: aes-128-gcm\n"
                "    password: p1\n"
                "    udp: false\n"
            ),
            "mihomo/1.19.0": "proxies: []\n",
        }
    )

    monkeypatch.setattr(
        "app.services.source_fetcher.build_async_http_client",
        lambda *_args, **_kwargs: client,
    )

    result = asyncio.run(fetcher.fetch_source(source))
    assert result.ok is True
    assert result.nodes[0].raw["udp"] is False


def test_fetch_clash_preserves_ss_plugin_fields(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="https://example.com/clash.yaml",
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    client = _VariantCaptureClient(
        {
            "ClashforWindows/0.20.39": "proxies: []\n",
            "clash-verge/2.0": (
                "proxies:\n"
                "  - name: n1\n"
                "    server: n1.example.com\n"
                "    port: 443\n"
                "    type: ss\n"
                "    cipher: aes-128-gcm\n"
                "    password: p1\n"
                "    plugin: obfs\n"
                "    plugin-opts:\n"
                "      mode: http\n"
                "      host: plugin.example.com\n"
            ),
            "mihomo/1.19.0": "proxies: []\n",
        }
    )

    monkeypatch.setattr(
        "app.services.source_fetcher.build_async_http_client",
        lambda *_args, **_kwargs: client,
    )

    result = asyncio.run(fetcher.fetch_source(source))
    assert result.ok is True
    assert result.nodes[0].raw["plugin"] == "obfs"
    assert result.nodes[0].raw["plugin-opts"] == {
        "mode": "http",
        "host": "plugin.example.com",
    }


def test_fetch_clash_normalizes_ss_plugin_opts_alias(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="https://example.com/clash.yaml",
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    client = _VariantCaptureClient(
        {
            "ClashforWindows/0.20.39": "proxies: []\n",
            "clash-verge/2.0": (
                "proxies:\n"
                "  - name: n1\n"
                "    server: n1.example.com\n"
                "    port: 443\n"
                "    type: ss\n"
                "    cipher: aes-128-gcm\n"
                "    password: p1\n"
                "    plugin: obfs\n"
                "    plugin_opts:\n"
                "      mode: http\n"
                "      host: plugin.example.com\n"
            ),
            "mihomo/1.19.0": "proxies: []\n",
        }
    )

    monkeypatch.setattr(
        "app.services.source_fetcher.build_async_http_client",
        lambda *_args, **_kwargs: client,
    )

    result = asyncio.run(fetcher.fetch_source(source))
    assert result.ok is True
    assert result.nodes[0].raw["plugin-opts"] == {
        "mode": "http",
        "host": "plugin.example.com",
    }
    assert "plugin_opts" not in result.nodes[0].raw


def test_fetch_shadowrocket_base64_uri_supports_anytls_hy2_tuic(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="",
        shadowrocket_url="https://example.com/sr.conf",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    uri_lines = "\n".join(
        [
            "STATUS=ok",
            "anytls://password1@a.example.com:443?sni=a.example.com#AnyTLS-A",
            "hy2://password2@h2.example.com:8443?sni=h2.example.com#HY2-A",
            "tuic://uuid-1:password3@tuic.example.com:9443?congestion-controller=bbr&udp-relay-mode=native#TUIC-A",
        ]
    )
    encoded = base64.b64encode(uri_lines.encode("utf-8")).decode("ascii")
    client = _CaptureClient(encoded)

    monkeypatch.setattr(
        "app.services.source_fetcher.build_async_http_client",
        lambda *_args, **_kwargs: client,
    )

    result = asyncio.run(fetcher._fetch_shadowrocket(source, trust_env=False))
    protocols = sorted(node.protocol for node in result.nodes)
    assert protocols == ["anytls", "hysteria2", "tuic"]
    assert result.request_variant == "format:base64-uri"
    assert result.parsed_protocol_counts.get("anytls") == 1
    assert result.parsed_protocol_counts.get("hysteria2") == 1
    assert result.parsed_protocol_counts.get("tuic") == 1


def test_fetch_shadowrocket_plain_uri_supports_anytls_hy2_tuic(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="",
        shadowrocket_url="https://example.com/sr.conf",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    plain_text = "\n".join(
        [
            "STATUS=ok",
            "anytls://password1@a.example.com:443?sni=a.example.com#AnyTLS-A",
            "hy2://password2@h2.example.com:8443?sni=h2.example.com#HY2-A",
            "tuic://uuid-1:password3@tuic.example.com:9443?congestion-controller=bbr&udp-relay-mode=native#TUIC-A",
        ]
    )
    client = _CaptureClient(plain_text)

    monkeypatch.setattr(
        "app.services.source_fetcher.build_async_http_client",
        lambda *_args, **_kwargs: client,
    )

    result = asyncio.run(fetcher._fetch_shadowrocket(source, trust_env=False))
    protocols = sorted(node.protocol for node in result.nodes)
    assert protocols == ["anytls", "hysteria2", "tuic"]
    assert result.request_variant == "format:uri-plain"


def test_fetch_clash_falls_back_to_plain_uri(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="https://example.com/clash.yaml",
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    plain_text = "\n".join(
        [
            "STATUS=ok",
            "anytls://password1@a.example.com:443?sni=a.example.com#AnyTLS-A",
            "hy2://password2@h2.example.com:8443?sni=h2.example.com#HY2-A",
        ]
    )
    client = _VariantCaptureClient(
        {
            "ClashforWindows/0.20.39": plain_text,
            "clash-verge/2.0": plain_text,
            "mihomo/1.19.0": plain_text,
        }
    )

    monkeypatch.setattr(
        "app.services.source_fetcher.build_async_http_client",
        lambda *_args, **_kwargs: client,
    )

    result = asyncio.run(fetcher.fetch_source(source))
    assert result.ok is True
    assert result.method == "clash"
    assert result.node_count == 2
    assert len(result.warnings) == 1
    assert result.warnings[0].code == "standard-source-clash-url-format-mismatch"
    assert result.warnings[0].field == "clash_url"
    assert result.warnings[0].actual_variant == "format:uri-plain"
    assert sorted(node.protocol for node in result.nodes) == ["anytls", "hysteria2"]
    assert any(
        item.ok and "|format:uri-plain" in item.request_variant
        for item in result.attempts
    )


def test_fetch_shadowrocket_clash_yaml_adds_semantic_warning(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="",
        shadowrocket_url="https://example.com/sr.conf",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    client = _CaptureClient(
        "proxies:\n"
        "  - name: trojan-a\n"
        "    type: trojan\n"
        "    server: trojan.example.com\n"
        "    port: 443\n"
        "    password: p1\n"
    )

    monkeypatch.setattr(
        "app.services.source_fetcher.build_async_http_client",
        lambda *_args, **_kwargs: client,
    )

    result = asyncio.run(fetcher.fetch_source(source))
    assert result.ok is True
    assert result.method == "shadowrocket"
    assert result.node_count == 1
    assert len(result.warnings) == 1
    assert result.warnings[0].code == "standard-source-shadowrocket-url-format-mismatch"
    assert result.warnings[0].field == "shadowrocket_url"
    assert result.warnings[0].actual_variant == "format:clash-yaml"


def test_fetch_surge_native_ini_has_no_semantic_warning(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="",
        shadowrocket_url="",
        surge_url="https://example.com/surge.conf",
        quality_group=QUALITY_MEDIUM,
    )
    client = _CaptureClient(
        "[Proxy]\n"
        "n1 = trojan, n1.example.com, 443, password=p1\n"
    )

    monkeypatch.setattr(
        "app.services.source_fetcher.build_async_http_client",
        lambda *_args, **_kwargs: client,
    )

    result = asyncio.run(fetcher.fetch_source(source))
    assert result.ok is True
    assert result.method == "surge"
    assert result.node_count == 1
    assert result.warnings == []


def test_parse_surge_line_supports_anytls_hy2_tuic() -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="",
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    anytls = fetcher._node_from_surge_line(
        "n-anytls = anytls, atls.example.com, 443, password=p1, sni=atls.example.com",
        source,
    )
    hy2 = fetcher._node_from_surge_line(
        "n-hy2 = hy2, hy2.example.com, 8443, password=p2, sni=hy2.example.com, obfs=salamander",
        source,
    )
    tuic = fetcher._node_from_surge_line(
        "n-tuic = tuic, tuic.example.com, 9443, uuid=u1, password=p3, congestion-controller=bbr",
        source,
    )
    assert anytls is not None and anytls.protocol == "anytls"
    assert hy2 is not None and hy2.protocol == "hysteria2"
    assert tuic is not None and tuic.protocol == "tuic"
    assert tuic.raw.get("congestion_controller") == "bbr"


def test_parse_tuic_v4_uri_and_surge_line_preserve_token_identity() -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="",
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    uri_node, uri_reason = fetcher._node_from_generic_uri(
        "tuic://token-v4@tuic.example.com:9443?reduce-rtt=1&udp-relay-mode=native#TUIC-V4",
        source,
    )
    assert uri_reason == ""
    assert uri_node is not None
    assert uri_node.protocol == "tuic"
    assert uri_node.raw.get("token") == "token-v4"
    assert uri_node.raw.get("tuic_version") == 4
    assert uri_node.raw.get("reduce_rtt") is True

    surge_node = fetcher._node_from_surge_line(
        "n-tuic-v4 = tuic, tuic.example.com, 9443, token=token-v4, udp-relay-mode=native",
        source,
    )
    assert surge_node is not None
    assert surge_node.raw.get("token") == "token-v4"
    assert surge_node.raw.get("tuic_version") == 4


def test_parse_surge_line_preserves_explicit_udp_setting() -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="",
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    node = fetcher._node_from_surge_line(
        "n-ss = ss, ss.example.com, 443, encrypt-method=aes-128-gcm, password=p1, udp=false",
        source,
    )
    assert node is not None
    assert node.raw.get("udp") is False


def test_fetch_source_attempts_include_diagnostics_without_token_leak(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="https://example.com/sub?token=abc123",
        shadowrocket_url="",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    client = _CaptureClient(
        "proxies:\n"
        "  - name: n1\n"
        "    server: n1.example.com\n"
        "    port: 443\n"
        "    type: unknown-proto\n"
    )
    monkeypatch.setattr(
        "app.services.source_fetcher.build_async_http_client",
        lambda *_args, **_kwargs: client,
    )

    result = asyncio.run(fetcher.fetch_source(source))
    assert result.ok is False
    assert "?token=" not in result.error
    first = result.attempts[0]
    assert first.request_variant.startswith("ua:")
    assert first.skip_reasons
    assert "unsupported protocol" in first.error


def test_fetch_surge_sets_surge_user_agent_header(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="",
        shadowrocket_url="",
        surge_url="https://example.com/surge.conf",
        quality_group=QUALITY_MEDIUM,
    )
    client = _CaptureClient(
        "[Proxy]\n"
        "n1 = trojan, n1.example.com, 443, password=p1\n"
    )

    monkeypatch.setattr(
        "app.services.source_fetcher.build_async_http_client",
        lambda *_args, **_kwargs: client,
    )

    result = asyncio.run(fetcher._fetch_surge(source, trust_env=False))
    assert len(result) == 1
    assert len(client.calls) == 1
    headers = client.calls[0]["headers"]
    assert isinstance(headers, dict)
    assert headers.get("User-Agent") == "Surge iOS/3867 SurgeCore/6010000"


def test_fetch_shadowrocket_sets_shadowrocket_user_agent_header(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())
    source = StandardSource(
        id="s1",
        name="机场A",
        clash_url="",
        shadowrocket_url="https://example.com/sr.conf",
        surge_url="",
        quality_group=QUALITY_MEDIUM,
    )
    client = _CaptureClient(
        "[Proxy]\n"
        "n1 = trojan, n1.example.com, 443, password=p1\n"
    )

    monkeypatch.setattr(
        "app.services.source_fetcher.build_async_http_client",
        lambda *_args, **_kwargs: client,
    )

    result = asyncio.run(fetcher._fetch_shadowrocket(source, trust_env=False))
    assert len(result) == 1
    assert len(client.calls) == 1
    headers = client.calls[0]["headers"]
    assert isinstance(headers, dict)
    assert headers.get("User-Agent") == "Shadowrocket/3488 CFNetwork/3896.200.61 Darwin/27.2.0 iPhone18,1"


# Known configured values: a case-sensitive literal alternation of each value
# as written, decoded once and encoded once, longest first with the marker.


def test_known_secret_near_miss_does_not_backtrack() -> None:
    # A sensitive query value that differs from the error text only at its
    # end. The earlier per-character alternation backtracked without bound.
    run = "a" * 2000
    matcher = known_source_secrets([StandardSource(id="s", name="S", clash_url=f"https://h.example/sub?token={run}+Z")])
    text = f"clash: upstream said {run}+Y"
    best = float("inf")
    for _ in range(3):
        started = perf_counter()
        sanitize_source_error(text, matcher)
        best = min(best, perf_counter() - started)
    assert matcher.search(text) is None
    assert best < 0.05


def test_known_secret_spellings_as_written_decoded_and_encoded_once() -> None:
    url = "https://user0:s%c3%a9cret%2142@h.example/sub"
    assert extract_source_secrets(url) == frozenset({"user0", "s%c3%a9cret%2142", "sécret!42", "s%C3%A9cret%2142"})
    matcher = known_source_secrets([StandardSource(id="s", name="S", clash_url=url)])
    for spelled in ("s%c3%a9cret%2142", "sécret!42", "s%C3%A9cret%2142"):
        assert sanitize_source_error(f"clash: login {spelled} refused", matcher) == "clash: login <redacted> refused"
    # Case-sensitive: other spellings are left to the generic heuristics.
    assert matcher.search("SÉCRET!42") is None


def test_known_secret_query_values_spell_plus_and_space_both_ways() -> None:
    url = "https://h.example/sub?token=orchard+lantern42"
    assert extract_source_secrets(url) == frozenset({"orchard+lantern42", "orchard lantern42", "orchard%20lantern42"})
    matcher = known_source_secrets([StandardSource(id="s", name="S", clash_url=url)])
    for spelled in ("orchard+lantern42", "orchard lantern42", "orchard%20lantern42"):
        assert sanitize_source_error(f"clash: HTTP 403 {spelled}", matcher) == "clash: HTTP 403 <redacted>"


def test_known_secret_host_labels_also_match_lowercased() -> None:
    url = "https://Ab12Cd34Ef56.example/sub"
    assert extract_source_secrets(url) == frozenset({"Ab12Cd34Ef56", "ab12cd34ef56"})
    matcher = known_source_secrets([StandardSource(id="s", name="S", clash_url=url)])
    for host in ("Ab12Cd34Ef56", "ab12cd34ef56"):  # httpx prints the host lowercased
        public = sanitize_source_error(f"clash: ConnectError: cannot reach {host}.example", matcher)
        assert public == "clash: ConnectError: cannot reach <redacted>.example"


def test_known_secret_marker_prefix_or_substring_leaves_nothing_behind() -> None:
    url = "https://dacted:x@h.example/x?token=%3Credacted%3Etail"
    assert extract_source_secrets(url) == frozenset({"dacted", "<redacted>tail", "%3Credacted%3Etail"})
    matcher = known_source_secrets([StandardSource(id="s", name="S", clash_url=url)])
    for spelled in ("<redacted>tail", "%3Credacted%3Etail"):
        assert sanitize_source_error(f"clash: {spelled}", matcher) == "clash: <redacted>"
    # A shorter value cannot split an existing marker.
    assert sanitize_source_error("clash: <redacted> dacted", matcher) == "clash: <redacted> <redacted>"
    assert sanitize_source_error("clash: <redacted>", matcher) == "clash: <redacted>"


def test_public_status_redacts_text_fields_only() -> None:
    url = "http://proxy:direct@h.example/sub"
    assert extract_source_secrets(url) == frozenset({"proxy", "direct"})
    matcher = known_source_secrets([StandardSource(id="s", name="S", clash_url=url)])
    attempt = SourcePullAttempt(method="clash", ok=False, node_count=0, error="clash: proxy refused direct login",
                                url=url, network_path="proxy", request_variant="ua:direct",
                                skip_reasons=["direct proxy"])
    public = attempt.to_dict(matcher)
    assert (public["method"], public["network_path"], public["request_variant"]) == ("clash", "proxy", "ua:direct")
    assert public["error"] == "clash: <redacted> refused <redacted> login"
    assert public["skip_reasons"] == ["<redacted> <redacted>"]
    status = {"status": "direct", "pull_network_mode": "direct_then_proxy", "pull_method": "proxy",
              "source_id": "proxy", "phase": "proxy", "error_type": "direct", "refresh_id": "proxy",
              "warnings": [{"code": "proxy", "field": "direct", "message": "proxy down"}],
              "attempts": [public], "last_error": "via proxy"}
    cleaned = public_source_status(status, matcher)
    for key in ("status", "pull_network_mode", "pull_method", "source_id", "phase", "error_type", "refresh_id"):
        assert cleaned[key] == status[key], key
    assert cleaned["warnings"] == [{"code": "proxy", "field": "direct", "message": "<redacted> down"}]
    assert cleaned["last_error"] == "via <redacted>"
    assert cleaned["attempts"][0]["network_path"] == "proxy"


def test_unsupported_protocol_names_get_the_source_matcher_before_the_cut() -> None:
    digits = "1234567890" * 9
    source = StandardSource(
        id="s", name="S", clash_url=f"https://h.example/sub?token={digits}",
        surge_url="https://h.example/s?token=orchardpassword%3Dx%3Blantern",
        shadowrocket_url="https://h.example/r?token=Orchard42lantern",
    )
    fetcher = SourceFetcher(_settings())
    expected = "unsupported protocol <redacted>"
    for protocol in (digits, "orchardpassword=x;lantern", "Orchard42lantern"):
        _node, reason = fetcher._node_from_clash_proxy_with_reason(
            {"name": "p", "server": "192.0.2.1", "port": 443, "type": protocol}, source)
        assert reason == expected, protocol
        assert unsupported_protocol_reason(protocol, known_source_secrets([source])) == expected
    assert fetcher._node_from_generic_uri("Orchard42lantern://192.0.2.1:443", source)[1] == expected
    assert fetcher._node_from_shadowrocket_line_with_reason("Probe = Orchard42lantern, 192.0.2.1, 443", source)[1] == expected
    assert fetcher._node_from_surge_line_with_reason("Probe = Orchard42lantern, 192.0.2.1, 443", source)[1] == expected
    # Without known values the display cut is unchanged.
    assert unsupported_protocol_reason(digits) == "unsupported protocol " + digits[:64] + "…"


def test_failure_reasons_give_each_method_a_stable_code_and_plain_message(monkeypatch) -> None:
    url = "https://private-user:private-pass@sub.example:8443/link/aB3dE5fG7hI9jK1m?foo=query-secret"
    safe_url = "https://sub.example:8443/link/<redacted>"

    def build_client(_settings, *, trust_env):
        def handle(request):
            if request.headers["User-Agent"].startswith("Surge"):
                raise httpx.ReadTimeout("read timed out", request=request)
            return httpx.Response(403 if request.headers["User-Agent"].startswith("mihomo") else 404, request=request)

        return httpx.AsyncClient(transport=httpx.MockTransport(handle), trust_env=False)

    monkeypatch.setattr("app.services.source_fetcher.build_async_http_client", build_client)
    source = StandardSource(id="codes", name="Codes", clash_url=url, surge_url=url)
    result = asyncio.run(SourceFetcher(_settings()).fetch_source(source))
    assert result.ok is False
    # Direct and proxy fail the same way; each distinct failure appears once.
    assert result.failure_reasons() == [
        {"method": "clash", "code": "http_status", "url": safe_url, "message": "HTTP 404"},
        {"method": "clash", "code": "http_status", "url": safe_url, "message": "HTTP 403"},
        {"method": "surge", "code": "timeout", "url": safe_url, "message": "timeout"},
        {"method": "shadowrocket", "code": "url_not_configured", "url": "", "message": "url not configured"},
    ]
    # The summary text keeps its old shape for `last_pull_error` readers.
    assert result.error.startswith("clash: HTTP 404; clash: HTTP 403; surge: timeout (surge, ")


@pytest.mark.parametrize(("exc", "code", "message"), [
    (ValueError("invalid clash yaml"), "invalid_payload", "invalid clash yaml"),
    (ValueError(""), "invalid_payload", "invalid payload"),
    (RuntimeError("network down"), "fetch_failed", "network down"),
    (RuntimeError(""), "fetch_failed", "RuntimeError"),
])
def test_fetch_exceptions_map_to_reason_codes(exc, code, message) -> None:
    assert SourceFetcher._classify_fetch_error(exc) == (code, message)


def test_zero_node_and_manual_failures_have_their_own_codes(monkeypatch) -> None:
    fetcher = SourceFetcher(_settings())

    async def empty(_source, *, trust_env):
        return FetchPayload(nodes=[], skip_reasons=["unsupported protocol foo"])

    monkeypatch.setattr(fetcher, "_fetch_clash", empty)
    result = asyncio.run(fetcher.fetch_source(StandardSource(id="z", name="Z", clash_url="https://example.test/c")))
    assert result.failure_reasons()[0] == {
        "method": "clash", "code": "no_valid_nodes", "url": "https://example.test/c",
        "message": "0 valid nodes parsed; unsupported protocol foo",
    }

    missing = fetcher.parse_manual_nodes(StandardSource(id="m", name="M", ingest_kind="manual_nodes"))
    assert [(item["method"], item["code"]) for item in missing.failure_reasons()] == [("manual_nodes", "manual_nodes_missing")]
    invalid = fetcher.parse_manual_nodes(StandardSource(id="m", name="M", ingest_kind="manual_nodes", manual_nodes_text="nope"))
    assert [(item["method"], item["code"]) for item in invalid.failure_reasons()] == [("manual_nodes", "no_valid_nodes")]


def test_failure_reasons_without_attempts_still_say_why() -> None:
    assert SourcePullResult(ok=True, method="clash").failure_reasons() == []
    assert SourcePullResult(ok=False).failure_reasons() == [
        {"method": "", "code": "all_methods_failed", "url": "", "message": "all methods failed"},
    ]
    assert SourcePullResult(ok=False, error="clash: boom").failure_reasons() == [
        {"method": "", "code": "unclassified", "url": "", "message": "clash: boom"},
    ]


def test_public_pull_reasons_only_send_known_codes() -> None:
    from app.services.source_diagnostics import PULL_REASON_CODES, public_pull_reasons

    reasons = public_pull_reasons([{"method": "clash", "code": "brand_new", "message": "x"}, {"code": "timeout"}, "junk"])
    assert [item["code"] for item in reasons] == ["unclassified", "timeout"]
    assert {"timeout", "http_status", "unclassified"} <= PULL_REASON_CODES
