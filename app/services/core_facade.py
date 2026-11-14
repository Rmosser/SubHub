from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.models import (
    BUSINESS_GROUP_MODE_STANDARD,
    CONTRACT_AD_BLOCK,
    CONTRACT_CHAIN_HOME,
    CONTRACT_DIRECT,
    ROUTE_DIRECT_ACTION,
    ROUTE_REJECT_ACTION,
    DEFAULT_STANDARD_SOURCE_PULL_NETWORK_MODE,
    QUALITY_GROUPS,
    QUALITY_HIGH_AIRPORT,
    RULE_CATEGORY_TYPE_AUTO,
    RULE_CATEGORY_TYPE_MANUAL,
    RULE_DIRECTNESS_CHOICES,
    RULE_DIRECTNESS_DIRECT,
    RULE_DIRECTNESS_PROXY,
    RULE_LOCK_SOURCE_MANUAL,
    RULE_LOCK_SOURCE_SYSTEM,
    STANDARD_SOURCE_INGEST_KINDS,
    STANDARD_SOURCE_INGEST_MANUAL_NODES,
    STANDARD_SOURCE_INGEST_REMOTE_SUBSCRIPTION,
    STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT,
    STANDARD_SOURCE_MODE_ROUTE_CONTRACT,
    STANDARD_SOURCE_PULL_NETWORK_MODES,
    CustomRule,
    GoRelaySource,
    RouteContract,
    RuleCategory,
    ServiceCatalogEntry,
    StandardSource,
    contract_display_name,
    contract_legacy_group,
    effective_contract_id,
    effective_contract_source,
    normalize_contract_id,
    normalize_standard_source_ingest_kind,
)
from app.services.hub_service import summarize_refresh_status
from app.services.error_diagnostics import error_detail
from app.services.lazycat_profile import normalize_lazycat_profile_settings
from app.services.rule_catalog import _RULE_TYPES as RULE_TYPES
from app.services.standard_source_resolver import resolve_standard_source_target
from app.services.source_diagnostics import (
    KnownSecrets, known_source_secrets, public_runtime, public_source_status, source_error_signal, source_pull_reasons,
    summarize_pull_errors,
)

_VALID_CATEGORY_RULE_TYPES = set(RULE_TYPES)
_UNREAD = object()  # matcher not read yet in this operation (None means "no values")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_hash(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def _public_rule_group_name(group: object) -> str:
    text = _clean_text(group)
    if not text:
        return ""
    contract_id = normalize_contract_id(text)
    return contract_display_name(contract_id) if contract_id else text


def _route_contracts_by_id(repo) -> dict[str, RouteContract]:
    return {
        str(item.id or "").strip(): item
        for item in repo.list_route_contracts()
        if str(item.id or "").strip()
    }


def _route_contract_display_name(repo, contract_id: object) -> str:
    normalized = normalize_contract_id(contract_id)
    if not normalized:
        return str(contract_id or "").strip()
    contract = _route_contracts_by_id(repo).get(normalized)
    if contract and str(contract.display_name or "").strip():
        return str(contract.display_name).strip()
    return contract_display_name(normalized)


def _route_contract_display_name_map(repo) -> dict[str, str]:
    return {
        contract_id: str(contract.display_name or "").strip()
        for contract_id, contract in _route_contracts_by_id(repo).items()
    }


def _eligible_standard_source_contract_ids(repo) -> set[str]:
    return {
        contract.id
        for contract in repo.list_route_contracts()
        if contract.can_bind_standard_source()
    }


def _normalize_standard_source_target(
    repo,
    *,
    target_contract_id: object = "",
    source_mode: object = "",
    quality_group: object = "",
    existing_source: StandardSource | None = None,
) -> tuple[str, str, str]:
    return resolve_standard_source_target(
        target_contract_id=target_contract_id,
        source_mode=source_mode,
        quality_group=quality_group,
        existing_source=existing_source,
        display_name_map=_route_contract_display_name_map(repo),
        eligible_contract_ids=_eligible_standard_source_contract_ids(repo),
        display_name_for_contract=lambda contract_id: _route_contract_display_name(repo, contract_id),
    )


def _derive_rule_category_states(category: RuleCategory) -> dict[str, object]:
    system_group = _clean_text(category.system_default_group)
    if not system_group and _clean_text(category.system_directness).upper() == RULE_DIRECTNESS_DIRECT:
        system_group = RULE_DIRECTNESS_DIRECT
    system_locked = bool(category.system_default_locked)
    if system_group == RULE_DIRECTNESS_DIRECT:
        system_locked = True

    override_active = bool(category.override_active)
    override_group = _clean_text(category.override_group)
    if category.category_type == RULE_CATEGORY_TYPE_AUTO and not override_active:
        if _clean_text(category.directness_override).upper() == RULE_DIRECTNESS_DIRECT:
            override_active = True
            override_group = RULE_DIRECTNESS_DIRECT
        elif _clean_text(category.directness_override).upper() == RULE_DIRECTNESS_PROXY:
            override_active = True
            assigned = _clean_text(category.assigned_group)
            override_group = assigned if assigned != RULE_DIRECTNESS_DIRECT else ""
        elif _clean_text(category.assigned_group) != system_group:
            override_active = True
            override_group = _clean_text(category.assigned_group)
    if category.category_type != RULE_CATEGORY_TYPE_AUTO:
        override_active = False
        override_group = ""

    effective_group = _clean_text(category.assigned_group)
    if category.category_type == RULE_CATEGORY_TYPE_AUTO:
        expected_group = override_group if override_active else system_group
        if effective_group != expected_group:
            effective_group = expected_group

    effective_locked = bool(category.locked)
    effective_lock_source = _clean_text(category.lock_source)
    if effective_lock_source == RULE_LOCK_SOURCE_MANUAL:
        effective_locked = True
    if (
        category.category_type == RULE_CATEGORY_TYPE_AUTO
        and not override_active
        and system_locked
        and effective_lock_source != RULE_LOCK_SOURCE_MANUAL
    ):
        effective_locked = True
        effective_lock_source = RULE_LOCK_SOURCE_SYSTEM
    if override_active and effective_lock_source == RULE_LOCK_SOURCE_SYSTEM:
        effective_locked = False
        effective_lock_source = ""
    if not effective_locked:
        effective_lock_source = ""

    effective_directness = (
        RULE_DIRECTNESS_DIRECT if effective_group == RULE_DIRECTNESS_DIRECT else RULE_DIRECTNESS_PROXY
    )
    if override_active and effective_group == RULE_DIRECTNESS_DIRECT:
        current_source = "override-direct"
    elif override_active:
        current_source = "override-proxy"
    elif system_group == RULE_DIRECTNESS_DIRECT:
        current_source = "system"
    else:
        current_source = "default-proxy"

    derived_override_directness = ""
    if override_active and effective_group == RULE_DIRECTNESS_DIRECT:
        derived_override_directness = RULE_DIRECTNESS_DIRECT
    elif override_active and system_group == RULE_DIRECTNESS_DIRECT:
        derived_override_directness = RULE_DIRECTNESS_PROXY

    return {
        "system_state": {
            "group": system_group,
            "locked": system_locked,
            "directness": RULE_DIRECTNESS_DIRECT if system_group == RULE_DIRECTNESS_DIRECT else RULE_DIRECTNESS_PROXY,
        },
        "override_state": {
            "active": override_active,
            "group": override_group if override_active else "",
        },
        "effective_state": {
            "group": effective_group,
            "locked": effective_locked,
            "lock_source": effective_lock_source,
            "directness": effective_directness,
        },
        "can_restore_system_default": category.category_type == RULE_CATEGORY_TYPE_AUTO and override_active,
        "current_decision_source": current_source,
        "directness_override": derived_override_directness,
    }


def _public_rule_category_states(states: dict[str, object]) -> dict[str, object]:
    public_states = {
        "system_state": dict(states["system_state"]),
        "override_state": dict(states["override_state"]),
        "effective_state": dict(states["effective_state"]),
        "can_restore_system_default": states["can_restore_system_default"],
        "current_decision_source": states["current_decision_source"],
        "directness_override": states["directness_override"],
    }
    public_states["system_state"]["group"] = _public_rule_group_name(public_states["system_state"]["group"])
    public_states["override_state"]["group"] = _public_rule_group_name(public_states["override_state"]["group"])
    public_states["effective_state"]["group"] = _public_rule_group_name(public_states["effective_state"]["group"])
    return public_states


def _parse_rule_line(line: str) -> dict[str, object] | None:
    parts = [item.strip() for item in _clean_text(line).split(",")]
    if len(parts) < 2:
        return None
    rule_type = parts[0].upper()
    value = parts[1]
    if not rule_type or not value:
        return None
    target = parts[2] if len(parts) >= 3 else ""
    extras = parts[3:] if len(parts) > 3 else []
    return {
        "rule_type": rule_type,
        "value": value,
        "target": target,
        "extras": extras,
    }


def _normalize_category_rule(rule_type: object, value: object) -> tuple[str, str]:
    normalized_rule_type = _clean_text(rule_type).upper()
    normalized_value = _clean_text(value)
    if not normalized_rule_type or not normalized_value:
        raise ValueError("rule_type and value are required")
    if normalized_rule_type not in _VALID_CATEGORY_RULE_TYPES:
        raise ValueError(f"rule_type must be one of: {', '.join(sorted(_VALID_CATEGORY_RULE_TYPES))}")
    return normalized_rule_type, normalized_value


def _normalize_standard_source_payload(
    raw: object,
    *,
    repo,
    existing_source: StandardSource | None = None,
) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ValueError("source must be an object")
    target_contract_id, source_mode, quality_group = _normalize_standard_source_target(
        repo,
        target_contract_id=raw.get("target_contract_id"),
        source_mode=raw.get("source_mode"),
        quality_group=raw.get("quality_group"),
        existing_source=existing_source,
    )
    payload = {
        "id": _clean_text(raw.get("id")),
        "name": _clean_text(raw.get("name")),
        "clash_url": _clean_text(raw.get("clash_url")),
        "shadowrocket_url": _clean_text(raw.get("shadowrocket_url")),
        "surge_url": _clean_text(raw.get("surge_url")),
        "login_url": _clean_text(raw.get("login_url")),
        "quality_group": quality_group,
        "target_contract_id": target_contract_id,
        "source_mode": source_mode,
        "ingest_kind": normalize_standard_source_ingest_kind(raw.get("ingest_kind")),
        "manual_nodes_text": _clean_text(raw.get("manual_nodes_text")),
        "enabled": bool(raw.get("enabled", True)),
        "pull_network_mode": _clean_text(raw.get("pull_network_mode")) or DEFAULT_STANDARD_SOURCE_PULL_NETWORK_MODE,
    }
    if not payload["name"]:
        raise ValueError("source.name is required")
    if payload["ingest_kind"] not in STANDARD_SOURCE_INGEST_KINDS:
        raise ValueError("source.ingest_kind is invalid")
    if payload["ingest_kind"] == STANDARD_SOURCE_INGEST_MANUAL_NODES:
        if payload["source_mode"] != STANDARD_SOURCE_MODE_ROUTE_CONTRACT:
            raise ValueError("manual_nodes ingest only supports route_contract source_mode")
        if not payload["manual_nodes_text"]:
            raise ValueError("source.manual_nodes_text is required for manual_nodes ingest")
        payload["clash_url"] = ""
        payload["shadowrocket_url"] = ""
        payload["surge_url"] = ""
        payload["login_url"] = ""
        payload["pull_network_mode"] = DEFAULT_STANDARD_SOURCE_PULL_NETWORK_MODE
        return payload
    if not payload["clash_url"] or not payload["shadowrocket_url"]:
        raise ValueError("source.clash_url and source.shadowrocket_url are required")
    if payload["pull_network_mode"] not in STANDARD_SOURCE_PULL_NETWORK_MODES:
        raise ValueError("source.pull_network_mode is invalid")
    return payload


def _normalize_gorelay_source_payload(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise ValueError("source must be an object")
    selectors_json = raw.get("selectors_json", "{}")
    selectors_text = selectors_json if isinstance(selectors_json, str) else json.dumps(selectors_json, ensure_ascii=False)
    payload = {
        "id": _clean_text(raw.get("id")),
        "name": _clean_text(raw.get("name")),
        "login_url": _clean_text(raw.get("login_url")),
        "gorelay_username": _clean_text(raw.get("gorelay_username")),
        "gorelay_password": str(raw.get("gorelay_password") or ""),
        "proxy_username": _clean_text(raw.get("proxy_username")),
        "proxy_password": str(raw.get("proxy_password") or ""),
        "selectors_json": selectors_text or "{}",
        "enabled": bool(raw.get("enabled", True)),
    }
    if not payload["name"] or not payload["login_url"] or not payload["gorelay_username"]:
        raise ValueError("source.name, source.login_url and source.gorelay_username are required")
    try:
        parsed = json.loads(payload["selectors_json"])
    except json.JSONDecodeError as exc:
        raise ValueError("source.selectors_json must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("source.selectors_json must be a JSON object")
    payload["selectors_json"] = json.dumps(parsed, ensure_ascii=False)
    return payload


def _rule_match_score(rule_type: str, value: str, domain: str) -> int:
    normalized_domain = _clean_text(domain).lower().strip(".")
    normalized_value = _clean_text(value).lower().strip(".")
    if not normalized_domain or not normalized_value:
        return -1
    if rule_type == "DOMAIN":
        return 400 + len(normalized_value) if normalized_domain == normalized_value else -1
    if rule_type == "DOMAIN-SUFFIX":
        if normalized_domain == normalized_value or normalized_domain.endswith(f".{normalized_value}"):
            return 300 + len(normalized_value)
        return -1
    if rule_type == "DOMAIN-KEYWORD":
        return 200 + len(normalized_value) if normalized_value in normalized_domain else -1
    return -1


def _format_rule_line(rule_type: str, value: str, target: str = "", extras: list[str] | None = None) -> str:
    parts = [rule_type, value]
    if target:
        parts.append(target)
    if extras:
        parts.extend([item for item in extras if item])
    return ",".join(parts)


class CoreFacade:
    def __init__(
        self,
        *,
        settings,
        repo,
        rule_catalog,
        hub_service,
        egress_diagnostics,
        gorelay_service,
    ) -> None:
        self.settings = settings
        self.repo = repo
        self.rule_catalog = rule_catalog
        self.hub_service = hub_service
        self.egress_diagnostics = egress_diagnostics
        self.gorelay_service = gorelay_service

    def _pin_group_modes(self) -> dict[str, str]:
        output: dict[str, str] = {}
        for item in self.repo.list_pin_groups():
            name = _clean_text(item.get("group_name"))
            if not name:
                continue
            output[name] = _clean_text(item.get("mode")) or BUSINESS_GROUP_MODE_STANDARD
        return output

    def _category_payload(
        self,
        category: RuleCategory,
        *,
        binding_by_name: dict[str, ServiceCatalogEntry],
        pin_group_modes: dict[str, str],
    ) -> dict[str, object]:
        states = _derive_rule_category_states(category)
        public_states = _public_rule_category_states(states)
        binding = binding_by_name.get(category.name)
        catalog_group = _clean_text(binding.catalog_group) if binding else ""
        group_mode = pin_group_modes.get(catalog_group, BUSINESS_GROUP_MODE_STANDARD)
        effective_contract = effective_contract_id(
            stored_contract_id=binding.contract_id if binding else "",
            catalog_group_mode=group_mode,
            current_directness=str(states["effective_state"]["directness"]),
        )
        payload = category.to_dict()
        payload["assigned_group"] = public_states["effective_state"]["group"]
        payload["system_state"] = public_states["system_state"]
        payload["override_state"] = public_states["override_state"]
        payload["effective_state"] = public_states["effective_state"]
        payload["current_decision_source"] = public_states["current_decision_source"]
        payload["can_restore_system_default"] = public_states["can_restore_system_default"]
        payload["directness_override"] = public_states["directness_override"]
        payload["effective_contract_id"] = effective_contract
        payload["effective_contract_display_name"] = _route_contract_display_name(self.repo, effective_contract)
        payload["effective_contract_source"] = effective_contract_source(
            stored_contract_id=binding.contract_id if binding else "",
            catalog_group_mode=group_mode,
            current_directness=str(states["effective_state"]["directness"]),
        )
        return payload

    def _gorelay_source_state(self, source: GoRelaySource) -> dict[str, object]:
        latest = self.repo.load_gorelay_latest_account_snapshot(source.id)
        latest_account = latest.account if latest else None
        latest_snapshot_id = latest_account.snapshot_id if latest_account else ""
        active_snapshot_id = self.repo.load_gorelay_active_snapshot_id(source.id) or ""
        payload = source.to_public_dict()
        payload.update(
            {
                "last_refresh_at": latest_account.created_at if latest_account else None,
                "last_refresh_status": latest_account.status if latest_account else "",
                "last_refresh_error": str(latest_account.error or "") if latest_account else "",
                "last_node_count": int(latest_account.node_count if latest_account else 0),
                "last_device_count": int(latest_account.device_count if latest_account else 0),
                "pending_domain_count": len(latest.pending_bindings) if latest else 0,
                "latest_snapshot_id": latest_snapshot_id,
                "active_snapshot_id": active_snapshot_id,
                "active_snapshot_is_latest": not latest_snapshot_id or latest_snapshot_id == active_snapshot_id,
            }
        )
        return payload

    def _standard_source_state(
        self, source: StandardSource, known_secrets: KnownSecrets | object = _UNREAD,
    ) -> dict[str, object]:
        if known_secrets is _UNREAD:
            known_secrets = known_source_secrets(self.repo.list_standard_sources())
        runtime_standard = dict((self.hub_service.runtime.source_status or {}).get("standard") or {})
        runtime_item = public_source_status(dict(runtime_standard.get(source.id) or {}), known_secrets)
        payload = source.to_dict()
        payload["last_pull_error"] = summarize_pull_errors(source.last_pull_error, known_secrets) if source.last_pull_error else ""
        payload["last_pull_reasons"] = source_pull_reasons(source, known_secrets)
        resolved_contract_id = source.resolved_target_contract_id()
        resolved_mode = source.resolved_source_mode()
        if resolved_mode == STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT:
            payload["quality_group"] = QUALITY_HIGH_AIRPORT
            payload["target_contract_id"] = ""
            payload["target_contract_display_name"] = ""
            payload["source_mode"] = STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT
        else:
            display_name = _route_contract_display_name(self.repo, resolved_contract_id)
            payload["quality_group"] = display_name
            payload["target_contract_id"] = resolved_contract_id
            payload["target_contract_display_name"] = display_name
            payload["source_mode"] = STANDARD_SOURCE_MODE_ROUTE_CONTRACT
        payload["cached_node_count"] = len(self.repo.load_standard_node_cache(source.id) or [])
        payload["filtered_technical_count"] = int(runtime_item.get("filtered_technical_count") or 0)
        examples = runtime_item.get("filtered_technical_examples")
        payload["filtered_technical_examples"] = (
            [str(item or "").strip() for item in examples if _clean_text(item)] if isinstance(examples, list) else []
        )
        warnings = runtime_item.get("warnings")
        payload["pull_warnings"] = [dict(item or {}) for item in warnings] if isinstance(warnings, list) else []
        payload["pull_warning_count"] = int(runtime_item.get("warning_count") or len(payload["pull_warnings"]))
        return payload

    def build_state(self) -> dict[str, object]:
        categories = sorted(self.repo.list_rule_categories(), key=lambda item: item.name)
        bindings = self.repo.list_service_catalog_entries()
        binding_by_name = {item.category_name: item for item in bindings}
        pin_group_modes = self._pin_group_modes()
        category_items = [
            self._category_payload(item, binding_by_name=binding_by_name, pin_group_modes=pin_group_modes)
            for item in categories
        ]

        category_rules: list[dict[str, object]] = []
        for category in categories:
            custom_rules = sorted(
                self.repo.list_custom_rules(category_name=category.name),
                key=lambda item: (item.rule_type, item.value, item.id),
            )
            for rule in custom_rules:
                category_rules.append(
                    {
                        "category_name": category.name,
                        "source_kind": "custom",
                        "rule_type": rule.rule_type,
                        "value": rule.value,
                        "rule_line": _format_rule_line(rule.rule_type, rule.value),
                    }
                )
            if category.category_type != RULE_CATEGORY_TYPE_AUTO:
                continue
            for line in self.repo.load_rule_cache(category.name) or []:
                parsed = _parse_rule_line(line)
                if not parsed:
                    continue
                category_rules.append(
                    {
                        "category_name": category.name,
                        "source_kind": "catalog",
                        "rule_type": parsed["rule_type"],
                        "value": parsed["value"],
                        "target": parsed["target"],
                        "extras": list(parsed["extras"]),
                        "rule_line": line,
                    }
                )

        # One source read and one matcher for the whole state document.
        configured_sources = self.repo.list_standard_sources()
        known_secrets = known_source_secrets(configured_sources)
        standard_sources = [
            self._standard_source_state(item, known_secrets)
            for item in sorted(configured_sources, key=lambda source: source.id)
        ]
        gorelay_sources = [
            self._gorelay_source_state(item)
            for item in sorted(self.repo.list_gorelay_sources(), key=lambda source: source.id)
        ]
        refresh_policy = {
            **self.rule_catalog.get_refresh_policy(),
            **self.hub_service.get_standard_source_refresh_policy(),
        }
        lazycat_profile = normalize_lazycat_profile_settings(self.repo.load_lazycat_profile_settings() or {})
        base_payload = {
            "schema": "subhub.state.v1",
            "sources": {
                "standard": standard_sources,
                "gorelay": gorelay_sources,
            },
            "routing": {
                "categories": category_items,
                "category_rules": category_rules,
                "service_catalog": [item.to_dict() for item in sorted(bindings, key=lambda entry: entry.category_name)],
                "contracts": [item.to_dict() for item in self.repo.list_route_contracts()],
            },
            "profiles": {
                "lazycat": lazycat_profile,
            },
            "settings": {
                "refresh_policy": refresh_policy,
            },
        }
        payload = dict(base_payload)
        payload["generated_at"] = _now()
        payload["revision"] = _stable_hash(base_payload)
        return payload

    def _current_revision(self) -> str:
        return str(self.build_state()["revision"])

    def _normalize_patch(self, payload: dict[str, object]) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("patch body must be an object")
        if _clean_text(payload.get("schema")) != "subhub.patch.v1":
            raise ValueError("schema must be subhub.patch.v1")
        actions = payload.get("actions")
        if not isinstance(actions, list) or not actions:
            raise ValueError("actions must be a non-empty array")
        normalized_actions: list[dict[str, object]] = []
        for raw_action in actions:
            if not isinstance(raw_action, dict):
                raise ValueError("each action must be an object")
            action_id = _clean_text(raw_action.get("id"))
            action_type = _clean_text(raw_action.get("type"))
            if not action_id or not action_type:
                raise ValueError("each action requires id and type")
            action: dict[str, object] = {"id": action_id, "type": action_type}
            if action_type == "ensure_manual_category":
                default_policy = _clean_text(raw_action.get("default_policy")).lower() or "proxy"
                default_group = _clean_text(raw_action.get("default_group"))
                if default_policy not in {"direct", "proxy", "group"}:
                    raise ValueError("default_policy must be direct, proxy or group")
                if default_policy == "group" and default_group not in QUALITY_GROUPS:
                    raise ValueError("default_group must be one of quality groups")
                if default_policy != "group":
                    default_group = ""
                action.update(
                    {
                        "name": _clean_text(raw_action.get("name")),
                        "default_policy": default_policy,
                        "default_group": default_group,
                        "locked": bool(raw_action.get("locked", False)),
                    }
                )
                if not action["name"]:
                    raise ValueError("ensure_manual_category.name is required")
            elif action_type == "rename_manual_category":
                action.update(
                    {
                        "name": _clean_text(raw_action.get("name")),
                        "new_name": _clean_text(raw_action.get("new_name")),
                    }
                )
                if not action["name"] or not action["new_name"]:
                    raise ValueError("rename_manual_category requires name and new_name")
            elif action_type == "delete_manual_category":
                action["name"] = _clean_text(raw_action.get("name"))
                if not action["name"]:
                    raise ValueError("delete_manual_category.name is required")
            elif action_type in {"add_category_rule", "remove_category_rule"}:
                rule_type, value = _normalize_category_rule(raw_action.get("rule_type"), raw_action.get("value"))
                action.update(
                    {
                        "category": _clean_text(raw_action.get("category")),
                        "rule_type": rule_type,
                        "value": value,
                    }
                )
                if not action["category"]:
                    raise ValueError(f"{action_type}.category is required")
            elif action_type == "set_category_route":
                contract_id = normalize_contract_id(raw_action.get("contract_id"))
                if not contract_id:
                    raise ValueError("set_category_route.contract_id is required")
                action.update(
                    {
                        "category": _clean_text(raw_action.get("category")),
                        "contract_id": contract_id,
                    }
                )
                if not action["category"]:
                    raise ValueError("set_category_route.category is required")
            elif action_type == "set_category_lock":
                action.update(
                    {
                        "category": _clean_text(raw_action.get("category")),
                        "locked": bool(raw_action.get("locked")),
                    }
                )
                if not action["category"]:
                    raise ValueError("set_category_lock.category is required")
            elif action_type == "set_category_directness":
                directness = _clean_text(raw_action.get("directness")).upper()
                if directness not in {"", *RULE_DIRECTNESS_CHOICES}:
                    raise ValueError("set_category_directness.directness must be DIRECT, PROXY or empty")
                action.update(
                    {
                        "category": _clean_text(raw_action.get("category")),
                        "directness": directness,
                    }
                )
                if not action["category"]:
                    raise ValueError("set_category_directness.category is required")
            elif action_type == "set_service_catalog_binding":
                contract_id = normalize_contract_id(raw_action.get("contract_id"))
                if not contract_id:
                    raise ValueError("set_service_catalog_binding.contract_id is required")
                action.update(
                    {
                        "category": _clean_text(raw_action.get("category")),
                        "contract_id": contract_id,
                        "catalog_group": (
                            _clean_text(raw_action.get("catalog_group"))
                            if "catalog_group" in raw_action
                            else None
                        ),
                        "sort_order": (
                            int(raw_action.get("sort_order") or 0)
                            if "sort_order" in raw_action
                            else None
                        ),
                    }
                )
                if not action["category"]:
                    raise ValueError("set_service_catalog_binding.category is required")
            elif action_type == "upsert_standard_source":
                raw_source = raw_action.get("source")
                existing_source = None
                if isinstance(raw_source, dict):
                    source_id = _clean_text(raw_source.get("id"))
                    if source_id:
                        existing_source = self.repo.get_standard_source(source_id)
                action["source"] = _normalize_standard_source_payload(
                    raw_source,
                    repo=self.repo,
                    existing_source=existing_source,
                )
            elif action_type == "delete_standard_source":
                action["source_id"] = _clean_text(raw_action.get("source_id"))
                if not action["source_id"]:
                    raise ValueError("delete_standard_source.source_id is required")
            elif action_type == "upsert_gorelay_source":
                action["source"] = _normalize_gorelay_source_payload(raw_action.get("source"))
            elif action_type == "delete_gorelay_source":
                action["source_id"] = _clean_text(raw_action.get("source_id"))
                if not action["source_id"]:
                    raise ValueError("delete_gorelay_source.source_id is required")
            elif action_type == "set_lazycat_profile":
                settings = raw_action.get("settings")
                if not isinstance(settings, dict):
                    raise ValueError("set_lazycat_profile.settings must be an object")
                action["settings"] = normalize_lazycat_profile_settings(settings)
            elif action_type == "set_refresh_policy":
                action["item"] = {
                    "rule_catalog_cache_hours": int(raw_action.get("rule_catalog_cache_hours") or 24),
                    "cn_cache_hours": int(raw_action.get("cn_cache_hours") or 24),
                    "standard_source_auto_pull_enabled": raw_action.get("standard_source_auto_pull_enabled"),
                    "standard_source_auto_pull_interval_minutes": raw_action.get(
                        "standard_source_auto_pull_interval_minutes"
                    ),
                }
            else:
                raise ValueError(f"unsupported action type: {action_type}")
            normalized_actions.append(action)
        return {
            "schema": "subhub.patch.v1",
            "base_revision": _clean_text(payload.get("base_revision")),
            "actions": normalized_actions,
        }

    def _preview_context(self) -> dict[str, object]:
        categories = {item.name: item for item in self.repo.list_rule_categories()}
        custom_rules = {
            name: {
                (rule.rule_type, rule.value)
                for rule in self.repo.list_custom_rules(category_name=name)
            }
            for name in categories
        }
        return {
            "categories": categories,
            "custom_rules": custom_rules,
            "bindings": {item.category_name: item for item in self.repo.list_service_catalog_entries()},
            "standard_sources": {item.id: item for item in self.repo.list_standard_sources()},
            "gorelay_sources": {item.id: item for item in self.repo.list_gorelay_sources()},
            "lazycat_profile": normalize_lazycat_profile_settings(self.repo.load_lazycat_profile_settings() or {}),
            "refresh_policy": {
                **self.rule_catalog.get_refresh_policy(),
                **self.hub_service.get_standard_source_refresh_policy(),
            },
        }

    def preview_patch(self, payload: dict[str, object]) -> dict[str, object]:
        current_revision = self._current_revision()
        try:
            normalized_patch = self._normalize_patch(payload)
        except ValueError as exc:
            return {
                "schema": "subhub.preview.v1",
                "ok": False,
                "current_revision": current_revision,
                "normalized_patch": None,
                "changes": [],
                "warnings": [],
                "blockers": [
                    {
                        "code": "invalid_patch",
                        "message": str(exc),
                    }
                ],
            }

        blockers: list[dict[str, object]] = []
        warnings: list[dict[str, object]] = []
        if normalized_patch["base_revision"] and normalized_patch["base_revision"] != current_revision:
            blockers.append(
                {
                    "code": "revision_mismatch",
                    "message": "base_revision does not match current state revision",
                }
            )

        ctx = self._preview_context()
        changes: list[dict[str, object]] = []
        for action in normalized_patch["actions"]:
            action_id = str(action["id"])
            action_type = str(action["type"])
            result = self._preview_action(ctx, action)
            changes.append(
                {
                    "id": action_id,
                    "type": action_type,
                    "status": result["status"],
                    "summary": result["summary"],
                }
            )
            for blocker in result.get("blockers", []):
                blockers.append({"id": action_id, "type": action_type, **blocker})
            for warning in result.get("warnings", []):
                warnings.append({"id": action_id, "type": action_type, **warning})

        return {
            "schema": "subhub.preview.v1",
            "ok": not blockers,
            "current_revision": current_revision,
            "normalized_patch": normalized_patch,
            "changes": changes,
            "warnings": warnings,
            "blockers": blockers,
        }

    def _preview_action(self, ctx: dict[str, object], action: dict[str, object]) -> dict[str, object]:
        action_type = str(action["type"])
        categories: dict[str, RuleCategory] = ctx["categories"]  # type: ignore[assignment]
        custom_rules: dict[str, set[tuple[str, str]]] = ctx["custom_rules"]  # type: ignore[assignment]
        bindings: dict[str, ServiceCatalogEntry] = ctx["bindings"]  # type: ignore[assignment]
        standard_sources: dict[str, StandardSource] = ctx["standard_sources"]  # type: ignore[assignment]
        gorelay_sources: dict[str, GoRelaySource] = ctx["gorelay_sources"]  # type: ignore[assignment]

        if action_type == "ensure_manual_category":
            name = str(action["name"])
            existing = categories.get(name)
            if existing and existing.category_type == RULE_CATEGORY_TYPE_MANUAL:
                return {"status": "noop", "summary": f"manual category {name} already exists"}
            if existing:
                return {
                    "status": "blocked",
                    "summary": f"category {name} conflicts with existing auto category",
                    "blockers": [{"code": "category_exists_auto", "message": f"{name} already exists as auto category"}],
                }
            assigned_group = ""
            if action["default_policy"] == "direct":
                assigned_group = RULE_DIRECTNESS_DIRECT
            elif action["default_policy"] == "group":
                assigned_group = str(action["default_group"])
            category = RuleCategory(
                name=name,
                assigned_group=assigned_group,
                rule_count=0,
                rule_source="manual",
                category_type=RULE_CATEGORY_TYPE_MANUAL,
                locked=bool(action["locked"]),
                system_directness=RULE_DIRECTNESS_DIRECT if assigned_group == RULE_DIRECTNESS_DIRECT else RULE_DIRECTNESS_PROXY,
                system_default_group=assigned_group,
                system_default_locked=bool(action["locked"]),
                lock_source=RULE_LOCK_SOURCE_MANUAL if bool(action["locked"]) else "",
            )
            categories[name] = category
            custom_rules.setdefault(name, set())
            return {"status": "planned", "summary": f"create manual category {name}"}

        if action_type == "rename_manual_category":
            name = str(action["name"])
            new_name = str(action["new_name"])
            existing = categories.get(name)
            if not existing:
                return {
                    "status": "blocked",
                    "summary": f"manual category {name} not found",
                    "blockers": [{"code": "category_not_found", "message": f"{name} not found"}],
                }
            if existing.category_type != RULE_CATEGORY_TYPE_MANUAL:
                return {
                    "status": "blocked",
                    "summary": f"{name} is not a manual category",
                    "blockers": [{"code": "category_not_manual", "message": f"{name} is not a manual category"}],
                }
            if new_name in categories:
                return {
                    "status": "blocked",
                    "summary": f"target category {new_name} already exists",
                    "blockers": [{"code": "category_already_exists", "message": f"{new_name} already exists"}],
                }
            updated = RuleCategory(**existing.to_dict())
            updated.name = new_name
            categories.pop(name, None)
            categories[new_name] = updated
            custom_rules[new_name] = custom_rules.pop(name, set())
            if name in bindings:
                binding = bindings.pop(name)
                bindings[new_name] = ServiceCatalogEntry(
                    category_name=new_name,
                    catalog_group=binding.catalog_group,
                    contract_id=binding.contract_id,
                    sort_order=binding.sort_order,
                    source=binding.source,
                    updated_at=binding.updated_at,
                )
            return {"status": "planned", "summary": f"rename manual category {name} to {new_name}"}

        if action_type == "delete_manual_category":
            name = str(action["name"])
            existing = categories.get(name)
            if not existing:
                return {"status": "noop", "summary": f"manual category {name} already absent"}
            if existing.category_type != RULE_CATEGORY_TYPE_MANUAL:
                return {
                    "status": "blocked",
                    "summary": f"{name} is not a manual category",
                    "blockers": [{"code": "category_not_manual", "message": f"{name} is not a manual category"}],
                }
            categories.pop(name, None)
            custom_rules.pop(name, None)
            bindings.pop(name, None)
            return {"status": "planned", "summary": f"delete manual category {name}"}

        if action_type in {"add_category_rule", "remove_category_rule"}:
            category_name = str(action["category"])
            existing = categories.get(category_name)
            if not existing:
                return {
                    "status": "blocked",
                    "summary": f"category {category_name} not found",
                    "blockers": [{"code": "category_not_found", "message": f"{category_name} not found"}],
                }
            rule_key = (str(action["rule_type"]), str(action["value"]))
            known_rules = custom_rules.setdefault(category_name, set())
            if action_type == "add_category_rule":
                if rule_key in known_rules:
                    return {"status": "noop", "summary": f"{category_name} already has rule {rule_key[0]},{rule_key[1]}"}
                known_rules.add(rule_key)
                return {"status": "planned", "summary": f"add rule {rule_key[0]},{rule_key[1]} to {category_name}"}
            if rule_key not in known_rules:
                return {"status": "noop", "summary": f"rule {rule_key[0]},{rule_key[1]} already absent from {category_name}"}
            known_rules.remove(rule_key)
            return {"status": "planned", "summary": f"remove rule {rule_key[0]},{rule_key[1]} from {category_name}"}

        if action_type == "set_category_route":
            category_name = str(action["category"])
            existing = categories.get(category_name)
            if not existing:
                return {
                    "status": "blocked",
                    "summary": f"category {category_name} not found",
                    "blockers": [{"code": "category_not_found", "message": f"{category_name} not found"}],
                }
            current = bindings.get(category_name)
            if current and current.contract_id == action["contract_id"]:
                return {"status": "noop", "summary": f"{category_name} already routes to {action['contract_id']}"}
            bindings[category_name] = ServiceCatalogEntry(
                category_name=category_name,
                catalog_group=current.catalog_group if current else "",
                contract_id=str(action["contract_id"]),
                sort_order=current.sort_order if current else 0,
                source=current.source if current else "manual",
            )
            return {"status": "planned", "summary": f"route {category_name} to {action['contract_id']}"}

        if action_type == "set_category_lock":
            category_name = str(action["category"])
            existing = categories.get(category_name)
            if not existing:
                return {
                    "status": "blocked",
                    "summary": f"category {category_name} not found",
                    "blockers": [{"code": "category_not_found", "message": f"{category_name} not found"}],
                }
            if bool(existing.locked) == bool(action["locked"]):
                return {"status": "noop", "summary": f"{category_name} lock already {bool(action['locked'])}"}
            existing.locked = bool(action["locked"])
            existing.lock_source = RULE_LOCK_SOURCE_MANUAL if bool(action["locked"]) else ""
            return {"status": "planned", "summary": f"set lock={bool(action['locked'])} for {category_name}"}

        if action_type == "set_category_directness":
            category_name = str(action["category"])
            existing = categories.get(category_name)
            if not existing:
                return {
                    "status": "blocked",
                    "summary": f"category {category_name} not found",
                    "blockers": [{"code": "category_not_found", "message": f"{category_name} not found"}],
                }
            if _clean_text(existing.directness_override).upper() == str(action["directness"]):
                return {"status": "noop", "summary": f"{category_name} directness already {action['directness'] or 'default'}"}
            existing.directness_override = str(action["directness"])
            return {
                "status": "planned",
                "summary": f"set directness of {category_name} to {action['directness'] or 'default'}",
            }

        if action_type == "set_service_catalog_binding":
            category_name = str(action["category"])
            existing = categories.get(category_name)
            if not existing:
                return {
                    "status": "blocked",
                    "summary": f"category {category_name} not found",
                    "blockers": [{"code": "category_not_found", "message": f"{category_name} not found"}],
                }
            current = bindings.get(category_name)
            next_group = current.catalog_group if current and action["catalog_group"] is None else str(action["catalog_group"] or "")
            next_sort = current.sort_order if current and action["sort_order"] is None else int(action["sort_order"] or 0)
            if current and current.contract_id == action["contract_id"] and current.catalog_group == next_group and current.sort_order == next_sort:
                return {"status": "noop", "summary": f"service catalog binding for {category_name} already matches"}
            bindings[category_name] = ServiceCatalogEntry(
                category_name=category_name,
                catalog_group=next_group,
                contract_id=str(action["contract_id"]),
                sort_order=next_sort,
                source=current.source if current else "manual",
            )
            return {"status": "planned", "summary": f"update service catalog binding for {category_name}"}

        if action_type == "upsert_standard_source":
            source_payload = dict(action["source"])
            source_id = _clean_text(source_payload.get("id"))
            if source_id and source_id in standard_sources:
                existing = standard_sources[source_id]
                same = existing.export_config_dict() == {
                    "name": source_payload["name"],
                    "clash_url": source_payload["clash_url"],
                    "shadowrocket_url": source_payload["shadowrocket_url"],
                    "surge_url": source_payload["surge_url"],
                    "login_url": source_payload["login_url"],
                    "quality_group": source_payload["quality_group"],
                    "target_contract_id": source_payload["target_contract_id"],
                    "source_mode": source_payload["source_mode"],
                    "ingest_kind": source_payload["ingest_kind"],
                    "manual_nodes_text": source_payload["manual_nodes_text"],
                    "enabled": bool(source_payload["enabled"]),
                    "pull_network_mode": source_payload["pull_network_mode"],
                }
                if same:
                    return {"status": "noop", "summary": f"standard source {source_id} already matches"}
                standard_sources[source_id] = StandardSource(
                    id=source_id,
                    name=str(source_payload["name"]),
                    clash_url=str(source_payload["clash_url"]),
                    shadowrocket_url=str(source_payload["shadowrocket_url"]),
                    surge_url=str(source_payload["surge_url"]),
                    login_url=str(source_payload["login_url"]),
                    quality_group=str(source_payload["quality_group"]),
                    target_contract_id=str(source_payload["target_contract_id"]),
                    source_mode=str(source_payload["source_mode"]),
                    ingest_kind=str(source_payload["ingest_kind"]),
                    manual_nodes_text=str(source_payload["manual_nodes_text"]),
                    enabled=bool(source_payload["enabled"]),
                    pull_network_mode=str(source_payload["pull_network_mode"]),
                )
                return {"status": "planned", "summary": f"update standard source {source_id}"}
            planned_id = source_id or "<new>"
            return {"status": "planned", "summary": f"create standard source {planned_id}"}

        if action_type == "delete_standard_source":
            source_id = str(action["source_id"])
            if source_id not in standard_sources:
                return {"status": "noop", "summary": f"standard source {source_id} already absent"}
            standard_sources.pop(source_id, None)
            return {"status": "planned", "summary": f"delete standard source {source_id}"}

        if action_type == "upsert_gorelay_source":
            source_payload = dict(action["source"])
            source_id = _clean_text(source_payload.get("id"))
            if source_id and source_id in gorelay_sources:
                existing = gorelay_sources[source_id]
                same = (
                    existing.name == source_payload["name"]
                    and existing.login_url == source_payload["login_url"]
                    and existing.gorelay_username == source_payload["gorelay_username"]
                    and existing.proxy_username == source_payload["proxy_username"]
                    and existing.selectors_json == source_payload["selectors_json"]
                    and bool(existing.enabled) == bool(source_payload["enabled"])
                )
                if same:
                    return {"status": "noop", "summary": f"gorelay source {source_id} already matches"}
                return {"status": "planned", "summary": f"update gorelay source {source_id}"}
            planned_id = source_id or "<new>"
            return {"status": "planned", "summary": f"create gorelay source {planned_id}"}

        if action_type == "delete_gorelay_source":
            source_id = str(action["source_id"])
            if source_id not in gorelay_sources:
                return {"status": "noop", "summary": f"gorelay source {source_id} already absent"}
            gorelay_sources.pop(source_id, None)
            return {"status": "planned", "summary": f"delete gorelay source {source_id}"}

        if action_type == "set_lazycat_profile":
            current = dict(ctx["lazycat_profile"])  # type: ignore[arg-type]
            if current == action["settings"]:
                return {"status": "noop", "summary": "lazycat profile already matches"}
            ctx["lazycat_profile"] = dict(action["settings"])
            return {"status": "planned", "summary": "update lazycat profile"}

        if action_type == "set_refresh_policy":
            current = dict(ctx["refresh_policy"])  # type: ignore[arg-type]
            next_item = dict(action["item"])
            relevant_current = {
                "rule_catalog_cache_hours": int(current.get("rule_catalog_cache_hours") or 0),
                "cn_cache_hours": int(current.get("cn_cache_hours") or 0),
                "standard_source_auto_pull_enabled": current.get("standard_source_auto_pull_enabled"),
                "standard_source_auto_pull_interval_minutes": current.get("standard_source_auto_pull_interval_minutes"),
            }
            if relevant_current == next_item:
                return {"status": "noop", "summary": "refresh policy already matches"}
            ctx["refresh_policy"] = {**current, **next_item}
            return {"status": "planned", "summary": "update refresh policy"}

        return {"status": "blocked", "summary": f"unsupported action {action_type}", "blockers": [{"code": "unsupported_action", "message": action_type}]}

    def apply_patch(self, payload: dict[str, object]) -> dict[str, object]:
        preview = self.preview_patch(payload)
        revision_before = str(preview["current_revision"])
        if not preview["ok"]:
            noop_count = sum(1 for item in preview["changes"] if item["status"] == "noop")
            return {
                "schema": "subhub.apply.v1",
                "ok": False,
                "revision_before": revision_before,
                "revision_after": revision_before,
                "applied_count": 0,
                "noop_count": noop_count,
                "changes": preview["changes"],
                "warnings": preview["warnings"],
                "blockers": preview["blockers"],
            }

        normalized_patch = preview["normalized_patch"]
        applied_count = 0
        noop_count = 0
        changes: list[dict[str, object]] = []
        preview_map = {item["id"]: item for item in preview["changes"]}
        for action in normalized_patch["actions"]:
            change_preview = preview_map[str(action["id"])]
            if change_preview["status"] == "noop":
                noop_count += 1
                changes.append(
                    {
                        "id": action["id"],
                        "status": "noop",
                        "summary": change_preview["summary"],
                    }
                )
                continue
            self._apply_action(action)
            applied_count += 1
            changes.append(
                {
                    "id": action["id"],
                    "status": "applied",
                    "summary": change_preview["summary"],
                }
            )

        revision_after = self._current_revision()
        return {
            "schema": "subhub.apply.v1",
            "ok": True,
            "revision_before": revision_before,
            "revision_after": revision_after,
            "applied_count": applied_count,
            "noop_count": noop_count,
            "changes": changes,
            "warnings": preview["warnings"],
        }

    def _apply_action(self, action: dict[str, object]) -> None:
        action_type = str(action["type"])
        if action_type == "ensure_manual_category":
            assigned_group = ""
            if action["default_policy"] == "direct":
                assigned_group = RULE_DIRECTNESS_DIRECT
            elif action["default_policy"] == "group":
                assigned_group = str(action["default_group"])
            self.repo.create_manual_rule_category(str(action["name"]), assigned_group, locked=bool(action["locked"]))
            return
        if action_type == "rename_manual_category":
            self.repo.rename_manual_rule_category(str(action["name"]), str(action["new_name"]))
            return
        if action_type == "delete_manual_category":
            self.repo.delete_manual_rule_category(str(action["name"]))
            return
        if action_type == "add_category_rule":
            self.repo.save_custom_rule(
                CustomRule(
                    id=uuid4().hex,
                    rule_type=str(action["rule_type"]),
                    value=str(action["value"]),
                    target_group="",
                    category_name=str(action["category"]),
                    created_at=_now(),
                )
            )
            return
        if action_type == "remove_category_rule":
            for item in self.repo.list_custom_rules(category_name=str(action["category"])):
                if item.rule_type == action["rule_type"] and item.value == action["value"]:
                    self.repo.delete_custom_rule(item.id)
            return
        if action_type == "set_category_route":
            existing = self.repo.get_service_catalog_entry(str(action["category"]))
            entry = ServiceCatalogEntry(
                category_name=str(action["category"]),
                catalog_group=existing.catalog_group if existing else "",
                contract_id=str(action["contract_id"]),
                sort_order=existing.sort_order if existing else 0,
                source=existing.source if existing else "manual",
            )
            self.repo.save_service_catalog_entry(entry)
            return
        if action_type == "set_category_lock":
            self.repo.update_rule_category_locked(
                str(action["category"]),
                bool(action["locked"]),
                lock_source=RULE_LOCK_SOURCE_MANUAL if bool(action["locked"]) else "",
            )
            return
        if action_type == "set_category_directness":
            self.repo.update_rule_category_directness_override(str(action["category"]), str(action["directness"]))
            return
        if action_type == "set_service_catalog_binding":
            category_name = str(action["category"])
            existing = self.repo.get_service_catalog_entry(category_name)
            entry = ServiceCatalogEntry(
                category_name=category_name,
                catalog_group=existing.catalog_group if existing and action["catalog_group"] is None else str(action["catalog_group"] or ""),
                contract_id=str(action["contract_id"]),
                sort_order=existing.sort_order if existing and action["sort_order"] is None else int(action["sort_order"] or 0),
                source=existing.source if existing else "manual",
            )
            self.repo.save_service_catalog_entry(entry)
            return
        if action_type == "upsert_standard_source":
            source = dict(action["source"])
            self.repo.save_standard_source(
                StandardSource(
                    id=_clean_text(source.get("id")) or uuid4().hex,
                    name=str(source["name"]),
                    clash_url=str(source["clash_url"]),
                    shadowrocket_url=str(source["shadowrocket_url"]),
                    surge_url=str(source["surge_url"]),
                    login_url=str(source["login_url"]),
                    quality_group=str(source["quality_group"]),
                    target_contract_id=str(source["target_contract_id"]),
                    source_mode=str(source["source_mode"]),
                    ingest_kind=str(source["ingest_kind"]),
                    manual_nodes_text=str(source["manual_nodes_text"]),
                    enabled=bool(source["enabled"]),
                    pull_network_mode=str(source["pull_network_mode"]),
                )
            )
            return
        if action_type == "delete_standard_source":
            self.repo.delete_standard_source(str(action["source_id"]))
            return
        if action_type == "upsert_gorelay_source":
            source = dict(action["source"])
            self.repo.save_gorelay_source(
                GoRelaySource(
                    id=_clean_text(source.get("id")) or uuid4().hex,
                    name=str(source["name"]),
                    login_url=str(source["login_url"]),
                    gorelay_username=str(source["gorelay_username"]),
                    gorelay_password=str(source["gorelay_password"]),
                    proxy_username=str(source["proxy_username"]),
                    proxy_password=str(source["proxy_password"]),
                    selectors_json=str(source["selectors_json"]),
                    enabled=bool(source["enabled"]),
                )
            )
            return
        if action_type == "delete_gorelay_source":
            self.repo.delete_gorelay_source(str(action["source_id"]))
            return
        if action_type == "set_lazycat_profile":
            self.repo.save_lazycat_profile_settings(dict(action["settings"]))
            return
        if action_type == "set_refresh_policy":
            item = dict(action["item"])
            self.rule_catalog.update_refresh_policy(
                rule_catalog_cache_hours=int(item["rule_catalog_cache_hours"]),
                cn_cache_hours=int(item["cn_cache_hours"]),
            )
            self.hub_service.update_standard_source_refresh_policy(
                enabled=item.get("standard_source_auto_pull_enabled"),
                interval_minutes=item.get("standard_source_auto_pull_interval_minutes"),
            )
            return
        raise ValueError(f"unsupported action type: {action_type}")

    async def diagnose_egress(self) -> dict[str, object]:
        payload = await self.egress_diagnostics.get_status(
            gorelay_source_count=len(self.repo.list_gorelay_sources()),
            force=True,
        )
        return {
            "schema": "subhub.diagnose.egress.v1",
            "proxy_bridge": dict(payload.get("proxy_bridge") or {}),
        }

    async def diagnose_source(self, source_id: str) -> dict[str, object]:
        standard = self.repo.get_standard_source(source_id)
        if standard:
            known_secrets = known_source_secrets(self.repo.list_standard_sources())
            last_pull_error = summarize_pull_errors(standard.last_pull_error, known_secrets) if standard.last_pull_error else ""
            runtime_standard = dict((self.hub_service.runtime.source_status or {}).get("standard") or {})
            runtime_item = public_source_status(dict(runtime_standard.get(source_id) or {}), known_secrets)
            attempts = runtime_item.get("attempts")
            attempt_items = list(attempts) if isinstance(attempts, list) else []
            egress = await self.diagnose_egress()
            proxy_bridge = dict(egress.get("proxy_bridge") or {})
            status = "healthy"
            reason = "latest pull succeeded"
            suggested_action = "none"
            error_signal = source_error_signal(last_pull_error)
            if standard.auto_pull_expired or any(code in error_signal for code in ("401", "403", "expired")):
                status = "suspected_expired"
                reason = last_pull_error or "source likely expired"
                suggested_action = "renew or replace the subscription URL"
            elif standard.last_pull_ok is False and "parse" in error_signal:
                status = "parse_failed"
                reason = last_pull_error or "content could not be parsed"
                suggested_action = "check upstream format changes"
            elif (
                standard.last_pull_ok is False
                and any(str(item.get("network_path") or "") == "proxy" for item in attempt_items if isinstance(item, dict))
                and _clean_text(proxy_bridge.get("code")) not in {"", "ok"}
            ):
                status = "egress_failed"
                reason = last_pull_error or "proxy path failed and egress bridge is unhealthy"
                suggested_action = str(proxy_bridge.get("repair_hint") or "repair the proxy bridge")
            elif standard.last_pull_ok is False:
                status = "unavailable"
                reason = last_pull_error or "latest pull failed"
                suggested_action = "retry pull and inspect attempts"
            cached_node_count = len(self.repo.load_standard_node_cache(source_id) or [])
            if standard.last_pull_ok is False and cached_node_count > 0 and status == "unavailable":
                status = "degraded"
                reason = last_pull_error or "latest pull failed but cached nodes remain available"
                suggested_action = "check upstream URL and retry pull"
            return {
                "schema": "subhub.diagnose.source.v1",
                "source_id": standard.id,
                "source_kind": "standard",
                "status": status,
                "pull_network_mode": standard.pull_network_mode,
                "last_pull_ok": standard.last_pull_ok,
                "last_pull_attempt_at": standard.last_pull_attempt_at,
                "last_success_at": standard.last_success_at,
                "last_pull_method": standard.last_pull_method,
                "last_pull_node_count": standard.last_pull_node_count,
                "last_pull_error": last_pull_error,
                "last_pull_reasons": source_pull_reasons(standard, known_secrets),
                "auto_pull_consecutive_failures": standard.auto_pull_consecutive_failures,
                "auto_pull_expired": standard.auto_pull_expired,
                "attempts": attempt_items,
                "reason": reason,
                "suggested_action": suggested_action,
            }

        gorelay = next((item for item in self.repo.list_gorelay_sources() if item.id == source_id), None)
        if not gorelay:
            raise ValueError("source not found")
        latest = self.repo.load_gorelay_latest_account_snapshot(source_id)
        account = latest.account if latest else None
        status = "healthy" if account and account.status != "failed" else "unavailable"
        reason = "latest crawl succeeded" if status == "healthy" else _clean_text(account.error if account else "") or "no successful crawl yet"
        suggested_action = "check gorelay account credentials and egress diagnostics" if status != "healthy" else "none"
        return {
            "schema": "subhub.diagnose.source.v1",
            "source_id": gorelay.id,
            "source_kind": "gorelay",
            "status": status,
            "pull_network_mode": "",
            "last_pull_ok": status == "healthy",
            "last_pull_attempt_at": account.created_at if account else None,
            "last_success_at": account.created_at if status == "healthy" and account else None,
            "last_pull_method": "gorelay",
            "last_pull_node_count": int(account.node_count if account else 0),
            "last_pull_error": _clean_text(account.error if account else ""),
            "auto_pull_consecutive_failures": 0,
            "auto_pull_expired": False,
            "attempts": [],
            "reason": reason,
            "suggested_action": suggested_action,
        }

    def _contract_for_category(self, category_name: str) -> tuple[RouteContract | None, RuleCategory | None, ServiceCatalogEntry | None]:
        category = self.repo.get_rule_category(category_name)
        binding = self.repo.get_service_catalog_entry(category_name)
        if not category:
            return None, None, binding
        pin_group_modes = self._pin_group_modes()
        states = _derive_rule_category_states(category)
        group_mode = pin_group_modes.get(_clean_text(binding.catalog_group if binding else ""), BUSINESS_GROUP_MODE_STANDARD)
        contract_id = effective_contract_id(
            stored_contract_id=binding.contract_id if binding else "",
            catalog_group_mode=group_mode,
            current_directness=str(states["effective_state"]["directness"]),
        )
        if contract_id in {ROUTE_DIRECT_ACTION, ROUTE_REJECT_ACTION}:
            action = "direct" if contract_id == ROUTE_DIRECT_ACTION else "reject"
            return RouteContract(id=contract_id, display_name=contract_display_name(contract_id), routing_action=action, is_system=False), category, binding
        return self.repo.get_route_contract(contract_id), category, binding

    def _pools_payload(self, contract: RouteContract | None, policy_ir) -> tuple[dict[str, object], dict[str, object]]:
        if contract is None:
            return (
                {"primary": [], "fallback": [], "renderable_nodes": {}},
                {"selected_pool": "", "selected_pool_display_name": "", "reason": "missing contract", "fallback_used": False},
            )

        def _renderable_count(pool_id: str) -> int:
            legacy_group = contract_legacy_group(pool_id)
            if legacy_group in QUALITY_GROUPS:
                return len(list(policy_ir.pools.get(legacy_group) or []))
            return len(list(policy_ir.pools.get(pool_id) or []))

        renderable_counts = {
            pool_id: _renderable_count(pool_id)
            for pool_id in [*contract.primary_pools, *contract.fallback_pools]
        }
        selected_pool = ""
        fallback_used = False
        reason = "no renderable nodes in contract pools"
        for pool_id in contract.primary_pools:
            if renderable_counts.get(pool_id, 0) > 0:
                selected_pool = pool_id
                reason = "primary pool has renderable nodes"
                break
        if not selected_pool:
            for pool_id in contract.fallback_pools:
                if renderable_counts.get(pool_id, 0) > 0:
                    selected_pool = pool_id
                    fallback_used = True
                    reason = "primary pool empty"
                    break
        return (
            {
                "primary": list(contract.primary_pools),
                "fallback": list(contract.fallback_pools),
                "renderable_nodes": renderable_counts,
            },
            {
                "selected_pool": selected_pool,
                "selected_pool_display_name": _route_contract_display_name(self.repo, selected_pool) if selected_pool else "",
                "reason": reason,
                "fallback_used": fallback_used,
            },
        )

    async def explain_category(self, category_name: str, *, device_token: str) -> dict[str, object]:
        policy_ir = await self.hub_service.build_policy_ir_for_token(device_token)
        if policy_ir is None:
            raise ValueError("device token not found")
        contract, category, binding = self._contract_for_category(category_name)
        if category is None:
            raise ValueError("category not found")
        states = _derive_rule_category_states(category)
        pin_group_modes = self._pin_group_modes()
        catalog_group = _clean_text(binding.catalog_group if binding else "")
        group_mode = pin_group_modes.get(catalog_group, BUSINESS_GROUP_MODE_STANDARD)
        pools_payload, result_payload = self._pools_payload(contract, policy_ir)
        return {
            "schema": "subhub.explain.category.v1",
            "input": {
                "category": category_name,
                "device": device_token,
            },
            "routing": {
                "effective_contract_id": contract.id if contract else "",
                "effective_contract_display_name": contract.display_name if contract else "",
                "effective_contract_source": effective_contract_source(
                    stored_contract_id=binding.contract_id if binding else "",
                    catalog_group_mode=group_mode,
                    current_directness=str(states["effective_state"]["directness"]),
                ),
                "catalog_group_mode": group_mode,
            },
            "pools": pools_payload,
            "result": result_payload,
        }

    async def explain_domain(self, domain: str, *, device_token: str) -> dict[str, object]:
        policy_ir = await self.hub_service.build_policy_ir_for_token(device_token)
        if policy_ir is None:
            raise ValueError("device token not found")
        normalized_domain = _clean_text(domain).lower().strip(".")
        best_entry = None
        best_score = -1
        for entry in policy_ir.rule_entries:
            score = _rule_match_score(entry.rule_type, entry.value, normalized_domain)
            if score > best_score:
                best_score = score
                best_entry = entry
        if best_entry is None:
            return {
                "schema": "subhub.explain.domain.v1",
                "input": {"domain": normalized_domain, "device": device_token},
                "match": {"matched": False},
                "routing": {"effective_contract_id": policy_ir.default_contract_id},
                "pools": {"primary": [], "fallback": [], "renderable_nodes": {}},
                "result": {"selected_pool": "", "selected_pool_display_name": "", "reason": "no matching rule", "fallback_used": False},
            }
        category_name = _clean_text(best_entry.category_name)
        category_explain = await self.explain_category(category_name, device_token=device_token)
        return {
            "schema": "subhub.explain.domain.v1",
            "input": {"domain": normalized_domain, "device": device_token},
            "match": {
                "matched": True,
                "rule_type": best_entry.rule_type,
                "value": best_entry.value,
                "rule_line": _format_rule_line(
                    best_entry.rule_type,
                    best_entry.value,
                    best_entry.target_display_name(),
                    best_entry.extras,
                ),
                "category": category_name,
            },
            "routing": category_explain["routing"],
            "pools": category_explain["pools"],
            "result": category_explain["result"],
        }

    async def sync(self, *, target: str, source_id: str = "", rule_catalog_mode: str = "incremental") -> dict[str, object]:
        normalized_target = _clean_text(target).lower()
        if normalized_target == "all":
            runtime = await self.hub_service.refresh(force=True, rule_catalog_mode=rule_catalog_mode)
            item = public_runtime(
                runtime.to_dict() if hasattr(runtime, "to_dict") else dict(runtime),
                known_source_secrets(self.repo.list_standard_sources()),
            )
            runtime_status = item.get("source_status") if isinstance(item, dict) else {}
            summary = (
                runtime_status.get("aggregate")
                if isinstance(runtime_status, dict)
                else None
            )
            if not isinstance(summary, dict):
                summary = summarize_refresh_status(runtime_status if isinstance(runtime_status, dict) else {})
            return {
                "schema": "subhub.sync.v1",
                **summary,
                "target": "all",
                "item": item,
            }
        if normalized_target == "rules":
            item = await self.rule_catalog.refresh_categories(force=True, mode=rule_catalog_mode)
            summary = summarize_refresh_status({"rule_catalog": item})
            return {
                "schema": "subhub.sync.v1",
                **summary,
                "target": "rules",
                "item": item,
            }
        if normalized_target == "source":
            safe_source_id = _clean_text(source_id)
            if not safe_source_id:
                raise ValueError("source_id is required for target=source")
            if self.repo.get_standard_source(safe_source_id):
                item = await self.hub_service.refresh_one_standard_source(safe_source_id, trigger="manual")
                summary = summarize_refresh_status({"standard": {safe_source_id: item}})
                return {
                    "schema": "subhub.sync.v1",
                    **summary,
                    "target": "source",
                    "source_kind": "standard",
                    "item": item,
                }
            account = next((item for item in self.gorelay_service.list_accounts() if item.id == safe_source_id), None)
            if account is not None:
                if not account.enabled:
                    raise ValueError("account is disabled")
                try:
                    item = await self.gorelay_service.crawl_account(safe_source_id)
                except Exception as exc:
                    diagnostic = error_detail(exc, "gorelay_account_crawl", uuid4().hex)
                    item = {"ok": False, "account_id": safe_source_id, "error": diagnostic["message"], "error_detail": diagnostic}
                summary = summarize_refresh_status({"gorelay": item})
                return {
                    "schema": "subhub.sync.v1",
                    **summary,
                    "target": "source",
                    "source_kind": "gorelay",
                    "item": item,
                }
            raise ValueError("source not found")
        raise ValueError("target must be all, rules or source")
