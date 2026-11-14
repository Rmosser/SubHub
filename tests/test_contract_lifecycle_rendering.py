from __future__ import annotations

import yaml

from app.models import (
    ROUTE_ACTION_DIRECT,
    ROUTE_ACTION_PROXY,
    ROUTE_ACTION_REJECT,
    ROUTE_DIRECT_ACTION,
    ROUTE_REJECT_ACTION,
    PolicyRuleEntry,
    QUALITY_HIGH_STANDARD,
    QUALITY_MEDIUM,
    RouteContract,
    NodeRecord,
)
from app.services.subscription_builder import (
    build_clash_blocked_detail,
    build_clash_config,
    build_clash_profile_artifacts,
    build_policy_ir,
    build_shadowrocket_config,
    build_surge_profile_artifacts,
    shadowrocket_blocked_detail,
    surge_blocked_detail,
)


def _node() -> NodeRecord:
    return NodeRecord(
        name="medium-1",
        host="medium.example.com",
        port=443,
        protocol="http",
        quality_group=QUALITY_MEDIUM,
    )


def _contract(
    contract_id: str,
    display_name: str,
    *,
    action: str = ROUTE_ACTION_PROXY,
    enabled: bool = True,
    pools: list[str] | None = None,
) -> RouteContract:
    return RouteContract(
        id=contract_id,
        display_name=display_name,
        routing_action=action,
        enabled=enabled,
        primary_pools=list(pools or []),
    )


def test_arbitrary_contract_actions_render_across_all_clients() -> None:
    direct = _contract("user-direct", "用户直连", action=ROUTE_ACTION_DIRECT)
    reject = _contract("user-reject", "用户拦截", action=ROUTE_ACTION_REJECT)
    entries = [
        PolicyRuleEntry("user-direct", "DOMAIN", "direct.example"),
        PolicyRuleEntry("user-reject", "DOMAIN", "reject.example"),
    ]
    ir = build_policy_ir(
        [_node()],
        [],
        rule_entries=entries,
        contracts=[direct, reject],
        default_contract_id="user-direct",
    )

    clash_text, _, _ = build_clash_profile_artifacts(
        [_node()], [], policy_ir=ir, render_mode="export"
    )
    clash = yaml.safe_load(clash_text)
    assert "DOMAIN,direct.example,DIRECT" in clash["rules"]
    assert "DOMAIN,reject.example,REJECT" in clash["rules"]

    surge = build_surge_profile_artifacts(
        [_node()], [], "http://test/surge.conf", policy_ir=ir
    )
    assert "DOMAIN-SET," in surge.main_conf
    assert ",DIRECT" in surge.main_conf
    assert "reject-domains" in surge.main_conf
    assert surge.blocked is False

    shadowrocket, _ = build_shadowrocket_config(
        [_node()], [], "http://test/shadowrocket.conf", policy_ir=ir
    )
    assert "DOMAIN,direct.example,DIRECT" in shadowrocket
    assert "DOMAIN,reject.example,REJECT" in shadowrocket


def test_legacy_preset_ids_are_editable_proxy_contracts() -> None:
    direct_id = _contract("direct", "改名后的直连 ID", pools=["medium"])
    reject_id = _contract("ad_block", "改名后的拦截 ID", pools=["medium"])
    entries = [
        PolicyRuleEntry("direct", "DOMAIN", "direct-id.example"),
        PolicyRuleEntry("ad_block", "DOMAIN", "reject-id.example"),
    ]
    ir = build_policy_ir(
        [_node()],
        [],
        rule_entries=entries,
        contracts=[direct_id, reject_id],
        default_contract_id="direct",
    )

    clash_text, _, _ = build_clash_profile_artifacts(
        [_node()], [], policy_ir=ir, render_mode="export"
    )
    clash = yaml.safe_load(clash_text)
    assert "改名后的直连 ID" in "\n".join(clash["rules"])
    assert "改名后的拦截 ID" in "\n".join(clash["rules"])
    assert "DIRECT" not in next(
        line for line in clash["rules"] if "direct-id.example" in line
    )
    assert "REJECT" not in next(
        line for line in clash["rules"] if "reject-id.example" in line
    )

    surge = build_surge_profile_artifacts(
        [_node()], [], "http://test/surge.conf", policy_ir=ir
    )
    assert "catalog-domains-direct.txt,改名后的直连 ID" in surge.main_conf
    assert "catalog-domains-ad_block.txt,改名后的拦截 ID" in surge.main_conf

    shadowrocket, _ = build_shadowrocket_config(
        [_node()], [], "http://test/shadowrocket.conf", policy_ir=ir
    )
    assert "DOMAIN,direct-id.example,改名后的直连 ID" in shadowrocket
    assert "DOMAIN,reject-id.example,改名后的拦截 ID" in shadowrocket


def test_primitive_targets_work_without_persisted_records() -> None:
    entries = [
        PolicyRuleEntry(ROUTE_DIRECT_ACTION, "DOMAIN", "direct.example"),
        PolicyRuleEntry(ROUTE_REJECT_ACTION, "DOMAIN", "reject.example"),
    ]
    ir = build_policy_ir(
        [_node()],
        [],
        rule_entries=entries,
        contracts=[],
        default_contract_id=ROUTE_DIRECT_ACTION,
    )

    clash_text, _, _ = build_clash_profile_artifacts(
        [_node()], [], policy_ir=ir, render_mode="export"
    )
    clash = yaml.safe_load(clash_text)
    assert "DOMAIN,direct.example,DIRECT" in clash["rules"]
    assert "DOMAIN,reject.example,REJECT" in clash["rules"]

    surge = build_surge_profile_artifacts(
        [_node()], [], "http://test/surge.conf", policy_ir=ir
    )
    assert surge.blocked is False
    assert "DIRECT" in surge.main_conf
    assert "reject-domains" in surge.main_conf

    shadowrocket, _ = build_shadowrocket_config(
        [_node()], [], "http://test/shadowrocket.conf", policy_ir=ir
    )
    assert "DOMAIN,direct.example,DIRECT" in shadowrocket
    assert "DOMAIN,reject.example,REJECT" in shadowrocket


def test_explicit_empty_contracts_fail_closed_without_chain_home_fallback() -> None:
    ir = build_policy_ir([_node()], [], contracts=[])
    assert ir.default_contract_id == ""
    assert ir.metadata["contracts_explicit"] is True

    clash_text, _ = build_clash_config([_node()], [], policy_ir=ir)
    clash = yaml.safe_load(clash_text)
    default_group = next(
        item for item in clash["proxy-groups"] if item["name"] == ir.default_group_name
    )
    assert default_group["proxies"] == ["REJECT"]
    assert "chain_home" not in clash_text

    surge = build_surge_profile_artifacts(
        [_node()], [], "http://test/surge.conf", policy_ir=ir
    )
    assert "surge-default-contract-missing" in {
        item["code"] for item in surge_blocked_detail(surge)["blockers"]
    }
    assert "兜底代理 = select, REJECT" in surge.main_conf

    shadowrocket, _ = build_shadowrocket_config(
        [_node()], [], "http://test/shadowrocket.conf", policy_ir=ir
    )
    assert "兜底代理 = select, REJECT" in shadowrocket
    assert "shadowrocket-default-contract-missing" in {
        item["code"] for item in shadowrocket_blocked_detail(ir)["blockers"]
    }


def test_explicit_catalog_does_not_imply_a_default_by_preset_identity() -> None:
    ir = build_policy_ir([_node()], [], contracts=[_contract("chain_home", "存在但没有被设为默认", pools=["medium"])])
    assert ir.default_contract_id == ""
    assert "surge-default-contract-missing" in {
        item["code"] for item in surge_blocked_detail(build_surge_profile_artifacts([_node()], [], "http://test/surge.conf", policy_ir=ir))["blockers"]
    }


def test_missing_and_disabled_references_produce_client_blockers() -> None:
    disabled = _contract("disabled", "禁用契约", enabled=False, pools=["medium"])
    ir = build_policy_ir(
        [_node()],
        [],
        rule_entries=[PolicyRuleEntry("missing", "DOMAIN", "missing.example")],
        contracts=[disabled],
        default_contract_id="disabled",
    )

    surge = build_surge_profile_artifacts(
        [_node()], [], "http://test/surge.conf", policy_ir=ir
    )
    assert {item["code"] for item in surge_blocked_detail(surge)["blockers"]} >= {
        "surge-default-contract-disabled",
        "surge-referenced-missing-contract",
    }
    assert {item["code"] for item in build_clash_blocked_detail(ir)["blockers"]} >= {
        "clash-default-contract-disabled",
        "clash-referenced-missing-contract",
    }
    assert {item["code"] for item in shadowrocket_blocked_detail(ir)["blockers"]} >= {
        "shadowrocket-default-contract-disabled",
        "shadowrocket-referenced-missing-contract",
    }


def test_repurposed_quality_id_uses_persisted_pool_topology() -> None:
    nodes = [
        _node(),
        NodeRecord(
            name="hq-standard-1",
            host="hq-standard.example.com",
            port=443,
            protocol="http",
            quality_group=QUALITY_HIGH_STANDARD,
        ),
    ]
    contract = _contract(
        "medium",
        "中等质量",
        pools=["hq_standard"],
    )
    ir = build_policy_ir(
        nodes,
        [],
        rule_entries=[PolicyRuleEntry("medium", "DOMAIN", "topology.example")],
        contracts=[contract],
        default_contract_id="medium",
    )

    clash_text, _, _ = build_clash_profile_artifacts(
        nodes, [], policy_ir=ir, render_mode="export"
    )
    clash = yaml.safe_load(clash_text)
    medium_group = next(item for item in clash["proxy-groups"] if item["name"] == "中等质量")
    assert medium_group["proxies"] == ["高质量-低倍率·自动", "REJECT"]
    high_standard_auto = next(
        item for item in clash["proxy-groups"] if item["name"] == "高质量-低倍率·自动"
    )
    assert high_standard_auto["use"] == ["high-standard"]
    assert "中等质量·自动" not in {item["name"] for item in clash["proxy-groups"]}

    surge = build_surge_profile_artifacts(nodes, [], "http://test/surge.conf", policy_ir=ir)
    assert "中等质量 = fallback, 高质量-低倍率·自动" in surge.main_conf
    assert "高质量-低倍率·自动 = url-test, hq-standard-1" in surge.main_conf
    assert "中等质量·自动" not in surge.main_conf

    shadowrocket, _ = build_shadowrocket_config(
        nodes, [], "http://test/shadowrocket.conf", policy_ir=ir
    )
    assert "中等质量 = fallback, 高质量-低倍率·自动" in shadowrocket
    assert "高质量-低倍率·自动 = url-test, hq-standard-1" in shadowrocket
    assert "中等质量·自动" not in shadowrocket
