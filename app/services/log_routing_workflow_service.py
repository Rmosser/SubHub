from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
import threading
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from app.models import (
    BUSINESS_GROUP_MODE_STANDARD,
    RULE_DIRECTNESS_DIRECT,
    ServiceCatalogEntry,
    contract_display_name,
    effective_contract_id,
    normalize_contract_id,
)
from app.services.core_facade import _derive_rule_category_states, _parse_rule_line, _rule_match_score
from app.services.rule_catalog import RuleCatalog
from app.storage.base import Repo

_SURGE_RULE_RE = re.compile(r"\[Rule\]\s+Rule matched:\s*(.+)$")
_SURGE_POLICY_PATH_RE = re.compile(r"\[Rule\]\s+Policy decision path:\s*(.+)$")
_CLASH_MSG_RE = re.compile(r'msg="(.+)"$')
_SHADOWROCKET_SQL = """
SELECT docid, c0url, c1ua, c2result, c3type, c4created
FROM logging_content
ORDER BY docid
"""
_MULTI_LABEL_SUFFIXES = {
    "com.cn",
    "net.cn",
    "org.cn",
    "gov.cn",
    "edu.cn",
    "co.uk",
    "ac.uk",
    "gov.uk",
    "com.hk",
    "com.tw",
    "co.jp",
    "co.kr",
}
_ALLOWED_ACTION_TYPES = (
    "ensure_manual_category",
    "set_category_route",
    "add_category_rule",
    "remove_category_rule",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _truncate(text: str, limit: int = 240) -> str:
    stripped = _clean_text(text)
    if len(stripped) <= limit:
        return stripped
    return f"{stripped[: limit - 1]}…"


def _normalize_host(value: object) -> str:
    host = _clean_text(value).lower().strip(".")
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if host.startswith("*.") or host.startswith("+."):
        host = host[2:]
    return host


def _is_ip_address(host: str) -> bool:
    if not host:
        return False
    try:
        ip_address(host)
        return True
    except ValueError:
        return False


def _extract_host_from_target(value: object) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    if "://" in text:
        parsed = urlsplit(text)
        return _normalize_host(parsed.hostname or "")
    if text.startswith("[") and "]:" in text:
        return _normalize_host(text[1:].split("]:", 1)[0])
    if text.count(":") == 1:
        return _normalize_host(text.split(":", 1)[0])
    if text.count(":") > 1 and "." not in text:
        return _normalize_host(text)
    return _normalize_host(text)


def _root_domain(host: str) -> str:
    normalized = _normalize_host(host)
    if not normalized or _is_ip_address(normalized):
        return ""
    labels = [item for item in normalized.split(".") if item]
    if len(labels) <= 2:
        return normalized
    suffix2 = ".".join(labels[-2:])
    if suffix2 in _MULTI_LABEL_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _category_name_from_domain(domain: str) -> str:
    base = _root_domain(domain) or _normalize_host(domain)
    if not base:
        return "待分流"
    parts = [item for item in base.split(".") if item]
    if not parts:
        return "待分流"
    head = parts[0].replace("-", " ").replace("_", " ").strip()
    if not head:
        return base
    return "".join(segment[:1].upper() + segment[1:] for segment in head.split())


@dataclass
class LogEvidenceRow:
    source_client: str
    source_file: str
    occurred_at: str
    host: str
    root_domain: str
    fallback_reason: str
    matched_rule: str
    matched_policy: str
    process_name: str
    app_name: str
    raw_excerpt: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class UploadedLogFile:
    id: str
    filename: str
    detected_client: str
    uploaded_at: str
    evidence_count: int
    fallback_count: int
    candidate_count: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class LogRoutingSession:
    id: str
    created_at: str
    updated_at: str
    files: list[UploadedLogFile] = field(default_factory=list)
    evidence_rows: list[LogEvidenceRow] = field(default_factory=list)


class LogRoutingWorkflowService:
    def __init__(self, settings, repo: Repo, rule_catalog: RuleCatalog, core_facade) -> None:
        self.settings = settings
        self.repo = repo
        self.rule_catalog = rule_catalog
        self.core_facade = core_facade
        self._lock = threading.Lock()
        self._sessions: dict[str, LogRoutingSession] = {}

    def list_workflows(self) -> list[dict[str, str]]:
        return [
            {"id": "log-routing", "title": "兜底审计", "template_key": "rules_preferences"},
        ]

    def create_session(self) -> dict[str, object]:
        session = LogRoutingSession(
            id=uuid4().hex,
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        with self._lock:
            self._sessions[session.id] = session
        return {
            "ok": True,
            "item": self._session_payload(session),
        }

    def add_file(
        self,
        session_id: str,
        *,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> dict[str, object]:
        session = self._get_session(session_id)
        detected_client, evidence_rows = self._parse_upload(filename=filename, content_type=content_type, content=content)
        file_item = UploadedLogFile(
            id=uuid4().hex,
            filename=filename or "upload",
            detected_client=detected_client,
            uploaded_at=_utc_now(),
            evidence_count=len(evidence_rows),
            fallback_count=len(evidence_rows),
            candidate_count=len({item.root_domain for item in evidence_rows if item.root_domain}),
        )
        with self._lock:
            session.files.append(file_item)
            session.evidence_rows.extend(evidence_rows)
            session.updated_at = _utc_now()
        candidates = self._build_candidates(session)
        return {
            "ok": True,
            "session_id": session.id,
            "file": file_item.to_dict(),
            "evidence_count": len(session.evidence_rows),
            "candidate_count": len(candidates),
        }

    def get_candidates(self, session_id: str) -> dict[str, object]:
        session = self._get_session(session_id)
        candidates = self._build_candidates(session)
        return {
            "ok": True,
            "session_id": session.id,
            "files": [item.to_dict() for item in session.files],
            "evidence_count": len(session.evidence_rows),
            "candidate_count": len(candidates),
            "candidates": candidates,
        }

    def export_session(
        self,
        session_id: str,
        *,
        intent_override: str = "",
        sample_evidence_limit: int = 3,
    ) -> dict[str, object]:
        session = self._get_session(session_id)
        candidates = self._build_candidates(session, sample_evidence_limit=sample_evidence_limit)
        snapshot_id = str(self.core_facade.build_state()["revision"])
        template = self.rule_catalog.get_llm_export_preferences().get("rules_preferences", "")
        available_routes = self._available_routes()
        return {
            "ok": True,
            "workflow": "log-routing",
            "schema": "subhub.llm.log_routing.v1",
            "generated_at": _utc_now(),
            "session_id": session.id,
            "snapshot_id": snapshot_id,
            "template": template,
            "intent_override": intent_override.strip(),
            "allowed_actions": list(_ALLOWED_ACTION_TYPES),
            "available_routes": available_routes,
            "files": [item.to_dict() for item in session.files],
            "candidates": candidates,
            "prompt": self._build_prompt(
                template=template,
                intent_override=intent_override,
                snapshot_id=snapshot_id,
                candidates=candidates,
                available_routes=available_routes,
            ),
        }

    def preview_patch(
        self,
        session_id: str,
        *,
        snapshot_id: str,
        patch: dict[str, object],
    ) -> dict[str, object]:
        self._get_session(session_id)
        self._assert_snapshot(snapshot_id)
        normalized_patch = self._validate_patch(patch)
        preview = self.core_facade.preview_patch(normalized_patch)
        return {
            "ok": bool(preview.get("ok")),
            "workflow": "log-routing",
            "session_id": session_id,
            "snapshot_id": snapshot_id,
            **preview,
        }

    def apply_patch(
        self,
        session_id: str,
        *,
        snapshot_id: str,
        patch: dict[str, object],
        selected_action_ids: list[str] | None = None,
    ) -> dict[str, object]:
        self._get_session(session_id)
        self._assert_snapshot(snapshot_id)
        normalized_patch = self._validate_patch(patch)
        if selected_action_ids is not None:
            selected = [str(item or "").strip() for item in selected_action_ids if str(item or "").strip()]
            action_map = {str(item.get("id") or ""): item for item in normalized_patch["actions"]}
            if any(item not in action_map for item in selected):
                raise ValueError("invalid selected_action_ids")
            normalized_patch = {
                **normalized_patch,
                "actions": [action_map[item] for item in selected],
            }
        result = self.core_facade.apply_patch(normalized_patch)
        return {
            "ok": bool(result.get("ok")),
            "workflow": "log-routing",
            "session_id": session_id,
            "snapshot_id": snapshot_id,
            **result,
        }

    def _get_session(self, session_id: str) -> LogRoutingSession:
        normalized = _clean_text(session_id)
        with self._lock:
            session = self._sessions.get(normalized)
        if not session:
            raise ValueError("session not found")
        return session

    def _session_payload(self, session: LogRoutingSession) -> dict[str, object]:
        return {
            "session_id": session.id,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
            "file_count": len(session.files),
            "evidence_count": len(session.evidence_rows),
        }

    def _assert_snapshot(self, snapshot_id: str) -> None:
        current = str(self.core_facade.build_state()["revision"])
        if _clean_text(snapshot_id) != current:
            raise ValueError("snapshot drifted, please export again")

    def _available_routes(self) -> list[dict[str, object]]:
        routes = [item for item in self.repo.list_route_contracts() if bool(item.enabled)]
        routes.sort(key=lambda item: (item.sort_order, item.id))
        return [item.to_dict() for item in routes]

    def _validate_patch(self, patch: dict[str, object]) -> dict[str, object]:
        if not isinstance(patch, dict):
            raise ValueError("patch body must be an object")
        if _clean_text(patch.get("schema")) != "subhub.patch.v1":
            raise ValueError("schema must be subhub.patch.v1")
        raw_actions = patch.get("actions")
        if not isinstance(raw_actions, list) or not raw_actions:
            raise ValueError("actions must be a non-empty array")
        allowed_routes = {item.id for item in self.repo.list_route_contracts() if bool(item.enabled)}
        for raw_action in raw_actions:
            if not isinstance(raw_action, dict):
                raise ValueError("each action must be an object")
            action_type = _clean_text(raw_action.get("type"))
            if action_type not in _ALLOWED_ACTION_TYPES:
                raise ValueError(f"unsupported action type: {action_type}")
            if action_type == "set_category_route":
                contract_id = normalize_contract_id(raw_action.get("contract_id"))
                raw_contract = _clean_text(raw_action.get("contract_id"))
                if not raw_contract or not contract_id or contract_id not in allowed_routes:
                    raise ValueError(f"unknown route contract: {raw_contract or raw_action.get('contract_id')}")
        preview = self.core_facade.preview_patch(patch)
        normalized_patch = preview.get("normalized_patch")
        if not normalized_patch:
            blockers = preview.get("blockers") or []
            message = blockers[0]["message"] if blockers else "invalid patch"
            raise ValueError(str(message))
        actions = list(normalized_patch.get("actions") or [])
        if not actions:
            raise ValueError("actions must be a non-empty array")
        for action in actions:
            action_type = _clean_text(action.get("type"))
            if action_type not in _ALLOWED_ACTION_TYPES:
                raise ValueError(f"unsupported action type: {action_type}")
            if action_type == "set_category_route":
                contract_id = normalize_contract_id(action.get("contract_id"))
                if contract_id not in allowed_routes:
                    raise ValueError(f"unknown route contract: {contract_id or action.get('contract_id')}")
        return normalized_patch

    def _parse_upload(self, *, filename: str, content_type: str, content: bytes) -> tuple[str, list[LogEvidenceRow]]:
        if content.startswith(b"SQLite format 3"):
            return "shadowrocket", self._parse_shadowrocket_db(filename, content)
        try:
            parsed = json.loads(content.decode("utf-8"))
        except Exception:
            parsed = None
        if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
            return "surge", self._parse_surge_archive(filename, parsed)
        text = content.decode("utf-8", errors="ignore")
        if "[TCP]" in text or "level=info" in text or "level=debug" in text:
            return "clash", self._parse_clash_log(filename, text)
        raise ValueError(f"unsupported log file: {filename or content_type or 'unknown'}")

    def _parse_surge_archive(self, filename: str, entries: list[dict[str, Any]]) -> list[LogEvidenceRow]:
        rows: list[LogEvidenceRow] = []
        for entry in entries:
            notes = [str(item or "").strip() for item in (entry.get("notes") or []) if str(item or "").strip()]
            matched_rule = ""
            policy_path = ""
            for note in notes:
                rule_match = _SURGE_RULE_RE.search(note)
                if rule_match:
                    matched_rule = _clean_text(rule_match.group(1))
                policy_match = _SURGE_POLICY_PATH_RE.search(note)
                if policy_match:
                    policy_path = _clean_text(policy_match.group(1))
            if matched_rule.upper() != "FINAL":
                continue
            host = _normalize_host(entry.get("remoteHost")) or _extract_host_from_target(entry.get("URL"))
            occurred_at = _clean_text(entry.get("startDate") or entry.get("completedDate"))
            matched_policy = _clean_text(entry.get("policyName"))
            if not matched_policy and policy_path:
                matched_policy = policy_path.split("->")[-1].strip()
            client_info = entry.get("clientInfo") if isinstance(entry.get("clientInfo"), dict) else {}
            rows.append(
                LogEvidenceRow(
                    source_client="surge",
                    source_file=filename or "surge",
                    occurred_at=occurred_at,
                    host=host,
                    root_domain=_root_domain(host),
                    fallback_reason="matched_final",
                    matched_rule=matched_rule,
                    matched_policy=matched_policy,
                    process_name=_clean_text(entry.get("processLocalizedName")),
                    app_name=_clean_text((client_info or {}).get("displayName")),
                    raw_excerpt=_truncate(" | ".join(notes[:4])),
                )
            )
        return rows

    def _parse_clash_log(self, filename: str, text: str) -> list[LogEvidenceRow]:
        rows: list[LogEvidenceRow] = []
        for line in text.splitlines():
            msg_match = _CLASH_MSG_RE.search(line)
            if not msg_match:
                continue
            message = msg_match.group(1)
            if not (message.startswith("[TCP]") or message.startswith("[UDP]")):
                continue
            if " --> " not in message or " match " not in message or " using " not in message:
                continue
            left, rest = message.split(" --> ", 1)
            target_part, rest = rest.split(" match ", 1)
            matched_rule, matched_policy = rest.split(" using ", 1)
            fallback_reason = self._clash_fallback_reason(matched_rule)
            if not fallback_reason:
                continue
            app_name = ""
            if "(" in left and left.endswith(")"):
                app_name = left.rsplit("(", 1)[-1][:-1]
            host = _extract_host_from_target(target_part.rsplit(":", 1)[0] if target_part.count(":") == 1 else target_part)
            timestamp = line.split("]", 1)[0].strip("[")
            rows.append(
                LogEvidenceRow(
                    source_client="clash",
                    source_file=filename or "clash.log",
                    occurred_at=timestamp,
                    host=host,
                    root_domain=_root_domain(host),
                    fallback_reason=fallback_reason,
                    matched_rule=_clean_text(matched_rule),
                    matched_policy=_clean_text(matched_policy),
                    process_name=_clean_text(app_name),
                    app_name=_clean_text(app_name),
                    raw_excerpt=_truncate(message),
                )
            )
        return rows

    def _clash_fallback_reason(self, matched_rule: str) -> str:
        normalized = _clean_text(matched_rule)
        if not normalized:
            return ""
        lowered = normalized.lower()
        if lowered == "match":
            return "default_match"
        if lowered == "final":
            return "matched_final"
        return ""

    def _parse_shadowrocket_db(self, filename: str, content: bytes) -> list[LogEvidenceRow]:
        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(prefix="shadowrocket-", suffix=".db", delete=False) as handle:
                handle.write(content)
                temp_path = handle.name
            conn = sqlite3.connect(temp_path)
            conn.row_factory = sqlite3.Row
            rows: list[LogEvidenceRow] = []
            try:
                for entry in conn.execute(_SHADOWROCKET_SQL):
                    matched_rule, matched_policy = self._parse_shadowrocket_result(entry["c2result"])
                    if matched_rule.upper() != "FINAL":
                        continue
                    host = _extract_host_from_target(entry["c0url"])
                    rows.append(
                        LogEvidenceRow(
                            source_client="shadowrocket",
                            source_file=filename or "shadowrocket.db",
                            occurred_at=_clean_text(entry["c4created"]),
                            host=host,
                            root_domain=_root_domain(host),
                            fallback_reason="matched_final",
                            matched_rule=matched_rule,
                            matched_policy=matched_policy,
                            process_name="",
                            app_name=_clean_text(entry["c3type"]),
                            raw_excerpt=_truncate(
                                f"{_clean_text(entry['c0url'])} | {_clean_text(entry['c2result'])} | {_clean_text(entry['c1ua'])}"
                            ),
                        )
                    )
            finally:
                conn.close()
            return rows
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def _parse_shadowrocket_result(self, value: object) -> tuple[str, str]:
        text = _clean_text(value)
        if not text:
            return "", ""
        parts = [item.strip() for item in text.split(",") if item.strip()]
        if len(parts) == 1:
            return parts[0], ""
        return ",".join(parts[:-1]), parts[-1]

    def _build_candidates(
        self,
        session: LogRoutingSession,
        *,
        sample_evidence_limit: int = 3,
    ) -> list[dict[str, object]]:
        rule_index = self._rule_index()
        grouped: dict[str, list[LogEvidenceRow]] = defaultdict(list)
        for row in session.evidence_rows:
            if row.root_domain:
                grouped[row.root_domain].append(row)

        candidates: list[dict[str, object]] = []
        for root_domain, rows in grouped.items():
            hosts = sorted({item.host for item in rows if item.host})
            existing = self._match_existing_rule(hosts=hosts, root_domain=root_domain, rule_index=rule_index)
            candidates.append(
                {
                    "root_domain": root_domain,
                    "hosts": hosts,
                    "hit_count": len(rows),
                    "fallback_hits": len(rows),
                    "observed_rules": sorted({item.matched_rule for item in rows if item.matched_rule}),
                    "observed_policies": sorted({item.matched_policy for item in rows if item.matched_policy}),
                    "sample_evidence": [item.to_dict() for item in rows[:sample_evidence_limit]],
                    "existing_category": existing["existing_category"],
                    "existing_route": existing["existing_route"],
                    "existing_route_display_name": contract_display_name(existing["existing_route"]),
                    "current_match_status": existing["current_match_status"],
                    "suggested_category_name": existing["existing_category"] or _category_name_from_domain(root_domain),
                }
            )
        candidates.sort(key=lambda item: (-int(item["fallback_hits"]), str(item["root_domain"])))
        return candidates

    def _rule_index(self) -> dict[str, object]:
        categories = {item.name: item for item in self.repo.list_rule_categories()}
        bindings = {item.category_name: item for item in self.repo.list_service_catalog_entries()}
        rules: list[dict[str, str]] = []
        for category in categories.values():
            for custom_rule in self.repo.list_custom_rules(category_name=category.name):
                rules.append(
                    {
                        "category": category.name,
                        "rule_type": custom_rule.rule_type,
                        "value": custom_rule.value,
                    }
                )
            for line in self.repo.load_rule_cache(category.name) or []:
                parsed = _parse_rule_line(line)
                if not parsed:
                    continue
                rules.append(
                    {
                        "category": category.name,
                        "rule_type": str(parsed["rule_type"]),
                        "value": str(parsed["value"]),
                    }
                )
        return {
            "categories": categories,
            "bindings": bindings,
            "rules": rules,
        }

    def _match_existing_rule(
        self,
        *,
        hosts: list[str],
        root_domain: str,
        rule_index: dict[str, object],
    ) -> dict[str, str]:
        best_match: dict[str, str] | None = None
        best_score = -1
        candidates = list(hosts)
        if root_domain and root_domain not in candidates:
            candidates.append(root_domain)
        for domain in candidates:
            for rule in rule_index["rules"]:
                score = _rule_match_score(str(rule["rule_type"]), str(rule["value"]), domain)
                if score > best_score:
                    best_score = score
                    best_match = {
                        "category": str(rule["category"]),
                    }
        if not best_match:
            return {
                "existing_category": "",
                "existing_route": "",
                "current_match_status": "fallback_only",
            }
        category_name = best_match["category"]
        categories: dict[str, Any] = rule_index["categories"]  # type: ignore[assignment]
        bindings: dict[str, ServiceCatalogEntry] = rule_index["bindings"]  # type: ignore[assignment]
        category = categories.get(category_name)
        binding = bindings.get(category_name)
        states = _derive_rule_category_states(category)
        current_directness = str((states.get("effective_state") or {}).get("directness") or "")
        catalog_group = binding.catalog_group if binding else ""
        effective_route = effective_contract_id(
            stored_contract_id=binding.contract_id if binding else "",
            catalog_group_mode=BUSINESS_GROUP_MODE_STANDARD if not catalog_group else BUSINESS_GROUP_MODE_STANDARD,
            current_directness=current_directness,
        )
        return {
            "existing_category": category_name,
            "existing_route": effective_route,
            "current_match_status": "matched_existing_rule",
        }

    def _build_prompt(
        self,
        *,
        template: str,
        intent_override: str,
        snapshot_id: str,
        candidates: list[dict[str, object]],
        available_routes: list[dict[str, object]],
    ) -> str:
        route_lines = [
            f"- {item['id']} | {item['display_name']} | primary={','.join(item.get('primary_pools', [])) or 'none'} | fallback={','.join(item.get('fallback_pools', [])) or 'none'}"
            for item in available_routes
        ]
        candidate_lines = []
        for item in candidates[:60]:
            hosts = ", ".join(item["hosts"][:5]) if isinstance(item.get("hosts"), list) else ""
            rules = ", ".join(item["observed_rules"][:3]) if isinstance(item.get("observed_rules"), list) else ""
            policies = ", ".join(item["observed_policies"][:3]) if isinstance(item.get("observed_policies"), list) else ""
            category = item["existing_category"] or "none"
            route_name = item["existing_route"] or "none"
            candidate_lines.append(
                f"- {item['root_domain']} | hits={item['fallback_hits']} | hosts={hosts} | current_category={category} | current_route={route_name} | observed_rules={rules} | observed_policies={policies}"
            )

        instructions = [
            "你是 SubHub 的日志分流审核器。",
            "任务：只根据下面这些“兜底命中 / FINAL / 默认规则命中”的候选，输出一个 subhub.patch.v1 JSON 对象。",
            f"snapshot_id/base_revision: {snapshot_id}",
            "只允许这些 action types：ensure_manual_category, set_category_route, add_category_rule, remove_category_rule。",
            "不要输出解释文字，不要输出 Markdown，不要输出代码块，只返回 JSON。",
            "优先复用已有分类；只有无法复用时才创建手工分类。",
            "每个候选如果需要落库，必须同时有分类归属和目标 route。",
            "新增域名规则优先使用 DOMAIN-SUFFIX；只有明确需要更细粒度时才用 DOMAIN。",
            "不要为纯 IP 目标生成域名规则。",
            f"可用 route:\n{chr(10).join(route_lines) if route_lines else '- none'}",
            f"候选列表:\n{chr(10).join(candidate_lines) if candidate_lines else '- none'}",
        ]
        if template:
            instructions.append(f"系统 routing 偏好:\n{template}")
        if _clean_text(intent_override):
            instructions.append(f"本次补充说明:\n{intent_override.strip()}")
        instructions.append(
            """输出示例：
{
  "schema": "subhub.patch.v1",
  "base_revision": "<snapshot_id>",
  "actions": [
    {
      "id": "example-category",
      "type": "ensure_manual_category",
      "name": "Example",
      "default_policy": "group",
      "default_group": "中等质量",
      "locked": false
    },
    {
      "id": "example-route",
      "type": "set_category_route",
      "category": "Example",
      "contract_id": "medium"
    },
    {
      "id": "example-rule",
      "type": "add_category_rule",
      "category": "Example",
      "rule_type": "DOMAIN-SUFFIX",
      "value": "example.com"
    }
  ]
}"""
        )
        return "\n\n".join(instructions)
