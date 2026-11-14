from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from app.config import Settings


def generate_public_subscription_id() -> str:
    return secrets.token_urlsafe(18)


def signing_secret(settings: Settings) -> bytes:
    raw = str(settings.url_signing_secret or "").strip()
    if raw:
        return raw.encode("utf-8")
    fallback = f"{settings.app_name}|{settings.storage_root}|subhub-url-signing"
    return hashlib.sha256(fallback.encode("utf-8")).digest()


def _asset_signature_payload(
    *,
    public_id: str,
    scenario_slug: str,
    kind: str,
    asset_key: str,
    revision: str,
    expires_at: int,
    include_revision: bool,
) -> str:
    parts = [
        str(public_id or "").strip(),
        str(scenario_slug or "").strip(),
        str(kind or "").strip(),
        str(asset_key or "").strip(),
    ]
    if include_revision:
        parts.append(str(revision or "").strip())
    parts.append(str(int(expires_at)))
    return ":".join(parts)


def _sign_subscription_asset(
    settings: Settings,
    *,
    public_id: str,
    scenario_slug: str,
    kind: str,
    asset_key: str,
    revision: str,
    expires_at: int,
    include_revision: bool,
) -> str:
    payload = _asset_signature_payload(
        public_id=public_id,
        scenario_slug=scenario_slug,
        kind=kind,
        asset_key=asset_key,
        revision=revision,
        expires_at=expires_at,
        include_revision=include_revision,
    )
    digest = hmac.new(signing_secret(settings), payload.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def sign_subscription_asset(
    settings: Settings,
    *,
    public_id: str,
    scenario_slug: str,
    kind: str,
    asset_key: str,
    revision: str,
    expires_at: int,
) -> str:
    # Keep the signature stable across revision churn so clients that cache
    # external resource URLs do not start hitting 403s before the managed
    # profile itself has refreshed to the new rev query parameter.
    return _sign_subscription_asset(
        settings,
        public_id=public_id,
        scenario_slug=scenario_slug,
        kind=kind,
        asset_key=asset_key,
        revision=revision,
        expires_at=expires_at,
        include_revision=False,
    )


def verify_subscription_asset_signature(
    settings: Settings,
    *,
    public_id: str,
    scenario_slug: str,
    kind: str,
    asset_key: str,
    revision: str,
    expires_at: int,
    signature: str,
) -> bool:
    normalized_signature = str(signature or "").strip()
    if not normalized_signature:
        return False
    candidates = (
        _sign_subscription_asset(
            settings,
            public_id=public_id,
            scenario_slug=scenario_slug,
            kind=kind,
            asset_key=asset_key,
            revision=revision,
            expires_at=expires_at,
            include_revision=False,
        ),
        _sign_subscription_asset(
            settings,
            public_id=public_id,
            scenario_slug=scenario_slug,
            kind=kind,
            asset_key=asset_key,
            revision=revision,
            expires_at=expires_at,
            include_revision=True,
        ),
    )
    return any(hmac.compare_digest(expected, normalized_signature) for expected in candidates)
