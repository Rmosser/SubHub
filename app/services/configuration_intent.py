"""Frozen desired state; compatibility defaults are chosen at derivation only."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import ipaddress
import json
from dataclasses import asdict, dataclass, field, fields, is_dataclass, replace
from functools import cache, cached_property
from pathlib import Path
from typing import Any, Mapping

from app.models import (
    BusinessGroup,
    ExternalProxyProgramTemplate,
    GeneralProfile,
    NodeRecord,
    PolicyIR,
    PolicyRuleEntry,
    ProcessRuleTemplate,
    RenderWarning,
    RouteContract,
    ServiceCatalogEntry,
)
from app.services.lazycat_profile import normalize_lazycat_profile_settings


class FrozenDict(dict):
    def _immutable(self, *args, **kwargs):
        raise TypeError("intent registry is immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = (
        __ior__
    ) = _immutable

    def __deepcopy__(self, memo):
        return {deepcopy(k, memo): deepcopy(v, memo) for k, v in self.items()}


def _freeze(value):
    if isinstance(value, dict):
        return FrozenDict({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


# Parse once; every public reference is recursively immutable.
_REGISTRY = _freeze(
    json.loads(Path(__file__).with_name("intent_registry.json").read_text())
)
TARGETS = ("clash", "surge", "shadowrocket")
MIHOMO_CIDR_RULE_TYPES = frozenset({"IP-CIDR", "IP-CIDR6", "SRC-IP-CIDR"})
IP_RULE_TYPES = frozenset({"IP-CIDR", "IP-CIDR6", "GEOIP", "IP-ASN"})


def intent_registry() -> Mapping[str, Any]:
    return _REGISTRY


@cache
def _record_fields(cls: type) -> tuple[str, ...]:
    return tuple(f.name for f in fields(cls))


def _json(value: object) -> str:
    # Native node raw data already permits Infinity/NaN. Snapshotting must not
    # impose a stricter source contract than the established renderers.
    def record(obj):
        if is_dataclass(obj):
            return {name: getattr(obj, name) for name in _record_fields(type(obj))}
        raise TypeError(f"Unsupported intent value: {type(obj).__name__}")

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=record)


def _rule_key(entry: PolicyRuleEntry) -> tuple:
    # The single definition of a rule's identity fields. It includes
    # ownership, target and options: two predicates with different
    # source/target semantics must not accidentally share a DNS policy.
    return (
        entry.rule_type,
        entry.value,
        tuple(entry.extras),
        entry.target_contract_id,
        entry.source_kind,
        entry.category_name,
        entry.platform_scope,
    )


def rule_identity(entry: PolicyRuleEntry) -> str:
    # Hash the key instead of listing the fields again. _json writes tuples
    # and lists the same way, so the digest is unchanged by tuple(extras).
    identity_json = _json(_rule_key(entry))
    return hashlib.sha256(identity_json.encode()).hexdigest()


@dataclass(frozen=True)
class IntentValue:
    key: str
    value_json: str = field(repr=False)


@dataclass(frozen=True)
class IPResolutionIntent:
    rule_index: int  # descriptive only; never used to bind a policy
    location: str
    clash: str
    surge: str
    shadowrocket: str
    origin: str
    rule_id: str
    rule_key: tuple
    source_options: tuple[str, ...]
    clash_options: tuple[str, ...]


def ip_resolution_for_rule(
    entry: PolicyRuleEntry, index: int = 0
) -> IPResolutionIntent | None:
    kind = entry.rule_type.upper()
    domain_ip = False
    # Valid IP literals start with a hex digit or ':'. Avoid two expensive
    # address parsers for ordinary domain rules, which never need an IP policy.
    if kind == "DOMAIN" and entry.value.strip()[:1].lower() in "0123456789abcdef:":
        try:
            ipaddress.ip_address(entry.value.strip())
            domain_ip = True
        except ValueError:
            pass
    if (
        kind not in IP_RULE_TYPES | MIHOMO_CIDR_RULE_TYPES | {"AND", "OR", "NOT"}
        and not domain_ip
    ):
        return None
    explicit = any(item.strip().lower() == "no-resolve" for item in entry.extras)
    native = "never" if explicit else "client-default"
    options = list(entry.extras)
    if kind in MIHOMO_CIDR_RULE_TYPES:
        # Reproduce the baseline, including its removal of other source options.
        options = ["no-resolve"]
    elif domain_ip and not explicit:
        options.append("no-resolve")
    return IPResolutionIntent(
        rule_index=index,
        rule_id=rule_identity(entry),
        rule_key=_rule_key(entry),
        location="logical-preserve" if kind in {"AND", "OR", "NOT"} else "top-level",
        clash="never" if kind in MIHOMO_CIDR_RULE_TYPES or domain_ip else native,
        surge=native,
        shadowrocket=native,
        origin="source-option" if explicit else "legacy-client-default",
        source_options=tuple(entry.extras),
        clash_options=tuple(options),
    )


def project_ip_match_options(
    resolution: IPResolutionIntent, *, target: str
) -> list[str]:
    """Consume explicit frozen options. No platform/type default is inferred."""
    options = list(
        resolution.clash_options if target == "clash" else resolution.source_options
    )
    if getattr(resolution, target) == "client-default":
        return [v for v in options if v.strip().lower() != "no-resolve"]
    if not any(v.strip().lower() == "no-resolve" for v in options):
        options.append("no-resolve")
    return options


@dataclass(frozen=True)
class ConfigurationIntent:
    schema_version: int
    profile: str
    values: tuple[IntentValue, ...]
    compatibility_overrides: tuple[IntentValue, ...]
    ip_resolution: tuple[IPResolutionIntent, ...]
    _policy_json: str = field(repr=False)
    _compiled_rules_json: str = field(
        repr=False
    )  # empty means identical to routing.rule_entries
    _compile_warnings_json: str = field(repr=False)
    _requested_settings_json: str = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "values": {v.key: json.loads(v.value_json) for v in self.values},
            "compatibility_overrides": {
                v.key: json.loads(v.value_json) for v in self.compatibility_overrides
            },
            "ip_resolution": [asdict(v) for v in self.ip_resolution],
            "routing": json.loads(self._policy_json),
            "compiled_rules": json.loads(self._compiled_rules_json)
            if self._compiled_rules_json
            else json.loads(self._policy_json)["rule_entries"],
            "compile_warnings": json.loads(self._compile_warnings_json),
            "requested_settings": json.loads(self._requested_settings_json),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ConfigurationIntent:
        if payload["schema_version"] != 1:
            raise ValueError("unsupported configuration intent schema")
        return cls(
            schema_version=1,
            profile=payload["profile"],
            values=tuple(
                IntentValue(k, _json(v)) for k, v in payload["values"].items()
            ),
            compatibility_overrides=tuple(
                IntentValue(k, _json(v))
                for k, v in payload["compatibility_overrides"].items()
            ),
            ip_resolution=tuple(
                IPResolutionIntent(
                    **{
                        **v,
                        "source_options": tuple(v["source_options"]),
                        "clash_options": tuple(v["clash_options"]),
                        "rule_key": tuple(
                            tuple(x) if i == 2 else x
                            for i, x in enumerate(v["rule_key"])
                        ),
                    }
                )
                for v in payload["ip_resolution"]
            ),
            _policy_json=_json(payload["routing"]),
            _compiled_rules_json=(
                ""
                if payload["compiled_rules"] == payload["routing"]["rule_entries"]
                else _json(payload["compiled_rules"])
            ),
            _compile_warnings_json=_json(payload["compile_warnings"]),
            _requested_settings_json=_json(payload["requested_settings"]),
        )


def derive_configuration_intent(
    policy: PolicyIR,
    profile_settings: Mapping[str, object] | None,
    *,
    profile: str,
    compiled_rules: list[PolicyRuleEntry] | None = None,
) -> ConfigurationIntent:
    # Reuse the existing pure compiler at the derivation boundary. Lazy import
    # avoids a module initialization cycle; rendering never invokes an LLM.
    from app.services.subscription_builder import _compiled_policy_rule_entries

    compiled, warnings = _compiled_policy_rule_entries(policy)
    if compiled_rules is not None and _json(compiled_rules) != _json(compiled):
        raise ValueError("compiled_rules differ from internally compiled intent")
    settings = normalize_lazycat_profile_settings(profile_settings)
    values: dict[str, object] = {}
    overrides = []
    for item in intent_registry()["settings"]:
        key, primary = item["id"], item["canonical_key"]
        values[primary] = settings[primary]
        if key != primary and settings[key] != settings[primary]:
            overrides.append(IntentValue(key, _json(settings[key])))
    return ConfigurationIntent(
        schema_version=1,
        profile=profile,
        values=tuple(IntentValue(k, _json(v)) for k, v in values.items()),
        compatibility_overrides=tuple(overrides),
        ip_resolution=tuple(
            p
            for i, e in enumerate(compiled)
            if (p := ip_resolution_for_rule(e, i)) is not None
        ),
        _policy_json=_json(policy),
        _compiled_rules_json="" if compiled == policy.rule_entries else _json(compiled),
        _compile_warnings_json=_json(warnings),
        _requested_settings_json=_json(dict(profile_settings or {})),
    )


def _restore_policy(payload: dict[str, Any]) -> PolicyIR:
    for key, cls in (
        ("nodes", NodeRecord),
        ("business_groups", BusinessGroup),
        ("rule_entries", PolicyRuleEntry),
        ("contracts", RouteContract),
        ("catalog_bindings", ServiceCatalogEntry),
        ("process_rules", ProcessRuleTemplate),
        ("external_proxy_programs", ExternalProxyProgramTemplate),
        ("warnings", RenderWarning),
    ):
        payload[key] = [cls(**item) for item in payload[key]]
    if payload["general_profile"] is not None:
        payload["general_profile"] = GeneralProfile(**payload["general_profile"])
    return PolicyIR(**payload)


@dataclass
class IntentProjection:
    target: str
    policy: PolicyIR
    settings: dict[str, Any]
    diagnostics: list[RenderWarning]
    ip_resolution: tuple[IPResolutionIntent, ...]
    _compiled_rules_json: str
    _compile_warnings_json: str
    requested_settings: dict[str, Any]

    @cached_property
    def _compiled(self) -> tuple[list[PolicyRuleEntry], list[RenderWarning]]:
        entries = (
            [PolicyRuleEntry(**v) for v in json.loads(self._compiled_rules_json)]
            if self._compiled_rules_json
            else self.policy.rule_entries
        )
        return entries, [
            RenderWarning(**v) for v in json.loads(self._compile_warnings_json)
        ]

    def compiled_rules(self) -> tuple[list[PolicyRuleEntry], list[RenderWarning]]:
        return self._compiled

    @cached_property
    def _ip_policies(self) -> dict[tuple, IPResolutionIntent]:
        # Derivation already hashed each relevant rule. Its frozen structural
        # key lets rendering and diagnostics reuse that identity without hashing.
        return {p.rule_key: p for p in self.ip_resolution}

    def project_rules(self, entries: list[PolicyRuleEntry]) -> list[PolicyRuleEntry]:
        policies = self._ip_policies
        if not policies:
            return list(entries)
        result = []
        for entry in entries:
            resolution = policies.get(_rule_key(entry))
            if resolution is not None and resolution.location == "top-level":
                entry = replace(
                    entry,
                    extras=project_ip_match_options(resolution, target=self.target),
                )
            result.append(entry)
        return result


def _warning(code_key: str, target: str, **format_values) -> RenderWarning:
    spec = intent_registry()["diagnostics"][code_key]
    return RenderWarning(
        code=spec["code"],
        target=target,
        bucket=spec["bucket"],
        message=spec["message"].format(**format_values),
    )


def project_configuration_intent(
    intent: ConfigurationIntent, target: str
) -> IntentProjection:
    if target not in TARGETS:
        raise ValueError(f"unknown intent target: {target}")
    values = {v.key: json.loads(v.value_json) for v in intent.values}
    overrides = {
        v.key: json.loads(v.value_json) for v in intent.compatibility_overrides
    }
    settings = {
        item["id"]: overrides.get(item["id"], values[item["canonical_key"]])
        for item in intent_registry()["settings"]
    }
    if intent.profile != "lazycat" and not (
        target == "clash" and intent.profile == "raw"
    ):
        settings = normalize_lazycat_profile_settings(None)
    policy = _restore_policy(json.loads(intent._policy_json))
    diagnostics = _setting_diagnostics(settings, target)
    projection = IntentProjection(
        target,
        policy,
        settings,
        diagnostics,
        intent.ip_resolution,
        intent._compiled_rules_json,
        intent._compile_warnings_json,
        json.loads(intent._requested_settings_json),
    )
    diagnostic_policy = (
        policy
        if policy.rule_entries
        else replace(policy, rule_entries=projection.compiled_rules()[0])
    )
    diagnostics.extend(_routing_capability_diagnostics(diagnostic_policy, target))
    return projection


def _setting_diagnostics(
    settings: Mapping[str, object], target: str
) -> list[RenderWarning]:
    defaults = normalize_lazycat_profile_settings(None)
    diagnostics = []
    for item in intent_registry()["settings"]:
        key = item["id"]
        projection = item["projections"][target]
        native_pending = (
            projection["status"] == "pending_validation"
            and projection.get("binding") == key
            and (bool(settings[key]) or item["family"] == "ipv6-policy")
        )
        if (
            item["family"] == "excluded-routes"
            and target == "clash"
            and not settings["clash_tun_enable"]
        ):
            native_pending = False
        if (
            key in {"clash_fake_ip_filter", "clash_always_real_ip"}
            and settings["clash_dns_enhanced_mode"] != "fake-ip"
        ):
            native_pending = False
        if not projection["diagnostic_code"] or (
            settings[key] == defaults[key] and not native_pending
        ):
            continue
        diagnostics.append(
            RenderWarning(
                code=projection["diagnostic_code"],
                target=key,
                message=f"{item['intent']}：{projection['consequence']}",
                bucket="pending_validation"
                if projection["status"] == "pending_validation"
                else "downgraded",
            )
        )
    return diagnostics


def _routing_capability_diagnostics(
    policy: PolicyIR, target: str
) -> list[RenderWarning]:
    diagnostics = {}
    for kind, objects, code_key in (
        ("process", policy.process_rules, "process_overlay"),
        ("external", policy.external_proxy_programs, "external_overlay"),
    ):
        if target == "surge":
            for obj in objects:
                # Hub disables every object that needs rebinding, so checking
                # enabled here would hide exactly the objects this warns about.
                if obj.migration_warning:
                    name = (
                        obj.value if kind == "process" else obj.name or obj.program_path
                    )
                    warning = _warning(kind + "_migration_surge", name)
                    diagnostics[(warning.code, name)] = warning
            continue
        for obj in objects:
            if obj.enabled:
                name = obj.value if kind == "process" else obj.name or obj.program_path
                warning = _warning(code_key + "_" + target, name)
                diagnostics[(warning.code, name)] = warning
    collections = {
        "PolicyIR": [policy],
        "RouteContract": policy.contracts,
        "PolicyRuleEntry": policy.rule_entries,
        "BusinessGroup": policy.business_groups,
        "ServiceCatalogEntry": policy.catalog_bindings,
    }
    rules_by_type: dict[str, list[PolicyRuleEntry]] = {}
    for entry in policy.rule_entries:
        rules_by_type.setdefault(entry.rule_type, []).append(entry)
    gaps: dict[tuple[str, int], str] = {}
    indexed_gap_roots: set[str] = set()
    # Rule types that this client's renderer drops share one registered code.
    # Collect them across their rows so one warning names the dropped types,
    # instead of one warning per category that names only the first type.
    dropped_rule_type_entry = intent_registry()["diagnostics"].get(
        "rule_type_dropped_" + target
    )
    dropped_rule_types: list[str] = []
    for row in intent_registry()["routing"]:
        p = row["projections"][target]
        if not p["diagnostic_code"] or row.get("scope", target) != target:
            continue
        root, key = row.get("field", row["id"]).split(".", 1)
        if (
            root in {"ProcessRuleTemplate", "ExternalProxyProgramTemplate"}
            or key == "ip_resolution"
        ):
            continue
        is_gap = p["diagnostic_code"].startswith("intent-routing-evidence-gap-")
        if is_gap and root in indexed_gap_roots:
            continue
        objects = (
            rules_by_type.get(row["value"], [])
            if root == "PolicyRuleEntry" and "value" in row
            else collections.get(root, [])
        )
        if key == "strategy_type" and row.get("value") == "strict":
            # Default scenarios carry several strict contracts. Report them
            # once per client with a count and a few names.
            warning = _strict_contract_warning(policy.contracts, target, row["intent"])
            if warning is not None:
                diagnostics[(warning.code, warning.target)] = warning
            continue
        is_dropped_rule_type = (
            dropped_rule_type_entry is not None
            and p["diagnostic_code"] == dropped_rule_type_entry["code"]
        )
        if is_dropped_rule_type:
            if objects:
                dropped_rule_types.append(row["value"])
            continue
        for obj in objects:
            value = getattr(obj, key, None)
            if not value or ("value" in row and value != row["value"]):
                continue
            if root == "RouteContract" and (
                not obj.enabled or obj.routing_action != "proxy"
            ):
                continue
            name = (
                getattr(obj, "display_name", "")
                or getattr(obj, "category_name", "")
                or getattr(obj, "name", "")
                or row["intent"]
            )
            if is_gap:
                # One declaration can have several unproven fields. Count it
                # once, and point to concrete rules/contracts instead of a label.
                if root == "PolicyIR":
                    continue
                name = obj.value if root == "PolicyRuleEntry" else name
                gaps[(root, id(obj))] = name
                continue
            elif root == "PolicyRuleEntry":
                name = obj.category_name or "未分类规则"
            elif key != "strategy_type":
                name = {
                    "RouteContract": "路由契约",
                    "BusinessGroup": "策略组",
                    "PolicyIR": "分流与运行配置",
                    "ServiceCatalogEntry": "分类契约绑定",
                }.get(root, name)
            if (p["diagnostic_code"], name) not in diagnostics:
                warning = RenderWarning(
                    code=p["diagnostic_code"],
                    target=name,
                    message=p["consequence"],
                    bucket="pending_validation"
                    if p["status"] == "pending_validation"
                    else "downgraded",
                )
                diagnostics[(warning.code, name)] = warning
        if (
            is_gap
            and "value" not in row
            and key in {"target_contract_id", "id", "name", "category_name"}
        ):
            indexed_gap_roots.add(root)
    if dropped_rule_types:
        examples = "、".join(dropped_rule_types[:3])
        warning = _warning(
            "rule_type_dropped_" + target,
            examples,
            count=len(dropped_rule_types),
            examples=examples,
        )
        diagnostics[(warning.code, warning.target)] = warning
    if gaps:
        names = list(dict.fromkeys(gaps.values()))[:3]
        warning = _warning(
            "routing_gap_" + target,
            "、".join(names),
            count=len(gaps),
            examples="、".join(names),
        )
        diagnostics[(warning.code, warning.target)] = warning
    return list(diagnostics.values())


def _strict_contract_warning(
    contracts: list[RouteContract], target: str, unnamed_label: str
) -> RenderWarning | None:
    """Merge the enabled strict proxy contracts into one warning for a client."""
    names: list[str] = []
    for contract in contracts:
        if contract.strategy_type != "strict":
            continue
        if not contract.enabled or contract.routing_action != "proxy":
            continue
        names.append(contract.display_name or unnamed_label)
    if not names:
        return None
    examples = "、".join(list(dict.fromkeys(names))[:3])
    return _warning(
        "strict_contract_" + target,
        examples,
        count=len(names),
        examples=examples,
    )


def count_strict_contracts_rendered_as_fallback(
    diagnostics: list[RenderWarning],
    policy: PolicyIR,
    target: str,
    fallback_contract_ids: set[str],
) -> list[RenderWarning]:
    """Recount the strict warning over the contracts a client rendered as fallback.

    Diagnostics are derived from the policy before rendering, and the strict
    warning describes fallback groups. A client can still render a strict
    contract another way: Surge writes one without renderable primary pools
    as "select, REJECT". The caller passes the contracts it rendered as
    fallback groups; the warning is rebuilt over those, in place, or removed
    when none of them is strict.
    """
    strict_code = intent_registry()["diagnostics"]["strict_contract_" + target]["code"]
    strict_row = next(
        row
        for row in intent_registry()["routing"]
        if row["id"] == "RouteContract.strategy_type[strict]"
    )
    rendered_contracts = [
        contract for contract in policy.contracts if contract.id in fallback_contract_ids
    ]
    result: list[RenderWarning] = []
    for warning in diagnostics:
        if warning.code != strict_code:
            result.append(warning)
            continue
        recounted = _strict_contract_warning(rendered_contracts, target, strict_row["intent"])
        if recounted is not None:
            result.append(recounted)
    return result


def routing_intent_diagnostics(
    entries: list[PolicyRuleEntry],
    *,
    target: str,
    default_action: str,
    ip_resolution: tuple[IPResolutionIntent, ...] | None = None,
    projection: IntentProjection | None = None,
) -> list[RenderWarning]:
    policies = projection._ip_policies if projection is not None else None
    by_identity = (
        {p.rule_id: p for p in ip_resolution}
        if policies is None and ip_resolution is not None
        else None
    )
    categories: dict[str, list[PolicyRuleEntry]] = {}
    differences: dict[str, list[PolicyRuleEntry]] = {}
    rocket: dict[str, list[PolicyRuleEntry]] = {}
    for entry in entries:
        category = entry.category_name or "未分类规则"
        if entry.category_name and entry.source_kind not in {"system", "lazycat"}:
            categories.setdefault(category, []).append(entry)
        if entry.rule_type.upper() in {"IP-CIDR", "IP-CIDR6"}:
            resolution = (
                policies.get(_rule_key(entry))
                if policies is not None
                else by_identity.get(rule_identity(entry))
                if by_identity is not None
                else ip_resolution_for_rule(entry)
            )
        else:
            resolution = None
        if (
            entry.rule_type.upper() in {"IP-CIDR", "IP-CIDR6"}
            and resolution is not None
            and len({resolution.clash, resolution.surge, resolution.shadowrocket}) > 1
        ):
            differences.setdefault(category, []).append(entry)
        if target == "shadowrocket" and entry.rule_type.upper() in IP_RULE_TYPES:
            rocket.setdefault(category, []).append(entry)
    diagnostics = []
    for category, rules in differences.items():
        diagnostics.append(
            _warning(
                "ip_defaults",
                category,
                count=len(rules),
                examples="、".join(e.value for e in rules[:3]),
            )
        )
    for category, rules in rocket.items():
        diagnostics.append(
            _warning(
                "rocket_ip",
                category,
                count=len(rules),
                examples="、".join(e.value for e in rules[:3]),
            )
        )
    if default_action == "direct":
        for category, rules in categories.items():
            if rules and all(e.rule_type.upper() in IP_RULE_TYPES for e in rules):
                diagnostics.append(_warning("ip_only", category, count=len(rules)))
    return diagnostics
