from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def _read_optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _parse_bool(name: str, default: bool) -> bool:
    raw = _read_optional_env(name)
    if raw is None:
        return default
    normalized = raw.lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    allowed = ", ".join(sorted(_TRUE_VALUES | _FALSE_VALUES))
    raise ValueError(f"Invalid {name}: expected one of {allowed}")


def _parse_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = _read_optional_env(name)
    if raw is None:
        return default
    try:
        value = int(raw, 10)
    except ValueError as exc:
        raise ValueError(f"Invalid {name}: expected an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"Invalid {name}: expected a value from {minimum} to {maximum}")
    return value


def _resolve_storage_root(raw: str) -> str:
    """Resolve relative storage paths against the repository, not process cwd."""
    path = Path(raw or "./var").expanduser()
    if path.is_absolute():
        return str(path)
    repo_root = Path(__file__).resolve().parent.parent
    return str((repo_root / path).resolve())


@dataclass
class Settings:
    app_name: str
    app_base_url: str
    storage_root: str
    refresh_interval_minutes: int
    request_timeout_seconds: int
    verify_tls: bool
    github_api_base: str
    github_raw_base: str
    rule_catalog_refresh_hours: int
    manage_api_require_login: bool
    max_snapshots_per_account: int
    account_crawl_parallelism: int
    app_version: str = "1.0.0"
    policy_backup_enabled: bool = False
    policy_backup_repo_url: str = ""
    policy_backup_branch: str = "main"
    policy_backup_github_token: str = ""
    policy_backup_author_name: str = ""
    policy_backup_author_email: str = ""
    policy_backup_subdir: str = ""
    policy_backup_debounce_seconds: int = 5
    url_signing_secret: str = ""
    gemini_api_key: str = ""
    review_model: str = "gemini-2.0-flash"
    # Keep newly introduced settings after the original positional fields so
    # callers that construct Settings positionally retain their old meaning.
    runtime_heartbeat_interval_seconds: int = 30
    runtime_heartbeat_stale_seconds: int = 90
    runtime_alert_webhook_url: str = ""
    runtime_alert_timeout_seconds: int = 5

    def __post_init__(self) -> None:
        if self.runtime_heartbeat_stale_seconds <= self.runtime_heartbeat_interval_seconds:
            raise ValueError(
                "RUNTIME_HEARTBEAT_STALE_SECONDS must be greater than "
                "RUNTIME_HEARTBEAT_INTERVAL_SECONDS"
            )
    legacy_data_owner_id: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        policy_backup_enabled = _parse_bool("POLICY_BACKUP_ENABLED", False)
        policy_backup_repo_url = _read_optional_env("POLICY_BACKUP_REPO_URL") or ""
        policy_backup_token = _read_optional_env("POLICY_BACKUP_GITHUB_TOKEN") or ""
        policy_backup_branch = _read_optional_env("POLICY_BACKUP_BRANCH") or "main"
        policy_backup_author_name = _read_optional_env("POLICY_BACKUP_AUTHOR_NAME") or ""
        policy_backup_author_email = _read_optional_env("POLICY_BACKUP_AUTHOR_EMAIL") or ""
        runtime_alert_webhook_url = _read_optional_env("RUNTIME_ALERT_WEBHOOK_URL") or ""
        if runtime_alert_webhook_url:
            try:
                parsed_alert_url = urlsplit(runtime_alert_webhook_url)
                alert_hostname = parsed_alert_url.hostname
            except ValueError as exc:
                raise ValueError("RUNTIME_ALERT_WEBHOOK_URL must be a valid HTTPS URL") from exc
            if (
                parsed_alert_url.scheme.lower() != "https"
                or not parsed_alert_url.netloc
                or not alert_hostname
                or parsed_alert_url.username
                or parsed_alert_url.password
            ):
                raise ValueError(
                    "RUNTIME_ALERT_WEBHOOK_URL must be HTTPS without embedded credentials"
                )
        if policy_backup_enabled:
            if not policy_backup_repo_url:
                raise ValueError("POLICY_BACKUP_ENABLED=true requires POLICY_BACKUP_REPO_URL")
            if policy_backup_repo_url.startswith(("http://", "https://")) and not policy_backup_token:
                raise ValueError(
                    "POLICY_BACKUP_ENABLED=true with an HTTPS repository requires "
                    "POLICY_BACKUP_GITHUB_TOKEN"
                )
            if not policy_backup_author_name or not policy_backup_author_email:
                raise ValueError(
                    "POLICY_BACKUP_ENABLED=true requires POLICY_BACKUP_AUTHOR_NAME and "
                    "POLICY_BACKUP_AUTHOR_EMAIL"
                )

        runtime_heartbeat_interval_seconds = _parse_int(
            "RUNTIME_HEARTBEAT_INTERVAL_SECONDS", 30, minimum=5, maximum=3600
        )
        runtime_heartbeat_stale_seconds = _parse_int(
            "RUNTIME_HEARTBEAT_STALE_SECONDS", 90, minimum=10, maximum=86400
        )
        if runtime_heartbeat_stale_seconds <= runtime_heartbeat_interval_seconds:
            raise ValueError(
                "RUNTIME_HEARTBEAT_STALE_SECONDS must be greater than "
                "RUNTIME_HEARTBEAT_INTERVAL_SECONDS"
            )

        return cls(
            app_name=_read_optional_env("APP_NAME") or "SubHub",
            app_version=_read_optional_env("APP_VERSION") or "1.0.0",
            app_base_url=(_read_optional_env("APP_BASE_URL") or "").rstrip("/"),
            storage_root=_resolve_storage_root(_read_optional_env("STORAGE_ROOT") or "./var"),
            refresh_interval_minutes=_parse_int(
                "REFRESH_INTERVAL_MINUTES", 30, minimum=1, maximum=1440
            ),
            request_timeout_seconds=_parse_int(
                "REQUEST_TIMEOUT_SECONDS", 20, minimum=1, maximum=300
            ),
            verify_tls=_parse_bool("VERIFY_TLS", True),
            github_api_base=(
                _read_optional_env("GITHUB_API_BASE")
                or "https://api.github.com/repos/blackmatrix7/ios_rule_script"
            ).rstrip("/"),
            github_raw_base=(
                _read_optional_env("GITHUB_RAW_BASE")
                or "https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master"
            ).rstrip("/"),
            rule_catalog_refresh_hours=_parse_int(
                "RULE_CATALOG_REFRESH_HOURS", 24, minimum=1, maximum=8760
            ),
            manage_api_require_login=_parse_bool("MANAGE_API_REQUIRE_LOGIN", False),
            max_snapshots_per_account=_parse_int(
                "MAX_SNAPSHOTS_PER_ACCOUNT", 20, minimum=1, maximum=1000
            ),
            account_crawl_parallelism=_parse_int(
                "ACCOUNT_CRAWL_PARALLELISM", 2, minimum=1, maximum=64
            ),
            policy_backup_enabled=policy_backup_enabled,
            policy_backup_repo_url=policy_backup_repo_url,
            policy_backup_branch=policy_backup_branch,
            policy_backup_github_token=policy_backup_token,
            policy_backup_author_name=policy_backup_author_name,
            policy_backup_author_email=policy_backup_author_email,
            policy_backup_subdir=(_read_optional_env("POLICY_BACKUP_SUBDIR") or "").strip("/"),
            policy_backup_debounce_seconds=_parse_int(
                "POLICY_BACKUP_DEBOUNCE_SECONDS", 5, minimum=1, maximum=86400
            ),
            runtime_heartbeat_interval_seconds=runtime_heartbeat_interval_seconds,
            runtime_heartbeat_stale_seconds=runtime_heartbeat_stale_seconds,
            runtime_alert_webhook_url=runtime_alert_webhook_url,
            runtime_alert_timeout_seconds=_parse_int(
                "RUNTIME_ALERT_TIMEOUT_SECONDS", 5, minimum=1, maximum=60
            ),
            url_signing_secret=_read_optional_env("URL_SIGNING_SECRET") or "",
            gemini_api_key=_read_optional_env("GEMINI_API_KEY") or "",
            review_model=_read_optional_env("REVIEW_MODEL") or "gemini-2.0-flash",
            legacy_data_owner_id=_read_optional_env("LEGACY_DATA_OWNER_ID") or "",
        )

    @property
    def field_cipher_key_path(self) -> Path:
        return Path(self.storage_root) / "data" / "field_cipher.key"
