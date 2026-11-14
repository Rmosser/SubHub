from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from app.config import Settings
from app.models import (
    BUSINESS_GROUP_MODE_AD_BLOCK,
    BUSINESS_GROUP_MODE_STANDARD,
    BUSINESS_GROUP_MODES,
    CONTRACT_AD_BLOCK,
    CONTRACT_DIRECT,
    ROUTE_ACTION_PROXY,
    normalize_route_action,
    RULE_DIRECTNESS_CHOICES,
    RULE_DIRECTNESS_DIRECT,
    RULE_DIRECTNESS_PROXY,
    RULE_DIRECTNESS_REVIEW_STATUS_PENDING,
    RULE_LOCK_SOURCE_MANUAL,
    RuleCategoryDirectnessReview,
    ServiceCatalogEntry,
    contract_display_name,
    contract_legacy_group,
    effective_contract_id,
    effective_contract_source,
    normalize_contract_id,
)
from app.services.route_contract_views import (
    scenario_contract_description,
    scenario_contract_display_name,
    scenario_contract_llm_routing_intent,
    scenario_default_contract_id,
    scenario_resolve_contract_id,
    scenario_route_contracts,
    scenario_route_contracts_by_id,
)
from app.services.rule_catalog import RuleCatalog
from app.storage.base import Repo

_WORKFLOWS = ("directness", "routing", "grouping")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class LlmWorkflowService:
    def __init__(self, settings: Settings, repo: Repo, rule_catalog: RuleCatalog) -> None:
        self.settings = settings
        self.repo = repo
        self.rule_catalog = rule_catalog

    def _contracts_map(self, *, scenario_id: str = "") -> dict[str, object]:
        return scenario_route_contracts_by_id(self.repo, scenario_id)

    def _contract_display_name(
        self,
        contract_id: object,
        *,
        contracts_map: dict[str, object] | None = None,
        scenario_id: str = "",
    ) -> str:
        normalized = normalize_contract_id(contract_id)
        if not normalized:
            return str(contract_id or "").strip()
        contracts = contracts_map or self._contracts_map(scenario_id=scenario_id)
        contract = contracts.get(normalized)
        if contract and str(getattr(contract, "display_name", "") or "").strip():
            return str(getattr(contract, "display_name", "")).strip()
        return scenario_contract_display_name(self.repo, scenario_id, normalized)

    def _contract_description(
        self,
        contract_id: object,
        *,
        contracts_map: dict[str, object] | None = None,
        scenario_id: str = "",
    ) -> str:
        normalized = normalize_contract_id(contract_id)
        if not normalized:
            return ""
        contracts = contracts_map or self._contracts_map(scenario_id=scenario_id)
        contract = contracts.get(normalized)
        if contract and str(getattr(contract, "description", "") or "").strip():
            return str(getattr(contract, "description", "")).strip()
        return scenario_contract_description(self.repo, scenario_id, normalized)

    def _resolve_contract_id(self, value: object, *, contracts_map: dict[str, object] | None = None, scenario_id: str = "") -> str:
        contracts = contracts_map or self._contracts_map(scenario_id=scenario_id)
        if contracts:
            normalized = scenario_resolve_contract_id(self.repo, scenario_id, value)
            if normalized:
                return normalized
        return scenario_resolve_contract_id(self.repo, scenario_id, value)

    def list_workflows(self) -> list[dict[str, str]]:
        return [
            {"id": "directness", "title": "直连审核", "template_key": "directness_preferences"},
            {"id": "routing", "title": "分类分流", "template_key": "rules_preferences"},
            {"id": "grouping", "title": "目录分组", "template_key": "pins_preferences"},
        ]

    def export_workflow(
        self,
        workflow: str,
        *,
        scenario_id: str = "",
        intent_override: str = "",
        sample_rule_limit: int = 5,
    ) -> dict[str, object]:
        normalized = self._require_workflow(workflow)
        categories = self._category_items(sample_rule_limit=sample_rule_limit, scenario_id=scenario_id)
        templates = self.rule_catalog.get_llm_export_preferences()
        if normalized == "routing":
            target_options = self._routing_target_options(scenario_id=scenario_id)
            fingerprint = self._snapshot_fingerprint(
                normalized,
                {
                    "categories": [
                        {
                            "name": item["name"],
                            "stored_contract_id": item["stored_contract_id"],
                            "effective_contract_id": item["effective_contract_id"],
                            "locked": item["locked"],
                            "current_effective_directness": item["current_effective_directness"],
                        }
                        for item in categories
                    ],
                    "target_options": target_options,
                },
            )
            return {
                "ok": True,
                "workflow": normalized,
                "schema": "subhub.llm.routing.v1",
                "generated_at": _utc_now(),
                "snapshot_fingerprint": fingerprint,
                "template": templates["rules_preferences"],
                "scenario_id": str(scenario_id or "").strip(),
                "intent_override": intent_override.strip(),
                "target_options": target_options,
                "items": categories,
                "prompt": self._routing_prompt(
                    categories=categories,
                    target_options=target_options,
                    template=templates["rules_preferences"],
                    intent_override=intent_override,
                    scenario_id=scenario_id,
                ),
            }
        if normalized == "grouping":
            groups = self._pin_groups(scenario_id=scenario_id)
            fingerprint = self._snapshot_fingerprint(
                normalized,
                {
                    "categories": [
                        {
                            "name": item["name"],
                            "catalog_group": item["catalog_group"],
                            "effective_contract_id": item["effective_contract_id"],
                        }
                        for item in categories
                    ],
                    "groups": groups,
                },
            )
            return {
                "ok": True,
                "workflow": normalized,
                "schema": "subhub.llm.grouping.v1",
                "generated_at": _utc_now(),
                "snapshot_fingerprint": fingerprint,
                "template": templates["pins_preferences"],
                "scenario_id": str(scenario_id or "").strip(),
                "intent_override": intent_override.strip(),
                "groups": groups,
                "items": categories,
                "prompt": self._grouping_prompt(
                    categories=categories,
                    groups=groups,
                    template=templates["pins_preferences"],
                    intent_override=intent_override,
                    scenario_id=scenario_id,
                ),
            }

        fingerprint = self._snapshot_fingerprint(
            normalized,
            {
                "categories": [
                    {
                        "name": item["name"],
                        "current_effective_directness": item["current_effective_directness"],
                        "locked": item["locked"],
                        "lock_source": item["lock_source"],
                    }
                    for item in categories
                ]
            },
        )
        return {
            "ok": True,
            "workflow": normalized,
            "schema": "subhub.llm.directness.v1",
            "generated_at": _utc_now(),
            "snapshot_fingerprint": fingerprint,
            "template": templates["directness_preferences"],
            "scenario_id": str(scenario_id or "").strip(),
            "intent_override": intent_override.strip(),
            "items": categories,
            "prompt": self._directness_prompt(
                categories=categories,
                template=templates["directness_preferences"],
                intent_override=intent_override,
            ),
        }

    def preview_import(self, workflow: str, *, scenario_id: str = "", snapshot_fingerprint: str, result: dict[str, object]) -> dict[str, object]:
        normalized = self._require_workflow(workflow)
        self._assert_snapshot(normalized, snapshot_fingerprint, scenario_id=scenario_id)
        if normalized == "routing":
            return self._preview_routing(result, scenario_id=scenario_id)
        if normalized == "grouping":
            return self._preview_grouping(result, scenario_id=scenario_id)
        return self._preview_directness(result, scenario_id=scenario_id)

    def apply_import(
        self,
        workflow: str,
        *,
        scenario_id: str = "",
        snapshot_fingerprint: str,
        result: dict[str, object],
        selected_change_ids: list[str] | None = None,
    ) -> dict[str, object]:
        normalized = self._require_workflow(workflow)
        self._assert_snapshot(normalized, snapshot_fingerprint, scenario_id=scenario_id)
        if normalized == "routing":
            preview = self._preview_routing(result, scenario_id=scenario_id)
            return self._apply_routing(preview, selected_change_ids=selected_change_ids, scenario_id=scenario_id)
        if normalized == "grouping":
            preview = self._preview_grouping(result, scenario_id=scenario_id)
            return self._apply_grouping(preview, selected_change_ids=selected_change_ids, scenario_id=scenario_id)
        preview = self._preview_directness(result, scenario_id=scenario_id)
        return self._apply_directness(preview, selected_change_ids=selected_change_ids, scenario_id=scenario_id)

    def _require_workflow(self, workflow: str) -> str:
        normalized = str(workflow or "").strip().lower()
        if normalized not in _WORKFLOWS:
            raise ValueError("invalid workflow")
        return normalized

    @staticmethod
    def _change_id(*parts: object) -> str:
        return ":".join(str(part or "").strip() for part in parts if str(part or "").strip())

    @staticmethod
    def _selected_changes(
        preview: dict[str, object],
        selected_change_ids: list[str] | None,
    ) -> list[dict[str, object]]:
        changes = list(preview.get("changes") or [])
        if selected_change_ids is None:
            return changes
        normalized_ids = [str(item or "").strip() for item in selected_change_ids if str(item or "").strip()]
        if not normalized_ids:
            return []
        change_map = {
            str(item.get("change_id") or "").strip(): item
            for item in changes
            if str(item.get("change_id") or "").strip()
        }
        if len(change_map) != len(changes):
            raise ValueError("preview changes missing change_id")
        if any(change_id not in change_map for change_id in normalized_ids):
            raise ValueError("invalid selected_change_ids")
        return [change_map[change_id] for change_id in normalized_ids]

    def _pin_groups(self, *, scenario_id: str = "") -> list[dict[str, object]]:
        safe_scenario_id = str(scenario_id or "").strip() or "scenario-default"
        if safe_scenario_id == "scenario-default":
            return [dict(item) for item in self.repo.list_scenario_pin_groups(safe_scenario_id)]
        merged: dict[str, dict[str, object]] = {
            str(item.get("group_name") or "").strip(): dict(item)
            for item in self.repo.list_scenario_pin_groups("scenario-default")
            if str(item.get("group_name") or "").strip()
        }
        for item in self.repo.list_scenario_pin_groups(safe_scenario_id):
            group_name = str(item.get("group_name") or "").strip()
            if group_name:
                merged[group_name] = dict(item)
        return sorted(
            merged.values(),
            key=lambda item: (int(item.get("sort_order") or 0), str(item.get("group_name") or "").strip()),
        )

    def _pin_groups_map(self, *, scenario_id: str = "") -> dict[str, dict[str, object]]:
        return {
            str(item.get("group_name") or "").strip(): dict(item)
            for item in self._pin_groups(scenario_id=scenario_id)
            if str(item.get("group_name") or "").strip()
        }

    def _catalog_map(self, *, scenario_id: str = "") -> dict[str, ServiceCatalogEntry]:
        safe_scenario_id = str(scenario_id or "").strip() or "scenario-default"
        return {item.category_name: item for item in self.repo.list_scenario_service_catalog_entries(safe_scenario_id)}

    def _pin_map(self, *, scenario_id: str = "") -> dict[str, dict[str, object]]:
        return {
            str(item.get("category_name") or "").strip(): dict(item)
            for item in self.repo.list_scenario_pinned_categories(str(scenario_id or "").strip() or "scenario-default")
            if str(item.get("category_name") or "").strip()
        }

    def _category_items(self, *, sample_rule_limit: int, scenario_id: str = "") -> list[dict[str, object]]:
        safe_scenario_id = str(scenario_id or "").strip() or "scenario-default"
        categories = self.repo.list_scenario_categories(safe_scenario_id)
        categories.sort(key=lambda item: item.name.lower())
        catalog_map = self._catalog_map(scenario_id=safe_scenario_id)
        pin_map = self._pin_map(scenario_id=safe_scenario_id)
        pin_groups = self._pin_groups_map(scenario_id=safe_scenario_id)
        contracts_map = self._contracts_map(scenario_id=safe_scenario_id)
        items: list[dict[str, object]] = []
        for category in categories:
            entry = catalog_map.get(category.name)
            pin = pin_map.get(category.name)
            catalog_group = str(entry.catalog_group or "").strip() if entry else ""
            if not catalog_group:
                catalog_group = str((pin or {}).get("pin_group") or "").strip()
            group_mode = str((pin_groups.get(catalog_group) or {}).get("mode") or BUSINESS_GROUP_MODE_STANDARD)
            current_directness = self.rule_catalog.get_effective_directness(category)
            stored_contract_id = normalize_contract_id(entry.contract_id if entry else "")
            resolved_contract_id = effective_contract_id(
                stored_contract_id=stored_contract_id,
                catalog_group_mode=group_mode,
                current_directness=current_directness,
            )
            items.append(
                {
                    "name": category.name,
                    "rule_count": int(category.rule_count or 0),
                    "sample_rules": list((self.repo.load_rule_cache(category.name) or [])[:sample_rule_limit]),
                    "category_type": category.category_type,
                    "locked": bool(category.locked),
                    "lock_source": str(category.lock_source or ""),
                    "catalog_group": catalog_group,
                    "catalog_group_mode": group_mode,
                    "stored_contract_id": stored_contract_id,
                    "stored_contract_display_name": self._contract_display_name(
                        stored_contract_id,
                        contracts_map=contracts_map,
                        scenario_id=safe_scenario_id,
                    ),
                    "effective_contract_id": resolved_contract_id,
                    "effective_contract_display_name": self._contract_display_name(
                        resolved_contract_id,
                        contracts_map=contracts_map,
                        scenario_id=safe_scenario_id,
                    ),
                    "effective_contract_source": effective_contract_source(
                        stored_contract_id=stored_contract_id,
                        catalog_group_mode=group_mode,
                        current_directness=current_directness,
                    ),
                    "current_effective_directness": current_directness,
                    "system_directness": str(category.system_directness or ""),
                }
            )
        return items

    def _routing_target_options(self, *, scenario_id: str = "") -> list[dict[str, object]]:
        pools = {item.id: item for item in self.repo.list_pool_statuses()}
        contracts_map = self._contracts_map(scenario_id=scenario_id)
        options: list[dict[str, object]] = []
        for contract in scenario_route_contracts(self.repo, scenario_id):
            if normalize_route_action(getattr(contract, "routing_action", ROUTE_ACTION_PROXY)) != ROUTE_ACTION_PROXY:
                continue
            if not bool(contract.enabled):
                continue
            options.append(
                {
                    "contract_id": contract.id,
                    "display_name": self._contract_display_name(contract.id, contracts_map=contracts_map, scenario_id=scenario_id),
                    "description": str(contract.llm_routing_intent or scenario_contract_llm_routing_intent(self.repo, scenario_id, contract.id)).strip(),
                    "strategy_type": contract.strategy_type,
                    "primary_pools": [
                        {
                            "pool_id": pool_id,
                            "display_name": contract_display_name(pool_id),
                            "node_count": int(getattr(pools.get(pool_id), "renderable_node_count", 0) or 0),
                        }
                        for pool_id in contract.primary_pools
                    ],
                    "fallback_pools": [
                        {
                            "pool_id": pool_id,
                            "display_name": contract_display_name(pool_id),
                            "node_count": int(getattr(pools.get(pool_id), "renderable_node_count", 0) or 0),
                        }
                        for pool_id in contract.fallback_pools
                    ],
                }
            )
        return options

    def _snapshot_fingerprint(self, workflow: str, payload: dict[str, object]) -> str:
        raw = json.dumps({"workflow": workflow, "payload": payload}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _assert_snapshot(self, workflow: str, snapshot_fingerprint: str, *, scenario_id: str = "") -> None:
        current = self.export_workflow(workflow, scenario_id=scenario_id, intent_override="", sample_rule_limit=0)
        if str(current["snapshot_fingerprint"]) != str(snapshot_fingerprint or "").strip():
            raise ValueError("snapshot drifted, please export again")

    def _parse_assignments(self, result: dict[str, object]) -> dict[str, object]:
        if isinstance(result.get("assignments"), dict):
            raw = result["assignments"]
        else:
            raw = result
        if not isinstance(raw, dict):
            raise ValueError("result must be a JSON object")
        return {str(key): value for key, value in raw.items()}

    def _preview_routing(self, result: dict[str, object], *, scenario_id: str = "") -> dict[str, object]:
        raw = self._parse_assignments(result)
        current = {item["name"]: item for item in self._category_items(sample_rule_limit=0, scenario_id=scenario_id)}
        allowed_contracts = {item["contract_id"] for item in self._routing_target_options(scenario_id=scenario_id)}
        contracts_map = self._contracts_map(scenario_id=scenario_id)
        changes: list[dict[str, object]] = []
        invalid_items: list[dict[str, str]] = []
        skipped_locked: list[str] = []
        skipped_unchanged: list[str] = []
        normalized: dict[str, str] = {}
        for name, value in raw.items():
            safe_name = str(name or "").strip()
            if not safe_name:
                continue
            item = current.get(safe_name)
            if not item:
                invalid_items.append({"name": safe_name, "reason": "unknown_category"})
                continue
            if item["locked"]:
                skipped_locked.append(safe_name)
                continue
            target = self._resolve_contract_id(value, contracts_map=contracts_map, scenario_id=scenario_id)
            if target not in allowed_contracts:
                invalid_items.append({"name": safe_name, "reason": "invalid_contract"})
                continue
            normalized[safe_name] = target
            if target == item["stored_contract_id"]:
                skipped_unchanged.append(safe_name)
                continue
            changes.append(
                {
                    "change_id": self._change_id("routing", safe_name),
                    "name": safe_name,
                    "from_contract_id": item["stored_contract_id"],
                    "to_contract_id": target,
                    "from_display_name": self._contract_display_name(
                        item["stored_contract_id"],
                        contracts_map=contracts_map,
                        scenario_id=scenario_id,
                    ),
                    "to_display_name": self._contract_display_name(target, contracts_map=contracts_map, scenario_id=scenario_id),
                    "current_effective_directness": item["current_effective_directness"],
                }
            )
        return {
            "ok": True,
            "workflow": "routing",
            "changes": changes,
            "normalized_assignments": normalized,
            "invalid_items": invalid_items,
            "skipped_locked": sorted(skipped_locked),
            "skipped_unchanged": sorted(skipped_unchanged),
        }

    def _apply_routing(
        self,
        preview: dict[str, object],
        *,
        selected_change_ids: list[str] | None = None,
        scenario_id: str = "",
    ) -> dict[str, object]:
        safe_scenario_id = str(scenario_id or "").strip() or "scenario-default"
        current = {item.name: item for item in self.repo.list_scenario_categories(safe_scenario_id)}
        catalog_map = self._catalog_map(scenario_id=safe_scenario_id)
        applied = 0
        applied_changes = self._selected_changes(preview, selected_change_ids)
        for item in applied_changes:
            name = str(item["name"])
            target = str(item["to_contract_id"])
            category = current.get(name)
            current_entry = catalog_map.get(name)
            if category and self.rule_catalog.get_effective_directness(category) != RULE_DIRECTNESS_DIRECT:
                contract = self._contracts_map(scenario_id=safe_scenario_id).get(target)
                legacy_group = contract.primary_legacy_group() if contract else contract_legacy_group(target)
                if legacy_group:
                    if safe_scenario_id == "scenario-default":
                        self.rule_catalog.assign_category(name, legacy_group)
                    else:
                        self.repo.update_scenario_category_assignment(
                            safe_scenario_id,
                            name,
                            legacy_group,
                        )
            if safe_scenario_id == "scenario-default":
                self.repo.save_service_catalog_entry(
                    ServiceCatalogEntry(
                        category_name=name,
                        catalog_group=current_entry.catalog_group if current_entry else "",
                        contract_id=target,
                        sort_order=current_entry.sort_order if current_entry else 0,
                        source="manual",
                    )
                )
            else:
                self.repo.save_scenario_service_catalog_entry(
                    safe_scenario_id,
                    ServiceCatalogEntry(
                        category_name=name,
                        catalog_group=current_entry.catalog_group if current_entry else "",
                        contract_id=target,
                        sort_order=current_entry.sort_order if current_entry else 0,
                        source="manual",
                    ),
                )
            applied += 1
        return {
            "ok": True,
            **preview,
            "applied": applied,
            "applied_change_ids": [str(item.get("change_id") or "") for item in applied_changes],
        }

    def _preview_grouping(self, result: dict[str, object], *, scenario_id: str = "") -> dict[str, object]:
        groups = result.get("groups")
        if not isinstance(groups, list):
            raise ValueError("groups must be a list")
        current_categories = {
            item["name"]: item for item in self._category_items(sample_rule_limit=0, scenario_id=scenario_id)
        }
        current_groups = self._pin_groups_map(scenario_id=scenario_id)
        seen_categories: set[str] = set()
        normalized_groups: list[dict[str, object]] = []
        invalid_items: list[dict[str, str]] = []
        for index, group in enumerate(groups):
            if not isinstance(group, dict):
                invalid_items.append({"name": f"group[{index}]", "reason": "invalid_group"})
                continue
            name = str(group.get("name") or "").strip()
            if not name:
                invalid_items.append({"name": f"group[{index}]", "reason": "empty_group_name"})
                continue
            mode = str(group.get("mode") or BUSINESS_GROUP_MODE_STANDARD).strip() or BUSINESS_GROUP_MODE_STANDARD
            if mode not in BUSINESS_GROUP_MODES:
                invalid_items.append({"name": name, "reason": "invalid_group_mode"})
                continue
            categories = []
            for raw_name in list(group.get("categories") or []):
                safe_name = str(raw_name or "").strip()
                if not safe_name:
                    continue
                if safe_name not in current_categories:
                    invalid_items.append({"name": safe_name, "reason": "unknown_category"})
                    continue
                if safe_name in seen_categories:
                    invalid_items.append({"name": safe_name, "reason": "duplicate_category"})
                    continue
                seen_categories.add(safe_name)
                categories.append(safe_name)
            normalized_groups.append(
                {
                    "name": name,
                    "mode": mode,
                    "description": str(group.get("description") or "").strip(),
                    "categories": categories,
                }
            )

        changes: list[dict[str, object]] = []
        next_groups = {item["name"]: item for item in normalized_groups}
        for group_name, meta in current_groups.items():
            if group_name not in next_groups:
                changes.append(
                    {
                        "change_id": self._change_id("grouping", "delete_group", group_name),
                        "type": "delete_group",
                        "group_name": group_name,
                    }
                )
                continue
            next_meta = next_groups[group_name]
            if (
                str(meta.get("description") or "") != next_meta["description"]
                or str(meta.get("mode") or "") != next_meta["mode"]
            ):
                changes.append(
                    {
                        "change_id": self._change_id("grouping", "update_group", group_name),
                        "type": "update_group",
                        "group_name": group_name,
                        "from_mode": meta.get("mode", BUSINESS_GROUP_MODE_STANDARD),
                        "to_mode": next_meta["mode"],
                        "from_description": str(meta.get("description") or ""),
                        "to_description": next_meta["description"],
                    }
                )
        for group_name, meta in next_groups.items():
            if group_name not in current_groups:
                changes.append(
                    {
                        "change_id": self._change_id("grouping", "create_group", group_name),
                        "type": "create_group",
                        "group_name": group_name,
                        "mode": meta["mode"],
                    }
                )

        skipped_locked: list[str] = []
        current_by_category = {name: item["catalog_group"] for name, item in current_categories.items()}
        current_mode_by_category = {name: item["catalog_group_mode"] for name, item in current_categories.items()}
        next_by_category = {
            category_name: group["name"]
            for group in normalized_groups
            for category_name in group["categories"]
        }
        for name, item in current_categories.items():
            current_group = current_by_category.get(name, "")
            next_group = next_by_category.get(name, "")
            if current_group == next_group:
                continue
            next_mode = next_groups.get(next_group, {}).get("mode", BUSINESS_GROUP_MODE_STANDARD)
            current_mode = current_mode_by_category.get(name, BUSINESS_GROUP_MODE_STANDARD)
            if item["lock_source"] == RULE_LOCK_SOURCE_MANUAL and (
                current_mode == BUSINESS_GROUP_MODE_AD_BLOCK or next_mode == BUSINESS_GROUP_MODE_AD_BLOCK
            ):
                skipped_locked.append(name)
                continue
            changes.append(
                {
                    "change_id": self._change_id("grouping", "move_category", name, current_group, next_group),
                    "type": "move_category",
                    "name": name,
                    "from_group": current_group,
                    "to_group": next_group,
                    "routing_side_effect": (
                        current_mode == BUSINESS_GROUP_MODE_AD_BLOCK or next_mode == BUSINESS_GROUP_MODE_AD_BLOCK
                    ),
                }
            )
        return {
            "ok": True,
            "workflow": "grouping",
            "changes": changes,
            "normalized_groups": normalized_groups,
            "invalid_items": invalid_items,
            "skipped_locked": sorted(set(skipped_locked)),
        }

    def _apply_grouping(
        self,
        preview: dict[str, object],
        *,
        selected_change_ids: list[str] | None = None,
        scenario_id: str = "",
    ) -> dict[str, object]:
        safe_scenario_id = str(scenario_id or "").strip() or "scenario-default"
        applied_changes = self._selected_changes(preview, selected_change_ids)
        if not applied_changes:
            return {"ok": True, **preview, "applied": 0, "applied_change_ids": []}

        normalized_groups = {
            str(group.get("name") or "").strip(): group
            for group in list(preview.get("normalized_groups") or [])
            if str(group.get("name") or "").strip()
        }
        if safe_scenario_id == "scenario-default":
            current_group_names = {str(item.get("group_name") or "").strip() for item in self.repo.list_pin_groups()}
        else:
            current_group_names = {
                str(item.get("group_name") or "").strip()
                for item in self._pin_groups(scenario_id=safe_scenario_id)
            }
        selected_create_groups = {
            str(item.get("group_name") or "").strip()
            for item in applied_changes
            if str(item.get("type") or "").strip() == "create_group"
        }
        for item in applied_changes:
            if str(item.get("type") or "").strip() != "move_category":
                continue
            to_group = str(item.get("to_group") or "").strip()
            if to_group and to_group not in current_group_names and to_group not in selected_create_groups:
                raise ValueError("grouping move requires selected target group creation")

        applied = 0
        ordered_changes = (
            [item for item in applied_changes if str(item.get("type") or "").strip() in {"create_group", "update_group"}]
            + [item for item in applied_changes if str(item.get("type") or "").strip() == "move_category"]
            + [item for item in applied_changes if str(item.get("type") or "").strip() == "delete_group"]
        )
        for item in ordered_changes:
            change_type = str(item.get("type") or "").strip()
            if change_type == "create_group":
                group_name = str(item.get("group_name") or "").strip()
                group = normalized_groups.get(group_name, {})
                created = (
                    self.repo.create_pin_group(
                        group_name,
                        mode=str(group.get("mode") or BUSINESS_GROUP_MODE_STANDARD),
                        description=str(group.get("description") or ""),
                    )
                    if safe_scenario_id == "scenario-default"
                    else self.repo.create_scenario_pin_group(
                        safe_scenario_id,
                        group_name,
                        mode=str(group.get("mode") or BUSINESS_GROUP_MODE_STANDARD),
                        description=str(group.get("description") or ""),
                    )
                )
                if created:
                    current_group_names.add(group_name)
                    applied += 1
                continue
            if change_type == "update_group":
                group_name = str(item.get("group_name") or "").strip()
                renamed = (
                    self.repo.rename_pin_group(
                        group_name,
                        group_name,
                        mode=str(item.get("to_mode") or BUSINESS_GROUP_MODE_STANDARD),
                        description=str(item.get("to_description") or ""),
                    )
                    if safe_scenario_id == "scenario-default"
                    else self.repo.rename_scenario_pin_group(
                        safe_scenario_id,
                        group_name,
                        group_name,
                        mode=str(item.get("to_mode") or BUSINESS_GROUP_MODE_STANDARD),
                        description=str(item.get("to_description") or ""),
                    )
                )
                if renamed:
                    applied += 1
                continue
            if change_type == "delete_group":
                deleted = (
                    self.repo.delete_pin_group(str(item.get("group_name") or "").strip())
                    if safe_scenario_id == "scenario-default"
                    else self.repo.delete_scenario_pin_group(safe_scenario_id, str(item.get("group_name") or "").strip())
                )
                if deleted:
                    applied += 1
                continue
            if change_type == "move_category":
                category_name = str(item.get("name") or "").strip()
                to_group = str(item.get("to_group") or "").strip()
                if to_group:
                    if safe_scenario_id == "scenario-default":
                        self.repo.pin_category(category_name, to_group, sort_order=0)
                    else:
                        self.repo.pin_scenario_category(safe_scenario_id, category_name, to_group, sort_order=0)
                else:
                    if safe_scenario_id == "scenario-default":
                        self.repo.unpin_category(category_name)
                    else:
                        self.repo.unpin_scenario_category(safe_scenario_id, category_name)
                applied += 1
        return {
            "ok": True,
            **preview,
            "applied": applied,
            "applied_change_ids": [str(item.get("change_id") or "") for item in applied_changes],
        }

    def _preview_directness(self, result: dict[str, object], *, scenario_id: str = "") -> dict[str, object]:
        raw = self._parse_assignments(result)
        safe_scenario_id = str(scenario_id or "").strip() or "scenario-default"
        current = {item.name: item for item in self.repo.list_scenario_categories(safe_scenario_id)}
        changes: list[dict[str, object]] = []
        invalid_items: list[dict[str, str]] = []
        skipped_locked: list[str] = []
        skipped_unchanged: list[str] = []
        normalized: dict[str, dict[str, str]] = {}
        for name, value in raw.items():
            safe_name = str(name or "").strip()
            if not safe_name:
                continue
            category = current.get(safe_name)
            if not category:
                invalid_items.append({"name": safe_name, "reason": "unknown_category"})
                continue
            if category.lock_source == RULE_LOCK_SOURCE_MANUAL:
                skipped_locked.append(safe_name)
                continue
            if isinstance(value, str):
                decision = str(value or "").strip().upper()
                confidence = ""
                reason = ""
            elif isinstance(value, dict):
                decision = str(value.get("decision") or "").strip().upper()
                confidence = str(value.get("confidence") or "").strip().lower()
                reason = str(value.get("reason") or "").strip()
            else:
                invalid_items.append({"name": safe_name, "reason": "invalid_decision_format"})
                continue
            if decision not in RULE_DIRECTNESS_CHOICES:
                invalid_items.append({"name": safe_name, "reason": "invalid_decision"})
                continue
            normalized[safe_name] = {"decision": decision, "confidence": confidence, "reason": reason}
            current_directness = self.rule_catalog.get_effective_directness(category)
            if decision == current_directness:
                skipped_unchanged.append(safe_name)
                continue
            changes.append(
                {
                    "change_id": self._change_id("directness", safe_name),
                    "name": safe_name,
                    "from_directness": current_directness,
                    "to_directness": decision,
                    "confidence": confidence,
                    "reason": reason,
                }
            )
        return {
            "ok": True,
            "workflow": "directness",
            "changes": changes,
            "normalized_assignments": normalized,
            "invalid_items": invalid_items,
            "skipped_locked": sorted(skipped_locked),
            "skipped_unchanged": sorted(skipped_unchanged),
        }

    def _apply_directness(
        self,
        preview: dict[str, object],
        *,
        selected_change_ids: list[str] | None = None,
        scenario_id: str = "",
    ) -> dict[str, object]:
        safe_scenario_id = str(scenario_id or "").strip() or "scenario-default"
        if safe_scenario_id != "scenario-default":
            applied = 0
            applied_changes = self._selected_changes(preview, selected_change_ids)
            applied_change_ids: list[str] = []
            for item in applied_changes:
                if self.repo.apply_scenario_category_directness_decision(
                    safe_scenario_id,
                    str(item["name"]),
                    str(item["to_directness"]),
                    lock_after_apply=True,
                ):
                    applied += 1
                    applied_change_ids.append(str(item.get("change_id") or ""))
            return {
                "ok": True,
                **preview,
                "applied": applied,
                "applied_change_ids": applied_change_ids,
            }

        reviews: list[RuleCategoryDirectnessReview] = []
        applied_changes = self._selected_changes(preview, selected_change_ids)
        for item in applied_changes:
            reviews.append(
                RuleCategoryDirectnessReview(
                    id=uuid4().hex,
                    category_name=str(item["name"]),
                    proposed_decision=str(item["to_directness"]),
                    confidence=str(item.get("confidence") or ""),
                    reason=str(item.get("reason") or ""),
                    source="llm-center",
                    status=RULE_DIRECTNESS_REVIEW_STATUS_PENDING,
                    created_at=_utc_now(),
                )
            )
        if reviews:
            self.repo.replace_pending_rule_category_directness_reviews(reviews)
            self.rule_catalog.apply_directness_reviews(
                review_ids=[item.id for item in reviews],
                action="accept",
                lock_after_apply=True,
            )
        return {
            "ok": True,
            **preview,
            "applied": len(reviews),
            "applied_change_ids": [str(item.get("change_id") or "") for item in applied_changes],
        }

    def _routing_prompt(
        self,
        *,
        categories: list[dict[str, object]],
        target_options: list[dict[str, object]],
        template: str,
        intent_override: str,
        scenario_id: str = "",
    ) -> str:
        lines = [
            "# 任务",
            "",
            "你要把每个分类绑定到最合适的路由契约。只输出需要修改的分类。",
            "",
            "# 全局说明",
            template.strip() or "（无）",
        ]
        if intent_override.strip():
            lines.extend(["", "# 本次补充意图", intent_override.strip()])
        lines.extend(["", "# 可选契约"])
        for option in target_options:
            primary_summary = ", ".join(
                f"{pool['display_name']}({pool['node_count']})" for pool in option["primary_pools"]
            ) or "无"
            fallback_summary = ", ".join(
                f"{pool['display_name']}({pool['node_count']})" for pool in option["fallback_pools"]
            ) or "无"
            lines.append(
                f"- {option['contract_id']} | {option['display_name']} | "
                f"说明 {option.get('description') or '（无）'} | "
                f"主池 {primary_summary} | 备池 {fallback_summary}"
            )
        lines.extend(["", "# 分类"])
        for item in categories:
            lines.append(
                f"- {item['name']} | 当前契约 {item['stored_contract_id'] or '未设置'} | 当前生效 {item['effective_contract_id'] or '未设置'} | "
                f"直连 {item['current_effective_directness']} | 锁定 {item['locked']}"
            )
        lines.extend(
            [
                "",
                "# 输出格式",
                "```json",
                '{ "分类名": "contract_id" }',
                "```",
            ]
        )
        return "\n".join(lines)

    def _grouping_prompt(
        self,
        *,
        categories: list[dict[str, object]],
        groups: list[dict[str, object]],
        template: str,
        intent_override: str,
        scenario_id: str = "",
    ) -> str:
        lines = [
            "# 任务",
            "",
            "你要重组目录分组。分组默认只用于管理视图，但 mode=ad_block 会产生路由副作用。",
            "",
            "# 全局说明",
            template.strip() or "（无）",
        ]
        if intent_override.strip():
            lines.extend(["", "# 本次补充意图", intent_override.strip()])
        lines.extend(["", "# 现有分组"])
        for group in groups:
            lines.append(
                f"- {group['group_name']} | mode={group.get('mode', BUSINESS_GROUP_MODE_STANDARD)} | {group.get('description', '')}"
            )
        lines.extend(["", "# 分类"])
        for item in categories:
            lines.append(
                f"- {item['name']} | 当前组 {item['catalog_group'] or '未分组'} | 当前生效契约 {item['effective_contract_id'] or '未设置'}"
            )
        lines.extend(
            [
                "",
                "# 输出格式",
                "```json",
                '{ "groups": [{ "name": "AI 服务", "description": "说明", "mode": "standard", "categories": ["OpenAI"] }] }',
                "```",
            ]
        )
        return "\n".join(lines)

    def _directness_prompt(
        self,
        *,
        categories: list[dict[str, object]],
        template: str,
        intent_override: str,
        scenario_id: str = "",
    ) -> str:
        lines = [
            "# 任务",
            "",
            "你只判断 DIRECT 或 PROXY。只输出需要修改当前结果的分类。",
            "",
            "# 全局说明",
            template.strip() or "（无）",
        ]
        if intent_override.strip():
            lines.extend(["", "# 本次补充意图", intent_override.strip()])
        lines.extend(["", "# 分类"])
        for item in categories:
            lines.append(
                f"- {item['name']} | 当前 {item['current_effective_directness']} | 系统判定 {item['system_directness']} | 锁定 {item['lock_source'] or 'none'}"
            )
        lines.extend(
            [
                "",
                "# 输出格式",
                "```json",
                '{ "分类名": { "decision": "DIRECT|PROXY", "confidence": "low|medium|high", "reason": "简短理由" } }',
                "```",
            ]
        )
        return "\n".join(lines)
