from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from app.config import Settings
from app.services.subscription_ids import sign_subscription_asset

_ASSET_SIGNATURE_TTL = timedelta(days=365)


def build_signed_subscription_asset_url(
    settings: Settings,
    *,
    base_url: str,
    public_id: str,
    scenario_slug: str,
    kind: str,
    asset_key: str,
    revision: str,
) -> str:
    normalized_base = str(base_url or "").strip().rstrip("/")
    normalized_public_id = str(public_id or "").strip()
    normalized_scenario_slug = str(scenario_slug or "").strip() or "default"
    normalized_kind = str(kind or "").strip()
    normalized_asset_key = str(asset_key or "").strip()
    normalized_revision = str(revision or "").strip()
    expires_at = int((datetime.now(timezone.utc) + _ASSET_SIGNATURE_TTL).timestamp())

    if normalized_kind == "clash-provider":
        path = f"/sub/device/{normalized_public_id}/{normalized_scenario_slug}/clash/providers/{normalized_asset_key}.yaml"
    elif normalized_kind == "clash-rule-provider":
        path = f"/sub/device/{normalized_public_id}/{normalized_scenario_slug}/clash/rules/{normalized_asset_key}.list"
    elif normalized_kind == "domain-set":
        path = f"/sub/device/{normalized_public_id}/{normalized_scenario_slug}/surge/domain-set/{normalized_asset_key}.txt"
    elif normalized_kind == "rule-set":
        path = f"/sub/device/{normalized_public_id}/{normalized_scenario_slug}/surge/rule-set/{normalized_asset_key}.list"
    else:
        raise ValueError(f"unsupported subscription asset kind: {normalized_kind}")

    signature = sign_subscription_asset(
        settings,
        public_id=normalized_public_id,
        scenario_slug=normalized_scenario_slug,
        kind=normalized_kind,
        asset_key=normalized_asset_key,
        revision=normalized_revision,
        expires_at=expires_at,
    )
    query = urlencode(
        {
            "rev": normalized_revision,
            "exp": str(expires_at),
            "sig": signature,
        }
    )
    return f"{normalized_base}{path}?{query}"
