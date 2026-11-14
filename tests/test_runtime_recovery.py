from __future__ import annotations

import asyncio
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.request import Request

import pytest

from app.config import Settings
from app.models import CustomRule
from app.routes.internal import _ready_payload
from app.services.policy_backup_service import (
    PolicyBackupService,
    _GitRemoteState,
    _GitSyncResult,
)
from app.services.hub_service import HubService
from app.services.gorelay_service import GorelayService
from app.services.runtime_observability import (
    HttpsRuntimeAlertSink,
    RuntimeAlertDeliveryError,
    RuntimeAlertDeliveryUnknown,
    RuntimeAlertService,
    RuntimeTaskMonitor,
    _HttpsOnlyRedirectHandler,
)
from app.storage.sqlite_repo import SqliteRepo


def _settings(root: Path, *, policy_backup_enabled: bool = False) -> Settings:
    return Settings(
        app_name="SubHub",
        app_base_url="",
        storage_root=str(root),
        refresh_interval_minutes=30,
        request_timeout_seconds=5,
        verify_tls=False,
        github_api_base="https://127.0.0.1/invalid",
        github_raw_base="https://127.0.0.1/invalid",
        rule_catalog_refresh_hours=24,
        manage_api_require_login=False,
        max_snapshots_per_account=20,
        account_crawl_parallelism=2,
        policy_backup_enabled=policy_backup_enabled,
        policy_backup_repo_url=str(root / "fake-policy.git"),
        policy_backup_branch="main",
        policy_backup_author_name="Fake Policy Bot",
        policy_backup_author_email="fake-policy@example.test",
        policy_backup_debounce_seconds=1,
        runtime_heartbeat_interval_seconds=5,
        runtime_heartbeat_stale_seconds=10,
    )


def test_policy_dirty_generation_survives_repo_restart(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state", policy_backup_enabled=True)
    repo = SqliteRepo(settings)
    service = PolicyBackupService(settings, repo)
    repo.set_policy_backup_notifier(service.mark_dirty)

    repo.create_manual_rule_category("restart-proof", "DIRECT")
    first = repo.get_policy_backup_state()
    assert first["dirty_generation"] == 1
    assert first["pending_count"] == 1
    assert repo.list_policy_backup_outbox()[0]["status"] == "pending"
    repo.close()

    restarted_repo = SqliteRepo(settings)
    restarted_service = PolicyBackupService(settings, restarted_repo)
    status = restarted_service.status().to_dict()
    assert status["dirty"] is True
    assert status["dirty_generation"] == 1
    assert status["outbox_pending_count"] == 1

    acked = restarted_repo.acknowledge_policy_backup_generation(
        1,
        sync_run_id="restart-reconcile",
        commit_sha="fake-commit",
        remote_digest="fake-digest",
    )
    assert acked["pending_count"] == 0
    assert restarted_repo.get_policy_backup_state()["acked_generation"] == 1
    restarted_repo.close()


def test_policy_sync_reconciles_ambiguous_push_without_second_push(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state", policy_backup_enabled=True)
    repo = SqliteRepo(settings)
    service = PolicyBackupService(settings, repo)
    repo.set_policy_backup_notifier(service.mark_dirty)
    repo.create_manual_rule_category("ambiguous-push", "DIRECT")

    expected_digest = str(service.export_snapshot()["manifest"]["digest"])

    class FakeGit:
        sync_calls = 0
        probe_calls = 0

        @staticmethod
        def current_source_repo():
            return ""

        def sync_files(self, *_args, **_kwargs):
            self.sync_calls += 1
            return _GitSyncResult(
                ok=False,
                changed=False,
                error="push connection lost after the request was sent",
                ambiguous=True,
            )

        def inspect_remote_manifest(self, **_kwargs):
            self.probe_calls += 1
            return _GitRemoteState(
                ok=True,
                commit_sha="remote-after-push",
                manifest_digest=expected_digest,
            )

    fake_git = FakeGit()
    service.backend = fake_git  # type: ignore[assignment]
    result = service._sync_now_blocking(force=False)

    assert result["ok"] is True
    assert result["reconciled"] is True
    assert fake_git.sync_calls == 1
    assert fake_git.probe_calls == 1
    status = service.status().to_dict()
    assert status["outbox_pending_count"] == 0
    assert status["reconciliation_required"] is False
    repo.close()


def test_policy_startup_compare_retries_when_remote_does_not_match(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state", policy_backup_enabled=True)
    repo = SqliteRepo(settings)
    service = PolicyBackupService(settings, repo)
    repo.set_policy_backup_notifier(service.mark_dirty)
    repo.create_manual_rule_category("startup-retry", "DIRECT")
    expected_digest = str(service.export_snapshot()["manifest"]["digest"])

    class FakeGit:
        sync_calls = 0
        probe_calls = 0

        @staticmethod
        def current_source_repo():
            return ""

        def inspect_remote_manifest(self, **_kwargs):
            self.probe_calls += 1
            return _GitRemoteState(
                ok=True,
                commit_sha="remote-reconciled",
                manifest_digest="old-generation" if self.probe_calls == 1 else expected_digest,
            )

        def sync_files(self, *_args, **_kwargs):
            self.sync_calls += 1
            return _GitSyncResult(
                ok=True,
                changed=True,
                commit_sha="new-generation",
                remote_digest=expected_digest,
            )

    fake_git = FakeGit()
    service.backend = fake_git  # type: ignore[assignment]

    async def run_startup_reconcile() -> None:
        result = await asyncio.to_thread(service._reconcile_on_startup)
        assert result["ok"] is True

    asyncio.run(run_startup_reconcile())
    assert fake_git.probe_calls == 1
    assert fake_git.sync_calls == 1
    assert service.status().to_dict()["outbox_pending_count"] == 0
    repo.close()


def test_policy_startup_compare_closes_missing_notifier_window(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state", policy_backup_enabled=True)
    repo = SqliteRepo(settings)
    service = PolicyBackupService(settings, repo)

    # Simulate policy commits that completed before the dirty callback ran,
    # first with no notifier and then with a notifier that fails.  The startup
    # compare must discover the mismatch and create an obligation before
    # retrying the external write.
    repo.create_manual_rule_category("notifier-window", "DIRECT")
    repo.set_policy_backup_notifier(lambda _reason: (_ for _ in ()).throw(RuntimeError("notifier down")))
    repo.create_manual_rule_category("failed-notifier-window", "DIRECT")
    assert repo.get_policy_backup_state()["pending_count"] == 0
    expected_digest = str(service.export_snapshot()["manifest"]["digest"])

    class FakeGit:
        sync_calls = 0

        @staticmethod
        def current_source_repo():
            return ""

        def inspect_remote_manifest(self, **_kwargs):
            return _GitRemoteState(ok=True, commit_sha="old", manifest_digest="old-generation")

        def sync_files(self, *_args, **_kwargs):
            self.sync_calls += 1
            return _GitSyncResult(
                ok=True,
                changed=True,
                commit_sha="startup-reconciled",
                remote_digest=expected_digest,
            )

    fake_git = FakeGit()
    service.backend = fake_git  # type: ignore[assignment]
    result = service._reconcile_on_startup()

    assert result["ok"] is True
    assert fake_git.sync_calls == 1
    state = repo.get_policy_backup_state()
    assert state["dirty_generation"] == 1
    assert state["acked_generation"] == 1
    assert state["pending_count"] == 0
    repo.close()


def test_policy_startup_probe_error_records_reconciliation_obligation(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state", policy_backup_enabled=True)
    repo = SqliteRepo(settings)
    service = PolicyBackupService(settings, repo)
    repo.create_manual_rule_category("probe-error", "DIRECT")
    expected_digest = str(service.export_snapshot()["manifest"]["digest"])

    class FakeGit:
        @staticmethod
        def current_source_repo():
            return ""

        @staticmethod
        def inspect_remote_manifest(**_kwargs):
            raise OSError("fixture probe unavailable")

        @staticmethod
        def sync_files(*_args, **_kwargs):
            return _GitSyncResult(
                ok=True,
                changed=True,
                commit_sha="probe-error-reconciled",
                remote_digest=expected_digest,
            )

    service.backend = FakeGit()  # type: ignore[assignment]
    result = service._reconcile_on_startup()

    assert result["ok"] is True
    state = repo.get_policy_backup_state()
    assert state["dirty_generation"] == 1
    assert state["acked_generation"] == 1
    assert state["pending_count"] == 0
    repo.close()


def test_failed_startup_push_is_retried_without_a_new_policy_event(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state", policy_backup_enabled=True)
    repo = SqliteRepo(settings)
    service = PolicyBackupService(settings, repo)
    repo.create_manual_rule_category("startup-worker-retry", "DIRECT")
    expected_digest = str(service.export_snapshot()["manifest"]["digest"])

    class FakeGit:
        sync_calls = 0

        @staticmethod
        def current_source_repo():
            return ""

        @staticmethod
        def inspect_remote_manifest(**_kwargs):
            return _GitRemoteState(ok=True, commit_sha="old", manifest_digest="old-generation")

        def sync_files(self, *_args, **_kwargs):
            self.sync_calls += 1
            if self.sync_calls == 1:
                return _GitSyncResult(
                    ok=False,
                    changed=False,
                    error="fixture startup push failed",
                )
            return _GitSyncResult(
                ok=True,
                changed=True,
                commit_sha="worker-retry-reconciled",
                remote_digest=expected_digest,
            )

    fake_git = FakeGit()
    service.backend = fake_git  # type: ignore[assignment]

    async def run() -> None:
        await service.ensure_started()
        assert service._startup_reconcile_task is not None
        await service._startup_reconcile_task
        # The first startup push failed.  The worker must observe the durable
        # outbox wake-up and retry after debounce without another mutation.
        await asyncio.sleep(1.25)
        await service.shutdown()

    asyncio.run(run())

    assert fake_git.sync_calls >= 2
    state = repo.get_policy_backup_state()
    assert state["pending_count"] == 0
    assert state["reconciliation_required"] is False
    repo.close()


def test_operator_sync_success_clears_old_policy_worker_failure(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state", policy_backup_enabled=True)
    repo = SqliteRepo(settings)
    alerts = RuntimeAlertService(repo, sink=lambda _payload: True)
    monitor = RuntimeTaskMonitor(repo, stale_after_seconds=10, alerts=alerts)
    service = PolicyBackupService(settings, repo, runtime_monitor=monitor, alerts=alerts)
    repo.set_policy_backup_notifier(service.mark_dirty)
    repo.create_manual_rule_category("operator-recovery", "DIRECT")
    monitor.register("policy_backup.worker", required=True, startup_success=True)
    monitor.failure("policy_backup.worker", "previous background sync failed")
    assert monitor.readiness(["policy_backup.worker"])["ok"] is False

    expected_digest = str(service.export_snapshot()["manifest"]["digest"])

    class FakeGit:
        @staticmethod
        def current_source_repo() -> str:
            return ""

        @staticmethod
        def sync_files(*_args: object, **_kwargs: object) -> _GitSyncResult:
            return _GitSyncResult(
                ok=True,
                changed=True,
                commit_sha="operator-recovery-commit",
                remote_digest=expected_digest,
            )

    service.backend = FakeGit()  # type: ignore[assignment]
    result = asyncio.run(service.sync_now(force=True))

    assert result["ok"] is True
    heartbeat = repo.get_runtime_heartbeat("policy_backup.worker")
    assert heartbeat is not None
    assert heartbeat["status"] == "running"
    assert heartbeat["consecutive_failures"] == 0
    assert monitor.readiness(["policy_backup.worker"])["ok"] is True
    repo.close()


def test_policy_backup_busy_is_retryable_and_worker_backs_off(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state", policy_backup_enabled=True)
    repo = SqliteRepo(settings)
    service = PolicyBackupService(settings, repo)
    repo.record_policy_backup_dirty("busy-drill")

    with service._state_lock:
        service._syncing = True
    try:
        busy = service._sync_now_blocking(force=False)
    finally:
        with service._state_lock:
            service._syncing = False
    assert busy["busy"] is True
    assert busy["ok"] is False
    assert busy["retryable"] is True

    calls: list[float] = []
    stop_after_call = asyncio.Event()

    async def fake_sync_now(*, force: bool = False) -> dict[str, object]:
        calls.append(time.monotonic())
        stop_after_call.set()
        return {"ok": False, "busy": True, "retryable": True}

    service.sync_now = fake_sync_now  # type: ignore[method-assign]

    async def run() -> None:
        service._event = asyncio.Event()
        service._event.set()
        service._startup_ready = asyncio.Event()
        service._startup_ready.set()
        service._shutdown = False
        worker = asyncio.create_task(service._worker())
        await asyncio.wait_for(stop_after_call.wait(), timeout=2)
        await asyncio.sleep(0.1)
        # A busy sync owner must yield for the debounce interval instead of
        # immediately re-entering the to_thread/SQLite path.
        assert len(calls) == 1
        service._shutdown = True
        await asyncio.wait_for(worker, timeout=2)

    asyncio.run(run())
    assert len(calls) == 1
    assert repo.get_policy_backup_state()["pending_count"] == 1
    repo.close()


def test_runtime_fatal_alert_receipt_is_durable_and_deduplicated(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    unconfigured = RuntimeAlertService(repo)
    assert unconfigured.readiness()["ok"] is False
    assert unconfigured.readiness()["reason"] == "RUNTIME_ALERT_WEBHOOK_URL is not configured"
    delivered: list[dict[str, object]] = []
    alerts = RuntimeAlertService(repo, sink=lambda payload: delivered.append(payload) or True)
    assert alerts.readiness()["ok"] is True
    monitor = RuntimeTaskMonitor(repo, stale_after_seconds=10, alerts=alerts)
    monitor.register("fake.worker", required=True)
    stale_at = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat().replace("+00:00", "Z")
    repo.upsert_runtime_heartbeat(
        "fake.worker",
        status="running",
        required=True,
        heartbeat_at=stale_at,
    )

    readiness = monitor.readiness(["fake.worker"])
    assert readiness["ok"] is False
    assert readiness["tasks"]["fake.worker"]["reason"] == "stale heartbeat"
    assert len(delivered) == 1
    receipt = repo.list_runtime_alert_receipts()[0]
    assert receipt["status"] == "sent"
    assert receipt["attempts"] == 1

    # Repeated probes reuse the stable alert key and do not spam the sink.
    monitor.readiness(["fake.worker"])
    assert len(delivered) == 1
    repo.close()

    restarted_repo = SqliteRepo(settings)
    assert restarted_repo.list_runtime_alert_receipts()[0]["status"] == "sent"
    restarted_repo.close()


def test_runtime_registration_preserves_old_failure_until_startup_success(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    alerts = RuntimeAlertService(repo, sink=lambda _payload: True)
    monitor = RuntimeTaskMonitor(repo, stale_after_seconds=10, alerts=alerts)

    monitor.register("fake.worker", required=True)
    monitor.failure("fake.worker", "previous worker failure")
    # A restart registers the new task but must not erase the durable failure
    # before the task has actually started.
    registered = monitor.register("fake.worker", required=True)
    assert registered["status"] == "starting"
    assert registered["consecutive_failures"] == 1
    assert monitor.readiness(["fake.worker"])["ok"] is False

    ready = monitor.startup_success("fake.worker")
    assert ready["status"] == "running"
    assert ready["consecutive_failures"] == 0
    assert ready["last_error"] == ""
    assert monitor.readiness(["fake.worker"])["ok"] is True

    # A failure recorded by the new process cannot be hidden by stale startup
    # bookkeeping, even if startup_success is called late.
    monitor.register("fake.worker", required=True)
    monitor.failure("fake.worker", "current worker failure")
    current = monitor.startup_success("fake.worker")
    assert current["status"] == "degraded"
    assert current["consecutive_failures"] == 1
    assert current["last_error"] == "current worker failure"
    repo.close()


def test_runtime_alert_episode_gets_new_id_after_success_recovery(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    delivered: list[dict[str, object]] = []
    alerts = RuntimeAlertService(repo, sink=lambda payload: delivered.append(payload) or True)
    monitor = RuntimeTaskMonitor(repo, stale_after_seconds=10, alerts=alerts)

    monitor.register("fake.worker", required=True)
    monitor.failure("fake.worker", "worker exploded", details={"attempt": 1})
    first = repo.list_runtime_alert_receipts()[0]
    monitor.success("fake.worker")
    monitor.failure("fake.worker", "worker exploded", details={"attempt": 2})
    receipts = repo.list_runtime_alert_receipts()

    assert len(delivered) == 2
    assert len(receipts) == 2
    assert {item["status"] for item in receipts} == {"sent"}
    assert first["alert_key"] != receipts[0]["alert_key"]
    assert {str(item["payload_json"]).count('failure_episode') for item in receipts} == {1}
    repo.close()


def test_https_runtime_alert_sink_is_https_only_and_idempotent() -> None:
    class FakeResponse:
        status = 202

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def getcode(self) -> int:
            return self.status

        def read(self, _limit: int) -> bytes:
            return b"accepted"

    class FakeOpener:
        def __init__(self) -> None:
            self.requests: list[object] = []
            self.timeouts: list[int] = []

        def open(self, request, *, timeout: int):  # type: ignore[no-untyped-def]
            self.requests.append(request)
            self.timeouts.append(timeout)
            return FakeResponse()

    with pytest.raises(ValueError, match="HTTPS"):
        HttpsRuntimeAlertSink("http://alerts.invalid/hook")

    opener = FakeOpener()
    sink = HttpsRuntimeAlertSink("https://alerts.invalid/hook", timeout_seconds=7, opener=opener)
    result = sink({"alert_key": "fatal:stable-key", "message": "worker failed"})

    assert result == {"delivered": True, "status_code": 202}
    assert opener.timeouts == [7]
    request = opener.requests[0]
    assert request.full_url == "https://alerts.invalid/hook"
    assert request.get_header("Idempotency-key") == "fatal:stable-key"
    assert request.get_header("X-subhub-alert-key") == "fatal:stable-key"


def test_unknown_alert_receipt_retries_after_restart(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    first_alerts = RuntimeAlertService(
        repo,
        sink=lambda _payload: (_ for _ in ()).throw(RuntimeAlertDeliveryUnknown("connection reset")),
    )
    receipt = first_alerts.emit_fatal("fake.worker", "worker failed")
    assert receipt["status"] == "unknown"
    assert repo.list_runtime_alert_receipts()[0]["status"] == "unknown"
    repo.close()

    restarted_repo = SqliteRepo(settings)
    delivered: list[dict[str, object]] = []
    restarted_alerts = RuntimeAlertService(
        restarted_repo,
        sink=lambda payload: delivered.append(payload) or True,
    )
    retried = restarted_alerts.retry_pending()

    assert len(retried) == 1
    assert retried[0]["status"] == "sent"
    assert len(delivered) == 1
    assert restarted_repo.list_runtime_alert_receipts()[0]["attempts"] == 2
    restarted_repo.close()


def test_non_async_failed_alert_retries_after_sink_recovers(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    healthy = False

    def recovering_sink(_payload: dict[str, object]) -> bool:
        return healthy

    alerts = RuntimeAlertService(repo, sink=recovering_sink)
    first = alerts.emit_fatal("fake.worker", "recoverable synchronous failure")
    assert first["status"] == "failed"
    assert alerts._active_delivery_keys == set()

    healthy = True
    retried = alerts.retry_pending()

    assert len(retried) == 1
    assert retried[0]["status"] == "sent"
    assert alerts._active_delivery_keys == set()
    assert repo.list_runtime_alert_receipts()[0]["attempts"] == 2
    repo.close()


def test_runtime_task_exit_emits_without_http_probe(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    delivered: list[dict[str, object]] = []
    alerts = RuntimeAlertService(repo, sink=lambda payload: delivered.append(payload) or True)
    monitor = RuntimeTaskMonitor(repo, stale_after_seconds=10, alerts=alerts)
    monitor.register("fake.worker", required=True)

    async def run() -> None:
        async def boom() -> None:
            raise RuntimeError("simulated task exit")

        task = asyncio.create_task(boom())
        monitor.watch("fake.worker", task)  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="simulated task exit"):
            await task
        for _ in range(50):
            receipts = repo.list_runtime_alert_receipts()
            if receipts and receipts[0]["status"] == "sent":
                break
            await asyncio.sleep(0.01)

    asyncio.run(run())

    heartbeat = repo.get_runtime_heartbeat("fake.worker")
    assert heartbeat is not None
    assert heartbeat["status"] == "degraded"
    assert heartbeat["last_error"] == "resident task fake.worker exited unexpectedly"
    assert len(delivered) == 1
    assert repo.list_runtime_alert_receipts()[0]["status"] == "sent"
    repo.close()


def test_runtime_task_unexpected_cancellation_emits_without_http_probe(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    delivered: list[dict[str, object]] = []
    alerts = RuntimeAlertService(repo, sink=lambda payload: delivered.append(payload) or True)
    monitor = RuntimeTaskMonitor(repo, stale_after_seconds=10, alerts=alerts)
    monitor.register("fake.worker", required=True)

    async def run() -> None:
        task = asyncio.create_task(asyncio.sleep(60))
        monitor.watch("fake.worker", task)  # type: ignore[arg-type]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        for _ in range(50):
            receipts = repo.list_runtime_alert_receipts()
            if receipts and receipts[0]["status"] == "sent":
                break
            await asyncio.sleep(0.01)

    asyncio.run(run())

    heartbeat = repo.get_runtime_heartbeat("fake.worker")
    assert heartbeat is not None
    assert heartbeat["status"] == "degraded"
    assert heartbeat["last_error"] == "resident task fake.worker was cancelled unexpectedly"
    assert len(delivered) == 1
    assert repo.list_runtime_alert_receipts()[0]["status"] == "sent"
    repo.close()


def test_startup_alert_retry_has_global_deadline_and_keeps_unprocessed_receipts(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    for index in range(2):
        key = f"fatal:pending-{index}"
        repo.create_runtime_alert_receipt(
            key,
            task_name="fake.worker",
            message=f"worker failed {index}",
            payload={"alert_key": key, "task_name": "fake.worker"},
        )

    def slow_sink(_payload: dict[str, object]) -> bool:
        time.sleep(1)
        return True

    alerts = RuntimeAlertService(repo, sink=slow_sink)
    started = time.monotonic()
    results = alerts.retry_pending(deadline_seconds=0.05, max_items=16)
    elapsed = time.monotonic() - started

    assert elapsed < 0.3
    assert len(results) == 1
    receipts = repo.list_runtime_alert_receipts()
    assert {item["status"] for item in receipts} == {"pending", "unknown"}
    repo.close()


def test_capped_alert_retries_are_fair_across_old_receipts(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    expected_keys = {f"fatal:fair-{index}" for index in range(17)}
    for key in expected_keys:
        repo.create_runtime_alert_receipt(
            key,
            task_name="fake.worker",
            message=key,
            payload={"alert_key": key, "task_name": "fake.worker"},
        )
    attempted: list[str] = []

    def declining_sink(payload: dict[str, object]) -> bool:
        attempted.append(str(payload["alert_key"]))
        return False

    alerts = RuntimeAlertService(repo, sink=declining_sink)
    for _ in range(3):
        alerts.retry_pending(max_items=16)

    assert set(attempted) == expected_keys
    assert len(set(attempted)) == 17
    repo.close()


def test_watchdog_retries_pending_alert_without_http_probe(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    key = "fatal:watchdog-retry"
    repo.create_runtime_alert_receipt(
        key,
        task_name="fake.worker",
        message="worker failed",
        payload={"alert_key": key, "task_name": "fake.worker"},
    )
    delivered: list[dict[str, object]] = []
    alerts = RuntimeAlertService(repo, sink=lambda payload: delivered.append(payload) or True)
    monitor = RuntimeTaskMonitor(repo, alerts=alerts)

    async def run() -> None:
        stop = asyncio.Event()
        watchdog = asyncio.create_task(monitor._watchdog_loop((), stop, 0.01))  # type: ignore[arg-type]
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(watchdog, timeout=1)

    asyncio.run(run())

    assert len(delivered) == 1
    assert repo.list_runtime_alert_receipts()[0]["status"] == "sent"
    repo.close()


def test_watchdog_uses_configured_alert_timeout_for_slow_success(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    key = "fatal:watchdog-slow-success"
    repo.create_runtime_alert_receipt(
        key,
        task_name="fake.worker",
        message="worker failed",
        payload={"alert_key": key, "task_name": "fake.worker"},
    )
    delivered: list[dict[str, object]] = []

    def slow_success(payload: dict[str, object]) -> bool:
        # This is deliberately longer than the old hard-coded one-second
        # watchdog budget, but shorter than the configured transport timeout.
        time.sleep(1.1)
        delivered.append(payload)
        return True

    alerts = RuntimeAlertService(repo, sink=slow_success, timeout_seconds=2)
    monitor = RuntimeTaskMonitor(repo, alerts=alerts)

    async def run() -> None:
        stop = asyncio.Event()
        watchdog = asyncio.create_task(monitor._watchdog_loop((), stop, 0.01))  # type: ignore[arg-type]
        await asyncio.sleep(1.35)
        stop.set()
        await asyncio.wait_for(watchdog, timeout=1)

    asyncio.run(run())

    assert len(delivered) == 1
    receipt = repo.list_runtime_alert_receipts()[0]
    assert receipt["status"] == "sent"
    assert receipt["attempts"] == 1
    repo.close()


def test_async_task_exit_keeps_event_loop_ticking_while_alert_sink_is_slow(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    delivered: list[dict[str, object]] = []

    def slow_sink(payload: dict[str, object]) -> bool:
        time.sleep(0.2)
        delivered.append(payload)
        return True

    alerts = RuntimeAlertService(repo, sink=slow_sink, timeout_seconds=1)
    monitor = RuntimeTaskMonitor(repo, alerts=alerts)
    monitor.register("fake.worker", required=True)

    async def run() -> None:
        task = asyncio.create_task(asyncio.sleep(0))
        monitor.watch("fake.worker", task)  # type: ignore[arg-type]
        ticks: list[float] = []

        async def ticker() -> None:
            for _ in range(5):
                ticks.append(time.monotonic())
                await asyncio.sleep(0.02)

        ticker_task = asyncio.create_task(ticker())
        await task
        await asyncio.sleep(0.06)
        assert len(ticks) >= 3
        assert ticks[-1] - ticks[0] >= 0.03
        await ticker_task
        for _ in range(20):
            if repo.list_runtime_alert_receipts()[0]["status"] == "sent":
                break
            await asyncio.sleep(0.02)

    asyncio.run(run())

    assert len(delivered) == 1
    assert repo.list_runtime_alert_receipts()[0]["status"] == "sent"
    repo.close()


def test_async_alert_timeout_does_not_hold_shared_executor(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    started = threading.Event()
    release = threading.Event()

    def stalled_sink(_payload: dict[str, object]) -> bool:
        started.set()
        release.wait(3)
        return True

    alerts = RuntimeAlertService(repo, sink=stalled_sink, timeout_seconds=1)

    async def run() -> None:
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        alerts.emit_fatal("fake.worker", "executor starvation drill")
        for _ in range(20):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set()
        # The unbounded sink must not occupy the only shared executor worker.
        marker = await asyncio.wait_for(
            asyncio.to_thread(lambda: "executor-free"),
            timeout=0.2,
        )
        assert marker == "executor-free"

    try:
        asyncio.run(run())
    finally:
        release.set()
    repo.close()


def test_async_alert_timeout_does_not_delay_loop_shutdown(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)

    def slow_sink(_payload: dict[str, object]) -> bool:
        time.sleep(2)
        return True

    alerts = RuntimeAlertService(repo, sink=slow_sink, timeout_seconds=1)

    async def run() -> None:
        alerts.emit_fatal("fake.worker", "shutdown deadline drill")
        await asyncio.sleep(1.1)

    started = time.monotonic()
    asyncio.run(run())
    elapsed = time.monotonic() - started

    assert elapsed < 1.7
    repo.close()


def test_stop_watchdog_does_not_wait_for_stalled_retry_worker(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    started = threading.Event()
    release = threading.Event()
    key = "fatal:watchdog-shutdown"
    repo.create_runtime_alert_receipt(
        key,
        task_name="fake.worker",
        message="watchdog shutdown",
        payload={"alert_key": key, "task_name": "fake.worker"},
    )

    def stalled_sink(_payload: dict[str, object]) -> bool:
        started.set()
        release.wait(5)
        return True

    alerts = RuntimeAlertService(repo, sink=stalled_sink, timeout_seconds=3)
    monitor = RuntimeTaskMonitor(repo, alerts=alerts)

    async def run() -> float:
        monitor.start_watchdog((), interval_seconds=0.01)
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set()
        started_stopping = time.monotonic()
        await monitor.stop_watchdog()
        return time.monotonic() - started_stopping

    elapsed = asyncio.run(run())
    assert elapsed < 0.5
    release.set()
    for _ in range(100):
        if repo.list_runtime_alert_receipts()[0]["status"] == "sent":
            break
        time.sleep(0.01)
    assert repo.list_runtime_alert_receipts()[0]["status"] == "sent"
    repo.close()


def test_alert_retry_cannot_overlap_async_delivery_or_downgrade_sent(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    first_started = threading.Event()
    second_started = threading.Event()
    first_release = threading.Event()
    second_release = threading.Event()
    calls: list[int] = []
    calls_lock = threading.Lock()

    def overlapping_sink(_payload: dict[str, object]) -> bool:
        with calls_lock:
            call_number = len(calls) + 1
            calls.append(call_number)
        if call_number == 1:
            first_started.set()
            first_release.wait(2)
            return True
        second_started.set()
        second_release.wait(2)
        return False

    alerts = RuntimeAlertService(repo, sink=overlapping_sink, timeout_seconds=1)

    async def run() -> None:
        alerts.emit_fatal("fake.worker", "overlap drill", incident_id="episode-1")
        for _ in range(20):
            if first_started.is_set():
                break
            await asyncio.sleep(0.01)
        assert first_started.is_set()

        retry_task = asyncio.create_task(asyncio.to_thread(alerts.retry_pending))
        await asyncio.sleep(0.05)
        first_release.set()
        for _ in range(50):
            receipt = repo.get_runtime_alert_receipt(
                repo.list_runtime_alert_receipts()[0]["alert_key"]
            )
            if receipt and receipt["status"] == "sent":
                break
            await asyncio.sleep(0.01)
        second_release.set()
        await asyncio.wait_for(retry_task, timeout=1)

    asyncio.run(run())

    assert not second_started.is_set()
    assert calls == [1]
    receipt = repo.list_runtime_alert_receipts()[0]
    assert receipt["status"] == "sent"
    # A stale completion attempting to report failure cannot downgrade sent.
    updated = repo.update_runtime_alert_receipt(
        str(receipt["alert_key"]),
        status="failed",
        last_error="late stale retry",
    )
    assert updated is not None
    assert updated["status"] == "sent"
    assert updated["sent_at"] == receipt["sent_at"]
    repo.close()


def test_https_alert_redirect_is_rejected_with_preserved_handler_signature() -> None:
    handler = _HttpsOnlyRedirectHandler()
    with pytest.raises(RuntimeAlertDeliveryError, match="redirects are not supported"):
        handler.redirect_request(
            Request("https://alerts.invalid/hook"),
            None,
            302,
            "Found",
            {},
            "https://alerts.invalid/final",
        )


def test_standard_source_wait_refreshes_heartbeat_during_long_policy_wait() -> None:
    class FakeMonitor:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def heartbeat(self, task_name: str, *, details: dict[str, object] | None = None):
            self.calls.append({"task_name": task_name, "details": details or {}})

    class FakeEvent:
        def __init__(self) -> None:
            self.wait_calls = 0
            self.clear_calls = 0

        async def wait(self) -> bool:
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise asyncio.TimeoutError
            return True

        def clear(self) -> None:
            self.clear_calls += 1

    monitor = FakeMonitor()
    event = FakeEvent()
    hub = object.__new__(HubService)
    hub.settings = SimpleNamespace(runtime_heartbeat_interval_seconds=5)
    hub.runtime_monitor = monitor
    hub._standard_source_policy_event = event

    changed = asyncio.run(hub._wait_for_standard_source_policy(10))

    assert changed is True
    assert event.wait_calls == 2
    assert event.clear_calls == 1
    assert len(monitor.calls) == 3
    assert monitor.calls[0]["details"]["remaining_seconds"] == 10
    assert monitor.calls[1]["details"]["phase"] == "waiting"
    assert monitor.calls[2]["details"]["phase"] == "policy_changed"


def test_long_refresh_reports_progress_but_a_hang_still_stales(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)

    class FakeRuleCatalog:
        async def refresh_categories(self, **_kwargs: object) -> dict[str, object]:
            await asyncio.sleep(0.02)
            return {"ok": True}

    class FakeGorelay:
        async def refresh(self, *, force: bool) -> SimpleNamespace:
            assert force is True
            await asyncio.sleep(0.02)
            return SimpleNamespace(last_refresh_at="", last_error=None, account_status={})

    class FakeRepo:
        def list_standard_sources(self) -> list[SimpleNamespace]:
            return [
                SimpleNamespace(id="slow-source-a", name="A", enabled=True, clash_url="", surge_url="", shadowrocket_url=""),
                SimpleNamespace(id="slow-source-b", name="B", enabled=True, clash_url="", surge_url="", shadowrocket_url=""),
            ]

    monitor = RuntimeTaskMonitor(repo, stale_after_seconds=10)
    monitor.stale_after_seconds = 0.05
    monitor.register("hub.refresh_loop", required=True)
    progress_calls: list[dict[str, object]] = []

    class RecordingMonitor:
        def heartbeat(self, task_name: str, *, details: dict[str, object] | None = None):
            progress_calls.append({"task_name": task_name, "details": details or {}})
            return monitor.heartbeat(task_name, details=details)

    recording_monitor = RecordingMonitor()
    hub = object.__new__(HubService)
    hub.settings = settings
    hub.repo = FakeRepo()
    hub.rule_catalog = FakeRuleCatalog()
    hub.gorelay_service = FakeGorelay()
    hub.runtime_monitor = recording_monitor
    hub.runtime = SimpleNamespace(
        last_refresh_at=None,
        last_error=None,
        source_status={},
    )
    hub._lock = asyncio.Lock()
    hub._is_cache_fresh = lambda: False
    hub._collect_gorelay_device_names = lambda: {}
    hub._ensure_default_device_subscription = lambda: None
    hub._clear_artifact_caches = lambda: None

    async def refresh_source(source, *, trigger: str, refresh_id: str):
        assert trigger == "auto"
        assert refresh_id
        await asyncio.sleep(0.02)
        return 0, {"ok": True}

    hub._refresh_standard_source_with_diagnostics = refresh_source
    asyncio.run(hub.refresh(force=True))

    progress_units = [
        item["details"].get("unit")
        for item in progress_calls
        if item["task_name"] == "hub.refresh_loop" and item["details"].get("unit")
    ]
    assert progress_units == ["rule_catalog", "gorelay", "standard_source", "standard_source"]
    assert monitor.readiness(["hub.refresh_loop"])["ok"] is True

    # If no real unit completes, the last progress heartbeat ages out and the
    # same watchdog/readiness rule still detects a genuine hang.
    time.sleep(0.08)
    assert monitor.readiness(["hub.refresh_loop"])["ok"] is False
    repo.close()


def test_standard_source_refresh_waiter_stays_live_without_hiding_stalled_owner(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    monitor = RuntimeTaskMonitor(repo, stale_after_seconds=10)
    monitor.stale_after_seconds = 0.12
    monitor.register("hub.refresh_loop", required=True, startup_success=True)
    monitor.register("hub.standard_source_loop", required=True, startup_success=True)

    hub = object.__new__(HubService)
    hub.settings = SimpleNamespace(runtime_heartbeat_interval_seconds=0.05)
    hub.repo = SimpleNamespace(list_standard_sources=lambda: [])
    hub.runtime = SimpleNamespace(source_status={})
    hub.runtime_monitor = monitor
    hub._lock = asyncio.Lock()
    hub._refresh_lock_owner = "hub.refresh_loop"
    hub._clear_artifact_caches = lambda: None

    async def run_probe() -> tuple[dict[str, object], dict[str, object]]:
        await hub._lock.acquire()
        waiting = asyncio.create_task(hub.refresh_standard_sources_only())
        await asyncio.sleep(0.27)
        queued_readiness = monitor.readiness(["hub.standard_source_loop"])
        owner_readiness = monitor.readiness(["hub.refresh_loop"])
        hub._lock.release()
        await asyncio.wait_for(waiting, timeout=1)
        return queued_readiness, owner_readiness

    queued_readiness, owner_readiness = asyncio.run(run_probe())

    assert queued_readiness["ok"] is True
    assert queued_readiness["tasks"]["hub.standard_source_loop"]["reason"] == ""
    assert owner_readiness["ok"] is False
    assert owner_readiness["tasks"]["hub.refresh_loop"]["reason"] == "stale heartbeat"
    repo.close()


def test_overlapping_standard_refresh_waiter_cannot_refresh_owner_heartbeat(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "state")
    settings.runtime_heartbeat_interval_seconds = 0
    repo = SqliteRepo(settings)
    monitor = RuntimeTaskMonitor(repo, stale_after_seconds=10)
    monitor.stale_after_seconds = 0.12
    monitor.register("hub.standard_source_loop", required=True, startup_success=True)
    source = SimpleNamespace(id="standard-owner", name="owner", enabled=True, clash_url="", surge_url="", shadowrocket_url="")
    owner_started = asyncio.Event()
    release_owner = asyncio.Event()

    class FakeRepo:
        @staticmethod
        def list_standard_sources() -> list[SimpleNamespace]:
            return [source]

        @staticmethod
        def get_standard_source(source_id: str) -> SimpleNamespace | None:
            return source if source_id == source.id else None

    hub = HubService(
        settings,
        FakeRepo(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        runtime_monitor=monitor,
    )

    async def blocked_refresh(*_args: object, **_kwargs: object) -> tuple[int, dict[str, object]]:
        owner_started.set()
        await release_owner.wait()
        return 1, {"ok": True}

    hub._refresh_standard_source_with_diagnostics = blocked_refresh  # type: ignore[method-assign]

    async def run_probe() -> tuple[dict[str, object], dict[str, object] | None]:
        owner = asyncio.create_task(hub.refresh_standard_sources_only())
        await asyncio.wait_for(owner_started.wait(), timeout=1)
        waiter = asyncio.create_task(hub.refresh_one_standard_source(source.id))
        await asyncio.sleep(0.3)
        owner_readiness = monitor.readiness(["hub.standard_source_loop"])
        waiter_heartbeat = repo.get_runtime_heartbeat("hub.standard_source.waiter")
        release_owner.set()
        await asyncio.wait_for(asyncio.gather(owner, waiter), timeout=1)
        return owner_readiness, waiter_heartbeat

    owner_readiness, waiter_heartbeat = asyncio.run(run_probe())

    assert owner_readiness["ok"] is False
    assert owner_readiness["tasks"]["hub.standard_source_loop"]["reason"] == "stale heartbeat"
    assert waiter_heartbeat is not None
    assert waiter_heartbeat["required"] == 0
    repo.close()


def test_full_refresh_waiter_keeps_required_heartbeat_behind_standard_owner(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "state")
    settings.runtime_heartbeat_interval_seconds = 0
    repo = SqliteRepo(settings)
    monitor = RuntimeTaskMonitor(repo, stale_after_seconds=10)
    monitor.stale_after_seconds = 0.12
    monitor.register("hub.refresh_loop", required=True, startup_success=True)
    monitor.register("hub.standard_source_loop", required=True, startup_success=True)
    source = SimpleNamespace(id="standard-owner", name="owner", enabled=True, clash_url="", surge_url="", shadowrocket_url="")
    owner_started = asyncio.Event()
    release_owner = asyncio.Event()

    class FakeRepo:
        @staticmethod
        def list_standard_sources() -> list[SimpleNamespace]:
            return [source]

    class FakeRuleCatalog:
        async def refresh_categories(self, **_kwargs: object) -> dict[str, object]:
            return {"ok": True}

    class FakeGorelay:
        def list_accounts(self) -> list[object]:
            return []

        async def refresh(self, *, force: bool) -> SimpleNamespace:
            assert force is True
            return SimpleNamespace(last_refresh_at="", last_error=None, account_status={})

    hub = HubService(
        settings,
        FakeRepo(),  # type: ignore[arg-type]
        FakeRuleCatalog(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        FakeGorelay(),  # type: ignore[arg-type]
        runtime_monitor=monitor,
    )
    hub._collect_gorelay_device_names = lambda: {}  # type: ignore[method-assign]
    hub._ensure_default_device_subscription = lambda: None  # type: ignore[method-assign]

    async def healthy_standard_refresh(*_args: object, **_kwargs: object) -> tuple[int, dict[str, object]]:
        owner_started.set()
        while not release_owner.is_set():
            monitor.heartbeat("hub.standard_source_loop", details={"phase": "test_progress"})
            await asyncio.sleep(0.03)
        return 1, {"ok": True}

    hub._refresh_standard_source_with_diagnostics = healthy_standard_refresh  # type: ignore[method-assign]

    async def run_probe() -> dict[str, object]:
        standard_owner = asyncio.create_task(hub.refresh_standard_sources_only())
        await asyncio.wait_for(owner_started.wait(), timeout=1)
        full_waiter = asyncio.create_task(hub.refresh(force=True))
        await asyncio.sleep(0.3)
        full_readiness = monitor.readiness(["hub.refresh_loop"])
        release_owner.set()
        await asyncio.wait_for(asyncio.gather(standard_owner, full_waiter), timeout=1)
        return full_readiness

    full_readiness = asyncio.run(run_probe())

    assert full_readiness["ok"] is True
    assert full_readiness["tasks"]["hub.refresh_loop"]["reason"] == ""
    repo.close()


def test_overlapping_refresh_waiter_cannot_refresh_stalled_owner_heartbeat(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "state")
    settings.runtime_heartbeat_interval_seconds = 0
    repo = SqliteRepo(settings)
    monitor = RuntimeTaskMonitor(repo, stale_after_seconds=10)
    monitor.stale_after_seconds = 0.12
    monitor.register("hub.refresh_loop", required=True, startup_success=True)

    owner_started = asyncio.Event()
    release_owner = asyncio.Event()

    class BlockingRuleCatalog:
        async def refresh_categories(self, **_kwargs: object) -> dict[str, object]:
            owner_started.set()
            await release_owner.wait()
            return {"ok": True}

    class IdleGorelay:
        def list_accounts(self) -> list[object]:
            return []

        async def refresh(self, *, force: bool) -> SimpleNamespace:
            assert force is True
            return SimpleNamespace(last_refresh_at="", last_error=None, account_status={})

    hub = HubService(
        settings,
        repo,
        BlockingRuleCatalog(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        IdleGorelay(),  # type: ignore[arg-type]
        runtime_monitor=monitor,
    )

    async def run_probe() -> tuple[dict[str, object], dict[str, object] | None]:
        owner = asyncio.create_task(hub.refresh(force=True))
        await asyncio.wait_for(owner_started.wait(), timeout=1)
        waiter = asyncio.create_task(hub.refresh(force=True))
        await asyncio.sleep(0.3)
        owner_readiness = monitor.readiness(["hub.refresh_loop"])
        waiter_heartbeat = repo.get_runtime_heartbeat("hub.refresh.waiter")
        release_owner.set()
        await asyncio.wait_for(asyncio.gather(owner, waiter), timeout=1)
        return owner_readiness, waiter_heartbeat

    owner_readiness, waiter_heartbeat = asyncio.run(run_probe())

    assert owner_readiness["ok"] is False
    assert owner_readiness["tasks"]["hub.refresh_loop"]["reason"] == "stale heartbeat"
    assert waiter_heartbeat is not None
    assert waiter_heartbeat["required"] == 0
    repo.close()


def test_dependency_progress_refreshes_hub_without_masking_a_hang(tmp_path: Path) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    monitor = RuntimeTaskMonitor(repo, stale_after_seconds=10)
    monitor.stale_after_seconds = 0.08
    monitor.register("hub.refresh_loop", required=True, startup_success=True)

    progress_seen = asyncio.Event()
    second_progress_seen = asyncio.Event()

    class ProgressRuleCatalog:
        _callback = None

        def set_progress_callback(self, callback):  # type: ignore[no-untyped-def]
            self._callback = callback

        async def refresh_categories(self, **_kwargs: object) -> dict[str, object]:
            await asyncio.sleep(0.04)
            assert self._callback is not None
            self._callback({"unit": "category", "category": "first"})
            progress_seen.set()
            await asyncio.sleep(0.04)
            self._callback({"unit": "category", "category": "second"})
            second_progress_seen.set()
            return {"ok": True}

    class IdleGorelay:
        def list_accounts(self) -> list[object]:
            return []

        async def refresh(self, *, force: bool) -> SimpleNamespace:
            assert force is True
            return SimpleNamespace(last_refresh_at="", last_error=None, account_status={})

    hub = HubService(
        settings,
        repo,
        ProgressRuleCatalog(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        IdleGorelay(),  # type: ignore[arg-type]
        runtime_monitor=monitor,
    )

    async def run_progress_probe() -> None:
        refresh = asyncio.create_task(hub.refresh(force=True))
        await asyncio.wait_for(progress_seen.wait(), timeout=1)
        assert monitor.readiness(["hub.refresh_loop"])["ok"] is True
        await asyncio.wait_for(second_progress_seen.wait(), timeout=1)
        await asyncio.wait_for(refresh, timeout=1)

    asyncio.run(run_progress_probe())

    class HangingRuleCatalog:
        def set_progress_callback(self, callback):  # type: ignore[no-untyped-def]
            self._callback = callback

        async def refresh_categories(self, **_kwargs: object) -> dict[str, object]:
            await asyncio.Event().wait()

    hub.rule_catalog = HangingRuleCatalog()  # type: ignore[assignment]
    hub._attach_dependency_progress(hub.rule_catalog, "rule_catalog")

    async def run_hang_probe() -> None:
        refresh = asyncio.create_task(hub.refresh(force=True))
        await asyncio.sleep(0.15)
        assert monitor.readiness(["hub.refresh_loop"])["ok"] is False
        refresh.cancel()
        with pytest.raises(asyncio.CancelledError):
            await refresh

    asyncio.run(run_hang_probe())
    repo.close()


def test_unrelated_dependency_progress_cannot_refresh_stalled_hub(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    monitor = RuntimeTaskMonitor(repo, stale_after_seconds=10)
    monitor.stale_after_seconds = 0.08
    monitor.register("hub.refresh_loop", required=True, startup_success=True)
    dependency_started = asyncio.Event()
    release_dependency = asyncio.Event()
    callback_holder: dict[str, object] = {}

    class IdleRuleCatalog:
        async def refresh_categories(self, **_kwargs: object) -> dict[str, object]:
            return {"ok": True}

    class CallbackGorelay:
        def set_progress_callback(self, callback):  # type: ignore[no-untyped-def]
            callback_holder["callback"] = callback

        def list_accounts(self) -> list[object]:
            return []

        async def refresh(self, *, force: bool) -> SimpleNamespace:
            assert force is True
            dependency_started.set()
            await release_dependency.wait()
            return SimpleNamespace(last_refresh_at="", last_error=None, account_status={})

    hub = HubService(
        settings,
        SimpleNamespace(list_standard_sources=lambda: []),  # type: ignore[arg-type]
        IdleRuleCatalog(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        CallbackGorelay(),  # type: ignore[arg-type]
        runtime_monitor=monitor,
    )
    hub._collect_gorelay_device_names = lambda: {}  # type: ignore[method-assign]
    hub._ensure_default_device_subscription = lambda: None  # type: ignore[method-assign]

    async def run_probe() -> dict[str, object]:
        refresh = asyncio.create_task(hub.refresh(force=True))
        await asyncio.wait_for(dependency_started.wait(), timeout=1)
        callback = callback_holder["callback"]
        assert callable(callback)
        # This callback runs from an independent task, as a resident GoRelay
        # refresh or management request would.  It must not count as progress
        # for the Hub invocation that is currently awaiting another call.
        for _ in range(12):
            callback({"unit": "account", "account_id": "unrelated"})
            await asyncio.sleep(0.02)
        readiness = monitor.readiness(["hub.refresh_loop"])
        release_dependency.set()
        await asyncio.wait_for(refresh, timeout=1)
        return readiness

    readiness = asyncio.run(run_probe())

    assert readiness["ok"] is False
    assert readiness["tasks"]["hub.refresh_loop"]["reason"] == "stale heartbeat"
    repo.close()


def test_backup_and_promotion_checkpoints_do_not_wait_for_old_readers(
    tmp_path: Path,
) -> None:
    repo = SqliteRepo(_settings(tmp_path / "state"))
    repo.set_runtime_setting("checkpoint_probe", {"value": "before-reader"})
    reader = sqlite3.connect(str(repo.db_path), timeout=30, check_same_thread=False)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT value_json FROM runtime_settings WHERE key='checkpoint_probe'").fetchone()
        repo.set_runtime_setting("checkpoint_probe", {"value": "after-reader"})

        statements: list[str] = []
        repo._conn.set_trace_callback(statements.append)
        backup_path = tmp_path / "backup.db"
        started = time.monotonic()
        backup = repo.backup_database(backup_path)
        backup_elapsed = time.monotonic() - started

        staged_path = tmp_path / "staged.db"
        staged = repo.backup_database(staged_path)
        started = time.monotonic()
        promoted = repo.promote_staged_database(
            staged_path,
            expected_change_token=str(staged["change_token"]),
        )
        promotion_elapsed = time.monotonic() - started

        assert backup["ok"] is True
        assert promoted["promoted"] is True
        assert backup_elapsed < 1
        assert promotion_elapsed < 1
        assert not any("wal_checkpoint(FULL)" in statement for statement in statements)
    finally:
        reader.rollback()
        reader.close()
        repo.close()


def test_ready_payload_runs_database_integrity_off_event_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path / "state")
    repo = SqliteRepo(settings)
    started = threading.Event()
    release = threading.Event()

    def blocked_integrity() -> dict[str, object]:
        started.set()
        if not release.wait(timeout=2):
            raise AssertionError("readyz database check was not released")
        return {"ok": True}

    monkeypatch.setattr(repo, "database_integrity", blocked_integrity)
    services = SimpleNamespace(
        settings=settings,
        repo=repo,
        runtime_monitor=SimpleNamespace(readiness=lambda _tasks: {"ok": True, "tasks": {}}),
        runtime_alerts=SimpleNamespace(readiness=lambda: {"ok": True}),
        policy_backup=SimpleNamespace(
            status=lambda: SimpleNamespace(
                to_dict=lambda: {"enabled": False, "configured": False, "reconciliation_required": False}
            )
        ),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(services=services)),
    )

    async def run_probe() -> tuple[int, dict[str, object]]:
        task = asyncio.create_task(_ready_payload(request))
        for _ in range(50):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set()
        ticks = 0
        while not release.is_set() and ticks < 10:
            ticks += 1
            await asyncio.sleep(0.01)
        release.set()
        payload = await asyncio.wait_for(task, timeout=1)
        return ticks, payload

    ticks, payload = asyncio.run(run_probe())

    assert ticks >= 3
    assert payload["checks"]["database"]["ok"] is True
    repo.close()


def test_database_integrity_uses_nonblocking_passive_checkpoint(tmp_path: Path) -> None:
    repo = SqliteRepo(_settings(tmp_path / "state"))
    statements: list[str] = []
    repo._conn.set_trace_callback(statements.append)

    result = repo.database_integrity()

    assert result["ok"] is True
    assert any("wal_checkpoint(PASSIVE)" in statement for statement in statements)
    repo.close()


def test_staged_restore_cas_rejects_old_token_after_connection_replacement(
    tmp_path: Path,
) -> None:
    repo = SqliteRepo(_settings(tmp_path / "state"))
    first_staged = tmp_path / "staged-first.db"
    second_staged = tmp_path / "staged-second.db"
    first = repo.backup_database(first_staged)
    second = repo.backup_database(second_staged)
    assert first["change_token"] == second["change_token"]

    promoted = repo.promote_staged_database(
        first_staged,
        expected_change_token=str(first["change_token"]),
    )
    rejected = repo.promote_staged_database(
        second_staged,
        expected_change_token=str(second["change_token"]),
    )

    assert promoted["promoted"] is True
    assert rejected["promoted"] is False
    assert "changed" in str(rejected["reason"])
    repo.close()


def test_policy_staged_restore_cas_ignores_runtime_heartbeat_writes(
    tmp_path: Path,
) -> None:
    repo = SqliteRepo(_settings(tmp_path / "state"))
    staged_path = tmp_path / "policy-staged.db"
    baseline = repo.backup_database(staged_path, change_token_scope="policy")

    repo.upsert_runtime_heartbeat("runtime.test", details={"phase": "heartbeat"})

    promoted = repo.promote_staged_database(
        staged_path,
        expected_change_token=str(baseline["change_token"]),
        change_token_scope="policy",
    )

    assert promoted["promoted"] is True
    assert promoted["change_token_scope"] == "policy"
    repo.close()


def test_overlapping_policy_restores_are_serialized_and_keep_runtime_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path / "state", policy_backup_enabled=True)
    repo = SqliteRepo(settings)
    service = PolicyBackupService(settings, repo)
    repo.create_manual_rule_category("restore-target", "DIRECT")
    target_snapshot = service.export_snapshot()
    repo.create_manual_rule_category("discarded-live-state", "DIRECT")

    first_stage_entered = threading.Event()
    release_first_stage = threading.Event()
    stage_state_lock = threading.Lock()
    active_stages = 0
    maximum_active_stages = 0
    first_stage = True
    original_apply = PolicyBackupService._apply_snapshot_in_place

    def blocked_stage(self, staged_snapshot):  # type: ignore[no-untyped-def]
        nonlocal active_stages, maximum_active_stages, first_stage
        with stage_state_lock:
            active_stages += 1
            maximum_active_stages = max(maximum_active_stages, active_stages)
            should_block = first_stage
            first_stage = False
        try:
            if should_block:
                first_stage_entered.set()
                if not release_first_stage.wait(timeout=5):
                    raise AssertionError("first staged restore did not receive release")
            return original_apply(self, staged_snapshot)
        finally:
            with stage_state_lock:
                active_stages -= 1

    monkeypatch.setattr(PolicyBackupService, "_apply_snapshot_in_place", blocked_stage)
    errors: list[BaseException] = []

    def apply_snapshot() -> None:
        try:
            service._apply_snapshot(target_snapshot)
        except BaseException as exc:
            errors.append(exc)

    first_thread = threading.Thread(target=apply_snapshot, name="policy-restore-first")
    second_thread = threading.Thread(target=apply_snapshot, name="policy-restore-second")
    first_thread.start()
    assert first_stage_entered.wait(timeout=5)
    repo.upsert_runtime_heartbeat(
        "runtime.overlapping-restore.writer",
        required=False,
        details={"source": "between-overlapping-restores"},
    )
    second_thread.start()
    time.sleep(0.1)
    assert second_thread.is_alive()
    with stage_state_lock:
        assert maximum_active_stages == 1

    release_first_stage.set()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert not second_thread.is_alive()
    assert errors == []
    assert maximum_active_stages == 1
    assert repo.get_runtime_heartbeat("runtime.overlapping-restore.writer") is not None
    assert [item.name for item in repo.list_rule_categories() if item.category_type == "manual"] == [
        "restore-target"
    ]
    repo.close()


def test_policy_restore_barrier_preserves_concurrent_runtime_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path / "state", policy_backup_enabled=True)
    repo = SqliteRepo(settings)
    service = PolicyBackupService(settings, repo)
    repo.create_manual_rule_category("restore-target", "DIRECT")
    target_snapshot = service.export_snapshot()
    repo.create_manual_rule_category("discarded-live-state", "DIRECT")

    stage_entered = threading.Event()
    allow_stage = threading.Event()
    first_stage = True
    stage_lock = threading.Lock()
    original_apply = PolicyBackupService._apply_snapshot_in_place

    def blocked_stage(self, staged_snapshot):  # type: ignore[no-untyped-def]
        nonlocal first_stage
        should_block = False
        with stage_lock:
            if first_stage:
                first_stage = False
                should_block = True
        if should_block:
            stage_entered.set()
            if not allow_stage.wait(timeout=5):
                raise AssertionError("staged restore did not receive the test release")
        return original_apply(self, staged_snapshot)

    monkeypatch.setattr(PolicyBackupService, "_apply_snapshot_in_place", blocked_stage)
    apply_errors: list[BaseException] = []

    def apply_snapshot() -> None:
        try:
            service._apply_snapshot(target_snapshot)
        except BaseException as exc:
            apply_errors.append(exc)

    apply_thread = threading.Thread(target=apply_snapshot, name="policy-restore-drill")
    apply_thread.start()
    assert stage_entered.wait(timeout=5)

    async def event_loop_writer_probe() -> float:
        started = time.monotonic()
        repo.upsert_runtime_heartbeat(
            "runtime.event-loop.writer",
            required=False,
            details={"source": "event-loop-restore-test"},
        )
        return time.monotonic() - started

    # Keep the staged apply blocked while an actual event-loop caller writes
    # through the live repository.  The old restore_barrier implementation
    # held its synchronous RLock here and froze this coroutine; the short-CAS
    # design must let it complete before promotion.
    release_timer = threading.Timer(0.25, allow_stage.set)
    release_timer.start()
    event_loop_write_elapsed = asyncio.run(event_loop_writer_probe())
    release_timer.cancel()
    assert event_loop_write_elapsed < 0.2

    writer_started = threading.Event()
    writer_finished = threading.Event()
    heartbeat_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def concurrent_writer() -> None:
        writer_started.set()
        repo.set_runtime_setting("runtime.concurrent.setting", {"kept": True})
        repo.upsert_runtime_heartbeat(
            "runtime.concurrent.writer",
            required=False,
            heartbeat_at=heartbeat_at,
            details={"source": "concurrent-restore-test"},
        )
        repo.create_runtime_alert_receipt(
            "fatal:concurrent-restore-test",
            task_name="runtime.concurrent.writer",
            message="concurrent receipt",
            payload={"fixture": True},
        )
        repo.record_policy_backup_dirty("concurrent-restore-test")
        writer_finished.set()

    writer_thread = threading.Thread(target=concurrent_writer, name="concurrent-runtime-writer")
    writer_thread.start()
    assert writer_started.wait(timeout=5)
    # Long staged work must not hold the live repository lock.  The writer is
    # allowed to commit while policy validation/apply is still in progress;
    # the restore's digest CAS will then rebuild from that newer live state.
    assert writer_finished.wait(timeout=0.5)

    allow_stage.set()
    apply_thread.join(timeout=5)
    writer_thread.join(timeout=5)
    assert not apply_thread.is_alive()
    assert not writer_thread.is_alive()
    assert apply_errors == []

    assert repo.get_runtime_setting("runtime.concurrent.setting") == {"kept": True}
    heartbeat = repo.get_runtime_heartbeat("runtime.concurrent.writer")
    assert heartbeat is not None
    assert heartbeat["details"]["source"] == "concurrent-restore-test"
    receipt = repo.get_runtime_alert_receipt("fatal:concurrent-restore-test")
    assert receipt is not None
    assert receipt["status"] == "pending"
    state = repo.get_policy_backup_state()
    assert state["pending_count"] == 1
    assert [item.name for item in repo.list_rule_categories() if item.category_type == "manual"] == [
        "restore-target"
    ]
    assert repo._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    repo.close()


def test_sqlite_backup_restore_blank_target_and_sigkill_readback(tmp_path: Path) -> None:
    source_settings = _settings(tmp_path / "source")
    source = SqliteRepo(source_settings)
    source.create_manual_rule_category("restore-source", "DIRECT", locked=True)
    source.save_custom_rule(
        CustomRule(
            id="restore-source-rule",
            rule_type="DOMAIN-SUFFIX",
            value="restore.example.test",
            target_group="DIRECT",
            created_at="2026-09-02T00:00:00Z",
        )
    )
    backup_path = tmp_path / "fixture" / "policy.db"
    backup_metadata = source.backup_database(backup_path)
    assert backup_metadata["ok"] is True
    source.close()

    target_settings = _settings(tmp_path / "target")
    target = SqliteRepo(target_settings)
    target.create_manual_rule_category("must-disappear", "DIRECT")
    before_fault = [item.name for item in target.list_rule_categories()]
    with pytest.raises(RuntimeError, match="after_stage"):
        target.restore_database(backup_path, fault_injection="after_stage")
    assert [item.name for item in target.list_rule_categories()] == before_fault

    restored = target.restore_database(backup_path)
    assert restored["ok"] is True
    assert any(item.name == "restore-source" for item in target.list_rule_categories())
    assert not any(item.name == "must-disappear" for item in target.list_rule_categories())
    assert [item.value for item in target.list_custom_rules() if item.id == "restore-source-rule"] == [
        "restore.example.test"
    ]
    assert target.database_integrity()["ok"] is True

    # A separate process is killed after os.replace.  A fresh process must
    # still read a complete restored database; the mere existence of a backup
    # file is not accepted as recovery evidence.
    target.close()
    kill_script = """
import sys
from app.config import Settings
from app.storage.sqlite_repo import SqliteRepo

settings = Settings(
    app_name='SubHub', app_base_url='', storage_root=sys.argv[1],
    refresh_interval_minutes=30, request_timeout_seconds=5, verify_tls=False,
    github_api_base='https://127.0.0.1/invalid', github_raw_base='https://127.0.0.1/invalid',
    rule_catalog_refresh_hours=24, manage_api_require_login=False,
    max_snapshots_per_account=20, account_crawl_parallelism=2,
)
repo = SqliteRepo(settings)
repo.restore_database(sys.argv[2], fault_injection='sigkill:after_swap')
"""
    result = subprocess.run(
        [sys.executable, "-c", kill_script, str(target_settings.storage_root), str(backup_path)],
        cwd=str(Path(__file__).resolve().parents[1]),
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == -signal.SIGKILL, result.stderr

    fresh_target = SqliteRepo(target_settings)
    assert any(item.name == "restore-source" for item in fresh_target.list_rule_categories())
    assert not any(item.name == "must-disappear" for item in fresh_target.list_rule_categories())
    assert [item.value for item in fresh_target.list_custom_rules() if item.id == "restore-source-rule"] == [
        "restore.example.test"
    ]
    assert fresh_target.database_integrity()["ok"] is True
    fresh_target.close()


def test_staged_promotion_sigkill_after_sidecar_cleanup_recovers_wal_state(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "target")
    initial = SqliteRepo(settings)
    initial.set_runtime_setting("promotion-wal-probe", {"value": "old"})
    initial.close()

    # Hold a read transaction on the old inode while a separate connection
    # commits a newer value into WAL.  PASSIVE checkpointing cannot discard
    # that reader's snapshot, so the promotion must preserve the complete
    # staged main database across the kill window.
    old_reader = sqlite3.connect(
        str(Path(settings.storage_root) / "data" / "subhub.db"),
        timeout=30,
    )
    old_reader.execute("BEGIN")
    assert old_reader.execute(
        "SELECT value_json FROM runtime_settings WHERE key='promotion-wal-probe'"
    ).fetchone()[0] == '{"value":"old"}'
    writer = SqliteRepo(settings)
    writer.set_runtime_setting("promotion-wal-probe", {"value": "latest"})
    writer.close()

    kill_script = """
import sys
from app.config import Settings
from app.storage.sqlite_repo import SqliteRepo

settings = Settings(
    app_name='SubHub', app_base_url='', storage_root=sys.argv[1],
    refresh_interval_minutes=30, request_timeout_seconds=5, verify_tls=False,
    github_api_base='https://127.0.0.1/invalid', github_raw_base='https://127.0.0.1/invalid',
    rule_catalog_refresh_hours=24, manage_api_require_login=False,
    max_snapshots_per_account=20, account_crawl_parallelism=2,
)
repo = SqliteRepo(settings)
staged = repo.backup_database(sys.argv[2])
repo.promote_staged_database(
    sys.argv[2],
    expected_change_token=str(staged['change_token']),
    fault_injection='sigkill:after_sidecar_delete',
)
"""
    staged_path = tmp_path / "staged-child.db"
    result = subprocess.run(
        [sys.executable, "-c", kill_script, settings.storage_root, str(staged_path)],
        cwd=str(Path(__file__).resolve().parents[1]),
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        capture_output=True,
        text=True,
        check=False,
    )
    old_reader.rollback()
    old_reader.close()

    assert result.returncode == -signal.SIGKILL, result.stderr
    fresh = SqliteRepo(settings)
    assert fresh.get_runtime_setting("promotion-wal-probe") == {"value": "latest"}
    assert fresh.database_integrity()["ok"] is True
    assert not Path(f"{fresh.db_path.parent}/.subhub-db-promotion.json").exists()
    fresh.close()


def test_restore_sigkill_after_sidecar_cleanup_recovers_wal_state(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "target")
    initial = SqliteRepo(settings)
    initial.set_runtime_setting("restore-wal-probe", {"value": "old"})
    initial.close()

    # Keep a snapshot on the old inode while a separate connection commits a
    # newer value into WAL.  The direct restore path must install its complete
    # staged main file before removing the old sidecars, just like the CAS
    # promotion path.
    old_reader = sqlite3.connect(
        str(Path(settings.storage_root) / "data" / "subhub.db"),
        timeout=30,
    )
    old_reader.execute("BEGIN")
    assert old_reader.execute(
        "SELECT value_json FROM runtime_settings WHERE key='restore-wal-probe'"
    ).fetchone()[0] == '{"value":"old"}'
    writer = SqliteRepo(settings)
    writer.set_runtime_setting("restore-wal-probe", {"value": "latest"})
    backup_path = tmp_path / "restore-source.db"
    writer.backup_database(backup_path)
    writer.close()

    kill_script = """
import sys
from app.config import Settings
from app.storage.sqlite_repo import SqliteRepo

settings = Settings(
    app_name='SubHub', app_base_url='', storage_root=sys.argv[1],
    refresh_interval_minutes=30, request_timeout_seconds=5, verify_tls=False,
    github_api_base='https://127.0.0.1/invalid', github_raw_base='https://127.0.0.1/invalid',
    rule_catalog_refresh_hours=24, manage_api_require_login=False,
    max_snapshots_per_account=20, account_crawl_parallelism=2,
)
repo = SqliteRepo(settings)
repo.restore_database(
    sys.argv[2],
    fault_injection='sigkill:after_sidecar_delete',
    preserve_previous=False,
)
"""
    result = subprocess.run(
        [sys.executable, "-c", kill_script, settings.storage_root, str(backup_path)],
        cwd=str(Path(__file__).resolve().parents[1]),
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])},
        capture_output=True,
        text=True,
        check=False,
    )
    old_reader.rollback()
    old_reader.close()

    assert result.returncode == -signal.SIGKILL, result.stderr
    fresh = SqliteRepo(settings)
    assert fresh.get_runtime_setting("restore-wal-probe") == {"value": "latest"}
    assert fresh.database_integrity()["ok"] is True
    assert not Path(f"{fresh.db_path.parent}/.subhub-db-promotion.json").exists()
    fresh.close()


def test_promotion_sidecar_failure_fails_closed_and_keeps_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path / "target")
    repo = SqliteRepo(settings)
    repo.set_runtime_setting("sidecar-failure-probe", {"value": "restored"})
    staged_path = tmp_path / "staged.db"
    staged = repo.backup_database(staged_path)

    def refuse_sidecar_cleanup() -> None:
        raise OSError("synthetic WAL unlink failure")

    monkeypatch.setattr(repo, "_remove_live_sidecars", refuse_sidecar_cleanup)
    with pytest.raises(OSError, match="synthetic WAL unlink failure"):
        repo.promote_staged_database(
            staged_path,
            expected_change_token=str(staged["change_token"]),
        )

    # The replacement may already have happened, but the repository must not
    # reopen or retire its journal while a stale WAL could still be present.
    assert repo._conn is None
    assert repo._cas_conn is None
    assert repo._promotion_journal_path.exists()
    monkeypatch.undo()
    repo.close()

    recovered = SqliteRepo(settings)
    assert recovered.get_runtime_setting("sidecar-failure-probe") == {"value": "restored"}
    assert not recovered._promotion_journal_path.exists()
    recovered.close()


def test_startup_sidecar_failure_does_not_open_recovered_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path / "target")
    repo = SqliteRepo(settings)
    repo.set_runtime_setting("startup-sidecar-failure-probe", {"value": "new"})
    staged_path = tmp_path / "startup-staged.db"
    repo.backup_database(staged_path)
    repo._write_promotion_journal(staged_path, "startup-sidecar-failure")
    repo.close()

    def refuse_sidecar_cleanup(_repo: SqliteRepo) -> None:
        raise OSError("synthetic startup WAL unlink failure")

    monkeypatch.setattr(SqliteRepo, "_remove_live_sidecars", refuse_sidecar_cleanup)
    with pytest.raises(RuntimeError, match="promotion recovery failed"):
        SqliteRepo(settings)
    assert (Path(settings.storage_root) / "data" / ".subhub-db-promotion.json").exists()

    monkeypatch.undo()
    recovered = SqliteRepo(settings)
    assert recovered.get_runtime_setting("startup-sidecar-failure-probe") == {"value": "new"}
    assert not recovered._promotion_journal_path.exists()
    recovered.close()


@pytest.mark.parametrize("operation", ["promote", "restore"])
def test_fsync_after_replace_confirms_hash_before_reconnect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    target_settings = _settings(tmp_path / "target")
    source_settings = _settings(tmp_path / "source")
    target = SqliteRepo(target_settings)
    source = SqliteRepo(source_settings)
    target.set_runtime_setting("fsync-promotion-probe", {"value": "live"})
    source.set_runtime_setting("fsync-promotion-probe", {"value": "restored"})
    source_path = tmp_path / "source.db"
    source.backup_database(source_path)
    source.close()

    original_fsync = target._fsync_file
    failed = False

    def fail_live_fsync(path: Path) -> None:
        nonlocal failed
        if Path(path).resolve() == target.db_path.resolve() and not failed:
            failed = True
            raise OSError("synthetic post-replace fsync failure")
        original_fsync(path)

    monkeypatch.setattr(target, "_fsync_file", fail_live_fsync)
    if operation == "promote":
        staged_path = tmp_path / "staged.db"
        baseline = target.backup_database(tmp_path / "baseline.db")
        source = SqliteRepo(source_settings)
        source.set_runtime_setting("fsync-promotion-probe", {"value": "restored"})
        source.backup_database(staged_path)
        source.close()
        with pytest.raises(OSError, match="synthetic post-replace fsync failure"):
            target.promote_staged_database(
                staged_path,
                expected_change_token=str(baseline["change_token"]),
            )
    else:
        with pytest.raises(OSError, match="synthetic post-replace fsync failure"):
            target.restore_database(source_path, preserve_previous=False)

    assert failed is True
    # The exception path can reconnect only after it proves the active main
    # hash is the staged hash and removes all old sidecars.
    assert target._conn is not None
    assert target.get_runtime_setting("fsync-promotion-probe") == {"value": "restored"}
    assert not target._promotion_journal_path.exists()
    target.close()


def test_operator_sync_does_not_clear_unexpected_worker_exit(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "state", policy_backup_enabled=True)
    repo = SqliteRepo(settings)
    monitor = RuntimeTaskMonitor(repo, stale_after_seconds=10)
    service = PolicyBackupService(settings, repo, runtime_monitor=monitor)
    monitor.register("policy_backup.worker", required=True, startup_success=True)

    expected_digest = str(service.export_snapshot()["manifest"]["digest"])

    class FakeGit:
        @staticmethod
        def current_source_repo() -> str:
            return ""

        @staticmethod
        def sync_files(*_args: object, **_kwargs: object) -> _GitSyncResult:
            return _GitSyncResult(
                ok=True,
                changed=True,
                commit_sha="operator-after-exit",
                remote_digest=expected_digest,
            )

    service.backend = FakeGit()  # type: ignore[assignment]

    async def run() -> None:
        async def exited() -> None:
            return None

        task = asyncio.create_task(exited())
        service._worker_task = task
        monitor.watch("policy_backup.worker", task)
        await task
        # Let the done callback persist the worker-exit episode before the
        # operator's successful sync is attempted.
        await asyncio.sleep(0)
        result = await service.sync_now(force=True)
        assert result["ok"] is True

    asyncio.run(run())
    heartbeat = repo.get_runtime_heartbeat("policy_backup.worker")
    assert heartbeat is not None
    assert heartbeat["status"] == "degraded"
    assert heartbeat["consecutive_failures"] == 1
    assert monitor.readiness(["policy_backup.worker"])["ok"] is False
    repo.close()


def test_hub_refresh_reports_progress_while_waiting_for_gorelay_lock(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "state")
    settings.runtime_heartbeat_interval_seconds = 0.05
    repo = SqliteRepo(settings)
    monitor = RuntimeTaskMonitor(repo, stale_after_seconds=10)
    monitor.stale_after_seconds = 0.12
    monitor.register("hub.refresh_loop", required=True, startup_success=True)

    class FakeRepo:
        @staticmethod
        def list_standard_sources() -> list[SimpleNamespace]:
            return []

        @staticmethod
        def list_gorelay_accounts() -> list[object]:
            return []

    class FakeRuleCatalog:
        async def refresh_categories(self, **_kwargs: object) -> dict[str, object]:
            return {"ok": True}

    gorelay = GorelayService(settings, FakeRepo(), runtime_monitor=monitor)  # type: ignore[arg-type]
    hub = HubService(
        settings,
        FakeRepo(),  # type: ignore[arg-type]
        FakeRuleCatalog(),  # type: ignore[arg-type]
        SimpleNamespace(),  # type: ignore[arg-type]
        gorelay,
        runtime_monitor=monitor,
    )
    hub._collect_gorelay_device_names = lambda: {}  # type: ignore[method-assign]
    hub._ensure_default_device_subscription = lambda: None  # type: ignore[method-assign]
    hub._clear_artifact_caches = lambda: None  # type: ignore[method-assign]

    async def run() -> None:
        await gorelay.runtime.lock.acquire()
        refresh = asyncio.create_task(hub.refresh(force=True))
        await asyncio.sleep(0.25)
        readiness = monitor.readiness(["hub.refresh_loop"])
        heartbeat = repo.get_runtime_heartbeat("hub.refresh_loop")
        assert readiness["ok"] is True
        assert heartbeat is not None
        assert heartbeat["details"]["phase"] == "waiting_for_runtime_lock"
        assert heartbeat["details"]["dependency_lock"] == "gorelay_runtime"
        gorelay.runtime.lock.release()
        await asyncio.wait_for(refresh, timeout=1)

    asyncio.run(run())
    repo.close()


def test_policy_worker_retries_reconciliation_without_pending_outbox(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path / "state", policy_backup_enabled=True)
    repo = SqliteRepo(settings)
    service = PolicyBackupService(settings, repo)
    repo.set_policy_backup_reconciliation(True, error="synthetic clean-outbox failure")
    calls: list[int] = []

    async def fake_sync_now(*, force: bool = False) -> dict[str, object]:
        calls.append(1)
        repo.set_policy_backup_reconciliation(False)
        service._shutdown = True
        return {"ok": True, "force": force}

    service.sync_now = fake_sync_now  # type: ignore[method-assign]

    async def run() -> None:
        service._event = asyncio.Event()
        service._event.set()
        service._startup_ready = asyncio.Event()
        service._startup_ready.set()
        service._shutdown = False
        worker = asyncio.create_task(service._worker())
        await asyncio.wait_for(worker, timeout=3)

    asyncio.run(run())
    assert calls == [1]
    assert repo.get_policy_backup_state()["reconciliation_required"] is False
    repo.close()


def test_event_loop_emit_fatal_persists_off_loop_before_sending(
    tmp_path: Path,
) -> None:
    repo = SqliteRepo(_settings(tmp_path / "state"))
    lock_held = threading.Event()
    release_lock = threading.Event()
    sink_calls: list[dict[str, object]] = []

    def hold_repo_lock() -> None:
        with repo._lock:
            lock_held.set()
            release_lock.wait(timeout=3)

    lock_thread = threading.Thread(target=hold_repo_lock, name="runtime-receipt-lock")
    lock_thread.start()
    assert lock_held.wait(timeout=1)
    alerts = RuntimeAlertService(
        repo,
        sink=lambda payload: sink_calls.append(payload) or True,
        timeout_seconds=1,
    )

    async def run() -> None:
        started = time.monotonic()
        result = alerts.emit_fatal(
            "fake.worker",
            "event-loop persistence drill",
            details={"fixture": "persist-first"},
            incident_id="episode-1",
        )
        elapsed = time.monotonic() - started
        assert result["status"] == "pending"
        assert elapsed < 0.2
        ticks = 0
        while not sink_calls and ticks < 10:
            ticks += 1
            await asyncio.sleep(0.02)
        assert not sink_calls
        release_lock.set()
        for _ in range(100):
            if sink_calls:
                break
            await asyncio.sleep(0.01)
        assert sink_calls

    try:
        asyncio.run(run())
    finally:
        release_lock.set()
        lock_thread.join(timeout=2)
    receipt = repo.list_runtime_alert_receipts()[0]
    assert receipt["status"] == "sent"
    assert json.loads(str(receipt["payload_json"])) == sink_calls[0]
    repo.close()


def test_repeated_alert_emission_reuses_persisted_payload(
    tmp_path: Path,
) -> None:
    repo = SqliteRepo(_settings(tmp_path / "state"))
    delivered: list[dict[str, object]] = []
    healthy = False

    def sink(payload: dict[str, object]) -> bool:
        if healthy:
            delivered.append(payload)
            return True
        return False

    alerts = RuntimeAlertService(repo, sink=sink)
    first = alerts.emit_fatal(
        "fake.worker",
        "same alert",
        details={"episode_detail": "first"},
        incident_id="episode-1",
    )
    persisted = json.loads(str(first["payload_json"]))
    healthy = True
    second = alerts.emit_fatal(
        "fake.worker",
        "same alert",
        details={"episode_detail": "second"},
        incident_id="episode-1",
    )

    assert second["status"] == "sent"
    assert len(delivered) == 1
    assert delivered[0] == persisted
    assert delivered[0]["details"] == {"episode_detail": "first"}
    repo.close()
