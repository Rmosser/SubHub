from __future__ import annotations

import json
import re
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from app.config import Settings
from app.models import CollectedOutbound, CollectedRule, RelayAccount
from app.services.collectors.gorelay_parser import parse_detail_text_to_rules
from app.services.device_grouper import extract_device_group
from app.services.normalize import normalize_entry_name
from app.services.http_client import build_async_http_client

_DEFAULT_LOGIN_PATH = "/api/v1/auth/login"
_DEFAULT_FORWARD_PATH = "/api/v1/user/forward"
_DEFAULT_DEVICEGROUP_PATH = "/api/v1/user/devicegroup"
_DEFAULT_USERINFO_PATH = "/api/v1/user/info"
_DEFAULT_AUTH_MODE = "raw"
_AUTH_MODES = {"raw", "bearer", "auto"}

_CONTACT_RE = re.compile(r"(需联系客服申请)(?!\s*[:：]\s*\d{2,5})")
_PORT_HINT_RE = re.compile(r"(?:端口|port)\s*[:：]\s*(\d{2,5})", re.I)
_ID_SUFFIX_RE = re.compile(r"#(\d+)")
_PORT_RANGE_RE = re.compile(r"(\d{2,5})")
_BRACKETED_HOST_PORT_RE = re.compile(r"^\[(.+)\]:(\d{2,5})$")


def _safe_int(raw: Any, default: int = 0) -> int:
    try:
        value = int(str(raw).strip())
    except Exception:
        return default
    return value


def _safe_port(raw: Any) -> int:
    value = _safe_int(raw)
    return value if 1 <= value <= 65535 else 0


def _join_url(base_url: str, path_or_url: str) -> str:
    text = str(path_or_url or "").strip()
    if text.startswith("http://") or text.startswith("https://"):
        return text
    base = base_url.rstrip("/")
    path = text or "/"
    return f"{base}/{path.lstrip('/')}"


def _as_items(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        for key in ("list", "items", "rows", "records", "data"):
            nested = raw.get(key)
            if isinstance(nested, list):
                return [dict(item) for item in nested if isinstance(item, dict)]
    return []


def _parse_host_port(raw: Any) -> tuple[str, int]:
    text = str(raw or "").strip()
    if not text:
        return "", 0
    bracketed = _BRACKETED_HOST_PORT_RE.match(text)
    if bracketed:
        host = str(bracketed.group(1) or "").strip()
        port = _safe_port(bracketed.group(2))
        return host, port
    host, sep, port_text = text.rpartition(":")
    if not sep:
        return "", 0
    clean_host = host.strip()
    port = _safe_port(port_text)
    if not clean_host or port <= 0:
        return "", 0
    return clean_host, port


class GoRelayApiCollector:
    def __init__(
        self,
        settings: Settings,
        client_factory: Callable[..., httpx.AsyncClient] | None = None,
    ) -> None:
        self.settings = settings
        self._client_factory = client_factory or self._default_client_factory

    def _default_client_factory(self, **kwargs: Any) -> httpx.AsyncClient:
        return build_async_http_client(self.settings, **kwargs)

    @staticmethod
    def _selector_config(account: RelayAccount) -> dict[str, Any]:
        try:
            raw = json.loads(account.selectors_json or "{}")
        except json.JSONDecodeError:
            return {}
        return raw if isinstance(raw, dict) else {}

    @staticmethod
    def _base_url(account: RelayAccount, selectors: dict[str, Any]) -> str:
        for candidate in (
            str(selectors.get("api_base") or "").strip(),
            str(selectors.get("api_base_url") or "").strip(),
            str(account.login_url or "").strip(),
            str(account.rules_url or "").strip(),
        ):
            if not candidate:
                continue
            parsed = urlparse(candidate)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"
        raise RuntimeError("unable to infer GoRelay API base URL")

    @staticmethod
    def _path(selectors: dict[str, Any], key: str, legacy_key: str, default: str) -> str:
        return str(selectors.get(key) or selectors.get(legacy_key) or default)

    @staticmethod
    def _format_template(raw: Any, mapping: dict[str, str]) -> Any:
        if isinstance(raw, dict):
            return {
                str(key): GoRelayApiCollector._format_template(value, mapping)
                for key, value in raw.items()
            }
        if isinstance(raw, list):
            return [GoRelayApiCollector._format_template(value, mapping) for value in raw]
        if isinstance(raw, str):
            text = raw
            for key, value in mapping.items():
                text = text.replace("{" + key + "}", value)
            return text
        return raw

    @staticmethod
    def _page_size(selectors: dict[str, Any]) -> int:
        value = _safe_int(selectors.get("page_size"), 200)
        return value if value > 0 else 200

    @staticmethod
    def _auth_mode(selectors: dict[str, Any]) -> tuple[str, bool]:
        raw = selectors.get("api_auth_mode")
        explicit = raw is not None
        mode = str(raw or _DEFAULT_AUTH_MODE).strip().lower()
        if mode not in _AUTH_MODES:
            return _DEFAULT_AUTH_MODE, explicit
        return mode, explicit

    @staticmethod
    def _auth_candidates(token: str, auth_mode: str) -> list[tuple[str, dict[str, str]]]:
        raw_headers = {"Authorization": token, "token": token}
        bearer_headers = {"Authorization": f"Bearer {token}", "token": token}
        if auth_mode == "bearer":
            return [("bearer", bearer_headers)]
        if auth_mode == "auto":
            return [("raw", raw_headers), ("bearer", bearer_headers)]
        return [("raw", raw_headers)]

    @staticmethod
    def _merge_headers(
        auth_headers: dict[str, str],
        custom_headers: dict[str, Any] | None,
        *,
        allow_auth_override: bool,
    ) -> dict[str, str]:
        merged = dict(auth_headers)
        if not isinstance(custom_headers, dict):
            return merged
        for key, value in custom_headers.items():
            key_text = str(key)
            if not allow_auth_override and key_text.lower() in {"authorization", "token"}:
                continue
            merged[key_text] = str(value)
        return merged

    @staticmethod
    def _extract_port_from_range(raw: Any) -> int:
        if isinstance(raw, int):
            return _safe_port(raw)
        text = str(raw or "").strip()
        if not text:
            return 0
        match = _PORT_RANGE_RE.search(text)
        if not match:
            return 0
        return _safe_port(match.group(1))

    @staticmethod
    def _extract_rules_page(payload: Any) -> tuple[list[dict[str, Any]], int]:
        if not isinstance(payload, dict):
            return [], 0
        data = payload.get("data")
        if isinstance(data, list):
            records = _as_items(data)
            return records, len(records)
        if isinstance(data, dict):
            records = _as_items(data)
            total = 0
            for key in ("count", "total", "total_count"):
                total = _safe_int(data.get(key), 0)
                if total > 0:
                    break
            return records, total
        records = _as_items(payload)
        return records, len(records)

    def _build_login_payload(self, account: RelayAccount, selectors: dict[str, Any]) -> dict[str, Any]:
        placeholders = {
            "username": account.gorelay_username,
            "password": account.gorelay_password,
        }
        payload_template = selectors.get("api_login_payload")
        if isinstance(payload_template, dict):
            formatted = self._format_template(payload_template, placeholders)
            return dict(formatted)

        try:
            account_template = json.loads(account.selectors_json or "{}")
            login_payload = account_template.get("api_login_payload")
            if isinstance(login_payload, dict):
                formatted = self._format_template(login_payload, placeholders)
                return dict(formatted)
        except (json.JSONDecodeError, AttributeError):
            pass

        return {
            "username": account.gorelay_username,
            "password": account.gorelay_password,
        }

    @staticmethod
    def _to_text(raw: Any) -> str:
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw.strip()
        if isinstance(raw, list):
            lines = []
            for item in raw:
                if item is None:
                    continue
                lines.append(str(item).strip())
            return "\n".join(line for line in lines if line)
        return str(raw).strip()

    @staticmethod
    def _prepare_detail_text(connect_host_text: str, port: int) -> str:
        text = connect_host_text.strip()
        if not text:
            return f"端口: {port}" if port else ""

        patched = text
        if port > 0:
            patched = _CONTACT_RE.sub(rf"\1: {port}", patched)
            if not _PORT_HINT_RE.search(patched):
                patched = f"端口: {port}\n{patched}"
        return patched

    @staticmethod
    def _response_error_message(response: Any) -> str:
        status_code = int(getattr(response, "status_code", 0) or 0)
        message = ""
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            for key in ("msg", "message", "error", "detail"):
                value = str(payload.get(key) or "").strip()
                if value:
                    message = value
                    break
        if not message:
            text = str(getattr(response, "text", "") or "").strip()
            if text:
                message = text[:200]
        if message:
            return f"HTTP {status_code}: {message}"
        return f"HTTP {status_code}"

    async def _login(
        self,
        client: httpx.AsyncClient,
        *,
        login_url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> str:
        response = await client.post(
            login_url,
            json=payload,
            headers=headers,
            timeout=self.settings.request_timeout_seconds,
        )
        if int(getattr(response, "status_code", 0) or 0) >= 400:
            raise RuntimeError(
                f"GoRelay login failed: {self._response_error_message(response)}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("invalid login payload")
        token = payload.get("data")
        if not isinstance(token, str) or not token.strip():
            raise RuntimeError("login response missing token string in data")
        return token.strip()

    async def _fetch_device_groups(
        self,
        client: httpx.AsyncClient,
        *,
        url: str,
        headers: dict[str, str],
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        response = await client.get(
            url,
            headers=headers,
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else payload
        groups = _as_items(data)
        if not groups:
            groups = _as_items(payload)

        by_id: dict[str, dict[str, Any]] = {}
        by_name: dict[str, dict[str, Any]] = {}
        for group in groups:
            group_id = str(
                group.get("id")
                or group.get("group_id")
                or group.get("devicegroup_id")
                or ""
            ).strip()
            name = str(
                group.get("name")
                or group.get("group_name")
                or group.get("device_name")
                or ""
            ).strip()
            if not group_id and not name:
                continue
            detail = {
                "id": group_id,
                "name": name,
                "type": str(group.get("type") or "").strip(),
                "ratio": str(group.get("ratio") or "").strip(),
                "fallback_group": str(group.get("fallback_group") or "").strip(),
                "display_protocol": str(group.get("display_protocol") or "").strip(),
                "connect_host": self._to_text(group.get("connect_host")),
                "port": _safe_port(group.get("connect_port") or group.get("port")),
                "port_range": self._to_text(group.get("port_range")),
            }
            if group_id:
                by_id[group_id] = detail
            if name:
                by_name[name] = detail
        return by_id, by_name

    async def _fetch_forwards(
        self,
        client: httpx.AsyncClient,
        *,
        url: str,
        headers: dict[str, str],
        page_size: int,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records: list[dict[str, Any]] = []
        pages = 0
        total = 0
        page = 1
        while True:
            response = await client.get(
                url,
                headers=headers,
                params={"page": page, "size": page_size},
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            page_records, page_total = self._extract_rules_page(payload)
            pages += 1
            if page_total > 0:
                total = page_total
            if not page_records:
                break
            records.extend(page_records)
            if total > 0 and len(records) >= total:
                break
            if total <= 0 and len(page_records) < page_size:
                break
            page += 1
        if total <= 0:
            total = len(records)
        return records, pages, total

    async def _fetch_user_info(
        self,
        client: httpx.AsyncClient,
        *,
        url: str,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        response = await client.get(
            url,
            headers=headers,
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        return dict(data) if isinstance(data, dict) else {}

    @staticmethod
    def _extract_quota(user_info: dict[str, Any]) -> dict[str, Any]:
        used = _safe_int(user_info.get("traffic_used"), 0)
        total = _safe_int(user_info.get("traffic_enable"), 0)
        remaining = max(total - used, 0) if total > 0 else 0
        expire = _safe_int(user_info.get("expire"), 0)
        plan_name = str(user_info.get("plan_name") or "").strip()
        group_name = str(user_info.get("group_name") or "").strip()
        return {
            "plan_name": plan_name,
            "group_name": group_name,
            "traffic_used": used,
            "traffic_enable": total,
            "traffic_remaining": remaining,
            "expire": expire,
        }

    @staticmethod
    def _forward_identity(item: dict[str, Any]) -> tuple[str, str, str]:
        line_name = str(
            item.get("line_name")
            or item.get("name")
            or item.get("forward_name")
            or item.get("title")
            or ""
        ).strip()
        rule_id = str(
            item.get("rule_id")
            or item.get("id")
            or item.get("forward_id")
            or ""
        ).strip()
        if not rule_id and line_name:
            match = _ID_SUFFIX_RE.search(line_name)
            rule_id = match.group(1) if match else ""

        parsed_device_name, _ = extract_device_group(line_name)
        device_name = parsed_device_name
        if device_name == "Unknown":
            device_name = str(item.get("device_name") or "").strip() or "Unknown"
        return line_name, rule_id, device_name

    def _build_rules(
        self,
        account: RelayAccount,
        forwards: list[dict[str, Any]],
        group_by_id: dict[str, dict[str, Any]],
        group_by_name: dict[str, dict[str, Any]],
    ) -> list[CollectedRule]:
        output: list[CollectedRule] = []
        for item in forwards:
            line_name, rule_id, device_name = self._forward_identity(item)
            if not line_name:
                continue

            group_ref = (
                item.get("devicegroup_id")
                or item.get("device_group_id")
                or item.get("group_id")
                or item.get("device_group_in")
                or item.get("device_group")
            )
            group_detail: dict[str, Any] | None = None
            if isinstance(group_ref, dict):
                group_detail = dict(group_ref)
            else:
                group_key = str(group_ref or "").strip()
                group_detail = group_by_id.get(group_key) or group_by_name.get(group_key)

            entry_name = normalize_entry_name(
                str(
                    item.get("entry_name")
                    or item.get("connect_name")
                    or (group_detail or {}).get("name")
                    or line_name
                )
            )
            port = _safe_port(
                item.get("listen_port")
                or item.get("connect_port")
                or item.get("port")
                or item.get("target_port")
                or (group_detail or {}).get("port")
                or self._extract_port_from_range((group_detail or {}).get("port_range"))
            )
            connect_host_raw = item.get("connect_host")
            if connect_host_raw in (None, "") and group_detail:
                connect_host_raw = group_detail.get("connect_host")
            detail_text = self._prepare_detail_text(
                self._to_text(connect_host_raw),
                port,
            )
            if not detail_text:
                continue

            output.extend(
                parse_detail_text_to_rules(
                    account_id=account.id,
                    rule_id=rule_id,
                    line_name=line_name,
                    device_name=device_name,
                    entry_name=entry_name,
                    detail_text=detail_text,
                )
            )
        return output

    def _build_outbounds(
        self,
        account: RelayAccount,
        forwards: list[dict[str, Any]],
        group_by_id: dict[str, dict[str, Any]],
        group_by_name: dict[str, dict[str, Any]],
    ) -> list[CollectedOutbound]:
        output: list[CollectedOutbound] = []
        for item in forwards:
            line_name, rule_id, device_name = self._forward_identity(item)
            if not line_name or not rule_id:
                continue

            outbound_ref = item.get("device_group_out") or item.get("out_device_group")
            outbound_group: dict[str, Any] | None = None
            if isinstance(outbound_ref, dict):
                outbound_group = dict(outbound_ref)
            else:
                outbound_key = str(outbound_ref or "").strip()
                if outbound_key:
                    outbound_group = group_by_id.get(outbound_key) or group_by_name.get(outbound_key)
            if not outbound_group:
                continue

            config_raw = item.get("config")
            config: dict[str, Any] = {}
            if isinstance(config_raw, dict):
                config = dict(config_raw)
            elif isinstance(config_raw, str):
                try:
                    parsed = json.loads(config_raw)
                except json.JSONDecodeError:
                    parsed = {}
                if isinstance(parsed, dict):
                    config = parsed

            targets: list[str] = []
            for dest in list(config.get("dest") or []):
                host, port = _parse_host_port(dest)
                if host and port > 0:
                    targets.append(f"{host}:{port}")
            if not targets:
                continue

            output.append(
                CollectedOutbound(
                    account_id=account.id,
                    rule_id=rule_id,
                    device_name=device_name,
                    line_name=line_name,
                    outbound_group_id=str(outbound_group.get("id") or "").strip(),
                    outbound_group_name=str(outbound_group.get("name") or "").strip(),
                    multiplier=str(outbound_group.get("ratio") or "").strip(),
                    targets=targets,
                    raw={
                        "forward": dict(item),
                        "outbound_group": dict(outbound_group),
                    },
                )
            )
        return output

    async def collect(
        self, account: RelayAccount, selectors: dict[str, Any] | None = None
    ) -> tuple[list[CollectedRule], list[CollectedOutbound], dict[str, Any]]:
        selectors = selectors if isinstance(selectors, dict) else self._selector_config(account)
        base_url = self._base_url(account, selectors)
        page_size = self._page_size(selectors)

        login_url = _join_url(
            base_url,
            self._path(selectors, "api_login_path", "login_path", _DEFAULT_LOGIN_PATH),
        )
        forward_url = _join_url(
            base_url,
            self._path(selectors, "api_forward_path", "forward_path", _DEFAULT_FORWARD_PATH),
        )
        devicegroup_url = _join_url(
            base_url,
            self._path(
                selectors,
                "api_devicegroup_path",
                "devicegroup_path",
                _DEFAULT_DEVICEGROUP_PATH,
            ),
        )
        userinfo_url = _join_url(
            base_url,
            self._path(selectors, "api_userinfo_path", "userinfo_path", _DEFAULT_USERINFO_PATH),
        )
        login_headers_raw = selectors.get("api_login_headers")
        login_headers = (
            {str(k): str(v) for k, v in login_headers_raw.items()}
            if isinstance(login_headers_raw, dict)
            else None
        )
        payload = self._build_login_payload(account, selectors)

        # GoRelay requests should honor the LazyCat egress proxy when configured.
        async with self._client_factory(trust_env=True) as client:
            token = await self._login(
                client,
                login_url=login_url,
                payload=payload,
                headers=login_headers,
            )
            auth_mode, explicit_auth_mode = self._auth_mode(selectors)
            auth_candidates = self._auth_candidates(token, auth_mode)
            custom_headers = (
                selectors.get("api_headers")
                if isinstance(selectors.get("api_headers"), dict)
                else None
            )

            group_by_id: dict[str, dict[str, Any]] = {}
            group_by_name: dict[str, dict[str, Any]] = {}
            forwards: list[dict[str, Any]] = []
            pages = 0
            total = 0
            auth_mode_used = ""
            quota: dict[str, Any] = {}
            userinfo_error: str | None = None

            for index, (candidate_mode, candidate_headers) in enumerate(auth_candidates):
                request_headers = self._merge_headers(
                    candidate_headers,
                    custom_headers,
                    allow_auth_override=explicit_auth_mode,
                )
                try:
                    group_by_id, group_by_name = await self._fetch_device_groups(
                        client,
                        url=devicegroup_url,
                        headers=request_headers,
                    )
                    forwards, pages, total = await self._fetch_forwards(
                        client,
                        url=forward_url,
                        headers=request_headers,
                        page_size=page_size,
                    )
                    try:
                        user_info = await self._fetch_user_info(
                            client,
                            url=userinfo_url,
                            headers=request_headers,
                        )
                        quota = self._extract_quota(user_info)
                    except Exception as exc:
                        # Best-effort. Should not break node collection.
                        userinfo_error = str(exc)
                    auth_mode_used = candidate_mode
                    break
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code if exc.response is not None else 0
                    can_retry_auth = (
                        status_code in {401, 403}
                        and index < len(auth_candidates) - 1
                    )
                    if can_retry_auth:
                        continue
                    raise

            if not auth_mode_used:
                raise RuntimeError("failed to fetch GoRelay data with configured auth mode")

        rules = self._build_rules(account, forwards, group_by_id, group_by_name)
        outbounds = self._build_outbounds(account, forwards, group_by_id, group_by_name)
        status = {
            "collector": "api",
            "auth_mode_requested": auth_mode,
            "auth_mode_used": auth_mode_used,
            "counts": {
                "forward_total": total if total > 0 else len(forwards),
                "forward_records": len(forwards),
                "forward_pages": pages,
                "device_groups": len(group_by_id),
                "rules": len(rules),
                "outbounds": len(outbounds),
            },
            "endpoints": {
                "login": login_url,
                "forward": forward_url,
                "devicegroup": devicegroup_url,
                "userinfo": userinfo_url,
            },
            "quota": quota,
        }
        if userinfo_error:
            status["userinfo_error"] = userinfo_error
        return rules, outbounds, status
