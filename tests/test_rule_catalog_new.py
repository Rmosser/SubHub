from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.models import CustomRule, RouteContract, RuleCategory, ServiceCatalogEntry
from app.services.rule_catalog import RuleCatalog, _CatalogEntry, _CnJudge
from app.storage.sqlite_repo import SqliteRepo


def _settings(tmp_path) -> Settings:
    return Settings(
        app_name="SubHub",
        app_base_url="",
        storage_root=str(tmp_path),
        refresh_interval_minutes=30,
        request_timeout_seconds=20,
        verify_tls=True,
        github_api_base="https://127.0.0.1/invalid",
        github_raw_base="https://127.0.0.1/invalid",
        rule_catalog_refresh_hours=24,
        manage_api_require_login=False,
        max_snapshots_per_account=20,
        account_crawl_parallelism=2,
    )


@pytest.mark.parametrize("fresh_success", [True, False])
def test_refresh_counts_network_results_separately_from_cached_fallback(tmp_path, monkeypatch, fresh_success) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    catalog = RuleCatalog(settings, repo)
    repo.save_rule_cache("Cached", ["DOMAIN,cached.example,PLACEHOLDER"], source_sha="same", source_path="cached.yaml")
    repo.save_rule_cache("Failed", ["DOMAIN,old.example,PLACEHOLDER"], source_sha="old", source_path="failed.yaml")

    async def category_index(*, use_etag=True):
        return {
            "Cached": _CatalogEntry(category="Cached", yaml_path="cached.yaml", yaml_sha="same"),
            "Fresh": _CatalogEntry(category="Fresh", yaml_path="fresh.yaml", yaml_sha="new"),
            "Failed": _CatalogEntry(category="Failed", yaml_path="failed.yaml", yaml_sha="changed"),
        }, False

    async def fetch_rules(name, entry, *, client=None):
        assert name != "Cached"
        if name == "Fresh" and fresh_success:
            return 1, "yaml", ["DOMAIN,fresh.example,PLACEHOLDER"]
        return 0, "yaml", []

    async def cn_judge(mode):
        return None, "cache"

    monkeypatch.setattr(catalog, "_fetch_category_catalog", category_index)
    monkeypatch.setattr(catalog, "_fetch_category_rules", fetch_rules)
    monkeypatch.setattr(catalog, "_load_cn_judge", cn_judge)
    result = asyncio.run(catalog.refresh_categories(force=True))
    assert result["count"] == 3
    assert result["reused_count"] == 1
    assert result["attempted_count"] == 2
    assert result["succeeded_count"] == int(fresh_success)
    assert result["failed_count"] == 2 - int(fresh_success)
    assert result["partial"] is fresh_success
    assert repo.load_rule_cache("Failed") == ["DOMAIN,old.example,PLACEHOLDER"]


def test_fresh_rule_cache_skips_attempts_and_index_failure_is_one_attempt(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_rule_categories([RuleCategory(name="Cached", updated_at=datetime.now(timezone.utc).isoformat())])
    catalog = RuleCatalog(settings, repo)
    cached = asyncio.run(catalog.refresh_categories())
    assert cached["attempted_count"] == cached["succeeded_count"] == cached["failed_count"] == 0

    async def unavailable(*, use_etag=True):
        raise RuntimeError("index unavailable")

    monkeypatch.setattr(catalog, "_fetch_category_catalog", unavailable)
    failed = asyncio.run(catalog.refresh_categories(force=True))
    assert failed["count"] == 1
    assert failed["attempted_count"] == failed["failed_count"] == 1
    assert failed["succeeded_count"] == 0


def test_rule_catalog_export_import_roundtrip(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_rule_categories([
        RuleCategory(name="OpenAI", assigned_group="", rule_count=10),
        RuleCategory(name="YouTube", assigned_group="", rule_count=20),
    ])
    catalog = RuleCatalog(_settings(tmp_path), repo)

    imported = catalog.import_assignment_payload({"assignments": {"OpenAI": "高质量-高倍率"}})
    assert imported["updated"] == 1

    exported = catalog.export_assignment_payload()
    assert exported["schema"] == "subhub.rules.assignment.v3"
    assert "OpenAI" not in exported.get("candidates", [])  # already assigned
    assert "YouTube" in exported["candidates"]  # still unassigned
    assert any(item["contract_id"] == "medium" for item in exported["target_options"])
    assert "prompt" in exported and len(exported["prompt"]) > 100


def test_rule_catalog_import_accepts_plain_object_and_reports_invalid(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_rule_categories([
        RuleCategory(name="OpenAI", assigned_group="", rule_count=10),
        RuleCategory(name="YouTube", assigned_group="", rule_count=20),
    ])
    catalog = RuleCatalog(_settings(tmp_path), repo)

    result = catalog.import_assignment_payload(
        {
            "OpenAI": "hq_premium",
            "UnknownCategory": "中等质量",
            "YouTube": "INVALID",
        }
    )
    assert result["updated"] == 1
    assert len(result["invalid_items"]) == 2


def test_normalize_rule_line_supports_domain_suffix() -> None:
    line = RuleCatalog.normalize_rule_line("openai.com")
    assert line == "DOMAIN-SUFFIX,openai.com,PLACEHOLDER"


def test_normalize_rule_line_autofills_missing_cidr_prefix() -> None:
    ipv4_line = RuleCatalog.normalize_rule_line("IP-CIDR,1.2.3.4,PLACEHOLDER")
    ipv6_line = RuleCatalog.normalize_rule_line("IP-CIDR6,2001:db8::1,PLACEHOLDER")
    assert ipv4_line == "IP-CIDR,1.2.3.4/32,PLACEHOLDER"
    assert ipv6_line == "IP-CIDR6,2001:db8::1/128,PLACEHOLDER"


def test_normalize_rule_line_rejects_invalid_cidr_values() -> None:
    assert RuleCatalog.normalize_rule_line("IP-CIDR,not-an-ip,PLACEHOLDER") is None
    assert RuleCatalog.normalize_rule_line("IP-CIDR6,1.2.3.4,PLACEHOLDER") is None
    assert RuleCatalog.normalize_rule_line("IP-CIDR,2001:db8::1,PLACEHOLDER") is None


def test_get_assigned_rule_lines_sanitizes_legacy_cidr_entries(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_rule_categories([RuleCategory(name="STUN", assigned_group="高质量-高倍率", rule_count=3)])
    repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="STUN",
            catalog_group="网络服务",
            contract_id="medium",
            sort_order=0,
            source="manual",
        )
    )
    repo.save_rule_cache(
        "STUN",
        [
            "IP-CIDR6,2001:db8::1,PLACEHOLDER",
            "IP-CIDR6,invalid-ipv6,PLACEHOLDER",
            "DOMAIN-SUFFIX,stun.example.com,PLACEHOLDER",
        ],
    )
    repo.save_custom_rule(
        CustomRule(
            id="stun-c1",
            rule_type="IP-CIDR6",
            value="2001:db8::2",
            target_group="",
            category_name="STUN",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    repo.save_custom_rule(
        CustomRule(
            id="stun-c2",
            rule_type="IP-CIDR6",
            value="invalid-ipv6",
            target_group="",
            category_name="STUN",
            created_at="2026-01-01T00:00:00Z",
        )
    )

    catalog = RuleCatalog(settings, repo)
    lines = asyncio.run(catalog.get_assigned_rule_lines())
    assert "IP-CIDR6,2001:db8::1/128,中等质量" in lines
    assert "IP-CIDR6,2001:db8::2/128,中等质量" in lines
    assert "DOMAIN-SUFFIX,stun.example.com,中等质量" in lines
    assert not any("invalid-ipv6" in line for line in lines)
    assert not any("IP-CIDR6,2001:db8::1,中等质量" == line for line in lines)


def test_category_custom_rules_follow_category_contract_and_precede_catalog(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_rule_categories(
        [
            RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=1),
            RuleCategory(name="YouTube", assigned_group="", rule_count=1),
        ]
    )
    repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="AI 服务",
            contract_id="medium",
            sort_order=0,
            source="manual",
        )
    )
    repo.save_rule_cache("OpenAI", ["DOMAIN-SUFFIX,openai.com,PLACEHOLDER"])
    repo.save_rule_cache("YouTube", ["DOMAIN-SUFFIX,youtube.com,PLACEHOLDER"])
    repo.save_custom_rule(
        CustomRule(
            id="c-openai",
            rule_type="DOMAIN-SUFFIX",
            value="api.openai.com",
            target_group="",
            category_name="OpenAI",
            created_at="2026-01-01T00:00:00Z",
        )
    )
    repo.save_custom_rule(
        CustomRule(
            id="c-youtube",
            rule_type="DOMAIN-SUFFIX",
            value="m.youtube.com",
            target_group="",
            category_name="YouTube",
            created_at="2026-01-01T00:00:00Z",
        )
    )

    catalog = RuleCatalog(settings, repo)
    lines = asyncio.run(catalog.get_assigned_rule_lines())
    assert lines == [
        "DOMAIN-SUFFIX,api.openai.com,中等质量",
        "DOMAIN-SUFFIX,openai.com,中等质量",
    ]


def test_custom_rule_category_name_persists_after_repo_reload(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_custom_rule(
        CustomRule(
            id="c1",
            rule_type="DOMAIN-SUFFIX",
            value="api.openai.com",
            target_group="",
            category_name="OpenAI",
            created_at="2026-01-01T00:00:00Z",
        )
    )

    repo_reloaded = SqliteRepo(settings)
    rows = repo_reloaded.list_custom_rules(category_name="OpenAI")
    assert len(rows) == 1
    assert rows[0].category_name == "OpenAI"


# ---- locked category tests ----


def test_lock_unlock_category(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_rule_categories([RuleCategory(name="OpenAI", rule_count=10)])

    assert repo.update_rule_category_locked("OpenAI", True)
    cat = repo.get_rule_category("OpenAI")
    assert cat is not None and cat.locked is True

    assert repo.update_rule_category_locked("OpenAI", False)
    cat = repo.get_rule_category("OpenAI")
    assert cat is not None and cat.locked is False


def test_lock_nonexistent_category_returns_false(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    assert repo.update_rule_category_locked("DoesNotExist", True) is False


def test_import_skips_locked_categories(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_rule_categories([
        RuleCategory(name="OpenAI", assigned_group="", rule_count=10),
        RuleCategory(name="YouTube", assigned_group="", rule_count=20),
    ])
    repo.update_rule_category_locked("OpenAI", True)

    catalog = RuleCatalog(_settings(tmp_path), repo)
    result = catalog.import_assignment_payload({
        "OpenAI": "高质量-高倍率",
        "YouTube": "中等质量",
    })
    assert result["updated"] == 1
    assert result["skipped_locked"] == ["OpenAI"]

    assert repo.get_rule_category("OpenAI").assigned_group == ""
    assert repo.get_rule_category("YouTube").assigned_group == "中等质量"


def test_export_excludes_locked_unassigned_from_candidates(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_rule_categories([
        RuleCategory(name="OpenAI", assigned_group="", rule_count=10),
        RuleCategory(name="YouTube", assigned_group="", rule_count=20),
    ])
    repo.update_rule_category_locked("OpenAI", True)

    catalog = RuleCatalog(_settings(tmp_path), repo)
    exported = catalog.export_assignment_payload()
    assert "OpenAI" not in exported["candidates"]
    assert "YouTube" in exported["candidates"]
    assert exported["unassigned_count"] == 1


def test_export_prompt_contains_group_descriptions(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    current = repo.get_route_contract("hq_premium")
    assert current is not None
    repo.save_route_contract(
        RouteContract(
            id=current.id,
            display_name="高质量 IP",
            description="适合 AI / 低延迟 / 高信誉出口",
            strategy_type=current.strategy_type,
            primary_pools=current.primary_pools,
            fallback_pools=current.fallback_pools,
            failure_action=current.failure_action,
            editable=current.editable,
            enabled=current.enabled,
            sort_order=current.sort_order,
            is_system=current.is_system,
            updated_at=current.updated_at,
        )
    )
    repo.save_rule_categories([
        RuleCategory(name="TestCat", assigned_group="", rule_count=5),
    ])
    catalog = RuleCatalog(_settings(tmp_path), repo)
    exported = catalog.export_assignment_payload()
    prompt = exported["prompt"]
    assert "高质量 IP" in prompt
    assert "适合 AI / 低延迟 / 高信誉出口" in prompt
    assert "hq_premium" in prompt
    assert "低质量大流量" in prompt
    assert "TestCat" in prompt


def test_export_assignment_payload_treats_service_catalog_contract_as_assigned(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_rule_categories([RuleCategory(name="OpenAI", assigned_group="", rule_count=1)])
    repo.save_service_catalog_entry(
        ServiceCatalogEntry(
            category_name="OpenAI",
            catalog_group="AI 服务",
            contract_id="medium",
            sort_order=0,
            source="manual",
        )
    )

    exported = RuleCatalog(settings, repo).export_assignment_payload()

    assert exported["assigned_count"] == 1
    assert exported["unassigned_count"] == 0
    assert "OpenAI" not in exported["candidates"]
    assert "- OpenAI → 中等质量" in exported["prompt"]


def test_llm_export_preferences_defaults_and_fallback(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    catalog = RuleCatalog(_settings(tmp_path), repo)

    defaults = catalog.get_llm_export_preferences()
    assert "如果这里的指令与上方系统固定说明冲突，以这里为准。" in defaults["rules_preferences"]
    assert "当前可选目标组的名称、描述和已有分配样本" in defaults["rules_preferences"]
    assert "AI 服务" in defaults["pins_preferences"]
    assert "只在高度确定是中国大陆直连场景时建议 DIRECT" in defaults["directness_preferences"]

    updated = catalog.update_llm_export_preferences(
        rules_preferences="Netflix 可以分配到中等质量组",
        pins_preferences="优先使用“流媒体”“AI 服务”这样的简洁中文名称",
        directness_preferences="不确定时统一建议 PROXY",
    )
    assert updated["rules_preferences"] == "Netflix 可以分配到中等质量组"
    assert "简洁中文名称" in updated["pins_preferences"]
    assert "建议 PROXY" in updated["directness_preferences"]

    fallback = catalog.update_llm_export_preferences(
        rules_preferences="   ",
        pins_preferences="",
        directness_preferences="",
    )
    assert "当前可选目标组的名称、描述和已有分配样本" in fallback["rules_preferences"]
    assert "AI 服务" in fallback["pins_preferences"]
    assert "只在高度确定是中国大陆直连场景时建议 DIRECT" in fallback["directness_preferences"]


def test_export_prompts_include_editable_preference_sections(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_rule_categories([
        RuleCategory(name="Netflix", assigned_group="", rule_count=5),
        RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=3),
    ])
    repo.pin_category("OpenAI", "AI 服务")
    catalog = RuleCatalog(_settings(tmp_path), repo)

    catalog.update_llm_export_preferences(
        rules_preferences="Netflix 可以分配到中等质量组",
        pins_preferences="优先把 OpenAI 放到 AI 服务",
    )

    exported = catalog.export_assignment_payload()
    assert "# 我的分组偏好" in exported["prompt"]
    assert "Netflix 可以分配到中等质量组" in exported["prompt"]
    assert '"分类名": "contract_id"' in exported["prompt"]
    assert "仅输出 JSON" in exported["prompt"]

    pin_exported = catalog.export_pins_payload()
    assert "# 你的置顶偏好" in pin_exported["prompt"]
    assert "优先把 OpenAI 放到 AI 服务" in pin_exported["prompt"]
    assert '"分类名": "置顶分组名"' in pin_exported["prompt"]
    assert "仅输出 JSON" in pin_exported["prompt"]


def test_locked_field_in_to_dict(tmp_path) -> None:
    cat = RuleCategory(name="X", locked=True)
    d = cat.to_dict()
    assert d["locked"] is True

    cat2 = RuleCategory(name="Y")
    assert cat2.to_dict()["locked"] is False


def test_list_categories_returns_locked_field(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_rule_categories([
        RuleCategory(name="OpenAI", rule_count=10),
        RuleCategory(name="YouTube", rule_count=20),
    ])
    repo.update_rule_category_locked("OpenAI", True)

    cats = {c.name: c for c in repo.list_rule_categories()}
    assert cats["OpenAI"].locked is True
    assert cats["YouTube"].locked is False


def test_bulk_assign_skip_locked(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_rule_categories([
        RuleCategory(name="OpenAI", assigned_group="", rule_count=10),
        RuleCategory(name="YouTube", assigned_group="", rule_count=20),
    ])
    repo.update_rule_category_locked("OpenAI", True)

    updated = repo.bulk_assign_rule_categories(
        {"OpenAI": "高质量-高倍率", "YouTube": "中等质量"},
        skip_locked=True,
    )
    assert updated == 1
    assert repo.get_rule_category("OpenAI").assigned_group == ""
    assert repo.get_rule_category("YouTube").assigned_group == "中等质量"


def test_bulk_assign_without_skip_locked_updates_all(tmp_path) -> None:
    repo = SqliteRepo(_settings(tmp_path))
    repo.save_rule_categories([
        RuleCategory(name="OpenAI", assigned_group="", rule_count=10),
    ])
    repo.update_rule_category_locked("OpenAI", True)

    updated = repo.bulk_assign_rule_categories(
        {"OpenAI": "高质量-高倍率"},
        skip_locked=False,
    )
    assert updated == 1
    assert repo.get_rule_category("OpenAI").assigned_group == "高质量-高倍率"


def test_refresh_auto_direct_when_cn_judge_matches(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    catalog = RuleCatalog(settings, repo)

    async def _fake_catalog(*, use_etag: bool = True):
        return (
            {
                "12306": _CatalogEntry(
                    category="12306",
                    yaml_path="rule/Clash/12306/12306.yaml",
                    yaml_sha="sha-12306",
                )
            },
            False,
        )

    async def _fake_rules(
        category: str,
        entry: _CatalogEntry | None = None,
        *,
        client=None,
    ) -> tuple[int, str, list[str]]:
        assert category == "12306"
        return (2, "yaml", ["DOMAIN-SUFFIX,12306.cn,PLACEHOLDER", "DOMAIN-SUFFIX,rails.cn,PLACEHOLDER"])

    class _AlwaysCnJudge:
        def is_cn_category(self, rules: list[str]) -> bool:  # pragma: no cover - simple stub
            return True

    async def _fake_cn_judge(mode: str = "incremental"):
        return _AlwaysCnJudge(), "memory"

    monkeypatch.setattr(catalog, "_fetch_category_catalog", _fake_catalog)
    monkeypatch.setattr(catalog, "_fetch_category_rules", _fake_rules)
    monkeypatch.setattr(catalog, "_load_cn_judge", _fake_cn_judge)

    result = asyncio.run(catalog.refresh_categories(force=True))
    assert result["ok"] is True
    assert result["source"] == "github"

    cat = repo.get_rule_category("12306")
    assert cat is not None
    assert cat.assigned_group == "DIRECT"
    assert cat.locked is True


def test_cn_judge_accepts_partial_cn_domain_hits_without_explicit_non_cn() -> None:
    judge = _CnJudge(
        domain_suffixes=frozenset({"cn", "com.cn"}),
        domain_exacts=frozenset(),
        domain_keywords=frozenset(),
        geoip_v4=tuple(),
        geoip_v6=tuple(),
    )
    rules = [
        "DOMAIN-SUFFIX,12306.cn,PLACEHOLDER",
        "DOMAIN-SUFFIX,95306.cn,PLACEHOLDER",
        "DOMAIN-SUFFIX,95572.com,PLACEHOLDER",
        "DOMAIN-SUFFIX,china-railway.com.cn,PLACEHOLDER",
        "DOMAIN-SUFFIX,china-ric.com,PLACEHOLDER",
    ]
    assert judge.is_cn_category(rules) is True


def test_cn_judge_rejects_explicit_non_cn_signal() -> None:
    judge = _CnJudge(
        domain_suffixes=frozenset({"cn"}),
        domain_exacts=frozenset(),
        domain_keywords=frozenset(),
        geoip_v4=tuple(),
        geoip_v6=tuple(),
    )
    rules = [
        "DOMAIN-SUFFIX,12306.cn,PLACEHOLDER",
        "DOMAIN-SUFFIX,rails.cn,PLACEHOLDER",
        "DOMAIN-SUFFIX,95306.cn,PLACEHOLDER",
        "GEOIP,US,PLACEHOLDER",
    ]
    assert judge.is_cn_category(rules) is False


def test_refresh_auto_direct_sets_lock_source_and_system_directness(tmp_path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    catalog = RuleCatalog(settings, repo)

    async def _fake_catalog(*, use_etag: bool = True):
        return (
            {
                "12306": _CatalogEntry(
                    category="12306",
                    yaml_path="rule/Clash/12306/12306.yaml",
                    yaml_sha="sha-12306",
                )
            },
            False,
        )

    async def _fake_rules(
        category: str,
        entry: _CatalogEntry | None = None,
        *,
        client=None,
    ) -> tuple[int, str, list[str]]:
        return (2, "yaml", ["DOMAIN-SUFFIX,12306.cn,PLACEHOLDER", "DOMAIN-SUFFIX,rails.cn,PLACEHOLDER"])

    class _AlwaysCnJudge:
        def is_cn_category(self, rules: list[str]) -> bool:
            return True

    async def _fake_cn_judge(mode: str = "incremental"):
        return _AlwaysCnJudge(), "memory"

    monkeypatch.setattr(catalog, "_fetch_category_catalog", _fake_catalog)
    monkeypatch.setattr(catalog, "_fetch_category_rules", _fake_rules)
    monkeypatch.setattr(catalog, "_load_cn_judge", _fake_cn_judge)

    asyncio.run(catalog.refresh_categories(force=True))
    cat = repo.get_rule_category("12306")
    assert cat is not None
    assert cat.system_directness == "DIRECT"
    assert cat.lock_source == "system"
    assert cat.locked is True


def test_manual_assign_on_system_direct_sets_proxy_override(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_rule_categories(
        [
            RuleCategory(
                name="OpenAI",
                assigned_group="DIRECT",
                rule_count=5,
                locked=True,
                system_directness="DIRECT",
                lock_source="system",
            )
        ]
    )
    catalog = RuleCatalog(settings, repo)
    ok = catalog.assign_category("OpenAI", "中等质量")
    assert ok is True

    cat = repo.get_rule_category("OpenAI")
    assert cat is not None
    assert cat.assigned_group == "中等质量"
    assert cat.directness_override == "PROXY"
    assert cat.locked is False
    assert cat.lock_source == ""


def test_directness_review_export_import_apply(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_rule_categories(
        [
            RuleCategory(
                name="12306",
                assigned_group="DIRECT",
                rule_count=3,
                system_directness="DIRECT",
                locked=True,
                lock_source="system",
            ),
            RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=3),
        ]
    )
    repo.save_rule_cache("12306", ["DOMAIN-SUFFIX,12306.cn,PLACEHOLDER"])
    repo.save_rule_cache("OpenAI", ["DOMAIN-SUFFIX,openai.com,PLACEHOLDER"])
    catalog = RuleCatalog(settings, repo)

    exported = catalog.export_directness_review_payload()
    assert exported["schema"] == "subhub.rules.directness.review.v1"
    assert exported["scope"] == "all"
    assert exported["candidates"] == ["12306", "OpenAI"]
    assert exported["items"][0]["current_effective_directness"] == "DIRECT"
    assert exported["items"][1]["current_effective_directness"] == "PROXY"

    imported = catalog.import_directness_review_payload(
        {
            "12306": {"decision": "PROXY", "confidence": "high", "reason": "跨境资源混合"},
            "OpenAI": {"decision": "PROXY", "confidence": "medium", "reason": "保持现状"},
            "Unknown": "DIRECT",
        }
    )
    assert imported["inserted"] == 1
    assert imported["skipped_same"] == ["OpenAI"]
    assert len(imported["invalid_items"]) == 1

    pending = catalog.list_directness_reviews(status="pending")
    assert len(pending) == 1
    assert pending[0].proposed_decision == "PROXY"

    applied = catalog.apply_directness_reviews(
        review_ids=[pending[0].id],
        action="accept",
        lock_after_apply=True,
    )
    assert applied["updated"] == 1

    cat = repo.get_rule_category("12306")
    assert cat is not None
    assert cat.directness_override == "PROXY"
    assert cat.assigned_group == ""
    assert cat.locked is True
    assert cat.lock_source == "manual"


def test_apply_rule_category_directness_decision_can_force_manual_lock(tmp_path) -> None:
    settings = _settings(tmp_path)
    repo = SqliteRepo(settings)
    repo.save_rule_categories(
        [
            RuleCategory(
                name="12306",
                assigned_group="DIRECT",
                rule_count=3,
                system_directness="DIRECT",
                locked=True,
                lock_source="system",
            ),
            RuleCategory(name="OpenAI", assigned_group="高质量-高倍率", rule_count=3),
        ]
    )

    assert repo.apply_rule_category_directness_decision("12306", "PROXY", lock_after_apply=True) is True
    assert repo.apply_rule_category_directness_decision("OpenAI", "DIRECT", lock_after_apply=True) is True

    train = repo.get_rule_category("12306")
    openai = repo.get_rule_category("OpenAI")
    assert train is not None
    assert openai is not None
    assert train.directness_override == "PROXY"
    assert train.locked is True
    assert train.lock_source == "manual"
    assert openai.directness_override == "DIRECT"
    assert openai.assigned_group == "DIRECT"
    assert openai.locked is True
    assert openai.lock_source == "manual"
