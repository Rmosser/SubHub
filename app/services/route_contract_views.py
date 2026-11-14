from __future__ import annotations

from dataclasses import replace
from typing import Iterable, Mapping

from app.models import (
    RouteContract,
    RouteContractView,
    contract_description,
    contract_display_name,
    normalize_contract_id,
    resolve_contract_id,
)

DEFAULT_SCENARIO_ID = "scenario-default"


def scenario_route_contract_view_map(repo, scenario_id: str) -> dict[str, RouteContractView]:
    safe_scenario_id = str(scenario_id or "").strip() or DEFAULT_SCENARIO_ID
    output = {
        str(item.contract_id or "").strip(): item
        for item in repo.list_scenario_route_contract_views(safe_scenario_id)
        if str(item.contract_id or "").strip()
    }
    if safe_scenario_id == DEFAULT_SCENARIO_ID:
        return output
    inherited = scenario_route_contract_view_map(repo, DEFAULT_SCENARIO_ID)
    if not output:
        return inherited
    merged = dict(inherited)
    merged.update(output)
    return merged


def scenario_route_contracts(repo, scenario_id: str) -> list[RouteContract]:
    view_map = scenario_route_contract_view_map(repo, scenario_id)
    items: list[RouteContract] = []
    safe_scenario_id = str(scenario_id or "").strip() or DEFAULT_SCENARIO_ID
    for contract in repo.list_route_contracts(safe_scenario_id):
        view = view_map.get(contract.id)
        items.append(_merge_contract_view(contract, view))
    items.sort(key=lambda item: (int(item.sort_order or 0), item.id))
    return items


def scenario_route_contracts_by_id(repo, scenario_id: str) -> dict[str, RouteContract]:
    return {
        str(item.id or "").strip(): item
        for item in scenario_route_contracts(repo, scenario_id)
        if str(item.id or "").strip()
    }


def scenario_route_contract(repo, scenario_id: str, contract_id: object) -> RouteContract | None:
    normalized = normalize_contract_id(contract_id)
    if not normalized:
        return None
    return scenario_route_contracts_by_id(repo, scenario_id).get(normalized)


class ScenarioContractLookup:
    """One scenario's merged route contracts, read from the repo once.

    The ``scenario_*`` helpers below re-read every contract and view on each call;
    a request that resolves a reference per row builds this once instead.
    """

    def __init__(self, contracts: Iterable[RouteContract]):
        self._by_id = {
            str(item.id or "").strip(): item
            for item in contracts
            if str(item.id or "").strip()
        }
        self._display_name_map = {
            contract_id: str(item.display_name or "").strip()
            for contract_id, item in self._by_id.items()
            if str(item.display_name or "").strip()
        }

    def resolve_contract_id(self, value: object) -> str:
        return resolve_contract_id(value, display_name_map=self._display_name_map)

    def display_name(self, contract_id: object) -> str:
        normalized = normalize_contract_id(contract_id)
        if not normalized:
            return str(contract_id or "").strip()
        contract = self._by_id.get(normalized)
        if contract and str(contract.display_name or "").strip():
            return str(contract.display_name or "").strip()
        return contract_display_name(normalized)


def scenario_contract_lookup(repo, scenario_id: str) -> ScenarioContractLookup:
    return ScenarioContractLookup(scenario_route_contracts(repo, scenario_id))


def scenario_contract_display_name(repo, scenario_id: str, contract_id: object) -> str:
    if not normalize_contract_id(contract_id):
        return str(contract_id or "").strip()
    return scenario_contract_lookup(repo, scenario_id).display_name(contract_id)


def scenario_contract_description(repo, scenario_id: str, contract_id: object) -> str:
    normalized = normalize_contract_id(contract_id)
    if not normalized:
        return ""
    contract = scenario_route_contract(repo, scenario_id, normalized)
    if contract and str(contract.description or "").strip():
        return str(contract.description or "").strip()
    return contract_description(normalized)


def scenario_contract_llm_routing_intent(repo, scenario_id: str, contract_id: object) -> str:
    normalized = normalize_contract_id(contract_id)
    if not normalized:
        return ""
    contract = scenario_route_contract(repo, scenario_id, normalized)
    return str(getattr(contract, "llm_routing_intent", "") or scenario_contract_description(repo, scenario_id, normalized)).strip()


def scenario_resolve_contract_id(repo, scenario_id: str, value: object) -> str:
    return scenario_contract_lookup(repo, scenario_id).resolve_contract_id(value)


def scenario_default_contract_id(repo, scenario_id: str) -> str:
    for item in scenario_route_contracts(repo, scenario_id):
        if bool(getattr(item, "is_default", False)):
            return item.id
    return ""


def _merge_contract_view(contract: RouteContract, view: RouteContractView | None) -> RouteContract:
    if view is None:
        return replace(
            contract,
            llm_routing_intent=str(contract.description or ""),
            is_default=False,
        )
    return replace(
        contract,
        display_name=str(view.display_name or contract.display_name or "").strip() or contract.id,
        description=str(view.description or "").strip(),
        enabled=bool(view.enabled),
        sort_order=int(view.sort_order or 0),
        llm_routing_intent=str(view.llm_routing_intent or "").strip(),
        is_default=bool(view.is_default),
    )
