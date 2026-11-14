from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlencode

import httpx


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.review_bundle import (  # noqa: E402
    ReviewBundleError,
    build_surge_review_bundle,
    validate_reviewer_base_url,
    write_surge_review_bundle,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a reviewer-ready Surge bundle zip.")
    parser.add_argument("--base-url", required=True, help="Public app base URL, for example https://subhub.example.com")
    parser.add_argument(
        "--fetch-url",
        default="",
        help="Optional runtime fetch URL when the app is only reachable locally, for example http://127.0.0.1:8080",
    )
    parser.add_argument("--token", required=True, help="Device subscription token")
    parser.add_argument("--profile", default="lazycat", choices=["lazycat", "raw"], help="Subscription profile")
    parser.add_argument("--out", required=True, help="Destination zip path")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP request timeout in seconds")
    return parser.parse_args()


def _git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    commit = result.stdout.strip()
    return commit or "unknown"


def _build_source_url(base_url: str, token: str, profile: str) -> str:
    query = urlencode({"profile": profile})
    return f"{base_url}/sub/device/{token}/surge.conf?{query}"


def _build_overlay_url(base_url: str, token: str) -> str:
    return f"{base_url}/sub/device/{token}/surge-mac-overlay.conf"


def _normalize_fetch_url(fetch_url: str, *, fallback: str) -> str:
    candidate = str(fetch_url or "").strip().rstrip("/")
    if not candidate:
        return fallback
    return validate_absolute_http_url(candidate, allow_private_host=True)


def validate_absolute_http_url(url: str, *, allow_private_host: bool) -> str:
    normalized = str(url or "").strip().rstrip("/")
    parsed = httpx.URL(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.host:
        raise ReviewBundleError("fetch URL must be an absolute http(s) URL")
    if not allow_private_host:
        validate_reviewer_base_url(normalized)
    return normalized


def _fetch_text(url: str, timeout: float) -> str:
    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        response = client.get(url)
    if response.status_code != 200:
        snippet = response.text.strip().replace("\n", " ")[:240]
        raise ReviewBundleError(f"GET {url} returned {response.status_code}: {snippet}")
    return response.text


def main() -> int:
    args = _parse_args()
    base_url = validate_reviewer_base_url(args.base_url)
    fetch_base_url = _normalize_fetch_url(args.fetch_url, fallback=base_url)
    source_url = _build_source_url(base_url, args.token, args.profile)
    fetch_url = _build_source_url(fetch_base_url, args.token, args.profile)
    overlay_source_url = _build_overlay_url(base_url, args.token)
    overlay_fetch_url = _build_overlay_url(fetch_base_url, args.token)
    main_conf = _fetch_text(fetch_url, args.timeout)
    overlay_conf = _fetch_text(overlay_fetch_url, args.timeout)
    artifacts = build_surge_review_bundle(
        main_conf,
        source_url=source_url,
        overlay_conf=overlay_conf,
        overlay_source_url=overlay_source_url,
        profile=args.profile,
        git_commit=_git_commit(),
    )
    output_path = write_surge_review_bundle(artifacts, args.out, require_review_ready=True)
    print(f"wrote {output_path}")
    print(f"source_url={source_url}")
    print(f"fetch_url={fetch_url}")
    print(f"overlay_source_url={overlay_source_url}")
    print(f"overlay_fetch_url={overlay_fetch_url}")
    print(f"review_gate=pass")
    print(f"proxies={artifacts.summary.proxy_count}")
    print(f"unique_proxy_group_names={artifacts.summary.unique_proxy_group_name_count}")
    print(f"rules={artifacts.summary.rule_count}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ReviewBundleError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
