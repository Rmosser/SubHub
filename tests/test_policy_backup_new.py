from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from copy import deepcopy
import sqlite3
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event

import pytest

from dulwich import porcelain

from app.models import CustomRule, RouteContract, RouteContractView, RuleCategory, ScenarioProfile, ServiceCatalogEntry
from app.services.policy_backup_service import _GitSyncResult
from app.services.route_contract_views import scenario_route_contract


def test_failed_policy_restore_rolls_back_every_owned_change_and_notifications(client, monkeypatch) -> None:
    services = client.app.state.services
    repo = services.repo
    backup = services.policy_backup
    repo.save_custom_rule(CustomRule(id="must-survive", rule_type="DOMAIN", value="keep.example", target_group="DIRECT"))
    repo.create_manual_rule_category("Keep manual", "DIRECT", locked=True)
    repo.save_scenario(ScenarioProfile(id="keep-scene", slug="keep-scene", name="Keep scene", settings={}))
    before = backup._build_snapshot_without_manifest()
    snapshot = deepcopy(backup.export_snapshot())
    snapshot["global"]["custom_rules"] = []
    snapshot["categories"]["manual_categories"] = []
    snapshot["scenarios"]["default"]["contract_views"].append({"contract_id": "does-not-exist"})
    monkeypatch.setattr(backup, "_load_snapshot_from_git", lambda ref="": snapshot)
    notified = []
    def callback(reason):
        notified.append(reason)
        backup.mark_dirty(reason)
    repo.set_policy_backup_notifier(callback)
    backup._dirty = False
    backup._reasons.clear()
    preview = client.post("/api/policy-backup/restore/preview", json={"ref": "main"}).json()
    result = client.post("/api/policy-backup/restore/apply", json={"ref": "main", "expected_digest": preview["snapshot_digest"]})
    assert result.status_code == 400
    assert "unknown contract_id" in result.json()["detail"]
    assert backup._build_snapshot_without_manifest() == before
    assert repo.list_custom_rules()[0].id == "must-survive"
    assert backup._dirty is False
    assert backup._reasons == set()
    assert notified == []
    assert not repo._conn.in_transaction
    # An ordinary save after rollback must still commit immediately.
    repo.save_custom_rule(CustomRule(id="after-failure", rule_type="DOMAIN", value="after.example", target_group="DIRECT"))
    with sqlite3.connect(repo.db_path) as observer:
        assert observer.execute("SELECT id FROM custom_rules WHERE id='after-failure'").fetchone() == ("after-failure",)
    assert "custom-rule-save" in notified
    assert backup._dirty is True


def test_successful_policy_restore_commits_before_notifying(client, monkeypatch) -> None:
    services = client.app.state.services
    repo = services.repo
    backup = services.policy_backup
    snapshot = backup.export_snapshot()
    snapshot["global"]["custom_rules"] = [{"rule_type": "DOMAIN", "value": "restored.example", "target_group": "DIRECT"}]
    monkeypatch.setattr(backup, "_load_snapshot_from_git", lambda ref="": snapshot)
    notified = []
    def callback(reason):
        with sqlite3.connect(repo.db_path) as observer:
            assert observer.execute("SELECT value FROM custom_rules WHERE value='restored.example'").fetchone() == ("restored.example",)
        assert not repo._conn.in_transaction
        notified.append(reason)
    repo.set_policy_backup_notifier(callback)
    preview = client.post("/api/policy-backup/restore/preview", json={"ref": "main"}).json()
    response = client.post("/api/policy-backup/restore/apply", json={"ref": "main", "expected_digest": preview["snapshot_digest"]})
    assert response.status_code == 200
    assert notified
    assert repo.list_custom_rules()[0].value == "restored.example"
    assert backup._dirty is True


def test_repository_transaction_rejects_nesting_without_losing_outer_write(client) -> None:
    repo = client.app.state.services.repo
    with repo.transaction():
        repo.save_custom_rule(CustomRule(id="outer", rule_type="DOMAIN", value="outer.example", target_group="DIRECT"))
        with pytest.raises(RuntimeError, match="nested repository transactions"):
            with repo.transaction():
                pass
        with sqlite3.connect(repo.db_path) as observer:
            assert observer.execute("SELECT id FROM custom_rules WHERE id='outer'").fetchone() is None
    with sqlite3.connect(repo.db_path) as observer:
        assert observer.execute("SELECT id FROM custom_rules WHERE id='outer'").fetchone() == ("outer",)


def test_failed_transaction_does_not_rollback_a_concurrent_writer(client) -> None:
    repo = client.app.state.services.repo
    started = Event()
    def concurrent_save():
        started.set()
        repo.save_custom_rule(CustomRule(id="concurrent", rule_type="DOMAIN", value="concurrent.example", target_group="DIRECT"))
    with ThreadPoolExecutor(max_workers=1) as executor:
        with pytest.raises(ValueError, match="abort restore"):
            with repo.transaction():
                repo.save_custom_rule(CustomRule(id="partial", rule_type="DOMAIN", value="partial.example", target_group="DIRECT"))
                saved = executor.submit(concurrent_save)
                assert started.wait(2)
                with pytest.raises(TimeoutError):
                    saved.result(timeout=0.05)
                raise ValueError("abort restore")
        saved.result(timeout=2)
    with sqlite3.connect(repo.db_path) as observer:
        assert observer.execute("SELECT id FROM custom_rules WHERE id='partial'").fetchone() is None
        assert observer.execute("SELECT id FROM custom_rules WHERE id='concurrent'").fetchone() == ("concurrent",)


def test_policy_restore_requires_reviewed_content_when_branch_moves(client, monkeypatch) -> None:
    services = client.app.state.services
    snapshot = services.policy_backup.export_snapshot()
    monkeypatch.setattr(services.policy_backup, "_load_snapshot_from_git", lambda ref="": snapshot)
    preview = client.post("/api/policy-backup/restore/preview", json={"ref": "main"})
    assert preview.status_code == 200
    reviewed_digest = preview.json()["snapshot_digest"]
    assert len(reviewed_digest) == 64
    missing = client.post("/api/policy-backup/restore/apply", json={"ref": "main"})
    assert missing.status_code == 409
    # The ref and the manifest's recorded digest remain unchanged. Actual
    # content changed after the user reviewed it.
    snapshot["categories"]["manual_categories"].append({
        "name": "Changed after preview", "assigned_group": "DIRECT", "locked": True,
        "lock_source": "manual", "rules": [],
    })
    stale = client.post(
        "/api/policy-backup/restore/apply", json={"ref": "main", "expected_digest": reviewed_digest},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "restore snapshot changed; preview again"
    assert services.repo.get_rule_category("Changed after preview") is None
    refreshed = client.post("/api/policy-backup/restore/preview", json={"ref": "main"})
    assert refreshed.json()["snapshot_digest"] != reviewed_digest
    applied = client.post(
        "/api/policy-backup/restore/apply", json={"ref": "main", "expected_digest": refreshed.json()["snapshot_digest"]},
    )
    assert applied.status_code == 200
    assert services.repo.get_rule_category("Changed after preview") is not None


def _enable_policy_backup(client) -> None:
    settings = client.app.state.services.settings
    settings.policy_backup_enabled = True
    settings.policy_backup_repo_url = "https://github.com/example/private-policy.git"
    settings.policy_backup_branch = "main"
    settings.policy_backup_github_token = "token"
    settings.policy_backup_author_name = "Policy Bot"
    settings.policy_backup_author_email = "policy-bot@example.com"
    settings.policy_backup_subdir = ""
    settings.policy_backup_debounce_seconds = 1


def test_policy_backup_export_snapshot_uses_structured_owned_assets(client) -> None:
    services = client.app.state.services
    repo = services.repo
    repo.save_rule_categories(
        [
            RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=4, rule_source="github"),
            RuleCategory(name="YouTube", assigned_group="中等质量", rule_count=8, rule_source="github"),
        ]
    )
    created = repo.create_manual_rule_category("SubHub", "DIRECT", locked=True)
    assert created is not None
    repo.save_custom_rule(
        CustomRule(
            id="global-rule-1",
            rule_type="DOMAIN-SUFFIX",
            value="api.openai.com",
            target_group="高质量-高倍率",
            created_at="2026-03-30T00:00:00Z",
        )
    )
    repo.save_custom_rule(
        CustomRule(
            id="manual-rule-1",
            rule_type="DOMAIN-SUFFIX",
            value="subhub.example.com",
            target_group="",
            category_name="SubHub",
            created_at="2026-03-30T00:00:00Z",
        )
    )
    repo.save_scenario(
        ScenarioProfile(
            id="scenario-work",
            slug="work",
            name="办公",
            enabled=True,
            sort_order=10,
        )
    )
    repo.create_route_contract(
        RouteContract(
            id="custom-office",
            display_name="办公中转",
            description="全局办公契约",
            strategy_type="strict",
            primary_pools=["medium"],
            fallback_pools=[],
            failure_action="interrupt",
            editable=True,
            enabled=True,
            sort_order=20,
            owner_scenario_id="",
            is_system=False,
        )
    )
    repo.save_scenario_route_contract_view(
        "scenario-default",
        RouteContractView(
            scenario_id="scenario-default",
            contract_id="custom-office",
            display_name="办公中转",
            description="全局办公契约",
            enabled=True,
            sort_order=20,
            is_default=False,
        ),
    )
    repo.create_route_contract(
        RouteContract(
            id="scenario-work-bulk",
            display_name="工作下载",
            description="工作场景私有契约",
            strategy_type="strict",
            primary_pools=["bulk"],
            fallback_pools=[],
            failure_action="interrupt",
            editable=True,
            enabled=True,
            sort_order=21,
            owner_scenario_id="scenario-work",
            is_system=False,
        )
    )
    repo.save_scenario_route_contract_view(
        "scenario-work",
        RouteContractView(
            scenario_id="scenario-work",
            contract_id="scenario-work-bulk",
            display_name="工作下载",
            description="工作场景私有契约",
            enabled=True,
            sort_order=21,
            is_default=False,
        ),
    )
    repo.create_scenario_pin_group("scenario-work", "办公分组", description="办公常用")
    repo.save_scenario_service_catalog_entry(
        "scenario-work",
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="办公分组",
            contract_id="hq_premium",
            sort_order=1,
            source="manual",
        ),
    )
    repo.update_scenario_category_assignment("scenario-work", "OpenAI", "DIRECT")
    repo.save_scenario_custom_rule(
        "scenario-work",
        CustomRule(
            id="scenario-rule-1",
            rule_type="DOMAIN",
            value="intranet.example.com",
            target_group="DIRECT",
            created_at="2026-03-30T00:00:00Z",
        ),
    )

    snapshot = services.policy_backup.export_snapshot()

    assert snapshot["manifest"]["schema_version"] == "subhub.policy-backup.v2"
    manual_categories = snapshot["categories"]["manual_categories"]
    assert manual_categories == [
        {
            "name": "SubHub",
            "assigned_group": "DIRECT",
            "locked": True,
            "lock_source": "manual",
            "rules": [{"rule_type": "DOMAIN-SUFFIX", "value": "subhub.example.com"}],
        }
    ]
    assert snapshot["global"]["custom_rules"] == [
        {
            "rule_type": "DOMAIN-SUFFIX",
            "value": "api.openai.com",
            "target_contract_id": "hq_premium",
            "target_group": "高质量-高倍率",
            "category_name": "",
            "created_at": "2026-03-30T00:00:00Z",
        }
    ]
    assert "default" in snapshot["scenarios"]
    assert "scenario-work" in snapshot["scenarios"]
    assert snapshot["scenarios"]["default"]["custom_rules"] == []
    global_definitions = snapshot["scenarios"]["default"]["contract_definitions"]
    assert {item["id"] for item in global_definitions} >= {"direct", "ad_block", "medium", "chain_home"}
    assert [item for item in global_definitions if item["id"] == "custom-office"] == [
        {
            "id": "custom-office",
            "display_name": "办公中转",
            "description": "全局办公契约",
            "llm_routing_intent": "",
            "routing_action": "proxy",
            "strategy_type": "strict",
            "primary_pools": ["medium"],
            "fallback_pools": [],
            "failure_action": "interrupt",
            "enabled": True,
            "sort_order": 20,
            "owner_scenario_id": "",
            "updated_at": next(item for item in global_definitions if item["id"] == "custom-office")["updated_at"],
        }
    ]
    assert snapshot["scenarios"]["scenario-work"]["custom_rules"] == [
        {
            "rule_type": "DOMAIN",
            "value": "intranet.example.com",
            "target_contract_id": "action-direct",
            "target_group": "DIRECT",
            "category_name": "",
            "created_at": "2026-03-30T00:00:00Z",
        }
    ]
    assert snapshot["scenarios"]["scenario-work"]["contract_definitions"] == [
        {
            "id": "scenario-work-bulk",
            "display_name": "工作下载",
            "description": "工作场景私有契约",
            "llm_routing_intent": "",
            "routing_action": "proxy",
            "strategy_type": "strict",
            "primary_pools": ["bulk"],
            "fallback_pools": [],
            "failure_action": "interrupt",
            "enabled": True,
            "sort_order": 21,
            "owner_scenario_id": "scenario-work",
            "updated_at": snapshot["scenarios"]["scenario-work"]["contract_definitions"][0]["updated_at"],
        }
    ]
    assert snapshot["scenarios"]["scenario-work"]["pin_groups"][0]["group_name"] == "办公分组"
    assert snapshot["scenarios"]["scenario-work"]["catalog_bindings"][0]["category_name"] == "OpenAI"


def test_policy_backup_notifier_marks_owned_changes_but_not_cache_updates(client) -> None:
    services = client.app.state.services
    policy_backup = services.policy_backup
    with policy_backup._state_lock:
        policy_backup._dirty = False
        policy_backup._reasons.clear()

    services.repo.create_manual_rule_category("SubHub", "DIRECT", locked=False)
    assert policy_backup._dirty is True
    assert "manual-category-create" in policy_backup._reasons

    with policy_backup._state_lock:
        policy_backup._dirty = False
        policy_backup._reasons.clear()

    services.repo.save_rule_cache("CacheOnly", ["DOMAIN-SUFFIX,cache.example.com,DIRECT"])
    assert policy_backup._dirty is False
    assert policy_backup._reasons == set()


def test_policy_backup_status_defaults_to_disabled(client) -> None:
    resp = client.get("/api/policy-backup/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["item"]["enabled"] is False
    assert body["item"]["configured"] is False
    assert body["item"]["last_result"] == "idle"


def test_policy_backup_sync_updates_runtime_status(client, monkeypatch) -> None:
    _enable_policy_backup(client)
    services = client.app.state.services
    services.repo.create_manual_rule_category("SubHub", "DIRECT", locked=False)

    def _fake_sync_files(*args, **kwargs):
        return _GitSyncResult(ok=True, changed=True, commit_sha="abc123")

    monkeypatch.setattr(services.policy_backup.backend, "sync_files", _fake_sync_files)

    resp = client.post("/api/policy-backup/sync")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["commit_sha"] == "abc123"

    status = client.get("/api/policy-backup/status")
    assert status.status_code == 200
    item = status.json()["item"]
    assert item["enabled"] is True
    assert item["configured"] is True
    assert item["last_result"] == "ok"
    assert item["last_commit_sha"] == "abc123"


def test_policy_backup_restore_preview_and_apply(client, monkeypatch) -> None:
    _enable_policy_backup(client)
    services = client.app.state.services
    repo = services.repo
    repo.save_rule_categories(
        [RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=3, rule_source="github")]
    )

    backup_snapshot = {
        "manifest": {
            "schema_version": "subhub.policy-backup.v1",
            "exported_at": "2026-03-30T12:00:00Z",
            "app_name": "SubHub",
            "app_version": "1.0.0",
            "source_repo": "https://github.com/example/subhub.git",
            "scenario_ids": ["scenario-default", "scenario-work"],
            "counts": {"manual_categories": 1, "global_custom_rules": 1, "scenarios": 2},
            "digest": "digest-1",
        },
        "global": {
            "custom_rules": [
                {
                    "rule_type": "DOMAIN-SUFFIX",
                    "value": "openai.example.com",
                    "target_contract_id": "direct",
                    "target_group": "DIRECT",
                    "category_name": "",
                    "created_at": "2026-03-30T12:00:00Z",
                }
            ]
        },
        "categories": {
            "manual_categories": [
                {
                    "name": "SubHub",
                    "assigned_group": "DIRECT",
                    "locked": True,
                    "lock_source": "manual",
                    "rules": [{"rule_type": "DOMAIN-SUFFIX", "value": "subhub.example.com"}],
                }
            ]
        },
        "scenarios": {
            "default": {
                "metadata": {
                    "id": "scenario-default",
                    "slug": "default",
                    "name": "默认场景",
                    "description": "",
                    "enabled": True,
                    "sort_order": 0,
                    "updated_at": "2026-03-30T12:00:00Z",
                },
                "category_overrides": [],
                "custom_rules": [],
                "contract_definitions": [
                    {
                        "id": "custom-office",
                        "display_name": "办公中转",
                        "description": "全局办公契约",
                        "llm_routing_intent": "",
                        "strategy_type": "strict",
                        "primary_pools": ["medium"],
                        "fallback_pools": [],
                        "failure_action": "interrupt",
                        "enabled": True,
                        "sort_order": 12,
                        "owner_scenario_id": "",
                        "updated_at": "2026-03-30T12:00:00Z",
                    }
                ],
                "pin_groups": [
                    {
                        "group_name": "默认分组",
                        "sort_order": 0,
                        "mode": "standard",
                        "description": "默认",
                    }
                ],
                "catalog_bindings": [
                    {
                        "category_name": "SubHub",
                        "catalog_group": "默认分组",
                        "contract_id": "direct",
                        "sort_order": 0,
                    }
                ],
            },
            "scenario-work": {
                "metadata": {
                    "id": "scenario-work",
                    "slug": "work",
                    "name": "办公",
                    "description": "工作环境",
                    "enabled": True,
                    "sort_order": 1,
                    "updated_at": "2026-03-30T12:00:00Z",
                },
                "category_overrides": [
                    {
                        "name": "OpenAI",
                        "assigned_group": "DIRECT",
                        "locked": True,
                        "lock_source": "manual",
                        "override_group": "DIRECT",
                        "override_active": True,
                        "directness_override": "DIRECT",
                    }
                ],
                "custom_rules": [
                    {
                        "rule_type": "DOMAIN",
                        "value": "office.internal",
                        "target_contract_id": "direct",
                        "target_group": "DIRECT",
                        "category_name": "",
                        "created_at": "2026-03-30T12:00:00Z",
                    }
                ],
                "contract_definitions": [
                    {
                        "id": "scenario-work-download",
                        "display_name": "工作下载",
                        "description": "工作场景私有契约",
                        "llm_routing_intent": "",
                        "strategy_type": "strict",
                        "primary_pools": ["bulk"],
                        "fallback_pools": [],
                        "failure_action": "interrupt",
                        "enabled": True,
                        "sort_order": 13,
                        "owner_scenario_id": "scenario-work",
                        "updated_at": "2026-03-30T12:00:00Z",
                    }
                ],
                "pin_groups": [
                    {
                        "group_name": "办公分组",
                        "sort_order": 0,
                        "mode": "standard",
                        "description": "办公常用",
                    }
                ],
                "catalog_bindings": [
                    {
                        "category_name": "OpenAI",
                        "catalog_group": "办公分组",
                        "contract_id": "hq_premium",
                        "sort_order": 1,
                    }
                ],
            },
        },
    }

    monkeypatch.setattr(services.policy_backup, "_load_snapshot_from_git", lambda ref="": backup_snapshot)

    preview = client.post("/api/policy-backup/restore/preview", json={"ref": "abc123"})
    assert preview.status_code == 200
    assert preview.json()["ok"] is True
    assert preview.json()["changed"] is True
    assert any(section["name"] == "manual_categories" for section in preview.json()["sections"])

    applied = client.post("/api/policy-backup/restore/apply", json={"ref": "abc123", "expected_digest": preview.json()["snapshot_digest"]})
    assert applied.status_code == 200
    assert applied.json()["ok"] is True

    manual = repo.get_rule_category("SubHub")
    assert manual is not None
    assert manual.category_type == "manual"
    assert manual.locked is True
    manual_rules = repo.list_custom_rules(category_name="SubHub")
    assert [item.value for item in manual_rules] == ["subhub.example.com"]

    global_rules = repo.list_custom_rules(global_only=True)
    assert [item.value for item in global_rules] == ["openai.example.com"]

    scenario = repo.get_scenario("scenario-work")
    assert scenario is not None
    assert scenario.slug == "work"
    scenario_groups = repo.list_scenario_pin_groups("scenario-work")
    assert scenario_groups[0]["group_name"] == "办公分组"
    scenario_rules = repo.list_explicit_scenario_custom_rules("scenario-work")
    assert [item.value for item in scenario_rules] == ["office.internal"]
    scenario_bindings = {
        item.category_name: item for item in repo.list_scenario_service_catalog_entries("scenario-work")
    }
    assert scenario_bindings["OpenAI"].catalog_group == "办公分组"
    overridden = {item.name: item for item in repo.list_scenario_categories("scenario-work")}
    assert overridden["OpenAI"].assigned_group == "DIRECT"
    assert overridden["OpenAI"].locked is True
    restored_global_contract = repo.get_route_contract("custom-office")
    assert restored_global_contract is not None
    assert restored_global_contract.owner_scenario_id == ""
    restored_work_contract = scenario_route_contract(repo, "scenario-work", "scenario-work-download")
    assert restored_work_contract is not None
    assert restored_work_contract.owner_scenario_id == "scenario-work"


def test_policy_backup_export_and_restore_keep_ad_block_target_contract(client) -> None:
    services = client.app.state.services
    repo = services.repo
    repo.save_custom_rule(
        CustomRule(
            id="global-reject-rule",
            rule_type="DOMAIN-SUFFIX",
            value="ads.example.com",
            target_contract_id="ad_block",
            created_at="2026-03-30T12:00:00Z",
        )
    )

    snapshot = services.policy_backup.export_snapshot()

    assert snapshot["global"]["custom_rules"] == [
        {
            "rule_type": "DOMAIN-SUFFIX",
            "value": "ads.example.com",
            "target_contract_id": "ad_block",
            "target_group": "广告拦截",
            "category_name": "",
            "created_at": "2026-03-30T12:00:00Z",
        }
    ]

    services.policy_backup._apply_snapshot(snapshot)

    restored = repo.list_custom_rules(global_only=True)
    assert len(restored) == 1
    assert restored[0].resolved_target_contract_id() == "ad_block"
    assert restored[0].display_target_group() == "广告拦截"


def test_policy_backup_load_snapshot_treats_missing_contract_views_as_empty(client, monkeypatch) -> None:
    _enable_policy_backup(client)
    services = client.app.state.services

    files = {
        "manifest.json": """{
            "schema_version": "subhub.policy-backup.v1",
            "exported_at": "2026-03-30T12:00:00Z",
            "app_name": "SubHub",
            "app_version": "1.0.0",
            "source_repo": "https://github.com/example/subhub.git",
            "scenario_ids": ["scenario-default", "scenario-work"],
            "counts": {"manual_categories": 0, "global_custom_rules": 0, "scenarios": 2},
            "digest": "digest-legacy"
        }""",
        "global/custom-rules.yaml": "custom_rules: []\n",
        "categories/manual-categories.yaml": "manual_categories: []\n",
        "scenarios/default/metadata.yaml": "id: scenario-default\nslug: default\nname: 默认场景\nenabled: true\nsort_order: 0\n",
        "scenarios/default/category-overrides.yaml": "category_overrides: []\n",
        "scenarios/default/custom-rules.yaml": "custom_rules: []\n",
        "scenarios/default/pin-groups.yaml": "pin_groups: []\n",
        "scenarios/default/catalog-bindings.yaml": "catalog_bindings: []\n",
        "scenarios/scenario-work/metadata.yaml": "id: scenario-work\nslug: work\nname: 办公\nenabled: true\nsort_order: 1\n",
        "scenarios/scenario-work/category-overrides.yaml": "category_overrides: []\n",
        "scenarios/scenario-work/custom-rules.yaml": "custom_rules: []\n",
        "scenarios/scenario-work/pin-groups.yaml": "pin_groups: []\n",
        "scenarios/scenario-work/catalog-bindings.yaml": "catalog_bindings: []\n",
    }

    def _read_file(path: str, ref: str | None = None) -> str:
        if path.endswith("contract-views.yaml"):
            raise FileNotFoundError(path)
        return files[path]

    monkeypatch.setattr(services.policy_backup.backend, "read_file", _read_file)

    snapshot = services.policy_backup._load_snapshot_from_git()

    assert snapshot["scenarios"]["default"]["contract_views"] == []
    assert snapshot["scenarios"]["scenario-work"]["contract_views"] == []


def test_policy_backup_restore_applies_contract_definitions_before_views(client) -> None:
    services = client.app.state.services

    snapshot = {
        "manifest": {
            "schema_version": "subhub.policy-backup.v1",
            "exported_at": "2026-03-30T12:00:00Z",
            "app_name": "SubHub",
            "app_version": "1.0.0",
            "source_repo": "https://github.com/example/subhub.git",
            "scenario_ids": ["scenario-default", "scenario-work"],
            "counts": {"manual_categories": 0, "global_custom_rules": 0, "scenarios": 2},
            "digest": "digest-contract-order",
        },
        "global": {"custom_rules": []},
        "categories": {"manual_categories": []},
        "scenarios": {
            "default": {
                "metadata": {
                    "id": "scenario-default",
                    "slug": "default",
                    "name": "默认场景",
                    "enabled": True,
                    "sort_order": 0,
                },
                "category_overrides": [],
                "custom_rules": [],
                "contract_definitions": [],
                "contract_views": [
                    {
                        "contract_id": "scenario-work-bulk",
                        "display_name": "工作下载",
                        "description": "默认场景里的历史坏数据视图",
                        "llm_routing_intent": "",
                        "enabled": True,
                        "sort_order": 21,
                        "is_default": False,
                        "updated_at": "2026-03-30T12:00:00Z",
                    }
                ],
                "pin_groups": [],
                "catalog_bindings": [],
            },
            "scenario-work": {
                "metadata": {
                    "id": "scenario-work",
                    "slug": "work",
                    "name": "工作场景",
                    "enabled": True,
                    "sort_order": 1,
                },
                "category_overrides": [],
                "custom_rules": [],
                "contract_definitions": [
                    {
                        "id": "scenario-work-bulk",
                        "display_name": "工作下载",
                        "description": "工作场景私有契约",
                        "llm_routing_intent": "",
                        "strategy_type": "strict",
                        "primary_pools": ["bulk"],
                        "fallback_pools": [],
                        "failure_action": "interrupt",
                        "enabled": True,
                        "sort_order": 21,
                        "owner_scenario_id": "scenario-work",
                        "updated_at": "2026-03-30T12:00:00Z",
                    }
                ],
                "contract_views": [
                    {
                        "contract_id": "scenario-work-bulk",
                        "display_name": "工作下载",
                        "description": "工作场景私有契约",
                        "llm_routing_intent": "",
                        "enabled": True,
                        "sort_order": 21,
                        "is_default": False,
                        "updated_at": "2026-03-30T12:00:00Z",
                    }
                ],
                "pin_groups": [],
                "catalog_bindings": [],
            },
        },
    }

    services.policy_backup._apply_snapshot(snapshot)

    restored = services.repo.get_route_contract("scenario-work-bulk")
    assert restored is not None
    assert restored.owner_scenario_id == "scenario-work"
    default_view = services.repo.get_scenario_route_contract_view("scenario-default", "scenario-work-bulk")
    assert default_view is not None
    assert default_view.display_name == "工作下载"


def test_policy_backup_sync_and_read_file_without_system_git(client, monkeypatch, tmp_path) -> None:
    # A service-generated commit must not inherit a desktop signing program.
    config_home = tmp_path / "git-config-home"
    config_home.mkdir()
    (config_home / ".gitconfig").write_text(
        "[commit]\n\tgpgsign = true\n[gpg]\n\tformat = ssh\n"
        "[gpg \"ssh\"]\n\tprogram = /nonexistent-subhub-signing-program\n"
        "[user]\n\tsigningkey = ssh-ed25519 synthetic-signing-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config_home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    _enable_policy_backup(client)
    services = client.app.state.services
    repo = services.repo
    settings = services.settings

    with TemporaryDirectory() as td:
        remote = Path(td) / "policy-backup.git"
        porcelain.init(remote, bare=True)
        settings.policy_backup_repo_url = str(remote)
        settings.policy_backup_github_token = ""

        repo.create_manual_rule_category("SubHub", "DIRECT", locked=True)
        repo.save_custom_rule(
            CustomRule(
                id="global-rule-1",
                rule_type="DOMAIN-SUFFIX",
                value="api.openai.com",
                target_group="高质量-高倍率",
                created_at="2026-03-30T00:00:00Z",
            )
        )

        resp = client.post("/api/policy-backup/sync")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["changed"] is True
        assert body["commit_sha"]

        manifest = services.policy_backup.backend.read_file("manifest.json")
        assert '"schema_version": "subhub.policy-backup.v2"' in manifest

        categories_yaml = services.policy_backup.backend.read_file("categories/manual-categories.yaml")
        assert "name: SubHub" in categories_yaml

        second = client.post("/api/policy-backup/sync")
        assert second.status_code == 200
        assert second.json()["changed"] is False
