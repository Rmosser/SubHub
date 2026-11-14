from __future__ import annotations

import asyncio
import ipaddress
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

import yaml

from app.config import Settings
from app.models import (
    BUSINESS_GROUP_MODE_STANDARD,
    CONTRACT_AD_BLOCK,
    CONTRACT_DIRECT,
    QUALITY_GROUPS,
    RULE_CATEGORY_TYPE_AUTO,
    RULE_CATEGORY_TYPE_MANUAL,
    RULE_DIRECTNESS_CHOICES,
    RULE_DIRECTNESS_DIRECT,
    RULE_DIRECTNESS_PROXY,
    RULE_DIRECTNESS_REVIEW_STATUS_APPLIED,
    RULE_DIRECTNESS_REVIEW_STATUS_DISMISSED,
    RULE_DIRECTNESS_REVIEW_STATUS_PENDING,
    RULE_LOCK_SOURCE_MANUAL,
    RULE_LOCK_SOURCE_SYSTEM,
    RuleCategory,
    RuleCategoryDirectnessReview,
    ROUTE_ACTION_PROXY,
    ROUTE_REJECT_ACTION,
    normalize_route_action,
    ServiceCatalogEntry,
    contract_display_name,
    contract_description,
    contract_legacy_group,
    effective_contract_id,
    normalize_contract_id,
    resolve_contract_id,
)
from app.services.http_client import build_async_http_client
from app.storage.base import Repo

_RULE_TYPES = {
    "DOMAIN",
    "DOMAIN-SUFFIX",
    "DOMAIN-KEYWORD",
    "IP-CIDR",
    "IP-CIDR6",
    "SRC-IP-CIDR",
    "GEOIP",
    "GEOSITE",
    "DST-PORT",
    "SRC-PORT",
    "PROCESS-NAME",
    "PROCESS-PATH",
    "USER-AGENT",
}
_CIDR_RULE_TYPES = {"IP-CIDR", "IP-CIDR6", "SRC-IP-CIDR"}
_logger = logging.getLogger("app.rule_catalog")

CATEGORY_TARGETS: set[str] = set(QUALITY_GROUPS)
EXPLICIT_TARGETS: set[str] = {"DIRECT", "REJECT"}

GEOSITE_CN_BASE_URL = "https://raw.githubusercontent.com/v2fly/domain-list-community/master/data"
GEOSITE_CN_ENTRY = "cn"
GEOIP_CN_URL = "https://raw.githubusercontent.com/Loyalsoldier/geoip/release/text/cn.txt"

CN_MATCH_MIN_HIT_RATIO = 0.5
CN_MATCH_MIN_HITS = 3

REFRESH_MODES = {"incremental", "full"}
RUNTIME_KEY_TREE_ETAG = "rule_catalog.tree.etag"
RUNTIME_KEY_RULE_CACHE_HOURS = "refresh_policy.rule_catalog_cache_hours"
RUNTIME_KEY_CN_CACHE_HOURS = "refresh_policy.cn_cache_hours"
RUNTIME_KEY_LLM_EXPORT_RULES_PREFERENCES = "llm_export.rules_preferences"
RUNTIME_KEY_LLM_EXPORT_PINS_PREFERENCES = "llm_export.pins_preferences"
RUNTIME_KEY_LLM_EXPORT_DIRECTNESS_PREFERENCES = "llm_export.directness_preferences"
DEFAULT_CN_CACHE_HOURS = 24

DEFAULT_RULES_PREFERENCES = "\n".join(
    [
        "如果这里的指令与上方系统固定说明冲突，以这里为准。",
        "优先沿用已有分配逻辑，避免无依据地大范围重分配。",
        "- 优先依据当前可选目标组的名称、描述和已有分配样本做判断。",
        "- 当分类语义不足以支持重分配时，优先保持现状，而不是猜测一个新方向。",
        "- 如果多个目标组都说得通，优先选择描述更明确、成本更低、覆盖面更大的那一个。",
    ]
)

DEFAULT_PINS_PREFERENCES = "\n".join(
    [
        "按用户查找习惯组织置顶分组，优先稳定、易懂、少歧义。",
        "- 可优先复用常见分组名：AI 服务、流媒体、社交网络、开发工具、游戏、金融支付、通信工具、搜索引擎、购物、新闻资讯、云服务、教育学术、音乐、其他。",
        "- 同类服务尽量归到同一置顶分组，避免同义拆分造成重复查找。",
        "- 分组名保持简洁，优先使用用户一眼能理解的中文名称。",
        "- 如果某个分类价值不高、使用频率低或难以归类，可以省略，不必强行置顶。",
    ]
)

DEFAULT_DIRECTNESS_PREFERENCES = "\n".join(
    [
        "只在高度确定是中国大陆直连场景时建议 DIRECT，宁可保守也不要误判。",
        "- 仅中国大陆本地服务、政务/民生平台、本地银行/支付、国内视频音乐优先建议 DIRECT。",
        "- 国际化服务、全球 SaaS、跨境平台、云服务、开发工具、CDN/API 平台默认建议 PROXY。",
        "- 名称语义不充分或无法判断时，一律建议 PROXY。",
        "- 输出仅允许 DIRECT 或 PROXY，不要使用其他词。",
    ]
)


def _normalize_preferences_text(value: object, *, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.split("\n")]
    compact = "\n".join(lines).strip()
    return compact or fallback


def _append_markdown_block(lines: list[str], title: str, body: str) -> None:
    lines.append(title)
    lines.append("")
    content = str(body or "").strip()
    if content:
        lines.extend(content.splitlines())
    else:
        lines.append("（无）")
    lines.append("")


@dataclass(frozen=True)
class _CatalogEntry:
    category: str
    yaml_path: str = ""
    yaml_sha: str = ""
    list_path: str = ""
    list_sha: str = ""

    @property
    def has_yaml(self) -> bool:
        return bool(self.yaml_path)

    @property
    def has_list(self) -> bool:
        return bool(self.list_path)

    def capability(self) -> dict[str, bool]:
        return {"yaml": self.has_yaml, "list": self.has_list}

    def preferred(self) -> tuple[str, str, str]:
        if self.has_yaml:
            return "yaml", self.yaml_path, self.yaml_sha
        if self.has_list:
            return "list", self.list_path, self.list_sha
        return "", "", ""

    def source_meta(self, rule_source: str) -> tuple[str, str]:
        if rule_source == "yaml":
            return self.yaml_sha, self.yaml_path
        if rule_source == "list":
            return self.list_sha, self.list_path
        return "", ""


@dataclass(frozen=True)
class _RuleSyncResult:
    category: RuleCategory
    downloaded: bool = False
    reused: bool = False
    failed: bool = False


@dataclass(frozen=True)
class _CnJudge:
    domain_suffixes: frozenset[str]
    domain_exacts: frozenset[str]
    domain_keywords: frozenset[str]
    geoip_v4: tuple[ipaddress.IPv4Network, ...]
    geoip_v6: tuple[ipaddress.IPv6Network, ...]

    @staticmethod
    def from_payload(payload: dict[str, object]) -> _CnJudge | None:
        try:
            suffixes = {
                _normalize_domain(str(item))
                for item in (payload.get("domain_suffixes") or [])
                if _normalize_domain(str(item))
            }
            exacts = {
                _normalize_domain(str(item))
                for item in (payload.get("domain_exacts") or [])
                if _normalize_domain(str(item))
            }
            keywords = {
                str(item).strip().lower()
                for item in (payload.get("domain_keywords") or [])
                if str(item).strip()
            }
            v4: list[ipaddress.IPv4Network] = []
            for item in (payload.get("geoip_v4") or []):
                network = ipaddress.ip_network(str(item), strict=False)
                if isinstance(network, ipaddress.IPv4Network):
                    v4.append(network)
            v6: list[ipaddress.IPv6Network] = []
            for item in (payload.get("geoip_v6") or []):
                network = ipaddress.ip_network(str(item), strict=False)
                if isinstance(network, ipaddress.IPv6Network):
                    v6.append(network)
        except Exception:
            return None

        return _CnJudge(
            domain_suffixes=frozenset(suffixes),
            domain_exacts=frozenset(exacts),
            domain_keywords=frozenset(keywords),
            geoip_v4=tuple(v4),
            geoip_v6=tuple(v6),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "domain_suffixes": sorted(self.domain_suffixes),
            "domain_exacts": sorted(self.domain_exacts),
            "domain_keywords": sorted(self.domain_keywords),
            "geoip_v4": [str(item) for item in self.geoip_v4],
            "geoip_v6": [str(item) for item in self.geoip_v6],
        }

    def is_cn_category(self, rules: list[str]) -> bool:
        total = len(rules or [])
        if total <= 0:
            return False

        cn_hits = 0
        explicit_non_cn = 0
        for line in rules:
            matched = self.match_rule(line)
            if matched is None:
                continue
            if matched:
                cn_hits += 1
                continue
            explicit_non_cn += 1

        if explicit_non_cn > 0:
            return False
        if cn_hits < CN_MATCH_MIN_HITS:
            return False
        if (cn_hits / total) < CN_MATCH_MIN_HIT_RATIO:
            return False
        return True

    def match_rule(self, line: str) -> bool | None:
        parts = [item.strip() for item in str(line or "").split(",")]
        if len(parts) < 2:
            return None

        rule_type = parts[0].upper()
        value = parts[1].strip()
        if not value:
            return None

        if rule_type in {"DOMAIN", "DOMAIN-SUFFIX"}:
            return True if self._is_cn_domain(value) else None
        if rule_type == "DOMAIN-KEYWORD":
            return True if value.lower() in self.domain_keywords else None
        if rule_type == "GEOIP":
            return value.upper() == "CN"
        if rule_type == "GEOSITE":
            normalized = value.lower()
            return normalized in {"cn", "geolocation-cn"}
        if rule_type in {"IP-CIDR", "IP-CIDR6", "SRC-IP-CIDR"}:
            return self._is_cn_cidr(value)
        return None

    def _is_cn_domain(self, value: str) -> bool:
        domain = _normalize_domain(value)
        if not domain:
            return False
        if domain in self.domain_exacts or domain in self.domain_suffixes:
            return True

        current = domain
        while "." in current:
            current = current.split(".", 1)[1]
            if current in self.domain_suffixes:
                return True
        return False

    def _is_cn_cidr(self, value: str) -> bool:
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError:
            return False

        candidates = self.geoip_v4 if network.version == 4 else self.geoip_v6
        for cn_network in candidates:
            if network.subnet_of(cn_network):
                return True
        return False


def _normalize_domain(raw: str) -> str:
    domain = str(raw or "").strip().lower().strip(".")
    if domain.startswith("*.") or domain.startswith("+."):
        domain = domain[2:]
    return domain


def _parse_utc(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


class RuleCatalog:
    def __init__(self, settings: Settings, repo: Repo) -> None:
        self.settings = settings
        self.repo = repo
        self._cn_judge: _CnJudge | None = None
        self._cn_judge_loaded_at: datetime | None = None
        self._cn_judge_lock = asyncio.Lock()
        self._progress_callback: Callable[[dict[str, object]], None] | None = None

    def set_progress_callback(
        self,
        callback: Callable[[dict[str, object]], None] | None,
    ) -> None:
        """Publish completed category work to an owning hub refresh."""
        self._progress_callback = callback

    def _report_progress(self, details: dict[str, object]) -> None:
        callback = self._progress_callback
        if callback is not None:
            try:
                callback(dict(details))
            except Exception:
                # Progress is observability only; a monitor failure must not
                # turn a successful category refresh into an error.
                _logger.exception("rule catalog progress callback failed")

    def get_refresh_policy(self) -> dict[str, int]:
        return {
            "rule_catalog_cache_hours": self._get_rule_catalog_cache_hours(),
            "cn_cache_hours": self._get_cn_cache_hours(),
        }

    def update_refresh_policy(self, *, rule_catalog_cache_hours: int, cn_cache_hours: int) -> dict[str, int]:
        self.repo.set_runtime_setting(RUNTIME_KEY_RULE_CACHE_HOURS, int(rule_catalog_cache_hours))
        self.repo.set_runtime_setting(RUNTIME_KEY_CN_CACHE_HOURS, int(cn_cache_hours))
        return self.get_refresh_policy()

    def _resolve_hours_setting(self, key: str, fallback: int) -> int:
        value = self.repo.get_runtime_setting(key)
        try:
            hours = int(value)
            if 1 <= hours <= 168:
                return hours
        except Exception:
            pass
        return fallback

    def _get_rule_catalog_cache_hours(self) -> int:
        return self._resolve_hours_setting(
            RUNTIME_KEY_RULE_CACHE_HOURS,
            max(int(self.settings.rule_catalog_refresh_hours), 1),
        )

    def _get_cn_cache_hours(self) -> int:
        return self._resolve_hours_setting(RUNTIME_KEY_CN_CACHE_HOURS, DEFAULT_CN_CACHE_HOURS)

    async def refresh_categories(
        self,
        force: bool = False,
        mode: str = "incremental",
    ) -> dict[str, Any]:
        refresh_mode = str(mode or "incremental").strip().lower()
        if refresh_mode not in REFRESH_MODES:
            raise ValueError("invalid refresh mode")

        existing = self.repo.list_rule_categories()
        if existing and not force:
            newest = max((item.updated_at for item in existing if item.updated_at), default="")
            ts = _parse_utc(newest)
            if ts and ts > datetime.now(timezone.utc) - timedelta(hours=self._get_rule_catalog_cache_hours()):
                return {
                    "ok": True,
                    "source": "cache",
                    "mode": refresh_mode,
                    "count": len(existing),
                    "downloaded_count": 0,
                    "reused_count": len(existing),
                    "tree_not_modified": False,
                    "failed_count": 0,
                    "attempted_count": 0,
                    "succeeded_count": 0,
                    "cn_cache_source": "none",
                }

        try:
            catalog, tree_not_modified = await self._fetch_category_catalog(
                use_etag=(refresh_mode == "incremental"),
            )
        except Exception as exc:
            return {
                "ok": False,
                "source": "cache",
                "mode": refresh_mode,
                "count": len(existing),
                "downloaded_count": 0,
                "reused_count": len(existing),
                "tree_not_modified": False,
                "failed_count": 1,
                "attempted_count": 1,
                "succeeded_count": 0,
                "cn_cache_source": "none",
                "error": str(exc),
            }

        if tree_not_modified and existing and refresh_mode == "incremental":
            return {
                "ok": True,
                "source": "cache",
                "mode": refresh_mode,
                "count": len(existing),
                "downloaded_count": 0,
                "reused_count": len(existing),
                "tree_not_modified": True,
                "failed_count": 0,
                "attempted_count": 1,
                "succeeded_count": 1,
                "cn_cache_source": "none",
            }

        cn_judge, cn_cache_source = await self._load_cn_judge(mode=refresh_mode)
        existing_map = {item.name: item for item in existing}
        semaphore = asyncio.Semaphore(10)
        catalog_items = []
        for name, entry in sorted(catalog.items()):
            current = existing_map.get(name)
            if current and current.category_type == RULE_CATEGORY_TYPE_MANUAL:
                continue
            catalog_items.append((name, entry))

        async with build_async_http_client(self.settings) as client:
            async def sync_one(name: str, entry: _CatalogEntry) -> _RuleSyncResult:
                current = existing_map.get(name)
                cached_entry = self.repo.load_rule_cache_entry(name) or {}
                cached_rules = cached_entry.get("rules") if isinstance(cached_entry, dict) else None
                preferred_source, _, preferred_sha = entry.preferred()

                reused = False
                downloaded = False
                failed = False
                rules: list[str] = []
                rule_source = preferred_source

                if (
                    refresh_mode == "incremental"
                    and preferred_sha
                    and isinstance(cached_rules, list)
                    and str(cached_entry.get("source_sha") or "") == preferred_sha
                ):
                    rules = list(cached_rules)
                    reused = True
                else:
                    async with semaphore:
                        _, fetched_source, fetched_rules = await self._fetch_category_rules(
                            name,
                            entry,
                            client=client,
                        )
                    if fetched_rules:
                        rules = fetched_rules
                        rule_source = fetched_source or rule_source
                        source_sha, source_path = entry.source_meta(rule_source)
                        self.repo.save_rule_cache(
                            name,
                            rules,
                            source_sha=source_sha,
                            source_path=source_path,
                        )
                        downloaded = True
                    else:
                        failed = True
                        if isinstance(cached_rules, list):
                            rules = list(cached_rules)
                            cached_path = str(cached_entry.get("source_path") or "")
                            if cached_path.endswith(".yaml"):
                                rule_source = "yaml"
                            elif cached_path.endswith(".list"):
                                rule_source = "list"
                            elif current and current.rule_source:
                                rule_source = current.rule_source
                        elif current and current.rule_source:
                            rule_source = current.rule_source

                is_auto_direct = self._should_auto_direct(name, rules, cn_judge)
                system_directness = RULE_DIRECTNESS_DIRECT if is_auto_direct else RULE_DIRECTNESS_PROXY
                system_default_group = (
                    RULE_DIRECTNESS_DIRECT if system_directness == RULE_DIRECTNESS_DIRECT else ""
                )
                system_default_locked = system_default_group == RULE_DIRECTNESS_DIRECT

                override_active = False
                override_group = ""
                directness_override = ""
                manual_locked = False
                if current:
                    if current.lock_source == RULE_LOCK_SOURCE_MANUAL and current.locked:
                        manual_locked = True
                    if current.directness_override in {"", *RULE_DIRECTNESS_CHOICES}:
                        directness_override = current.directness_override

                    raw_override_active = bool(current.override_active)
                    raw_override_group = str(current.override_group or "").strip()
                    if raw_override_group not in {"", RULE_DIRECTNESS_DIRECT, *QUALITY_GROUPS}:
                        raw_override_group = ""

                    legacy_override_active = False
                    legacy_override_group = ""
                    if current.directness_override == RULE_DIRECTNESS_DIRECT:
                        legacy_override_active = True
                        legacy_override_group = RULE_DIRECTNESS_DIRECT
                    elif current.directness_override == RULE_DIRECTNESS_PROXY:
                        legacy_override_active = True
                        legacy_override_group = (
                            current.assigned_group
                            if current.assigned_group and current.assigned_group != RULE_DIRECTNESS_DIRECT
                            else ""
                        )
                    elif current.assigned_group != system_default_group:
                        legacy_override_active = True
                        legacy_override_group = current.assigned_group

                    override_active = raw_override_active or legacy_override_active
                    if raw_override_active:
                        override_group = raw_override_group
                    elif legacy_override_active:
                        override_group = legacy_override_group

                if override_active:
                    assigned_group = override_group
                    if assigned_group not in {"", RULE_DIRECTNESS_DIRECT, *QUALITY_GROUPS}:
                        assigned_group = ""
                    if assigned_group == RULE_DIRECTNESS_DIRECT:
                        directness_override = RULE_DIRECTNESS_DIRECT
                    elif system_default_group == RULE_DIRECTNESS_DIRECT:
                        directness_override = RULE_DIRECTNESS_PROXY
                    elif directness_override == RULE_DIRECTNESS_DIRECT:
                        directness_override = RULE_DIRECTNESS_PROXY
                    else:
                        directness_override = ""
                    locked = manual_locked
                    lock_source = RULE_LOCK_SOURCE_MANUAL if manual_locked else ""
                else:
                    assigned_group = system_default_group
                    directness_override = ""
                    if manual_locked:
                        locked = True
                        lock_source = RULE_LOCK_SOURCE_MANUAL
                    else:
                        locked = system_default_locked
                        lock_source = RULE_LOCK_SOURCE_SYSTEM if system_default_locked else ""

                category = RuleCategory(
                    name=name,
                    assigned_group=assigned_group,
                    rule_count=len(rules),
                    rule_source=rule_source,
                    category_type=RULE_CATEGORY_TYPE_AUTO,
                    updated_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    locked=locked,
                    system_directness=system_directness,
                    system_default_group=system_default_group,
                    system_default_locked=system_default_locked,
                    override_group=override_group if override_active else "",
                    override_active=override_active,
                    directness_override=directness_override,
                    lock_source=lock_source,
                )
                result = _RuleSyncResult(
                    category=category,
                    downloaded=downloaded,
                    reused=reused,
                    failed=failed,
                )
                self._report_progress(
                    {
                        "phase": "refresh_progress",
                        "unit": "category",
                        "category": name,
                        "ok": not failed,
                        "downloaded": downloaded,
                        "reused": reused,
                    }
                )
                return result

            results = await asyncio.gather(
                *(sync_one(name, entry) for name, entry in catalog_items),
                return_exceptions=True,
            )

        merged: list[RuleCategory] = []
        failed_count = 0
        downloaded_count = 0
        reused_count = 0

        for result in results:
            if isinstance(result, Exception):
                failed_count += 1
                continue
            merged.append(result.category)
            if result.failed:
                failed_count += 1
            if result.downloaded:
                downloaded_count += 1
            if result.reused:
                reused_count += 1

        if merged:
            self.repo.save_rule_categories(merged)

        return {
            "ok": failed_count == 0,
            "partial": bool(failed_count and downloaded_count),
            "source": "github",
            "mode": refresh_mode,
            "count": len(merged),
            "downloaded_count": downloaded_count,
            "reused_count": reused_count,
            "tree_not_modified": tree_not_modified,
            "failed_count": failed_count,
            "attempted_count": downloaded_count + failed_count,
            "succeeded_count": downloaded_count,
            "cn_cache_source": cn_cache_source,
        }

    @staticmethod
    def _should_auto_direct(
        category_name: str,
        rules: list[str],
        cn_judge: _CnJudge | None = None,
    ) -> bool:
        if str(category_name or "").strip().lower() == "direct":
            return True
        for line in rules or []:
            parts = [item.strip() for item in str(line or "").split(",")]
            if len(parts) >= 3 and parts[2].upper() == "DIRECT":
                return True
        if cn_judge and cn_judge.is_cn_category(rules):
            return True
        return False

    async def _load_cn_judge(self, mode: str = "incremental") -> tuple[_CnJudge | None, str]:
        now = datetime.now(timezone.utc)
        ttl_hours = self._get_cn_cache_hours()
        ttl_edge = now - timedelta(hours=ttl_hours)

        stale_sqlite: tuple[_CnJudge, datetime] | None = None

        if mode != "full":
            if self._cn_judge and self._cn_judge_loaded_at and self._cn_judge_loaded_at > ttl_edge:
                return self._cn_judge, "memory"

            cached_sqlite = self.repo.load_cn_judge_cache()
            if cached_sqlite:
                payload, fetched_at = cached_sqlite
                judge = _CnJudge.from_payload(payload)
                ts = _parse_utc(fetched_at)
                if judge and ts:
                    stale_sqlite = (judge, ts)
                    if ts > ttl_edge:
                        self._cn_judge = judge
                        self._cn_judge_loaded_at = ts
                        return judge, "sqlite"

        async with self._cn_judge_lock:
            if mode != "full":
                if self._cn_judge and self._cn_judge_loaded_at and self._cn_judge_loaded_at > ttl_edge:
                    return self._cn_judge, "memory"

            try:
                async with build_async_http_client(self.settings) as client:
                    geosite_result, geoip_result = await asyncio.gather(
                        self._fetch_geosite_cn_domains(client),
                        self._fetch_geoip_cn_networks(client),
                        return_exceptions=True,
                    )
            except Exception:
                geosite_result, geoip_result = (Exception("network"), Exception("network"))

            domain_suffixes: set[str] = set()
            domain_exacts: set[str] = set()
            domain_keywords: set[str] = set()
            geoip_v4: list[ipaddress.IPv4Network] = []
            geoip_v6: list[ipaddress.IPv6Network] = []
            if isinstance(geosite_result, tuple):
                domain_suffixes, domain_exacts, domain_keywords = geosite_result
            if isinstance(geoip_result, tuple):
                geoip_v4, geoip_v6 = geoip_result

            if domain_suffixes or domain_exacts or domain_keywords or geoip_v4 or geoip_v6:
                judge = _CnJudge(
                    domain_suffixes=frozenset(domain_suffixes),
                    domain_exacts=frozenset(domain_exacts),
                    domain_keywords=frozenset(domain_keywords),
                    geoip_v4=tuple(geoip_v4),
                    geoip_v6=tuple(geoip_v6),
                )
                ts = now.isoformat().replace("+00:00", "Z")
                self.repo.save_cn_judge_cache(judge.to_payload(), fetched_at=ts)
                self._cn_judge = judge
                self._cn_judge_loaded_at = _parse_utc(ts)
                return judge, "network"

            if self._cn_judge:
                return self._cn_judge, "stale_fallback"

            if stale_sqlite:
                judge, ts = stale_sqlite
                self._cn_judge = judge
                self._cn_judge_loaded_at = ts
                return judge, "stale_fallback"

            return None, "none"

    async def _fetch_geosite_cn_domains(
        self,
        client: Any,
    ) -> tuple[set[str], set[str], set[str]]:
        base = GEOSITE_CN_BASE_URL.rstrip("/")
        domain_suffixes: set[str] = set()
        domain_exacts: set[str] = set()
        domain_keywords: set[str] = set()
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        visited: set[str] = set()
        visited_lock = asyncio.Lock()

        async def enqueue(token: str) -> None:
            item = token.strip()
            if not item:
                return
            async with visited_lock:
                if item in visited:
                    return
                visited.add(item)
            await queue.put(item)

        async def worker() -> None:
            while True:
                token = await queue.get()
                try:
                    if token is None:
                        return
                    url = f"{base}/{token}"
                    response = await client.get(url, timeout=self.settings.request_timeout_seconds)
                    if response.status_code >= 400:
                        continue
                    for raw_line in response.text.splitlines():
                        line = raw_line.strip()
                        if not line or line.startswith("#"):
                            continue
                        head = line.split(" ", 1)[0].strip()
                        if not head:
                            continue
                        if head.startswith("include:"):
                            include_target = head.split(":", 1)[1].strip()
                            if include_target:
                                await enqueue(include_target)
                            continue

                        lowered = head.lower()
                        if lowered.startswith("regexp:"):
                            continue
                        if lowered.startswith("keyword:"):
                            keyword = lowered.split(":", 1)[1].strip()
                            if keyword:
                                domain_keywords.add(keyword)
                            continue
                        if lowered.startswith("full:"):
                            domain = _normalize_domain(lowered.split(":", 1)[1])
                            if domain:
                                domain_exacts.add(domain)
                            continue
                        if lowered.startswith("domain:"):
                            domain = _normalize_domain(lowered.split(":", 1)[1])
                            if domain:
                                domain_suffixes.add(domain)
                            continue
                        if ":" in head:
                            # Skip unsupported forms (e.g. ext:, regexp:).
                            continue

                        domain = _normalize_domain(head)
                        if domain:
                            domain_suffixes.add(domain)
                finally:
                    queue.task_done()

        await enqueue(GEOSITE_CN_ENTRY)
        workers = [asyncio.create_task(worker()) for _ in range(10)]
        await queue.join()
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)

        return domain_suffixes, domain_exacts, domain_keywords

    async def _fetch_geoip_cn_networks(
        self,
        client: Any,
    ) -> tuple[list[ipaddress.IPv4Network], list[ipaddress.IPv6Network]]:
        response = await client.get(GEOIP_CN_URL, timeout=self.settings.request_timeout_seconds)
        if response.status_code >= 400:
            return [], []

        v4: list[ipaddress.IPv4Network] = []
        v6: list[ipaddress.IPv6Network] = []
        for raw in response.text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            try:
                network = ipaddress.ip_network(line, strict=False)
            except ValueError:
                continue
            if isinstance(network, ipaddress.IPv4Network):
                v4.append(network)
            elif isinstance(network, ipaddress.IPv6Network):
                v6.append(network)
        return v4, v6

    async def _fetch_category_catalog(self, *, use_etag: bool = True) -> tuple[dict[str, _CatalogEntry], bool]:
        url = f"{self.settings.github_api_base}/git/trees/master?recursive=1"
        headers: dict[str, str] = {}
        if use_etag:
            cached_etag = self.repo.get_runtime_setting(RUNTIME_KEY_TREE_ETAG)
            cached_text = str(cached_etag).strip() if cached_etag is not None else ""
            if cached_text:
                headers["If-None-Match"] = cached_text

        async with build_async_http_client(self.settings) as client:
            resp = await client.get(
                url,
                headers=headers,
                timeout=self.settings.request_timeout_seconds,
            )

        if resp.status_code == 304:
            return {}, True

        resp.raise_for_status()
        if use_etag:
            latest_etag = str(resp.headers.get("ETag") or "").strip()
            if latest_etag:
                self.repo.set_runtime_setting(RUNTIME_KEY_TREE_ETAG, latest_etag)

        payload = resp.json()
        tree = payload.get("tree") if isinstance(payload, dict) else None
        if not isinstance(tree, list):
            return {}, False

        raw_catalog: dict[str, dict[str, str]] = {}
        for item in tree:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            if not path.startswith("rule/Clash/"):
                continue
            chunks = path.split("/")
            if len(chunks) < 4:
                continue
            category = chunks[2].strip()
            filename = chunks[-1].strip()
            if not category or category.startswith("_"):
                continue

            lower_file = filename.lower()
            cat_lower = category.lower()
            slot = raw_catalog.setdefault(category, {"yaml_path": "", "yaml_sha": "", "list_path": "", "list_sha": ""})
            if lower_file == f"{cat_lower}.yaml":
                slot["yaml_path"] = path
                slot["yaml_sha"] = str(item.get("sha") or "")
            elif lower_file == f"{cat_lower}.list":
                slot["list_path"] = path
                slot["list_sha"] = str(item.get("sha") or "")

        catalog: dict[str, _CatalogEntry] = {}
        for category, slot in raw_catalog.items():
            entry = _CatalogEntry(
                category=category,
                yaml_path=slot.get("yaml_path", ""),
                yaml_sha=slot.get("yaml_sha", ""),
                list_path=slot.get("list_path", ""),
                list_sha=slot.get("list_sha", ""),
            )
            if entry.has_yaml or entry.has_list:
                catalog[category] = entry

        return catalog, False

    async def _fetch_category_rules(
        self,
        category: str,
        entry: _CatalogEntry | None = None,
        *,
        client: Any | None = None,
    ) -> tuple[int, str, list[str]]:
        cap = entry.capability() if entry else {"yaml": True, "list": True}

        if cap.get("yaml"):
            yaml_path = entry.yaml_path if entry and entry.yaml_path else f"rule/Clash/{category}/{category}.yaml"
            rules = await self._fetch_rules_from_yaml_path(yaml_path, client=client)
            if rules:
                return len(rules), "yaml", rules

        if cap.get("list"):
            list_path = entry.list_path if entry and entry.list_path else f"rule/Clash/{category}/{category}.list"
            rules = await self._fetch_rules_from_list_path(list_path, client=client)
            if rules:
                return len(rules), "list", rules

        return 0, "", []

    async def _fetch_rules_from_yaml(self, category: str, *, client: Any | None = None) -> list[str]:
        return await self._fetch_rules_from_yaml_path(
            f"rule/Clash/{category}/{category}.yaml",
            client=client,
        )

    async def _fetch_rules_from_yaml_path(self, path: str, *, client: Any | None = None) -> list[str]:
        url = f"{self.settings.github_raw_base}/{path.lstrip('/')}"
        text = await self._fetch_text(url, client=client)
        if not text:
            return []

        try:
            payload = yaml.safe_load(text) or {}
        except Exception:
            return []

        items = payload.get("payload") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            return []

        rules: list[str] = []
        seen: set[str] = set()
        for item in items:
            normalized = self.normalize_rule_line(item)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            rules.append(normalized)
        return rules

    async def _fetch_rules_from_list(self, category: str, *, client: Any | None = None) -> list[str]:
        return await self._fetch_rules_from_list_path(
            f"rule/Clash/{category}/{category}.list",
            client=client,
        )

    async def _fetch_rules_from_list_path(self, path: str, *, client: Any | None = None) -> list[str]:
        url = f"{self.settings.github_raw_base}/{path.lstrip('/')}"
        text = await self._fetch_text(url, client=client)
        if not text:
            return []

        rules: list[str] = []
        seen: set[str] = set()
        for raw in text.splitlines():
            normalized = self.normalize_rule_line(raw)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            rules.append(normalized)
        return rules

    async def _fetch_text(self, url: str, *, client: Any | None = None) -> str:
        if client is not None:
            resp = await client.get(url, timeout=self.settings.request_timeout_seconds)
            if resp.status_code >= 400:
                return ""
            return resp.text

        async with build_async_http_client(self.settings) as own_client:
            resp = await own_client.get(url, timeout=self.settings.request_timeout_seconds)
            if resp.status_code >= 400:
                return ""
            return resp.text

    def list_categories(self, query: str = "") -> list[RuleCategory]:
        return self.repo.list_rule_categories(query=query)

    async def get_category_raw_rules(self, name: str) -> list[str]:
        category_name = str(name or "").strip()
        if not category_name:
            return []

        category = self.repo.get_rule_category(category_name)
        if not category:
            raise ValueError("category not found")
        if category.category_type == RULE_CATEGORY_TYPE_MANUAL:
            return []

        cached = self.repo.load_rule_cache(category_name)
        if isinstance(cached, list):
            return list(cached)

        entry: _CatalogEntry | None = None
        default_yaml_path = f"rule/Clash/{category_name}/{category_name}.yaml"
        default_list_path = f"rule/Clash/{category_name}/{category_name}.list"
        if category.rule_source == "yaml":
            entry = _CatalogEntry(category=category_name, yaml_path=default_yaml_path)
        elif category.rule_source == "list":
            entry = _CatalogEntry(category=category_name, list_path=default_list_path)

        async with build_async_http_client(self.settings) as client:
            _, fetched_source, rules = await self._fetch_category_rules(
                category_name,
                entry,
                client=client,
            )

        if not rules:
            return []

        source_path = (
            default_yaml_path
            if fetched_source == "yaml"
            else default_list_path if fetched_source == "list" else ""
        )
        self.repo.save_rule_cache(
            category_name,
            rules,
            source_sha="",
            source_path=source_path,
        )
        return list(rules)

    @staticmethod
    def get_effective_directness(category: RuleCategory) -> str:
        if category.assigned_group == RULE_DIRECTNESS_DIRECT:
            return RULE_DIRECTNESS_DIRECT
        if category.override_active:
            return RULE_DIRECTNESS_PROXY
        if category.system_default_group == RULE_DIRECTNESS_DIRECT:
            return RULE_DIRECTNESS_DIRECT
        if category.system_directness == RULE_DIRECTNESS_DIRECT:
            return RULE_DIRECTNESS_DIRECT
        return RULE_DIRECTNESS_PROXY

    @staticmethod
    def get_current_decision_source(category: RuleCategory) -> str:
        if category.override_active and category.assigned_group == RULE_DIRECTNESS_DIRECT:
            return "override-direct"
        if category.override_active:
            return "override-proxy"
        if category.system_default_group == RULE_DIRECTNESS_DIRECT:
            return "system"
        if category.system_directness == RULE_DIRECTNESS_DIRECT:
            return "system"
        return "default-proxy"

    def _pin_group_modes(self) -> dict[str, str]:
        known = {
            str(item.get("group_name") or "").strip(): str(item.get("mode") or BUSINESS_GROUP_MODE_STANDARD).strip()
            or BUSINESS_GROUP_MODE_STANDARD
            for item in self.repo.list_pin_groups()
            if str(item.get("group_name") or "").strip()
        }
        for entry in self.repo.list_service_catalog_entries():
            group_name = str(entry.catalog_group or "").strip()
            if group_name and group_name not in known:
                known[group_name] = BUSINESS_GROUP_MODE_STANDARD
        return known

    def _effective_contract_for_category(
        self,
        category: RuleCategory,
        *,
        binding_by_name: dict[str, ServiceCatalogEntry],
        pin_group_modes: dict[str, str],
    ) -> str:
        binding = binding_by_name.get(category.name)
        catalog_group = str(binding.catalog_group or "").strip() if binding else ""
        group_mode = pin_group_modes.get(catalog_group, BUSINESS_GROUP_MODE_STANDARD)
        return effective_contract_id(
            stored_contract_id=binding.contract_id if binding else "",
            catalog_group_mode=group_mode,
            current_directness=self.get_effective_directness(category),
        )

    def get_llm_export_preferences(self) -> dict[str, str]:
        return {
            "rules_preferences": _normalize_preferences_text(
                self.repo.get_runtime_setting(RUNTIME_KEY_LLM_EXPORT_RULES_PREFERENCES),
                fallback=DEFAULT_RULES_PREFERENCES,
            ),
            "pins_preferences": _normalize_preferences_text(
                self.repo.get_runtime_setting(RUNTIME_KEY_LLM_EXPORT_PINS_PREFERENCES),
                fallback=DEFAULT_PINS_PREFERENCES,
            ),
            "directness_preferences": _normalize_preferences_text(
                self.repo.get_runtime_setting(RUNTIME_KEY_LLM_EXPORT_DIRECTNESS_PREFERENCES),
                fallback=DEFAULT_DIRECTNESS_PREFERENCES,
            ),
        }

    def update_llm_export_preferences(
        self,
        *,
        rules_preferences: str | None = None,
        pins_preferences: str | None = None,
        directness_preferences: str | None = None,
    ) -> dict[str, str]:
        if rules_preferences is not None:
            normalized = str(rules_preferences).replace("\r\n", "\n").replace("\r", "\n").strip()
            self.repo.set_runtime_setting(RUNTIME_KEY_LLM_EXPORT_RULES_PREFERENCES, normalized)
        if pins_preferences is not None:
            normalized = str(pins_preferences).replace("\r\n", "\n").replace("\r", "\n").strip()
            self.repo.set_runtime_setting(RUNTIME_KEY_LLM_EXPORT_PINS_PREFERENCES, normalized)
        if directness_preferences is not None:
            normalized = str(directness_preferences).replace("\r\n", "\n").replace("\r", "\n").strip()
            self.repo.set_runtime_setting(RUNTIME_KEY_LLM_EXPORT_DIRECTNESS_PREFERENCES, normalized)
        return self.get_llm_export_preferences()

    def _routing_contracts(self) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        for contract in self.repo.list_route_contracts():
            if not bool(contract.enabled):
                continue
            if normalize_route_action(getattr(contract, "routing_action", ROUTE_ACTION_PROXY)) != ROUTE_ACTION_PROXY:
                continue
            legacy_group = contract.primary_legacy_group()
            if legacy_group not in QUALITY_GROUPS:
                continue
            items.append(
                {
                    "contract_id": contract.id,
                    "display_name": str(contract.display_name or contract_display_name(contract.id)).strip(),
                    "description": str(contract.description or contract_description(contract.id)).strip(),
                    "legacy_group": legacy_group,
                }
            )
        return items

    def _routing_contract_display_name_map(self) -> dict[str, str]:
        return {
            item["contract_id"]: item["display_name"]
            for item in self._routing_contracts()
            if item["contract_id"]
        }

    def _resolve_routing_contract_id(self, value: object) -> str:
        return resolve_contract_id(value, display_name_map=self._routing_contract_display_name_map())

    def _contract_legacy_group(self, contract_id: object) -> str:
        normalized = normalize_contract_id(contract_id)
        if not normalized:
            return ""
        contract = self.repo.get_route_contract(normalized)
        if contract:
            return contract.primary_legacy_group()
        return contract_legacy_group(normalized)

    def assign_category(self, name: str, group: str) -> bool:
        item = self.repo.get_rule_category(name)
        if not item:
            return False
        if item.locked:
            raise ValueError("category locked")
        allowed_targets = set(CATEGORY_TARGETS)
        if item.category_type == RULE_CATEGORY_TYPE_MANUAL:
            allowed_targets.add(RULE_DIRECTNESS_DIRECT)
        normalized_contract_id = self._resolve_routing_contract_id(group)
        if normalized_contract_id:
            group = self._contract_legacy_group(normalized_contract_id)
        if group and group not in allowed_targets:
            raise ValueError("invalid quality group")
        if item.category_type == RULE_CATEGORY_TYPE_MANUAL:
            return self.repo.update_rule_category_group(name, group)
        return self.repo.set_rule_category_override_group(name, group)

    def bulk_assign(self, assignments: dict[str, str]) -> tuple[int, list[str]]:
        existing = {item.name: item for item in self.repo.list_rule_categories()}
        skipped_locked: list[str] = []
        filtered: dict[str, str] = {}
        for name, group in (assignments or {}).items():
            if existing.get(name) and existing[name].locked:
                skipped_locked.append(name)
                continue
            filtered[name] = group

        for name, group in filtered.items():
            item = existing.get(name)
            allowed = set(CATEGORY_TARGETS)
            if item and item.category_type == RULE_CATEGORY_TYPE_MANUAL:
                allowed.add(RULE_DIRECTNESS_DIRECT)
            normalized_contract_id = self._resolve_routing_contract_id(group)
            if normalized_contract_id:
                group = self._contract_legacy_group(normalized_contract_id)
                filtered[name] = group
            if group and group not in allowed:
                raise ValueError("invalid quality group in assignments")

        updated = self.repo.bulk_assign_rule_categories(filtered, skip_locked=True)
        return updated, skipped_locked

    async def get_targeted_rule_entries(
        self,
        target_resolver: Callable[[RuleCategory], str] | None = None,
    ) -> list[dict[str, str]]:
        categories = self.repo.list_rule_categories()
        if not categories:
            return []
        binding_by_name = {item.category_name: item for item in self.repo.list_service_catalog_entries()}
        pin_group_modes = self._pin_group_modes()

        merged: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        cidr_autofixed_count = 0
        dropped_invalid_count = 0
        targeted_categories = 0

        async with build_async_http_client(self.settings) as client:
            for item in categories:
                resolved_target = (
                    str(target_resolver(item)).strip()
                    if callable(target_resolver)
                    else contract_display_name(
                        self._effective_contract_for_category(
                            item,
                            binding_by_name=binding_by_name,
                            pin_group_modes=pin_group_modes,
                        )
                    )
                )
                if not resolved_target:
                    continue
                targeted_categories += 1
                for custom_rule in self.repo.list_custom_rules(category_name=item.name):
                    targeted_custom = custom_rule.to_line(target_group=resolved_target)
                    normalized_custom, autofixed = self.normalize_output_rule_line(targeted_custom)
                    if not normalized_custom:
                        dropped_invalid_count += 1
                        continue
                    if autofixed:
                        cidr_autofixed_count += 1
                    identity_key = self.rule_identity_key(normalized_custom)
                    dedupe_key = (item.name, identity_key if identity_key is not None else normalized_custom)
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    merged.append(
                        {
                            "category_name": item.name,
                            "target": resolved_target,
                            "line": normalized_custom,
                            "source_kind": "custom",
                        }
                    )

                if item.category_type == RULE_CATEGORY_TYPE_MANUAL:
                    continue

                cached = self.repo.load_rule_cache(item.name)
                if not cached:
                    _, _, cached = await self._fetch_category_rules(
                        item.name,
                        _CatalogEntry(
                            category=item.name,
                            yaml_path=f"rule/Clash/{item.name}/{item.name}.yaml" if item.rule_source in ("", "yaml") else "",
                            list_path=f"rule/Clash/{item.name}/{item.name}.list" if item.rule_source in ("", "list") else "",
                        ),
                        client=client,
                    )
                    if cached:
                        self.repo.save_rule_cache(item.name, cached)

                for line in cached or []:
                    targeted = self._retarget_rule(line, resolved_target)
                    normalized_targeted, autofixed = self.normalize_output_rule_line(targeted)
                    if not normalized_targeted:
                        dropped_invalid_count += 1
                        continue
                    if autofixed:
                        cidr_autofixed_count += 1
                    identity_key = self.rule_identity_key(normalized_targeted)
                    dedupe_key = (item.name, identity_key if identity_key is not None else normalized_targeted)
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    merged.append(
                        {
                            "category_name": item.name,
                            "target": resolved_target,
                            "line": normalized_targeted,
                            "source_kind": "catalog",
                        }
                    )
        if cidr_autofixed_count or dropped_invalid_count:
            _logger.info(
                "rule export sanitization (category-level): cidr_autofixed=%s dropped_invalid=%s assigned_categories=%s merged_rules=%s",
                cidr_autofixed_count,
                dropped_invalid_count,
                targeted_categories,
                len(merged),
            )
        return merged

    async def get_assigned_rule_lines(self) -> list[str]:
        return [item["line"] for item in await self.get_targeted_rule_entries()]

    @staticmethod
    def _retarget_rule(line: str, target: str) -> str:
        parts = [item.strip() for item in line.split(",")]
        if len(parts) == 2:
            return f"{parts[0]},{parts[1]},{target}"
        # Only retarget placeholder rules. If upstream explicitly set DIRECT/REJECT, preserve it.
        if parts[2].upper() != "PLACEHOLDER":
            return ",".join(parts)
        parts[2] = target
        return ",".join(parts)

    @staticmethod
    def _normalize_cidr_value(rule_type: str, value: str) -> tuple[str | None, bool]:
        text = str(value or "").strip()
        if not text:
            return None, False

        if "/" in text:
            try:
                network = ipaddress.ip_network(text, strict=False)
            except ValueError:
                return None, False
            if rule_type == "IP-CIDR" and isinstance(network, ipaddress.IPv6Network):
                return None, False
            if rule_type == "IP-CIDR6" and isinstance(network, ipaddress.IPv4Network):
                return None, False
            return text, False

        try:
            ip_value = ipaddress.ip_address(text)
        except ValueError:
            return None, False
        if rule_type == "IP-CIDR" and isinstance(ip_value, ipaddress.IPv6Address):
            return None, False
        if rule_type == "IP-CIDR6" and isinstance(ip_value, ipaddress.IPv4Address):
            return None, False
        if isinstance(ip_value, ipaddress.IPv4Address):
            return f"{ip_value.compressed}/32", True
        return f"{ip_value.compressed}/128", True

    @staticmethod
    def normalize_output_rule_line(raw: Any) -> tuple[str | None, bool]:
        text = str(raw or "").strip()
        if not text:
            return None, False
        parts = [item.strip() for item in text.split(",")]
        if len(parts) < 2:
            return None, False
        rule_type = parts[0].upper()
        if rule_type in _CIDR_RULE_TYPES:
            normalized_value, autofixed = RuleCatalog._normalize_cidr_value(rule_type, parts[1])
            if not normalized_value:
                return None, False
            parts[1] = normalized_value
            parts[0] = rule_type
            return ",".join(parts), autofixed
        return text, False

    @staticmethod
    def rule_identity_key(raw: Any) -> tuple[str, str, tuple[str, ...]] | None:
        text = str(raw or "").strip()
        if not text:
            return None
        parts = [item.strip() for item in text.split(",")]
        if len(parts) < 2:
            return None
        rule_type = parts[0].upper()
        value = parts[1]
        extra = tuple(item for item in parts[3:] if item)
        return (rule_type, value, extra)

    @staticmethod
    def normalize_rule_line(raw: Any) -> str | None:
        text = str(raw or "").strip()
        if not text or text.startswith("#") or text.startswith("!") or text.startswith(";"):
            return None
        if text.startswith("payload:"):
            return None
        if text.startswith("- "):
            text = text[2:].strip()

        if "," not in text and "." in text and " " not in text:
            return f"DOMAIN-SUFFIX,{text},PLACEHOLDER"

        parts = [item.strip() for item in text.split(",")]
        if len(parts) < 2:
            return None

        rule_type = parts[0].upper()
        if rule_type not in _RULE_TYPES:
            return None
        value = parts[1]
        if rule_type in _CIDR_RULE_TYPES:
            normalized_value, _ = RuleCatalog._normalize_cidr_value(rule_type, value)
            if not normalized_value:
                return None
            value = normalized_value

        if len(parts) == 2:
            return f"{rule_type},{value},PLACEHOLDER"

        # 3+ parts: third item can be an upstream explicit target (DIRECT/REJECT) or an option
        # like "no-resolve". Preserve upstream targets and keep options in the "extra" tail.
        third = parts[2].strip()
        third_upper = third.upper()

        extra: list[str] = []
        if third and third_upper in EXPLICIT_TARGETS:
            target = third_upper
            extra = [p for p in parts[3:] if p]
            return ",".join([rule_type, value, target, *extra])

        if third_upper == "PLACEHOLDER":
            extra = [p for p in parts[3:] if p]
            return ",".join([rule_type, value, "PLACEHOLDER", *extra])

        # If the third part looks like an option (commonly "no-resolve"), treat it as extra.
        extra = [p for p in ([third] + parts[3:]) if p]
        return ",".join([rule_type, value, "PLACEHOLDER", *extra])

    def export_assignment_payload(self) -> dict[str, Any]:
        categories = self.repo.list_rule_categories()
        categories.sort(key=lambda item: item.name.lower())
        preferences = self.get_llm_export_preferences()
        routing_contracts = self._routing_contracts()
        contract_display_names = {
            item["contract_id"]: item["display_name"]
            for item in routing_contracts
            if item["contract_id"]
        }
        routing_contract_ids = set(contract_display_names)
        binding_by_name = {item.category_name: item for item in self.repo.list_service_catalog_entries()}
        pin_group_modes = self._pin_group_modes()
        category_targets: list[dict[str, object]] = []
        for item in categories:
            effective_directness = self.get_effective_directness(item)
            effective_contract = self._effective_contract_for_category(
                item,
                binding_by_name=binding_by_name,
                pin_group_modes=pin_group_modes,
            )
            category_targets.append(
                {
                    "category": item,
                    "effective_directness": effective_directness,
                    "effective_contract": effective_contract,
                }
            )

        assigned = [
            item
            for item in category_targets
            if str(item["effective_contract"] or "") in routing_contract_ids
        ]
        unassigned = [
            item
            for item in category_targets
            if not bool(item["category"].locked)
            and str(item["effective_directness"] or "") != RULE_DIRECTNESS_DIRECT
            and str(item["effective_contract"] or "") not in {ROUTE_REJECT_ACTION, *routing_contract_ids}
        ]

        # Build the LLM-ready prompt text
        lines: list[str] = []
        lines.append("# 任务")
        lines.append("")
        lines.append(
            "你是一个网络代理分流策略助手。"
            "下面有一批「规则分类」尚未分配到代理节点组，请根据分类名称所代表的服务语义，"
            "为每个分类选择最合适的目标组。"
        )
        lines.append("")

        lines.append("# 可选目标组")
        lines.append("")
        for item in routing_contracts:
            lines.append(f"## {item['display_name']} (`{item['contract_id']}`)")
            if item["description"]:
                lines.append(item["description"])
            else:
                lines.append("（无描述）")
            lines.append("")

        _append_markdown_block(lines, "# 我的分组偏好", preferences["rules_preferences"])

        lines.append("# 已分配的分类（仅供参考，帮助你理解分配逻辑）")
        lines.append("")
        if assigned:
            for item in assigned:
                category = item["category"]
                lock_mark = " [已锁定]" if category.locked else ""
                contract_id = str(item["effective_contract"] or "")
                display_name = contract_display_names.get(contract_id, contract_id)
                lines.append(f"- {category.name} → {display_name}{lock_mark}")
        else:
            lines.append("（暂无已分配分类）")
        lines.append("")

        lines.append("# 待分配分类")
        lines.append("")
        if unassigned:
            lines.append("请为以下每个分类选择一个目标组：")
            lines.append("")
            for item in unassigned:
                category = item["category"]
                lines.append(f"- {category.name}（{category.rule_count} 条规则）")
        else:
            lines.append("（当前没有待分配的分类）")
        lines.append("")

        lines.append("# 输出要求")
        lines.append("")
        lines.append("请严格输出以下 JSON 格式，不要输出任何解释文字：")
        lines.append("")
        lines.append("```json")
        lines.append("{")
        lines.append('  "分类名": "contract_id",')
        lines.append('  "分类名": "contract_id"')
        lines.append("}")
        lines.append("```")
        lines.append("")
        lines.append("规则：")
        lines.append("1. 键 = 待分配分类的名称（必须与上方列表完全一致）")
        lines.append(
            "2. 值 = 目标 contract_id（必须是以下之一：{targets}）".format(
                targets=" / ".join(item["contract_id"] for item in routing_contracts)
            )
        )
        lines.append("3. 如果无法判断，优先保持留空，或选择描述最通用的默认目标")
        lines.append("4. 仅输出 JSON，禁止输出其他内容")

        prompt = "\n".join(lines)

        return {
            "schema": "subhub.rules.assignment.v3",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "prompt": prompt,
            "target_options": routing_contracts,
            "total_categories": len(categories),
            "assigned_count": len(assigned),
            "unassigned_count": len(unassigned),
            "candidates": [str(item["category"].name) for item in unassigned],
        }

    def export_pins_payload(self) -> dict[str, Any]:
        categories = self.repo.list_rule_categories()
        categories.sort(key=lambda item: item.name.lower())
        preferences = self.get_llm_export_preferences()
        pinned = self.repo.list_pinned_categories()

        lines: list[str] = []
        lines.append("# 任务")
        lines.append("")
        lines.append(
            "你是一个网络代理分流策略助手。"
            "下面有一批「规则分类」，请根据分类名称所代表的服务语义，"
            "将它们分配到合适的「置顶分组」。置顶分组是用户自定义的逻辑分组（非代理节点组）。"
        )
        lines.append("")

        lines.append("# 常见置顶分组参考")
        lines.append("")
        lines.append(
            "AI 服务、流媒体、社交网络、开发工具、游戏、金融支付、通信工具、"
            "搜索引擎、购物、新闻资讯、云服务、教育学术、音乐、其他"
        )
        lines.append("")

        _append_markdown_block(lines, "# 你的置顶偏好", preferences["pins_preferences"])

        lines.append("# 已有置顶分配（仅供参考）")
        lines.append("")
        if pinned:
            for item in pinned:
                lines.append(f"- {item['category_name']} → {item['pin_group']}")
        else:
            lines.append("（暂无已置顶分类）")
        lines.append("")

        candidates = [
            item for item in categories if not (item.locked and item.assigned_group == "DIRECT")
        ]
        lines.append("# 待分配分类")
        lines.append("")
        if candidates:
            lines.append("请为以下分类选择合适的置顶分组：")
            lines.append("")
            for item in candidates:
                group_hint = f"（当前节点组: {item.assigned_group}）" if item.assigned_group else ""
                lines.append(f"- {item.name}（{item.rule_count} 条规则）{group_hint}")
        else:
            lines.append("（当前没有待分配的分类）")
        lines.append("")

        lines.append("# 输出要求")
        lines.append("")
        lines.append("请严格输出以下 JSON 格式，不要输出任何解释文字：")
        lines.append("")
        lines.append("```json")
        lines.append("{")
        lines.append('  "分类名": "置顶分组名",')
        lines.append('  "分类名": "置顶分组名"')
        lines.append("}")
        lines.append("```")
        lines.append("")
        lines.append("规则：")
        lines.append("1. 键 = 分类名称（必须与上方列表完全一致）")
        lines.append("2. 值 = 置顶分组名（可以自由命名，建议使用上方常见分组名）")
        lines.append("3. 不需要分组的分类可以省略")
        lines.append("4. 仅输出 JSON，禁止输出其他内容")

        return {
            "ok": True,
            "schema": "subhub.pins.assignment.v1",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "prompt": "\n".join(lines),
            "total_categories": len(categories),
            "pinned_count": len(pinned),
            "candidates": [item.name for item in candidates],
        }

    def import_assignment_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        assignments_raw: Any
        if isinstance(payload.get("assignments"), dict):
            assignments_raw = payload["assignments"]
        else:
            assignments_raw = payload

        if not isinstance(assignments_raw, dict):
            raise ValueError("invalid payload: assignments must be an object")

        existing = {item.name: item for item in self.repo.list_rule_categories()}
        valid_assignments: dict[str, str] = {}
        invalid_items: list[dict[str, str]] = []
        skipped_locked: list[str] = []
        allowed_contracts = {item["contract_id"]: item["legacy_group"] for item in self._routing_contracts()}

        for key, value in assignments_raw.items():
            name = str(key or "").strip()
            group = str(value or "").strip()
            if not name:
                continue
            if name not in existing:
                invalid_items.append({"name": name, "reason": "unknown_category"})
                continue
            if existing[name].locked:
                skipped_locked.append(name)
                continue
            normalized_contract_id = self._resolve_routing_contract_id(group)
            if normalized_contract_id:
                group = allowed_contracts.get(normalized_contract_id, "")
            if group and group not in CATEGORY_TARGETS:
                invalid_items.append(
                    {
                        "name": name,
                        "reason": "invalid_group",
                        "group": group,
                    }
                )
                continue
            valid_assignments[name] = group

        updated = self.repo.bulk_assign_rule_categories(valid_assignments, skip_locked=True)
        return {
            "updated": updated,
            "skipped_locked": skipped_locked,
            "invalid_items": invalid_items,
        }

    def export_directness_review_payload(self, *, scope: str = "all") -> dict[str, Any]:
        normalized_scope = str(scope or "all").strip().lower()
        if normalized_scope not in {"direct_locked", "all"}:
            raise ValueError("invalid scope")

        categories = self.repo.list_rule_categories()
        categories.sort(key=lambda item: item.name.lower())
        preferences = self.get_llm_export_preferences()

        if normalized_scope == "direct_locked":
            candidates = [
                item
                for item in categories
                if item.assigned_group == RULE_DIRECTNESS_DIRECT and item.lock_source == RULE_LOCK_SOURCE_SYSTEM
            ]
        else:
            candidates = list(categories)

        sample_rules: dict[str, list[str]] = {}
        for item in candidates:
            cached = self.repo.load_rule_cache(item.name) or []
            sample_rules[item.name] = list(cached[:5])

        lines: list[str] = []
        lines.append("# 任务")
        lines.append("")
        lines.append(
            "你是网络分流审核助手。请只判断每个分类应为 DIRECT 还是 PROXY。"
            "DIRECT 表示走直连，PROXY 表示应走代理组。"
        )
        lines.append("")
        lines.append("## 判定定义")
        lines.append("")
        lines.append("- DIRECT：仅在高度确定属于中国大陆本地直连场景时使用。")
        lines.append("- PROXY：其余全部场景（含不确定场景）。")
        lines.append("")

        _append_markdown_block(lines, "# 我的直连审核偏好", preferences["directness_preferences"])

        lines.append("# 待审核分类")
        lines.append("")
        if candidates:
            for item in candidates:
                current_effective_directness = self.get_effective_directness(item)
                current_decision_source = self.get_current_decision_source(item)
                lines.append(
                    f"- {item.name}（当前二分结果: {current_effective_directness}，"
                    f"当前代理组: {item.assigned_group or '未分配'}，"
                    f"系统判定: {item.system_directness}，"
                    f"当前结果来源: {current_decision_source}，"
                    f"规则数: {item.rule_count}）"
                )
                for rule in sample_rules.get(item.name) or []:
                    lines.append(f"  - {rule}")
        else:
            lines.append("（无）")
        lines.append("")

        lines.append("# 输出要求")
        lines.append("")
        lines.append("仅输出你认为需要修改当前二分结果的分类，不要返回已经认可当前状态的分类。")
        lines.append("仅输出 JSON，不要解释文字。")
        lines.append("允许两种格式：")
        lines.append("```json")
        lines.append('{ "分类名": "DIRECT|PROXY" }')
        lines.append("```")
        lines.append("或")
        lines.append("```json")
        lines.append('{ "分类名": { "decision": "DIRECT|PROXY", "confidence": "low|medium|high", "reason": "简短理由" } }')
        lines.append("```")

        return {
            "ok": True,
            "schema": "subhub.rules.directness.review.v1",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "scope": normalized_scope,
            "prompt": "\n".join(lines),
            "total_categories": len(categories),
            "candidates_count": len(candidates),
            "candidates": [item.name for item in candidates],
            "items": [
                {
                    "name": item.name,
                    "current_effective_directness": self.get_effective_directness(item),
                    "current_group": item.assigned_group,
                    "system_directness": item.system_directness,
                    "current_decision_source": self.get_current_decision_source(item),
                    "rule_count": item.rule_count,
                    "sample_rules": sample_rules.get(item.name) or [],
                }
                for item in candidates
            ],
        }

    def import_directness_review_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        assignments_raw: Any
        if isinstance(payload.get("assignments"), dict):
            assignments_raw = payload["assignments"]
        else:
            assignments_raw = payload

        if not isinstance(assignments_raw, dict):
            raise ValueError("invalid payload: assignments must be an object")

        categories = {item.name: item for item in self.repo.list_rule_categories()}
        reviews: list[RuleCategoryDirectnessReview] = []
        invalid_items: list[dict[str, str]] = []
        skipped_same: list[str] = []

        for key, value in assignments_raw.items():
            name = str(key or "").strip()
            if not name:
                continue
            if name not in categories:
                invalid_items.append({"name": name, "reason": "unknown_category"})
                continue

            decision = ""
            confidence = ""
            reason = ""
            if isinstance(value, str):
                decision = value.strip().upper()
            elif isinstance(value, dict):
                decision = str(value.get("decision") or "").strip().upper()
                confidence = str(value.get("confidence") or "").strip().lower()
                reason = str(value.get("reason") or "").strip()
            else:
                invalid_items.append({"name": name, "reason": "invalid_decision_format"})
                continue

            if decision not in RULE_DIRECTNESS_CHOICES:
                invalid_items.append({"name": name, "reason": "invalid_decision", "decision": decision})
                continue
            if confidence and confidence not in {"low", "medium", "high"}:
                invalid_items.append({"name": name, "reason": "invalid_confidence", "confidence": confidence})
                continue

            current_effective_directness = self.get_effective_directness(categories[name])
            if decision == current_effective_directness:
                skipped_same.append(name)
                continue

            reviews.append(
                RuleCategoryDirectnessReview(
                    id=uuid4().hex,
                    category_name=name,
                    proposed_decision=decision,
                    confidence=confidence,
                    reason=reason,
                    source="llm-import",
                    status=RULE_DIRECTNESS_REVIEW_STATUS_PENDING,
                    created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                )
            )

        inserted = self.repo.replace_pending_rule_category_directness_reviews(reviews)
        return {
            "inserted": inserted,
            "invalid_items": invalid_items,
            "skipped_same": skipped_same,
        }

    def list_directness_reviews(self, *, status: str = RULE_DIRECTNESS_REVIEW_STATUS_PENDING) -> list[RuleCategoryDirectnessReview]:
        return self.repo.list_rule_category_directness_reviews(status=status)

    def apply_directness_reviews(
        self,
        *,
        review_ids: list[str],
        action: str,
        lock_after_apply: bool = False,
    ) -> dict[str, Any]:
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in {"accept", "dismiss"}:
            raise ValueError("invalid action")
        reviews = self.repo.get_rule_category_directness_reviews_by_ids(review_ids)
        pending = [item for item in reviews if item.status == RULE_DIRECTNESS_REVIEW_STATUS_PENDING]
        if not pending:
            return {"updated": 0, "skipped": len(review_ids)}

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if normalized_action == "dismiss":
            changed = self.repo.set_rule_category_directness_review_status(
                [item.id for item in pending],
                status=RULE_DIRECTNESS_REVIEW_STATUS_DISMISSED,
                decided_at=now,
            )
            return {"updated": changed, "skipped": len(review_ids) - len(pending)}

        applied_ids: list[str] = []
        for item in pending:
            ok = self.repo.apply_rule_category_directness_decision(
                item.category_name,
                item.proposed_decision,
                lock_after_apply=lock_after_apply,
            )
            if ok:
                applied_ids.append(item.id)
        changed = self.repo.set_rule_category_directness_review_status(
            applied_ids,
            status=RULE_DIRECTNESS_REVIEW_STATUS_APPLIED,
            decided_at=now,
        )
        return {
            "updated": changed,
            "skipped": len(review_ids) - len(pending),
            "applied": len(applied_ids),
        }
