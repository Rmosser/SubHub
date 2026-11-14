from __future__ import annotations

import asyncio
import os
import socket
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.services.http_client import _resolve_verify

_DEFAULT_PROXY_PROBE_URL = "https://api.openai.com/v1/models"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class EgressDiagnostics:
    def __init__(self, settings: Settings, *, cache_ttl_seconds: int = 30) -> None:
        self.settings = settings
        self.cache_ttl_seconds = max(int(cache_ttl_seconds), 1)
        self._cache_deadline = 0.0
        self._cache_env_key = ""
        self._cache_payload: dict[str, object] | None = None
        self._lock = asyncio.Lock()

    def _payload_with_requirement(
        self,
        payload: dict[str, object],
        *,
        gorelay_source_count: int,
    ) -> dict[str, object]:
        normalized = dict(payload)
        required = int(gorelay_source_count) > 0
        severity = str(normalized.get("severity") or "info")
        if not required and str(normalized.get("code") or "") == "missing_proxy_env":
            severity = "info"
        elif required and str(normalized.get("code") or "") == "missing_proxy_env":
            severity = "warning"

        normalized["required"] = required
        normalized["gorelay_source_count"] = int(gorelay_source_count)
        normalized["severity"] = severity
        return {"proxy_bridge": normalized}

    def get_cached_status(self, *, gorelay_source_count: int = 0) -> dict[str, object]:
        if self._cache_payload is not None:
            return self._payload_with_requirement(
                self._cache_payload,
                gorelay_source_count=gorelay_source_count,
            )
        return self._payload_with_requirement(
            {
                "configured": bool(self._proxy_url_from_env()),
                "proxy_url": self._proxy_url_from_env(),
                "no_proxy": self._no_proxy_from_env(),
                "cache_ttl_seconds": self.cache_ttl_seconds,
                "checked_at": "",
                "bridge_host": "",
                "bridge_port": 0,
                "tcp_reachable": None,
                "proxy_probe_ok": None,
                "proxy_probe_status_code": None,
                "probe_url": _DEFAULT_PROXY_PROBE_URL,
                "last_error": "",
                "code": "not_checked",
                "severity": "info",
                "summary": "尚未执行代理桥接探测。",
                "meaning": "healthz 仅返回最近一次 egress 探测快照，不会触发实时网络探测。",
                "repair_hint": "如需实时探测，请调用 /diagnostics 或等待下一次主动探测更新缓存。",
                "actions": [],
            },
            gorelay_source_count=gorelay_source_count,
        )

    @staticmethod
    def _proxy_url_from_env() -> str:
        for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            value = str(os.getenv(key, "") or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _no_proxy_from_env() -> str:
        for key in ("NO_PROXY", "no_proxy"):
            value = str(os.getenv(key, "") or "").strip()
            if value:
                return value
        return ""

    async def _tcp_probe(self, host: str, port: int, timeout: float) -> tuple[bool, str]:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True, ""
        except Exception as exc:
            return False, str(exc).strip() or exc.__class__.__name__

    async def _proxy_http_probe(
        self,
        proxy_url: str,
        *,
        timeout: float,
        probe_url: str,
    ) -> tuple[bool, int | None, str]:
        try:
            async with httpx.AsyncClient(
                proxy=proxy_url,
                trust_env=False,
                verify=_resolve_verify(self.settings),
                timeout=timeout,
                headers={"User-Agent": "SubHub-EgressProbe/1.0"},
            ) as client:
                response = await client.get(probe_url)
            status_code = int(response.status_code)
            return (200 <= status_code < 500), status_code, ""
        except Exception as exc:
            return False, None, str(exc).strip() or exc.__class__.__name__

    async def _run_probe(self, proxy_url: str, no_proxy: str) -> dict[str, object]:
        payload: dict[str, object] = {
            "configured": bool(proxy_url),
            "proxy_url": proxy_url,
            "no_proxy": no_proxy,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "checked_at": _utc_now(),
            "bridge_host": "",
            "bridge_port": 0,
            "tcp_reachable": None,
            "proxy_probe_ok": None,
            "proxy_probe_status_code": None,
            "probe_url": _DEFAULT_PROXY_PROBE_URL,
            "last_error": "",
            "code": "",
            "severity": "info",
            "summary": "",
            "meaning": "",
            "repair_hint": "",
            "actions": [],
        }
        if not proxy_url:
            payload.update(
                {
                    "code": "missing_proxy_env",
                    "summary": "未配置 GoRelay 出站代理环境。",
                    "meaning": "SubHub 当前进程没有 HTTP_PROXY/HTTPS_PROXY，GoRelay 采集不会自动走盒子代理入口。",
                    "repair_hint": "确认 lzc-manifest.yml 已注入 HTTP_PROXY/HTTPS_PROXY，并重新部署 cloud.lazycat.subhub。",
                    "actions": [
                        "在 web 服务环境变量中配置 HTTP_PROXY/HTTPS_PROXY 指向 http://172.18.0.1:17890",
                        "重新部署后进入容器执行 env | grep -Ei 'proxy|no_proxy' 确认生效",
                    ],
                }
            )
            return payload

        parsed = urlsplit(proxy_url)
        host = str(parsed.hostname or "").strip()
        if parsed.scheme not in {"http", "https"} or not host:
            payload.update(
                {
                    "code": "invalid_proxy_env",
                    "severity": "error",
                    "summary": "GoRelay 出站代理配置格式无效。",
                    "meaning": f"当前代理地址 {proxy_url!r} 不是合法的 http/https URL，SubHub 无法用它连接盒子桥接代理。",
                    "repair_hint": "把 HTTP_PROXY/HTTPS_PROXY 修正为类似 http://172.18.0.1:17890 的地址后重新部署。",
                    "actions": [
                        "检查 lzc-manifest.yml 中的 HTTP_PROXY/HTTPS_PROXY",
                        "确认地址包含协议、主机和端口",
                    ],
                }
            )
            return payload

        port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
        payload["bridge_host"] = host
        payload["bridge_port"] = port
        timeout = float(min(max(self.settings.request_timeout_seconds, 1), 5))

        tcp_ok, tcp_error = await self._tcp_probe(host, port, timeout)
        payload["tcp_reachable"] = tcp_ok
        if not tcp_ok:
            payload.update(
                {
                    "code": "proxy_bridge_unreachable",
                    "severity": "warning",
                    "last_error": tcp_error,
                    "summary": "盒子代理桥接入口不可达。",
                    "meaning": f"SubHub 无法从容器内连接 {host}:{port}，这通常表示 172.18.0.1:17890 没监听，或 socket 虽存在但已失效。",
                    "repair_hint": "先在盒子上运行 sudo bash scripts/lazycat-proxy-bridge/check_mihomo_bridge.sh，再按提示重启 mihomo-container-proxy.socket。",
                    "actions": [
                        "盒子上执行 sudo bash scripts/lazycat-proxy-bridge/check_mihomo_bridge.sh",
                        "若 socket 不活跃，执行 sudo systemctl enable --now mihomo-container-proxy.socket && sudo systemctl restart mihomo-container-proxy.socket",
                    ],
                }
            )
            return payload

        probe_ok, probe_status_code, probe_error = await self._proxy_http_probe(
            proxy_url,
            timeout=timeout,
            probe_url=_DEFAULT_PROXY_PROBE_URL,
        )
        payload["proxy_probe_ok"] = probe_ok
        payload["proxy_probe_status_code"] = probe_status_code
        if not probe_ok:
            payload.update(
                {
                    "code": "proxy_bridge_upstream_failed",
                    "severity": "warning",
                    "last_error": probe_error,
                    "summary": "盒子代理桥接可连接，但上游 Mihomo 代理探测失败。",
                    "meaning": (
                        f"SubHub 已能连到 {host}:{port}，但通过该入口发出的 HTTPS 代理探测没有成功，"
                        "这通常表示桥接 socket 还在，而 Mihomo/Clash MiHome 上游代理已掉线或目标端口变了。"
                    ),
                    "repair_hint": "检查 Mihomo 本地监听是否仍在 127.0.0.1:7890；若端口变更，重新安装桥接脚本并覆盖 TARGET_PORT。",
                    "actions": [
                        "盒子上检查 Mihomo 本地监听，例如 ss -ltnp | grep 127.0.0.1:7890",
                        "必要时重新执行 sudo TARGET_PORT=<新端口> bash scripts/lazycat-proxy-bridge/install_mihomo_bridge.sh",
                    ],
                }
            )
            return payload

        payload.update(
            {
                "code": "ok",
                "severity": "info",
                "summary": "GoRelay 出站代理桥接正常。",
                "meaning": f"SubHub 已检测到代理环境变量，且 {host}:{port} 可连通并能完成外部 HTTPS 代理探测。",
                "repair_hint": "如 GoRelay 仍失败，优先检查上游账号鉴权或接口配置，而不是盒子代理桥接。",
                "actions": [
                    "若 GoRelay 拉取仍失败，查看最近一次 source_status 或刷新错误中的 HTTP 状态码与鉴权信息",
                ],
            }
        )
        return payload

    async def get_status(self, *, gorelay_source_count: int = 0, force: bool = False) -> dict[str, object]:
        proxy_url = self._proxy_url_from_env()
        no_proxy = self._no_proxy_from_env()
        env_key = f"{proxy_url}\n{no_proxy}"
        now = time.monotonic()

        if (
            not force
            and self._cache_payload is not None
            and env_key == self._cache_env_key
            and now < self._cache_deadline
        ):
            payload = dict(self._cache_payload)
        else:
            async with self._lock:
                now = time.monotonic()
                if (
                    not force
                    and self._cache_payload is not None
                    and env_key == self._cache_env_key
                    and now < self._cache_deadline
                ):
                    payload = dict(self._cache_payload)
                else:
                    payload = await self._run_probe(proxy_url, no_proxy)
                    self._cache_payload = dict(payload)
                    self._cache_env_key = env_key
                    self._cache_deadline = now + self.cache_ttl_seconds

        return self._payload_with_requirement(payload, gorelay_source_count=gorelay_source_count)
