from __future__ import annotations

from collections.abc import Mapping

from fastapi import Request

DEFAULT_LOCALE = "zh-CN"
SUPPORTED_LOCALES = ("zh-CN", "en-US")
LANG_COOKIE_NAME = "subhub_lang"

_ALIASES = {
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh_hans": "zh-CN",
    "zh-hans": "zh-CN",
    "en": "en-US",
    "en-us": "en-US",
}

_TEMPLATE_MESSAGES = {
    "zh-CN": {
        "manage_title_suffix": "管理台",
        "manage_eyebrow": "订阅聚合管理",
        "manage_status_button": "系统状态",
        "manage_refresh_button": "全量刷新",
        "manage_summary_status": "运行状态",
        "manage_summary_status_loading": "初始化中",
        "manage_summary_status_waiting": "等待管理台加载",
        "manage_summary_catalog": "规则目录",
        "manage_summary_sources": "标准源",
        "manage_summary_devices": "设备订阅",
        "workspace_label": "Workspace",
        "workspace_current": "当前工作区",
        "workspace_switch": "切换工作区",
        "workspace_nav": "工作区导航",
        "workspace_catalog": "服务目录",
        "workspace_contracts": "路由契约",
        "workspace_profile": "配置",
        "workspace_llm": "LLM 工作流",
        "workspace_pools": "节点池",
        "workspace_sources": "订阅源",
        "workspace_devices": "设备与编译",
        "workspace_review": "审阅",
        "workspace_advanced": "高级",
        "workspace_catalog_subtitle": "从业务目录进入契约与节点池，而不是反过来用业务分组当路由目标。",
        "close": "关闭",
        "detail": "详情",
        "confirm_action": "确认操作",
        "danger_action": "危险操作",
        "confirm_cancel": "取消",
        "confirm_delete": "确认删除",
        "cancel_action": "取消操作",
        "language_label": "语言",
        "language_zh": "中文",
        "language_en": "English",
        "gorelay_title": "多账号管理",
        "gorelay_heading": "GoRelay 多账号管理",
        "gorelay_actor": "当前登录用户（懒猫）",
        "gorelay_intro": "支持账号独立抓取、域名回填自动传播、设备独立订阅。",
        "gorelay_base_url": "当前订阅基址",
        "gorelay_local_warning": "当前为本机地址，仅本机可更新订阅。请配置 `APP_BASE_URL` 或使用懒猫分配的公网域名。",
        "gorelay_refresh_all": "全量刷新",
        "gorelay_open_new_console": "进入新版 GoRelay 源配置",
        "gorelay_back_home": "返回用户页面",
        "gorelay_refresh_hint": "全量刷新 = 强制拉取规则源 + 抓取所有启用账号 + 重建快照",
        "gorelay_account_form": "新增账号",
        "gorelay_account_form_hint": "常用配置：登录页和规则页已按 GoRelay 官方站预填，可按需改成自定义站点。",
    },
    "en-US": {
        "manage_title_suffix": "Console",
        "manage_eyebrow": "Subscription Aggregation Console",
        "manage_status_button": "System Status",
        "manage_refresh_button": "Refresh All",
        "manage_summary_status": "Runtime",
        "manage_summary_status_loading": "Starting",
        "manage_summary_status_waiting": "Waiting for the console to load",
        "manage_summary_catalog": "Rule Catalog",
        "manage_summary_sources": "Standard Sources",
        "manage_summary_devices": "Device Subscriptions",
        "workspace_label": "Workspace",
        "workspace_current": "Current workspace",
        "workspace_switch": "Switch Workspace",
        "workspace_nav": "Workspace Navigation",
        "workspace_catalog": "Service Catalog",
        "workspace_contracts": "Route Contracts",
        "workspace_profile": "Profile",
        "workspace_llm": "LLM Workflows",
        "workspace_pools": "Node Pools",
        "workspace_sources": "Sources",
        "workspace_devices": "Devices & Build",
        "workspace_review": "Review",
        "workspace_advanced": "Advanced",
        "workspace_catalog_subtitle": "Start from the service catalog and flow into contracts and node pools, not the other way around.",
        "close": "Close",
        "detail": "Detail",
        "confirm_action": "Confirm Action",
        "danger_action": "Danger Zone",
        "confirm_cancel": "Cancel",
        "confirm_delete": "Delete",
        "cancel_action": "Cancel action",
        "language_label": "Language",
        "language_zh": "中文",
        "language_en": "English",
        "gorelay_title": "Multi-account Console",
        "gorelay_heading": "GoRelay Multi-account Console",
        "gorelay_actor": "Current LazyCat user",
        "gorelay_intro": "Supports per-account collection, automatic domain backfill propagation, and per-device subscriptions.",
        "gorelay_base_url": "Current subscription base URL",
        "gorelay_local_warning": "The current base URL is local-only, so subscriptions can only update on this machine. Set `APP_BASE_URL` or use the public LazyCat domain.",
        "gorelay_refresh_all": "Refresh All",
        "gorelay_open_new_console": "Open the new GoRelay source console",
        "gorelay_back_home": "Back to Home",
        "gorelay_refresh_hint": "Refresh All = force rule sync + crawl every enabled account + rebuild snapshots",
        "gorelay_account_form": "Add Account",
        "gorelay_account_form_hint": "Common defaults are prefilled for the official GoRelay login and rules pages. Replace them if you use a custom site.",
    },
}


def normalize_locale(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    candidate = _ALIASES.get(text.lower(), text)
    return candidate if candidate in SUPPORTED_LOCALES else ""


def localized_text(locale: str, zh_cn: str, en_us: str) -> str:
    return en_us if normalize_locale(locale) == "en-US" else zh_cn


def resolve_locale(request: Request | None, preferred: object = None) -> str:
    explicit = normalize_locale(preferred)
    if explicit:
        return explicit
    if request is not None:
        cookie_locale = normalize_locale(request.cookies.get(LANG_COOKIE_NAME, ""))
        if cookie_locale:
            return cookie_locale
        header = str(request.headers.get("accept-language", "") or "")
        for part in header.split(","):
            lang = normalize_locale(part.split(";", 1)[0])
            if lang:
                return lang
    return DEFAULT_LOCALE


def template_messages(locale: str) -> Mapping[str, str]:
    normalized = normalize_locale(locale) or DEFAULT_LOCALE
    return _TEMPLATE_MESSAGES[normalized]


def template_context(request: Request, **extra: object) -> dict[str, object]:
    locale = resolve_locale(request)
    return {
        "locale": locale,
        "supported_locales": list(SUPPORTED_LOCALES),
        "tr": dict(template_messages(locale)),
        **extra,
    }


def localize_base_url_mismatch_reason(reason: str, locale: str) -> str:
    text = str(reason or "").strip()
    if not text or normalize_locale(locale) != "en-US":
        return text
    if "已自动回退为" in text and "APP_BASE_URL=" in text and "与当前请求地址" in text:
        prefix, suffix = text.split("已自动回退为", 1)
        configured, current = prefix.replace("APP_BASE_URL=", "", 1).split("与当前请求地址", 1)
        return (
            f"APP_BASE_URL={configured.strip()} does not match the current request URL "
            f"{current.strip()}; automatically falling back to {suffix.strip()}"
        )
    return text


def localize_gorelay_reason_text(items: list[str], locale: str) -> list[str]:
    if normalize_locale(locale) != "en-US":
        return list(items)
    messages = []
    for item in items:
        text = str(item or "").strip()
        if text == "ok":
            messages.append("ok")
        elif text == "subscription disabled or token missing":
            messages.append("subscription disabled or token missing")
        else:
            messages.append(text)
    return messages


def localize_egress_payload(payload: dict[str, object], locale: str) -> dict[str, object]:
    normalized = normalize_locale(locale)
    if normalized != "en-US":
        return dict(payload)

    translated = dict(payload)
    code = str(translated.get("code") or "")
    summary = str(translated.get("summary") or "")
    meaning = str(translated.get("meaning") or "")
    repair_hint = str(translated.get("repair_hint") or "")
    actions = list(translated.get("actions") or [])

    if code == "not_checked":
        translated["summary"] = "The proxy bridge probe has not run yet."
        translated["meaning"] = "healthz only returns the latest cached egress probe snapshot and does not trigger a live network check."
        translated["repair_hint"] = "Call /diagnostics for a live probe or wait for the next scheduled refresh."
        translated["actions"] = []
    elif code == "missing_proxy_env":
        translated["summary"] = "The GoRelay outbound proxy environment is not configured."
        translated["meaning"] = "The current SubHub process has no HTTP_PROXY/HTTPS_PROXY, so GoRelay collection will not use the box proxy bridge automatically."
        translated["repair_hint"] = "Make sure lzc-manifest.yml injects HTTP_PROXY/HTTPS_PROXY, then redeploy cloud.lazycat.subhub."
        translated["actions"] = [
            "Set HTTP_PROXY/HTTPS_PROXY for the web service to http://172.18.0.1:17890",
            "After redeploying, run env | grep -Ei 'proxy|no_proxy' inside the container to confirm the values are present",
        ]
    elif code == "invalid_proxy_env":
        translated["summary"] = "The GoRelay outbound proxy URL is invalid."
        translated["meaning"] = "The configured proxy URL is not a valid http/https URL, so SubHub cannot connect to the box proxy bridge through it."
        translated["repair_hint"] = "Change HTTP_PROXY/HTTPS_PROXY to a valid URL such as http://172.18.0.1:17890 and redeploy."
        translated["actions"] = [
            "Check HTTP_PROXY/HTTPS_PROXY in lzc-manifest.yml",
            "Make sure the value includes the protocol, host, and port",
        ]
    elif code == "proxy_bridge_unreachable":
        translated["summary"] = "The box proxy bridge endpoint is unreachable."
        translated["meaning"] = "SubHub cannot connect to the container bridge endpoint. This usually means 172.18.0.1:17890 is not listening or the socket is stale."
        translated["repair_hint"] = "Run sudo bash scripts/lazycat-proxy-bridge/check_mihomo_bridge.sh on the box, then restart mihomo-container-proxy.socket if needed."
        translated["actions"] = [
            "Run sudo bash scripts/lazycat-proxy-bridge/check_mihomo_bridge.sh on the box",
            "If the socket is inactive, run sudo systemctl enable --now mihomo-container-proxy.socket && sudo systemctl restart mihomo-container-proxy.socket",
        ]
    elif code == "proxy_bridge_upstream_failed":
        translated["summary"] = "The box proxy bridge is reachable, but the upstream Mihomo probe failed."
        translated["meaning"] = "SubHub can reach the bridge endpoint, but HTTPS traffic through that proxy path still fails. The bridge may be up while the upstream Mihomo/Clash listener is down or moved."
        translated["repair_hint"] = "Check whether Mihomo is still listening on 127.0.0.1:7890. If the port changed, reinstall the bridge script with the new TARGET_PORT."
        translated["actions"] = [
            "Check the Mihomo listener on the box, for example with ss -ltnp | grep 127.0.0.1:7890",
            "If needed, rerun sudo TARGET_PORT=<new-port> bash scripts/lazycat-proxy-bridge/install_mihomo_bridge.sh",
        ]
    elif code == "ok":
        translated["summary"] = "The GoRelay outbound proxy bridge is healthy."
        translated["meaning"] = "SubHub detected proxy environment variables, reached the bridge endpoint, and completed an outbound HTTPS probe through it."
        translated["repair_hint"] = "If GoRelay still fails, investigate upstream account auth or endpoint configuration before suspecting the proxy bridge."
        translated["actions"] = [
            "If GoRelay fetches still fail, inspect the latest source_status or refresh error for HTTP status codes and auth details",
        ]
    else:
        translated["summary"] = localized_text(locale, summary, summary)
        translated["meaning"] = localized_text(locale, meaning, meaning)
        translated["repair_hint"] = localized_text(locale, repair_hint, repair_hint)
        translated["actions"] = actions

    return translated
