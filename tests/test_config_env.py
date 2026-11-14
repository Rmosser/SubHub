from __future__ import annotations

from pathlib import Path
import hashlib
import os
import shutil
import subprocess

import pytest
import yaml

from app.config import Settings


CONFIG_ENV_KEYS = {
    "APP_NAME",
    "APP_VERSION",
    "APP_BASE_URL",
    "STORAGE_ROOT",
    "REFRESH_INTERVAL_MINUTES",
    "REQUEST_TIMEOUT_SECONDS",
    "VERIFY_TLS",
    "GITHUB_API_BASE",
    "GITHUB_RAW_BASE",
    "RULE_CATALOG_REFRESH_HOURS",
    "MANAGE_API_REQUIRE_LOGIN",
    "MAX_SNAPSHOTS_PER_ACCOUNT",
    "ACCOUNT_CRAWL_PARALLELISM",
    "POLICY_BACKUP_ENABLED",
    "POLICY_BACKUP_REPO_URL",
    "POLICY_BACKUP_BRANCH",
    "POLICY_BACKUP_GITHUB_TOKEN",
    "POLICY_BACKUP_AUTHOR_NAME",
    "POLICY_BACKUP_AUTHOR_EMAIL",
    "POLICY_BACKUP_SUBDIR",
    "POLICY_BACKUP_DEBOUNCE_SECONDS",
    "RUNTIME_HEARTBEAT_INTERVAL_SECONDS",
    "RUNTIME_HEARTBEAT_STALE_SECONDS",
    "RUNTIME_ALERT_WEBHOOK_URL",
    "RUNTIME_ALERT_TIMEOUT_SECONDS",
    "URL_SIGNING_SECRET",
    "GEMINI_API_KEY",
    "REVIEW_MODEL",
    "LEGACY_DATA_OWNER_ID",
}


@pytest.fixture(autouse=True)
def clear_config_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_env_example_matches_settings_contract() -> None:
    root = Path(__file__).parents[1]
    declared = {
        line.split("=", 1)[0].strip()
        for line in (root / ".env.example").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    assert declared == CONFIG_ENV_KEYS


def test_defaults_are_safe_and_manifest_uses_deployment_secret() -> None:
    settings = Settings.from_env()
    assert settings.verify_tls is True
    assert settings.manage_api_require_login is False
    assert settings.policy_backup_enabled is False
    assert settings.account_crawl_parallelism == 2

    root = Path(__file__).parents[1]
    manifest = (root / "lzc-manifest.yml").read_text(encoding="utf-8")
    template = (root / "lzc-manifest.template.yml").read_text(encoding="utf-8")
    deploy_params = (root / "lzc-deploy-params.yml").read_text(encoding="utf-8")
    assert "github_pat_" not in manifest
    assert "github_pat_" not in template
    assert 'POLICY_BACKUP_GITHUB_TOKEN={{ default "" .U.policy_backup_github_token }}' in manifest
    assert 'POLICY_BACKUP_GITHUB_TOKEN=' not in template
    assert "type: secret" in deploy_params


def test_storage_root_binds_relative_values_to_repository_and_preserves_absolute_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = Path(__file__).parents[1]
    monkeypatch.setenv("STORAGE_ROOT", "./var")
    assert Path(Settings.from_env().storage_root) == (root / "var").resolve()

    absolute = tmp_path / "absolute-storage"
    monkeypatch.setenv("STORAGE_ROOT", str(absolute))
    assert Settings.from_env().storage_root == str(absolute)


def test_deployment_parameters_are_optional_and_mapped_without_instance_values() -> None:
    root = Path(__file__).parents[1]
    manifest = yaml.safe_load((root / "lzc-manifest.yml").read_text(encoding="utf-8"))
    params = yaml.safe_load((root / "lzc-deploy-params.yml").read_text(encoding="utf-8"))
    declared = {param["id"]: param for param in params["params"]}
    environment = dict(entry.split("=", 1) for entry in manifest["services"]["web"]["environment"])
    bindings = {
        "LEGACY_DATA_OWNER_ID": ("legacy_data_owner_id", "lzc_uid"),
        "POLICY_BACKUP_GITHUB_TOKEN": ("policy_backup_github_token", "secret"),
    }
    for variable, (param_id, param_type) in bindings.items():
        param = declared[param_id]
        assert param["type"] == param_type
        assert param["optional"] is True
        assert param["default_value"] == ""
        # Parameter declarations alone do not inject service environment values.
        # Every binding must use the platform render context with an empty default.
        assert environment[variable] == '{{ default "" .U.' + param_id + " }}"
    assert environment["POLICY_BACKUP_ENABLED"] == "false"
    assert "SUB_TOKEN" not in environment
    assert "DATA_ENCRYPTION_KEY" not in environment


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("VERIFY_TLS", "true", True),
        ("VERIFY_TLS", "ON", True),
        ("MANAGE_API_REQUIRE_LOGIN", "0", False),
        ("POLICY_BACKUP_ENABLED", "no", False),
    ],
)
def test_boolean_environment_values_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
    expected: bool,
) -> None:
    monkeypatch.setenv(name, value)
    settings = Settings.from_env()
    assert getattr(settings, {
        "VERIFY_TLS": "verify_tls",
        "MANAGE_API_REQUIRE_LOGIN": "manage_api_require_login",
        "POLICY_BACKUP_ENABLED": "policy_backup_enabled",
    }[name]) is expected


@pytest.mark.parametrize("name", ["VERIFY_TLS", "MANAGE_API_REQUIRE_LOGIN", "POLICY_BACKUP_ENABLED"])
def test_invalid_boolean_fails_fast(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setenv(name, "treu")
    with pytest.raises(ValueError, match=name):
        Settings.from_env()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("REFRESH_INTERVAL_MINUTES", "0"),
        ("REQUEST_TIMEOUT_SECONDS", "not-a-number"),
        ("RULE_CATALOG_REFRESH_HOURS", "8761"),
        ("ACCOUNT_CRAWL_PARALLELISM", "65"),
    ],
)
def test_invalid_integer_fails_fast(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        Settings.from_env()


def test_enabled_https_backup_requires_runtime_token_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLICY_BACKUP_ENABLED", "true")
    monkeypatch.setenv("POLICY_BACKUP_REPO_URL", "https://github.com/example/policy.git")
    with pytest.raises(ValueError, match="POLICY_BACKUP_GITHUB_TOKEN"):
        Settings.from_env()

    monkeypatch.setenv("POLICY_BACKUP_GITHUB_TOKEN", "synthetic-test-token")
    monkeypatch.setenv("POLICY_BACKUP_AUTHOR_NAME", "Policy Bot")
    monkeypatch.setenv("POLICY_BACKUP_AUTHOR_EMAIL", "policy@example.test")
    settings = Settings.from_env()
    assert settings.policy_backup_enabled is True


@pytest.mark.parametrize("url", ["http://alerts.example.test/hook", "ftp://alerts.example.test/hook", "not-a-url"])
def test_runtime_alert_webhook_requires_https(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("RUNTIME_ALERT_WEBHOOK_URL", url)
    with pytest.raises(ValueError, match="RUNTIME_ALERT_WEBHOOK_URL"):
        Settings.from_env()


def test_runtime_heartbeat_stale_threshold_must_exceed_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUNTIME_HEARTBEAT_INTERVAL_SECONDS", "3600")
    monkeypatch.setenv("RUNTIME_HEARTBEAT_STALE_SECONDS", "10")
    with pytest.raises(ValueError, match="RUNTIME_HEARTBEAT_STALE_SECONDS"):
        Settings.from_env()

    monkeypatch.setenv("RUNTIME_HEARTBEAT_INTERVAL_SECONDS", "30")
    monkeypatch.setenv("RUNTIME_HEARTBEAT_STALE_SECONDS", "90")
    settings = Settings.from_env()
    assert settings.runtime_heartbeat_stale_seconds > settings.runtime_heartbeat_interval_seconds

    with pytest.raises(ValueError, match="RUNTIME_HEARTBEAT_STALE_SECONDS"):
        Settings(
            app_name="SubHub",
            app_base_url="",
            storage_root="./var",
            refresh_interval_minutes=30,
            request_timeout_seconds=5,
            verify_tls=True,
            github_api_base="https://example.test/api",
            github_raw_base="https://example.test/raw",
            rule_catalog_refresh_hours=24,
            manage_api_require_login=False,
            max_snapshots_per_account=20,
            account_crawl_parallelism=2,
            runtime_heartbeat_interval_seconds=3600,
            runtime_heartbeat_stale_seconds=10,
        )

NOT_RUNNING = 'Error: Service "web" is not running. Run "lzc-cli project start" first.'
REFUSED = "urllib.error.URLError: <urlopen error [Errno 111] Connection refused>"


def _run_deploy(
    tmp_path: Path,
    *,
    digest_matches: bool = True,
    exec_failures: int = 0,
    health_failures: int = 0,
    fail_command: str = "",
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the deploy script against a fake lzc-cli. The first `exec_failures` `project exec` calls fail the
    way lzc-cli does while the release container is still being recreated after `app install`; after that,
    the first `health_failures` health readbacks fail the way they do while the app is not listening yet."""
    root = Path(__file__).parents[1]
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(root / "scripts" / "deploy_to_lazycat.sh", scripts)
    (tmp_path / "lzc-manifest.yml").write_text("package: cloud.lazycat.subhub\nversion: 1.0.9\n")
    (tmp_path / "lzc-build.yml").write_text("contentdir: ./dist\n")
    content = tmp_path / "dist"
    content.mkdir()
    (content / "runtime.txt").write_text("packaged-runtime\n")
    file_hash = hashlib.sha256((content / "runtime.txt").read_bytes()).hexdigest()
    digest = hashlib.sha256(f"{file_hash}  ./runtime.txt\n".encode()).hexdigest()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_lzc = fake_bin / "lzc-cli"
    fake_lzc.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\nfrom pathlib import Path\n"
        "args = sys.argv[1:]\nbox = Path('current-box')\n"
        "fail = os.environ.get('SUBHUB_TEST_FAIL_COMMAND')\n"
        "if fail and ' '.join(args).startswith(fail):\n"
        " print('Error: simulated failure', file=sys.stderr); raise SystemExit(1)\n"
        "if args == ['project', 'build']:\n"
        " Path('.pkgout').mkdir(exist_ok=True); Path('.pkgout/app.lpk').write_text('build')\n"
        "elif args == ['box', 'default']:\n print(box.read_text().strip())\n"
        "elif args[:2] == ['box', 'switch']:\n box.write_text(args[2])\n"
        "elif args[:2] == ['app', 'install']:\n print('installed')\n"
        "elif args[:2] == ['app', 'status']:\n print('installed running')\n"
        "elif args[:2] == ['project', 'info']:\n print('cloud.lazycat.subhub 1.0.9 Deployed version: 1.0.9')\n"
        "elif args[:2] == ['project', 'exec']:\n"
        " left = Path('exec-failures'); n = int(left.read_text())\n"
        " if n > 0:\n"
        "  left.write_text(str(n - 1))\n"
        "  print('Build config: lzc-build.yml')\n"
        f"  print({NOT_RUNNING!r}, file=sys.stderr); print('Use lzc-cli help to see more help', file=sys.stderr)\n"
        "  raise SystemExit(1)\n"
        " left = Path('health-failures'); n = int(left.read_text())\n"
        " if 'healthz' in args[-1] and n > 0:\n"
        "  left.write_text(str(n - 1))\n"
        "  print('Traceback (most recent call last):', file=sys.stderr)\n"
        f"  print({REFUSED!r}, file=sys.stderr); print('Error: exit status 1', file=sys.stderr)\n"
        "  raise SystemExit(1)\n"
        " print(os.environ['SUBHUB_TEST_REMOTE_DIGEST'] if 'find .' in args[-1] else 'health ok')\n"
        "else:\n raise SystemExit('unexpected lzc arguments: ' + repr(args))\n",
        encoding="utf-8",
    )
    fake_lzc.chmod(0o755)
    (tmp_path / "current-box").write_text("original-box")
    (tmp_path / "exec-failures").write_text(str(exec_failures))
    (tmp_path / "health-failures").write_text(str(health_failures))
    env = {
        **os.environ,
        "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
        "SUBHUB_TEST_REMOTE_DIGEST": digest if digest_matches else "0" * 64,
        "SUBHUB_TEST_FAIL_COMMAND": fail_command,
        "DEPLOY_READBACK_TIMEOUT_SECONDS": "0",
        "DEPLOY_READBACK_INTERVAL_SECONDS": "0",
        **(env_extra or {}),
    }
    return subprocess.run(
        ["bash", str(scripts / "deploy_to_lazycat.sh"), "--deploy", "--box", "devbox", "--confirm"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


VERIFIED = "verified cloud.lazycat.subhub 1.0.9 on devbox"


@pytest.mark.parametrize("digest_matches", [True, False])
def test_deployment_reads_configured_content_directory_and_restores_box(tmp_path, digest_matches) -> None:
    result = _run_deploy(tmp_path, digest_matches=digest_matches)
    assert (tmp_path / "current-box").read_text() == "original-box"
    assert (tmp_path / ".pkgout" / "app.lpk").exists()
    if digest_matches:
        assert result.returncode == 0, result.stdout + result.stderr
        assert VERIFIED in result.stdout
    else:
        assert result.returncode != 0
        assert "installed content digest does not match" in result.stderr
        assert VERIFIED not in result.stdout


def test_deployment_waits_for_the_release_container_after_install(tmp_path) -> None:
    result = _run_deploy(
        tmp_path, exec_failures=2, health_failures=1, env_extra={"DEPLOY_READBACK_TIMEOUT_SECONDS": "30"}
    )
    assert result.returncode == 0, result.stdout + result.stderr
    waits = [line for line in result.stdout.splitlines() if "waiting for the release container" in line]
    assert len(waits) == 3
    assert waits[0].endswith(f"could not read the installed content digest ({NOT_RUNNING})")
    assert waits[1].endswith(f"could not read the installed content digest ({NOT_RUNNING})")
    assert waits[2].endswith(f"in-container health readback failed ({REFUSED})")
    assert result.stdout.rstrip().splitlines()[-1].endswith(
        "old build artifacts retained; pass --cleanup-old --confirm-cleanup after a verified deploy to remove them."
    )
    assert VERIFIED in result.stdout
    assert (tmp_path / "current-box").read_text() == "original-box"


def test_deployment_names_the_reason_when_the_release_container_never_comes_up(tmp_path) -> None:
    result = _run_deploy(tmp_path, exec_failures=1000)
    assert result.returncode == 1
    assert f"could not read the installed content digest ({NOT_RUNNING}); gave up after 0s" in result.stderr
    assert VERIFIED not in result.stdout
    assert (tmp_path / "current-box").read_text() == "original-box"


@pytest.mark.parametrize("command", ["app install", "app status", "project info"])
def test_deployment_reports_a_failing_lzc_command_instead_of_exiting_silently(tmp_path, command) -> None:
    result = _run_deploy(tmp_path, fail_command=command)
    assert result.returncode != 0
    assert "[deploy_to_lazycat] ERROR:" in result.stderr
    if command == "app install":
        assert "command failed at line" in result.stderr and "lzc-cli app install" in result.stderr
    else:
        assert "readback failed: Error: simulated failure" in result.stderr
    assert VERIFIED not in result.stdout
    assert (tmp_path / "current-box").read_text() == "original-box"


def test_deployment_rejects_a_readback_wait_that_is_not_whole_seconds(tmp_path) -> None:
    result = _run_deploy(tmp_path, env_extra={"DEPLOY_READBACK_TIMEOUT_SECONDS": "3m"})
    assert result.returncode == 2
    assert "must be whole seconds" in result.stderr
    assert not (tmp_path / ".pkgout").exists()
    assert (tmp_path / "current-box").read_text() == "original-box"
