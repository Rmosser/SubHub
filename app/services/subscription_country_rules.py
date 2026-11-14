from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Sequence


PREFERRED_COUNTRY = "美国"
OTHER_COUNTRY = "其他"
INTERNATIONAL_BEST = "国际最优"


@dataclass(frozen=True)
class CountryAliasRule:
    country: str
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class SourceCountryRuleSet:
    source_key: str
    match_tokens: tuple[str, ...]
    alias_rules: tuple[CountryAliasRule, ...] = ()


# 全局兜底规则：不依赖来源，所有标准源/Gorelay 节点都可复用。
GLOBAL_COUNTRY_ALIAS_RULES: tuple[CountryAliasRule, ...] = (
    CountryAliasRule("印度尼西亚", ("印度尼西亚", "印尼", "indonesia")),
    CountryAliasRule("新西兰", ("新西兰", "new zealand")),
    CountryAliasRule("尼日利亚", ("尼日利亚", "nigeria")),
    CountryAliasRule("摩尔多瓦", ("摩尔多瓦", "moldova")),
    CountryAliasRule("乌克兰", ("乌克兰", "ukraine")),
    CountryAliasRule("新加坡", ("新加坡", "singapore")),
    CountryAliasRule("马来西亚", ("马来西亚", "malaysia")),
    CountryAliasRule("菲律宾", ("菲律宾", "philippines")),
    CountryAliasRule("阿联酋", ("阿联酋", "united arab emirates", "uae")),
    CountryAliasRule("阿根廷", ("阿根廷", "argentina")),
    CountryAliasRule("澳大利亚", ("澳大利亚", "australia")),
    CountryAliasRule("加拿大", ("加拿大", "canada")),
    CountryAliasRule("西班牙", ("西班牙", "spain")),
    CountryAliasRule("匈牙利", ("匈牙利", "hungary")),
    CountryAliasRule("以色列", ("以色列", "israel")),
    CountryAliasRule("意大利", ("意大利", "italy")),
    CountryAliasRule("土耳其", ("土耳其", "turkey")),
    CountryAliasRule("巴基斯坦", ("巴基斯坦", "pakistan")),
    CountryAliasRule("巴西", ("巴西", "brazil")),
    CountryAliasRule("智利", ("智利", "chile")),
    CountryAliasRule("德国", ("德国", "germany")),
    CountryAliasRule("法国", ("法国", "france")),
    CountryAliasRule("英国", ("英国", "united kingdom", "england", "britain")),
    CountryAliasRule("荷兰", ("荷兰", "netherlands")),
    CountryAliasRule("埃及", ("埃及", "egypt")),
    CountryAliasRule("印度", ("印度", "india")),
    CountryAliasRule("泰国", ("泰国", "thailand")),
    CountryAliasRule("越南", ("越南", "vietnam")),
    CountryAliasRule("韩国", ("韩国", "korea", "south korea")),
    CountryAliasRule("日本", ("日本", "japan")),
    CountryAliasRule("台湾", ("台湾", "taiwan")),
    CountryAliasRule("香港", ("香港", "hong kong")),
    CountryAliasRule("澳门", ("澳门", "macau")),
    CountryAliasRule("蒙古", ("蒙古", "mongolia")),
    CountryAliasRule(PREFERRED_COUNTRY, (PREFERRED_COUNTRY, "united states", "usa", "us")),
)

# 来源级规则：为后续接入新源预留局部覆盖点。
# 当前 FlowerCloud / 山海 主要仍复用全局规则，但新增来源时优先在这里补充局部别名。
SOURCE_COUNTRY_RULESETS: tuple[SourceCountryRuleSet, ...] = (
    SourceCountryRuleSet(source_key="flowercloud", match_tokens=("flowercloud",)),
    SourceCountryRuleSet(source_key="山海", match_tokens=("山海", "shanhai")),
)

# 兼容现有调用方与测试命名。
COUNTRY_ALIAS_RULES = GLOBAL_COUNTRY_ALIAS_RULES


def _compile_alias_map(rules: Sequence[CountryAliasRule]) -> dict[str, tuple[str, ...]]:
    return {
        rule.country: tuple(alias for alias in rule.aliases if alias)
        for rule in rules
    }


_ALIASES_BY_COUNTRY: dict[str, tuple[str, ...]] = _compile_alias_map(GLOBAL_COUNTRY_ALIAS_RULES)
def _alias_pattern(alias: str) -> str:
    escaped = re.escape(alias)
    # Digits, underscores and adjacent Chinese are valid separators for aliases.
    if re.fullmatch(r"[A-Za-z ]+", alias):
        return rf"(?<![A-Za-z]){escaped}(?![A-Za-z])"
    return escaped


_KNOWN_COUNTRY_REGEX = "(?i)" + "|".join(
    _alias_pattern(alias)
    for rule in GLOBAL_COUNTRY_ALIAS_RULES
    for alias in rule.aliases
    if alias
)
def _match_ruleset(source_hint: str) -> SourceCountryRuleSet | None:
    hint = str(source_hint or "").strip().lower()
    if not hint:
        return None
    for ruleset in SOURCE_COUNTRY_RULESETS:
        if any(token and token.lower() in hint for token in ruleset.match_tokens):
            return ruleset
    return None


def _detect_from_rules(name: str, rules: Sequence[CountryAliasRule]) -> str:
    text = str(name or "").strip()
    for rule in rules:
        for alias in rule.aliases:
            normalized_alias = str(alias or "").strip()
            if not normalized_alias:
                continue
            if re.search(_alias_pattern(normalized_alias), text, re.IGNORECASE):
                return rule.country
    return ""


def extract_source_hint(name: str) -> str:
    text = str(name or "").strip()
    if text.startswith("[") and "]" in text:
        return text[1 : text.index("]")].strip()
    return ""


def country_group_name(pool_name: str, country: str) -> str:
    return f"{pool_name}·{country}"


def international_group_name(pool_name: str) -> str:
    return f"{pool_name}·{INTERNATIONAL_BEST}"


def country_regex(country: str) -> str:
    aliases = _ALIASES_BY_COUNTRY.get(country, (country,))
    return "(?i)" + "|".join(_alias_pattern(alias) for alias in aliases if alias)


def known_country_regex() -> str:
    return _KNOWN_COUNTRY_REGEX


def detect_node_country(name: str, *, source_hint: str = "") -> str:
    ruleset = _match_ruleset(source_hint) or _match_ruleset(extract_source_hint(name))
    if ruleset and ruleset.alias_rules:
        detected = _detect_from_rules(name, ruleset.alias_rules)
        if detected:
            return detected

    detected = _detect_from_rules(name, GLOBAL_COUNTRY_ALIAS_RULES)
    if detected:
        return detected
    return OTHER_COUNTRY


def ordered_country_names(country_members: Mapping[str, Sequence[object]]) -> list[str]:
    def sort_key(country: str, count: int) -> tuple[int, int, str]:
        if country == PREFERRED_COUNTRY:
            return (0, 0, country)
        if country == OTHER_COUNTRY:
            return (2, 0, country)
        return (1, -count, country)

    return [
        country
        for country, members in sorted(
            country_members.items(),
            key=lambda item: sort_key(item[0], len(item[1])),
        )
        if members
    ]


def country_routing_plan(pool_name: str, country_members: Mapping[str, Sequence[object]]) -> dict[str, object]:
    ordered_countries = ordered_country_names(country_members)
    country_groups = [country_group_name(pool_name, country) for country in ordered_countries]
    preferred_group = (
        country_group_name(pool_name, PREFERRED_COUNTRY) if PREFERRED_COUNTRY in ordered_countries else ""
    )
    non_preferred_groups = [
        country_group_name(pool_name, country)
        for country in ordered_countries
        if country != PREFERRED_COUNTRY
    ]
    international_group = ""
    if non_preferred_groups and (preferred_group or len(non_preferred_groups) > 1):
        international_group = international_group_name(pool_name)

    fallback_groups: list[str] = []
    if preferred_group:
        fallback_groups.append(preferred_group)
        if international_group:
            fallback_groups.append(international_group)
        else:
            fallback_groups.extend(non_preferred_groups)
    elif international_group:
        fallback_groups.append(international_group)
    else:
        fallback_groups.extend(non_preferred_groups)

    return {
        "countries": ordered_countries,
        "country_groups": country_groups,
        "non_preferred_groups": non_preferred_groups,
        "international_group": international_group,
        "fallback_groups": fallback_groups,
    }
