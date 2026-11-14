from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def assert_distribution_manifest_has_no_backup_credential(manifest: str) -> None:
    parsed = yaml.safe_load(manifest)
    token_bindings = [
        entry.split("=", 1)[1]
        for service in parsed["services"].values()
        for entry in service.get("environment", [])
        if entry.startswith("POLICY_BACKUP_GITHUB_TOKEN=")
    ]
    assert token_bindings == ['{{ default "" .U.policy_backup_github_token }}']
    assert "POLICY_BACKUP_ENABLED=false" in parsed["services"]["web"]["environment"]
    assert not re.search(r"(?:github_pat_|gh[pousr]_)", manifest)


def test_distribution_manifest_does_not_embed_backup_credential() -> None:
    manifest = (REPO_ROOT / "lzc-manifest.yml").read_text(encoding="utf-8")
    assert_distribution_manifest_has_no_backup_credential(manifest)


@pytest.mark.parametrize(
    "unsafe_binding",
    [
        "synthetic-private-token",
        '{{ default "synthetic-private-token" .U.policy_backup_github_token }}',
        '{{ default "" .U.other_secret }}',
        '{{ default "" .U.policy_backup_github_token }}suffix',
    ],
)
def test_distribution_manifest_rejects_embedded_or_unapproved_backup_credential(
    unsafe_binding: str,
) -> None:
    parsed = yaml.safe_load((REPO_ROOT / "lzc-manifest.yml").read_text(encoding="utf-8"))
    environment = parsed["services"]["web"]["environment"]
    environment[:] = [
        "POLICY_BACKUP_GITHUB_TOKEN=" + unsafe_binding
        if entry.startswith("POLICY_BACKUP_GITHUB_TOKEN=") else entry
        for entry in environment
    ]
    with pytest.raises(AssertionError):
        assert_distribution_manifest_has_no_backup_credential(yaml.safe_dump(parsed))


def test_distribution_manifest_rejects_duplicate_backup_credential_binding() -> None:
    parsed = yaml.safe_load((REPO_ROOT / "lzc-manifest.yml").read_text(encoding="utf-8"))
    parsed["services"]["web"]["environment"].append(
        'POLICY_BACKUP_GITHUB_TOKEN={{ default "" .U.policy_backup_github_token }}',
    )
    with pytest.raises(AssertionError):
        assert_distribution_manifest_has_no_backup_credential(yaml.safe_dump(parsed))
