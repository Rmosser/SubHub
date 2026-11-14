from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Callable

from app.models import (
    QUALITY_HIGH_AIRPORT,
    STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT,
    STANDARD_SOURCE_MODE_ROUTE_CONTRACT,
    STANDARD_SOURCE_MODES,
    StandardSource,
    contract_display_name,
    resolve_contract_id,
)


_TARGET_CONTRACT_ERROR = "target_contract_id must reference an enabled route contract usable by standard sources"


def _clean_text(value: object) -> str:
    return str(value or "").strip()


def resolve_standard_source_target(
    *,
    target_contract_id: object = "",
    source_mode: object = "",
    quality_group: object = "",
    existing_source: StandardSource | None = None,
    display_name_map: Mapping[str, str],
    eligible_contract_ids: Collection[str],
    display_name_for_contract: Callable[[str], str] | None = None,
) -> tuple[str, str, str]:
    """Resolve one standard-source target for management and core patch paths.

    The caller supplies the contract view appropriate to its surface. This
    keeps scenario-specific display names and eligibility in the route layer,
    while making omission, explicit-invalid, and update semantics identical.
    """

    raw_target_contract_id = _clean_text(target_contract_id)
    raw_quality_group = _clean_text(quality_group)
    raw_source_mode = _clean_text(source_mode)
    if raw_source_mode and raw_source_mode not in STANDARD_SOURCE_MODES:
        raise ValueError(f"source_mode must be one of: {', '.join(STANDARD_SOURCE_MODES)}")

    if raw_source_mode:
        resolved_mode = raw_source_mode
    elif raw_quality_group == QUALITY_HIGH_AIRPORT:
        resolved_mode = STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT
    elif not raw_quality_group and existing_source is not None:
        resolved_mode = existing_source.resolved_source_mode()
    else:
        resolved_mode = STANDARD_SOURCE_MODE_ROUTE_CONTRACT

    if resolved_mode == STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT:
        if raw_target_contract_id:
            raise ValueError(_TARGET_CONTRACT_ERROR)
        if raw_quality_group and raw_quality_group != QUALITY_HIGH_AIRPORT:
            raise ValueError(_TARGET_CONTRACT_ERROR)
        return "", STANDARD_SOURCE_MODE_HIGH_QUALITY_AIRPORT, QUALITY_HIGH_AIRPORT

    resolved_contract_id = ""
    if raw_target_contract_id:
        resolved_contract_id = resolve_contract_id(
            raw_target_contract_id,
            display_name_map=display_name_map,
        )
        if not resolved_contract_id:
            raise ValueError(_TARGET_CONTRACT_ERROR)
    elif raw_quality_group:
        resolved_contract_id = resolve_contract_id(
            raw_quality_group,
            display_name_map=display_name_map,
        )
        if not resolved_contract_id:
            raise ValueError(_TARGET_CONTRACT_ERROR)
    elif existing_source is not None:
        resolved_contract_id = existing_source.resolved_target_contract_id()

    if not resolved_contract_id:
        raise ValueError(_TARGET_CONTRACT_ERROR)

    eligible_ids = {str(item or "").strip() for item in eligible_contract_ids}
    if resolved_contract_id not in eligible_ids and not (
        existing_source is not None
        and resolved_contract_id == existing_source.resolved_target_contract_id()
    ):
        raise ValueError(_TARGET_CONTRACT_ERROR)

    if display_name_for_contract is not None:
        display_name = _clean_text(display_name_for_contract(resolved_contract_id))
    else:
        display_name = _clean_text(display_name_map.get(resolved_contract_id))
    return (
        resolved_contract_id,
        STANDARD_SOURCE_MODE_ROUTE_CONTRACT,
        display_name or contract_display_name(resolved_contract_id),
    )
