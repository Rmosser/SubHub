from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.services.error_diagnostics import error_detail, safe_error_text
from app.storage.sqlite_repo import SqliteRepo

_logger = logging.getLogger("app.runtime_observability")

REQUIRED_RUNTIME_TASKS = (
    "gorelay.refresh_loop",
    "hub.refresh_loop",
    "hub.standard_source_loop",
    "policy_backup.worker",
)
RUNTIME_ALERT_STARTUP_RETRY_DEADLINE_SECONDS = 5.0
RUNTIME_ALERT_RETRY_MAX_ITEMS = 16
_PUBLIC_HEARTBEAT_FIELDS = (
    "task_name",
    "status",
    "required",
    "started_at",
    "heartbeat_at",
    "last_success_at",
    "consecutive_failures",
    "failure_episode",
)
_PUBLIC_HEARTBEAT_DETAIL_FIELDS = frozenset(
    {
        "phase",
        "unit",
        "dependency",
        "source_id",
        "account_id",
        "category",
        "remaining_seconds",
        "pending",
        "ok",
        "ambiguous",
        "lock_owner_task",
        "registered",
        "restarted",
        "startup_success",
        "stopped_at",
        "exit",
        "enabled",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class RuntimeAlertDeliveryError(RuntimeError):
    """A webhook response proves that the alert was not accepted."""


class RuntimeAlertDeliveryUnknown(RuntimeError):
    """The transport outcome is unknown and must be retried idempotently."""


class _HttpsOnlyRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        # urllib may rewrite POST to GET while following a redirect, which
        # would silently lose the body and idempotency headers.  Require the
        # configured receiver to be the final HTTPS URL instead.
        raise RuntimeAlertDeliveryError("alert webhook redirects are not supported")


class HttpsRuntimeAlertSink:
    """Small HTTPS JSON receiver with a stable idempotency header.

    The opener is injectable only so local tests can exercise request and
    response semantics without contacting a real alert service.
    """

    def __init__(
        self,
        webhook_url: str,
        *,
        timeout_seconds: int = 5,
        opener=None,  # type: ignore[no-untyped-def]
    ) -> None:
        normalized = str(webhook_url or "").strip()
        try:
            parsed = urlsplit(normalized)
            hostname = parsed.hostname
        except ValueError as exc:
            raise ValueError("RUNTIME_ALERT_WEBHOOK_URL must be a valid HTTPS URL") from exc
        if (
            parsed.scheme.lower() != "https"
            or not parsed.netloc
            or not hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("RUNTIME_ALERT_WEBHOOK_URL must be HTTPS without embedded credentials")
        self.webhook_url = normalized
        self.timeout_seconds = max(1, min(int(timeout_seconds or 5), 60))
        self._opener = opener or build_opener(_HttpsOnlyRedirectHandler())

    def __call__(self, payload: dict[str, object]) -> dict[str, object]:
        alert_key = str(payload.get("alert_key") or "").strip()
        if not alert_key:
            raise RuntimeAlertDeliveryError("runtime alert payload is missing alert_key")
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        request = Request(
            self.webhook_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Idempotency-Key": alert_key,
                "X-SubHub-Alert-Key": alert_key,
            },
            method="POST",
        )
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                status_value = getattr(response, "status", None)
                status_code = int(status_value if status_value is not None else response.getcode() or 0)
                response.read(4096)
        except HTTPError as exc:
            if int(exc.code or 0) >= 500:
                raise RuntimeAlertDeliveryUnknown(f"alert webhook returned HTTP {exc.code}") from exc
            raise RuntimeAlertDeliveryError(f"alert webhook returned HTTP {exc.code}") from exc
        except (TimeoutError, URLError, OSError) as exc:
            raise RuntimeAlertDeliveryUnknown("alert webhook transport outcome is unknown") from exc
        if 200 <= status_code < 300:
            return {"delivered": True, "status_code": status_code}
        if status_code >= 500:
            raise RuntimeAlertDeliveryUnknown(f"alert webhook returned HTTP {status_code}")
        raise RuntimeAlertDeliveryError(f"alert webhook returned HTTP {status_code}")


class RuntimeAlertService:
    """Durable fatal-alert receipts with an HTTPS or injected alert sink.

    Production wiring uses ``RUNTIME_ALERT_WEBHOOK_URL``.  Tests and local
    drills can inject a fake sink without contacting an external service.
    """

    def __init__(
        self,
        repo: SqliteRepo,
        sink: Callable[[dict[str, object]], object] | None = None,
        *,
        webhook_url: str = "",
        timeout_seconds: int = 5,
    ) -> None:
        self.repo = repo
        self.webhook_url = str(webhook_url or "").strip()
        self.timeout_seconds = max(1, min(int(timeout_seconds or 5), 60))
        self._injected_sink = sink is not None
        self._sink = sink or (
            HttpsRuntimeAlertSink(self.webhook_url, timeout_seconds=self.timeout_seconds)
            if self.webhook_url
            else self._logging_sink
        )
        self._delivery_lock = threading.Lock()
        # One owner per alert key across both the resident asyncio path and
        # the synchronous retry worker.  Without a shared lease, a watchdog
        # retry can race the initial delivery and overwrite a later ``sent``
        # receipt with its stale failure result.
        self._active_delivery_keys: set[str] = set()
        self._delivery_tasks: set[asyncio.Task[None]] = set()

    async def _run_in_daemon_thread(self, callback, *args, **kwargs):  # type: ignore[no-untyped-def]
        """Run a potentially blocking callback without owning the event loop.

        ``asyncio.to_thread`` uses the loop's shared executor.  Cancelling its
        awaitable does not stop the worker, and ``asyncio.run`` waits for that
        executor during shutdown.  Alert delivery and its receipt persistence
        are deliberately isolated in daemon threads instead: cancellation
        returns control immediately while the durable operation can still
        finish in the background.
        """
        outcome: list[tuple[bool, object]] = []
        completed = threading.Event()

        def invoke() -> None:
            try:
                outcome.append((True, callback(*args, **kwargs)))
            except BaseException as exc:
                outcome.append((False, exc))
            finally:
                completed.set()

        worker = threading.Thread(
            target=invoke,
            name="runtime-alert-daemon-work",
            daemon=True,
        )
        worker.start()
        while not completed.is_set():
            await asyncio.sleep(0.01)
        if not outcome:
            raise RuntimeAlertDeliveryUnknown("runtime alert daemon work produced no outcome")
        succeeded, value = outcome[0]
        if succeeded:
            return value
        if isinstance(value, Exception):
            raise value
        raise RuntimeAlertDeliveryUnknown("runtime alert daemon work stopped unexpectedly")

    def _deliver_with_timeout(
        self,
        payload: dict[str, object],
        *,
        timeout_seconds: float | None = None,
    ) -> object:
        """Run a sink with a bounded wait without blocking the resident loop.

        A transport call that outlives the wait may already have reached the
        receiver.  Callers therefore record ``unknown`` and retry with the
        same idempotency key instead of treating a timeout as proof of
        non-delivery.  The helper thread is daemonized because a stuck fake or
        network socket must never prevent process shutdown.
        """
        if timeout_seconds is None:
            return self._sink(payload)
        timeout = max(0.0, float(timeout_seconds))
        if timeout <= 0:
            raise RuntimeAlertDeliveryUnknown("runtime alert retry deadline exhausted")
        outcome: list[tuple[bool, object]] = []

        def invoke() -> None:
            try:
                outcome.append((True, self._sink(payload)))
            except BaseException as exc:  # keep sink failures inside the receipt path
                outcome.append((False, exc))

        worker = threading.Thread(
            target=invoke,
            name="runtime-alert-delivery",
            daemon=True,
        )
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            raise RuntimeAlertDeliveryUnknown("runtime alert delivery deadline exceeded")
        if not outcome:
            raise RuntimeAlertDeliveryUnknown("runtime alert delivery produced no outcome")
        succeeded, value = outcome[0]
        if not succeeded:
            if isinstance(value, Exception):
                raise value
            raise RuntimeAlertDeliveryUnknown("runtime alert sink stopped unexpectedly")
        return value

    @staticmethod
    def _logging_sink(payload: dict[str, object]) -> bool:
        _logger.error("fatal runtime alert (no external sink configured): %s", payload)
        return False

    @staticmethod
    def _require_delivery(delivered: object) -> None:
        if isinstance(delivered, dict) and delivered.get("delivered") is False:
            raise RuntimeError(str(delivered.get("reason") or "alert sink declined delivery"))
        if delivered is False:
            raise RuntimeError("alert sink declined delivery")

    @staticmethod
    def _payload_from_receipt(receipt: dict[str, object]) -> dict[str, object] | None:
        """Decode the exact body persisted for a durable alert receipt."""
        try:
            payload = json.loads(str(receipt.get("payload_json") or ""))
        except (TypeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    async def _persist_delivery_result(
        self,
        alert_key: str,
        *,
        status: str,
        last_error: str = "",
    ) -> None:
        try:
            await self._run_in_daemon_thread(
                self.repo.update_runtime_alert_receipt,
                alert_key,
                status=status,
                last_error=last_error,
            )
        except Exception as exc:
            _logger.error("runtime alert receipt update failed: %s", exc)

    async def _deliver_async(
        self,
        alert_key: str,
        payload: dict[str, object],
        *,
        persist_first: bool = False,
    ) -> None:
        """Deliver from a daemon worker so an alert cannot freeze the loop.

        The sink is deliberately not submitted to asyncio's shared default
        executor.  A transport that ignores its timeout (or a fake sink in a
        fault drill) must not keep ``asyncio.run`` shutdown or unrelated
        ``to_thread`` work waiting for that executor's worker.
        """
        if persist_first:
            try:
                receipt = await self._run_in_daemon_thread(
                    self.repo.create_runtime_alert_receipt,
                    alert_key,
                    task_name=str(payload.get("task_name") or "runtime"),
                    message=str(payload.get("message") or "runtime alert"),
                    payload=payload,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _logger.error("fatal runtime alert receipt persistence failed: %s", exc)
                return
            if not isinstance(receipt, dict):
                _logger.error("fatal runtime alert receipt persistence returned invalid data")
                return
            if str(receipt.get("status") or "") == "sent":
                return
            persisted_payload = self._payload_from_receipt(receipt)
            if persisted_payload is None:
                await self._persist_delivery_result(
                    alert_key,
                    status="failed",
                    last_error="persisted runtime alert payload is invalid",
                )
                return
            payload = persisted_payload
        outcome: list[tuple[bool, object]] = []
        completed = threading.Event()

        def invoke() -> None:
            try:
                outcome.append((True, self._sink(payload)))
            except BaseException as exc:  # keep sink failures inside the receipt path
                outcome.append((False, exc))
            finally:
                completed.set()

        worker = threading.Thread(
            target=invoke,
            name="runtime-alert-async-delivery",
            daemon=True,
        )
        worker.start()
        try:
            deadline = time.monotonic() + self.timeout_seconds
            while not completed.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeAlertDeliveryUnknown("runtime alert delivery timed out")
                await asyncio.sleep(min(0.02, remaining))
            if not outcome:
                raise RuntimeAlertDeliveryUnknown("runtime alert delivery produced no outcome")
            succeeded, delivered = outcome[0]
            if not succeeded:
                if isinstance(delivered, Exception):
                    raise delivered
                raise RuntimeAlertDeliveryUnknown("runtime alert sink stopped unexpectedly")
            self._require_delivery(delivered)
        except asyncio.CancelledError:
            # Keep the receipt pending for the next retry when the process is
            # shutting down or the task is explicitly cancelled.
            raise
        except asyncio.TimeoutError:
            detail = error_detail(
                RuntimeAlertDeliveryUnknown("runtime alert delivery timed out"),
                "runtime_fatal_alert",
                alert_key,
            )
            await self._persist_delivery_result(
                alert_key,
                status="unknown",
                last_error=str(detail["message"]),
            )
        except Exception as exc:
            detail = error_detail(exc, "runtime_fatal_alert", alert_key)
            _logger.error("fatal runtime alert delivery failed: %s", detail)
            status = "unknown" if isinstance(exc, RuntimeAlertDeliveryUnknown) else "failed"
            await self._persist_delivery_result(
                alert_key,
                status=status,
                last_error=str(detail["message"]),
            )
        else:
            await self._persist_delivery_result(alert_key, status="sent")

    def _delivery_task_done(self, alert_key: str, task: asyncio.Task[None]) -> None:
        self._delivery_tasks.discard(task)
        self._release_delivery(alert_key)
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            _logger.error("runtime alert async delivery task failed: %s", exc)

    def _claim_delivery(self, alert_key: str) -> bool:
        with self._delivery_lock:
            if alert_key in self._active_delivery_keys:
                return False
            self._active_delivery_keys.add(alert_key)
            return True

    def _release_delivery(self, alert_key: str) -> None:
        with self._delivery_lock:
            self._active_delivery_keys.discard(alert_key)

    def _schedule_async_delivery(
        self,
        alert_key: str,
        payload: dict[str, object],
        *,
        persist_first: bool = False,
    ) -> bool:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        # ``True`` also means an existing synchronous retry owns the key; the
        # caller must not fall through into a second synchronous send.
        if not self._claim_delivery(alert_key):
            return True
        try:
            task = loop.create_task(
                self._deliver_async(alert_key, payload, persist_first=persist_first)
            )
        except Exception:
            self._release_delivery(alert_key)
            raise
        self._delivery_tasks.add(task)
        task.add_done_callback(
            lambda completed, key=alert_key: self._delivery_task_done(key, completed)
        )
        return True

    async def retry_pending_async(
        self,
        *,
        deadline_seconds: float | None = None,
        max_items: int | None = None,
    ) -> list[dict[str, object]]:
        """Retry receipts in a shutdown-independent daemon worker.

        ``retry_pending`` intentionally remains synchronous for callers that
        need a direct result.  Resident watchdogs must use this async wrapper
        so a slow transport cannot strand the event loop's default executor
        during shutdown.
        """
        return await self._run_in_daemon_thread(
            self.retry_pending,
            deadline_seconds=deadline_seconds,
            max_items=max_items,
        )

    def set_sink(self, sink: Callable[[dict[str, object]], object] | None) -> None:
        self._injected_sink = sink is not None
        self._sink = sink or (
            HttpsRuntimeAlertSink(self.webhook_url, timeout_seconds=self.timeout_seconds)
            if self.webhook_url
            else self._logging_sink
        )

    @staticmethod
    def _alert_key(
        task_name: str,
        message: str,
        details: dict[str, object],
        incident_id: str = "",
    ) -> str:
        # Error diagnostics contain a fresh correlation id and stack on every
        # attempt.  They belong in the receipt payload, not in its identity;
        # otherwise one stuck worker would create an unbounded alert stream.
        stable = json.dumps(
            {"task_name": task_name, "message": message, "incident_id": incident_id},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"fatal:{task_name}:{hashlib.sha256(stable.encode('utf-8')).hexdigest()}"

    def readiness(self) -> dict[str, object]:
        """Expose whether the configured runtime can actively notify an operator."""
        if self._injected_sink:
            return {
                "ok": True,
                "configured": True,
                "capable": True,
                "transport": "injected",
                "timeout_seconds": self.timeout_seconds,
            }
        if self.webhook_url:
            return {
                "ok": True,
                "configured": True,
                "capable": True,
                "transport": "https",
                "timeout_seconds": self.timeout_seconds,
            }
        return {
            "ok": False,
            "configured": False,
            "capable": False,
            "transport": "none",
            "timeout_seconds": self.timeout_seconds,
            "reason": "RUNTIME_ALERT_WEBHOOK_URL is not configured",
        }

    def emit_fatal(
        self,
        task_name: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
        incident_id: str = "",
    ) -> dict[str, object]:
        safe_task = str(task_name or "runtime").strip()[:100]
        safe_message = safe_error_text(message, 1000)
        safe_details = dict(details or {})
        safe_incident_id = str(incident_id or "").strip()[:200]
        key = self._alert_key(safe_task, safe_message, safe_details, safe_incident_id)
        payload = {
            "alert_key": key,
            "task_name": safe_task,
            "severity": "fatal",
            "message": safe_message,
            "details": safe_details,
            "incident_id": safe_incident_id,
            "created_at": _now(),
        }

        # Receipt creation itself is SQLite I/O and can wait behind a writer
        # transaction.  Never perform it synchronously from an event-loop
        # caller: claim the key and let the async delivery task persist first,
        # then send the exact row it read back from SQLite.
        if self._schedule_async_delivery(key, payload, persist_first=True):
            return {"alert_key": key, "status": "pending"}

        try:
            receipt = self.repo.create_runtime_alert_receipt(
                key,
                task_name=safe_task,
                message=safe_message,
                payload=payload,
            )
        except Exception as exc:
            detail = error_detail(exc, "runtime_fatal_alert_receipt", key)
            _logger.error("fatal runtime alert receipt persistence failed: %s", detail)
            return {
                "alert_key": key,
                "status": "unknown",
                "last_error": str(detail["message"]),
            }
        if str(receipt.get("status") or "") == "sent":
            return receipt

        persisted_payload = self._payload_from_receipt(receipt)
        if persisted_payload is None:
            try:
                return self.repo.update_runtime_alert_receipt(
                    key,
                    status="failed",
                    last_error="persisted runtime alert payload is invalid",
                ) or receipt
            except Exception as exc:
                _logger.error("runtime alert invalid payload receipt update failed: %s", exc)
                return receipt
        payload = persisted_payload

        # Resident failures are reported from the asyncio event loop.  Store
        # the receipt synchronously, then hand the network wait to a task that
        # executes the sink in a worker thread; the loop keeps heartbeating.
        if self._schedule_async_delivery(key, payload):
            return receipt

        # Calls made by non-asyncio threads still share the same ownership
        # set as retry_pending(); only one delivery may mutate a receipt.
        if not self._claim_delivery(key):
            return receipt

        try:
            try:
                delivered = self._deliver_with_timeout(payload, timeout_seconds=self.timeout_seconds)
                self._require_delivery(delivered)
            except Exception as exc:
                detail = error_detail(exc, "runtime_fatal_alert", receipt.get("alert_id", key))
                _logger.error("fatal runtime alert delivery failed: %s", detail)
                try:
                    status = "unknown" if isinstance(exc, RuntimeAlertDeliveryUnknown) else "failed"
                    return self.repo.update_runtime_alert_receipt(
                        key,
                        status=status,
                        last_error=str(detail["message"]),
                    ) or receipt
                except Exception as persist_exc:
                    _logger.error("fatal runtime alert failure receipt persistence failed: %s", persist_exc)
                    return receipt
            try:
                return self.repo.update_runtime_alert_receipt(key, status="sent") or receipt
            except Exception as exc:
                _logger.error("fatal runtime alert success receipt persistence failed: %s", exc)
                return receipt
        finally:
            self._release_delivery(key)

    def retry_pending(
        self,
        *,
        deadline_seconds: float | None = None,
        max_items: int | None = None,
    ) -> list[dict[str, object]]:
        """Retry durable obligations within an optional global budget.

        Startup and watchdog callers pass a deadline and item cap.  Rows not
        reached before either bound remain pending/unknown in SQLite and are
        eligible for the next watchdog cycle.  The default is retained for
        administrative callers that explicitly want to drain the table.
        """
        results: list[dict[str, object]] = []
        if not bool(self.readiness().get("capable")):
            return results
        started = time.monotonic()
        item_limit = None if max_items is None else max(0, int(max_items))
        try:
            receipts = self.repo.list_runtime_alert_receipts()
        except Exception as exc:
            _logger.error("pending runtime alert receipt lookup failed: %s", exc)
            return results
        # Retry the oldest obligation first.  Sorting by newest ``updated_at``
        # would keep refreshing the same capped batch and starve older
        # receipts whenever delivery keeps failing.
        receipts.sort(
            key=lambda item: (
                str(item.get("updated_at") or ""),
                str(item.get("alert_key") or ""),
            )
        )
        for receipt in receipts:
            if str(receipt.get("status") or "") not in {"pending", "failed", "unknown"}:
                continue
            if item_limit is not None and len(results) >= item_limit:
                break
            remaining: float | None = None
            if deadline_seconds is not None:
                remaining = float(deadline_seconds) - (time.monotonic() - started)
                if remaining <= 0:
                    break
            key = str(receipt.get("alert_key") or "")
            if not self._claim_delivery(key):
                continue
            try:
                latest = self.repo.get_runtime_alert_receipt(key)
                if latest and str(latest.get("status") or "") == "sent":
                    continue
                payload = self._payload_from_receipt(receipt)
                if payload is None:
                    raise RuntimeAlertDeliveryError(
                        "persisted runtime alert payload is invalid"
                    )
                delivered = self._deliver_with_timeout(payload, timeout_seconds=remaining)
                self._require_delivery(delivered)
            except Exception as exc:
                detail = error_detail(exc, "runtime_fatal_alert_retry", str(receipt.get("alert_id") or key))
                try:
                    status = "unknown" if isinstance(exc, RuntimeAlertDeliveryUnknown) else "failed"
                    updated = self.repo.update_runtime_alert_receipt(
                        key,
                        status=status,
                        last_error=str(detail["message"]),
                    )
                except Exception as persist_exc:
                    _logger.error("runtime alert retry failure receipt persistence failed: %s", persist_exc)
                    updated = None
                results.append(updated or receipt)
            else:
                try:
                    updated = self.repo.update_runtime_alert_receipt(key, status="sent")
                except Exception as exc:
                    _logger.error("runtime alert retry success receipt persistence failed: %s", exc)
                    updated = None
                results.append(updated or receipt)
            finally:
                self._release_delivery(key)
        return results


class RuntimeTaskMonitor:
    """SQLite-backed liveness/readiness for resident service tasks."""

    def __init__(
        self,
        repo: SqliteRepo,
        *,
        stale_after_seconds: int = 90,
        alerts: RuntimeAlertService | None = None,
    ) -> None:
        self.repo = repo
        self.stale_after_seconds = max(10, int(stale_after_seconds or 90))
        self.alerts = alerts
        self._expected_stops: set[str] = set()
        # A registration starts a new process episode.  Keep the previous
        # failure visible until the task proves that it started; this map lets
        # ``startup_success`` distinguish that old failure from one recorded
        # by the new task while it was starting.
        self._startup_baselines: dict[str, tuple[int, int]] = {}
        self._watchdog_task: asyncio.Task[None] | None = None
        self._watchdog_stop: asyncio.Event | None = None

    def _persist(self, task_name: str, **kwargs: object) -> dict[str, object]:
        try:
            return self.repo.upsert_runtime_heartbeat(  # type: ignore[arg-type]
                task_name,
                busy_timeout_ms=0,
                **kwargs,
            )
        except Exception as exc:
            detail = error_detail(exc, "runtime_heartbeat_persist", task_name)
            _logger.error("runtime heartbeat persistence failed: %s", detail)
            return {
                "task_name": task_name,
                "status": "unknown",
                "persistence_error": str(detail["message"]),
            }

    def register(
        self,
        task_name: str,
        *,
        required: bool = True,
        startup_success: bool = False,
    ) -> dict[str, object]:
        safe_name = str(task_name or "").strip()
        if not safe_name:
            raise ValueError("task_name is required")
        try:
            existing = self.repo.get_runtime_heartbeat(safe_name)
        except Exception as exc:
            _logger.error("runtime heartbeat lookup failed for %s: %s", safe_name, exc)
            existing = None
        baseline = (
            int(existing.get("consecutive_failures") or 0) if existing else 0,
            int(existing.get("failure_episode") or 0) if existing else 0,
        )
        self._startup_baselines[safe_name] = baseline
        result = self._persist(
            safe_name,
            # Do not claim readiness until the owning service has actually
            # created/started its resident task and calls startup_success.
            status="starting",
            required=required,
            started_at=_now(),
            heartbeat_at=_now(),
            last_success_at=str(existing.get("last_success_at") or "") if existing else None,
            last_error=str(existing.get("last_error") or "") if existing else "",
            consecutive_failures=int(existing.get("consecutive_failures") or 0) if existing else 0,
            failure_episode=int(existing.get("failure_episode") or 0) if existing else 0,
            details={"registered": True, "restarted": bool(existing)},
        )
        if startup_success:
            return self.startup_success(safe_name)
        return result

    def startup_success(
        self,
        task_name: str,
        *,
        details: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Mark a newly registered task ready without hiding a new failure.

        A prior process may have left a degraded heartbeat.  Registration
        keeps that evidence durable, while this explicit transition clears it
        once the new task is known to be alive.  If a failure was recorded
        after registration, return it unchanged so startup bookkeeping cannot
        overwrite the current incident.
        """
        safe_name = str(task_name or "").strip()
        if not safe_name:
            raise ValueError("task_name is required")
        try:
            existing = self.repo.get_runtime_heartbeat(safe_name)
        except Exception as exc:
            _logger.error("runtime heartbeat lookup failed for %s: %s", safe_name, exc)
            existing = None
        if existing is None:
            self._startup_baselines.pop(safe_name, None)
            return self._persist(
                safe_name,
                status="running",
                required=True,
                heartbeat_at=_now(),
                last_success_at=_now(),
                last_error="",
                consecutive_failures=0,
                failure_episode=0,
                details=details or {"startup_success": True},
            )
        current = (
            int(existing.get("consecutive_failures") or 0),
            int(existing.get("failure_episode") or 0),
        )
        baseline = self._startup_baselines.pop(safe_name, None)
        if (
            (baseline is None and (current[0] > 0 or current[1] > 0))
            or (baseline is not None and current != baseline)
        ):
            return existing
        return self._persist(
            safe_name,
            status="running",
            required=bool(existing.get("required", True)),
            started_at=str(existing.get("started_at") or "") or None,
            heartbeat_at=_now(),
            last_success_at=_now(),
            last_error="",
            consecutive_failures=0,
            # Keep the episode counter monotonic for the next failure's
            # idempotency identity even though the current count is cleared.
            failure_episode=current[1],
            details=details or {"startup_success": True},
        )

    def heartbeat(
        self,
        task_name: str,
        *,
        status: str = "running",
        required: bool | None = None,
        details: dict[str, object] | None = None,
    ) -> dict[str, object]:
        try:
            existing = self.repo.get_runtime_heartbeat(task_name)
        except Exception as exc:
            _logger.error("runtime heartbeat lookup failed for %s: %s", task_name, exc)
            existing = None
        heartbeat_required = (
            bool(existing.get("required", True))
            if required is None and existing
            else bool(required)
            if required is not None
            else True
        )
        return self._persist(
            task_name,
            status=status,
            required=heartbeat_required,
            started_at=str(existing.get("started_at") or "") if existing else None,
            heartbeat_at=_now(),
            last_success_at=str(existing.get("last_success_at") or "") if existing else None,
            last_error=str(existing.get("last_error") or "") if existing else "",
            consecutive_failures=int(existing.get("consecutive_failures") or 0) if existing else 0,
            failure_episode=int(existing.get("failure_episode") or 0) if existing else 0,
            details=details,
        )

    def success(self, task_name: str, *, details: dict[str, object] | None = None) -> dict[str, object]:
        try:
            existing = self.repo.get_runtime_heartbeat(task_name)
        except Exception as exc:
            _logger.error("runtime heartbeat lookup failed for %s: %s", task_name, exc)
            existing = None
        return self._persist(
            task_name,
            status="running",
            required=bool((existing or {}).get("required", True)),
            heartbeat_at=_now(),
            last_success_at=_now(),
            last_error="",
            consecutive_failures=0,
            failure_episode=int((existing or {}).get("failure_episode") or 0),
            details=details,
        )

    def failure(
        self,
        task_name: str,
        message: str,
        *,
        details: dict[str, object] | None = None,
        fatal: bool = True,
    ) -> dict[str, object]:
        try:
            existing = self.repo.get_runtime_heartbeat(task_name)
        except Exception as exc:
            _logger.error("runtime heartbeat lookup failed for %s: %s", task_name, exc)
            existing = None
        previous_failures = int(existing.get("consecutive_failures") or 0) if existing else 0
        count = previous_failures + 1
        previous_episode = int(existing.get("failure_episode") or 0) if existing else 0
        episode = previous_episode + (1 if previous_failures == 0 else 0)
        payload = dict(details or {})
        payload["fatal"] = fatal
        payload["failure_episode"] = episode
        result = self._persist(
            task_name,
            status="degraded",
            required=bool(existing.get("required", True)) if existing else True,
            started_at=str(existing.get("started_at") or "") if existing else None,
            heartbeat_at=_now(),
            last_success_at=str(existing.get("last_success_at") or "") if existing else None,
            last_error=safe_error_text(message, 500),
            consecutive_failures=count,
            failure_episode=episode,
            details=payload,
        )
        if fatal and self.alerts:
            try:
                self.alerts.emit_fatal(
                    task_name,
                    message,
                    details=payload,
                    incident_id=f"failure-episode:{episode}",
                )
            except Exception as exc:
                _logger.error("fatal runtime alert emission failed: %s", exc)
        return result

    def stopped(self, task_name: str) -> dict[str, object]:
        return self.heartbeat(task_name, status="stopped", details={"stopped_at": _now()})

    def expect_stop(self, task_name: str) -> None:
        self._expected_stops.add(str(task_name or "").strip())

    def watch(self, task_name: str, task: asyncio.Task[object]) -> None:
        safe_name = str(task_name or "").strip()
        self._expected_stops.discard(safe_name)
        task.add_done_callback(lambda completed: self._task_done(safe_name, completed))

    def _task_done(self, task_name: str, task: asyncio.Task[object]) -> None:
        if task_name in self._expected_stops:
            self._expected_stops.discard(task_name)
            return
        if task.cancelled():
            self.failure(
                task_name,
                f"resident task {task_name} was cancelled unexpectedly",
                details={"exit": "cancelled"},
            )
            return
        try:
            failure = task.exception()
        except Exception as exc:
            failure = exc
        if failure is None:
            self.failure(
                task_name,
                f"resident task {task_name} exited unexpectedly",
                details={"exit": "returned"},
            )
            return
        self.failure(
            task_name,
            f"resident task {task_name} exited unexpectedly",
            details=error_detail(failure, "runtime_task_exit", task_name),
        )

    def start_watchdog(
        self,
        required_tasks: list[str] | tuple[str, ...],
        *,
        interval_seconds: int = 30,
    ) -> None:
        if self._watchdog_task and not self._watchdog_task.done():
            return
        stop = asyncio.Event()
        self._watchdog_stop = stop
        interval = max(1, int(interval_seconds or 30))
        task_names = tuple(str(item) for item in required_tasks)
        self._watchdog_task = asyncio.create_task(
            self._watchdog_loop(task_names, stop, interval),
            name="runtime-readiness-watchdog",
        )

    async def _watchdog_loop(
        self,
        required_tasks: tuple[str, ...],
        stop: asyncio.Event,
        interval_seconds: int,
    ) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                try:
                    self.readiness(required_tasks)
                except Exception as exc:
                    _logger.error("runtime readiness watchdog check failed: %s", exc)
                try:
                    alerts_capable = bool(self.alerts and self.alerts.readiness().get("capable"))
                except Exception as exc:
                    _logger.error("runtime alert capability check failed: %s", exc)
                    alerts_capable = False
                if alerts_capable and self.alerts:
                    try:
                        await self.alerts.retry_pending_async(
                            # The retry call is globally bounded by the
                            # configured transport timeout.  A hard-coded
                            # one-second budget could mark a receiver that
                            # succeeds within its configured timeout as
                            # UNKNOWN forever on every watchdog cycle.
                            deadline_seconds=float(self.alerts.timeout_seconds),
                            max_items=RUNTIME_ALERT_RETRY_MAX_ITEMS,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        _logger.error("runtime alert watchdog retry failed: %s", exc)
            except asyncio.CancelledError:
                raise

    async def stop_watchdog(self) -> None:
        task = self._watchdog_task
        self._watchdog_task = None
        if self._watchdog_stop:
            self._watchdog_stop.set()
        self._watchdog_stop = None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def snapshot(self) -> list[dict[str, object]]:
        return self.repo.list_runtime_heartbeats()

    @staticmethod
    def _public_heartbeat(item: dict[str, object]) -> dict[str, object]:
        """Project a heartbeat for the anonymous health endpoint.

        The authenticated readiness/management paths retain the raw error and
        detail fields.  Public probes receive only a fixed allowlist and a
        boolean error signal; arbitrary exception messages can contain Git
        URLs, credentials, local paths, or stack details.
        """
        public = {key: item.get(key) for key in _PUBLIC_HEARTBEAT_FIELDS}
        raw_details = item.get("details")
        public_details: dict[str, object] = {}
        if isinstance(raw_details, dict):
            for key in _PUBLIC_HEARTBEAT_DETAIL_FIELDS:
                value = raw_details.get(key)
                if value is None:
                    continue
                if isinstance(value, str):
                    if len(value) <= 160:
                        public_details[key] = value
                elif isinstance(value, (bool, int, float)):
                    public_details[key] = value
        public["details"] = public_details
        public["has_error"] = bool(item.get("last_error")) or bool(
            isinstance(raw_details, dict) and (raw_details.get("error") or raw_details.get("error_detail"))
        )
        return public

    def public_snapshot(self) -> list[dict[str, object]]:
        return [self._public_heartbeat(item) for item in self.snapshot()]

    def readiness(self, required_tasks: list[str] | tuple[str, ...]) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        try:
            by_name = {str(item.get("task_name")): item for item in self.snapshot()}
        except Exception as exc:
            _logger.error("runtime heartbeat readiness lookup failed: %s", exc)
            return {
                "ok": False,
                "stale_after_seconds": self.stale_after_seconds,
                "error": safe_error_text(exc, 500),
                "tasks": {},
            }
        checks: dict[str, dict[str, object]] = {}
        ready = True
        for task_name in required_tasks:
            item = by_name.get(task_name)
            reason = ""
            age_seconds: float | None = None
            if not item:
                reason = "missing heartbeat"
            else:
                heartbeat_at = _parse_time(item.get("heartbeat_at"))
                if heartbeat_at is None:
                    reason = "invalid heartbeat timestamp"
                else:
                    age_seconds = max(0.0, (now - heartbeat_at).total_seconds())
                    if age_seconds > self.stale_after_seconds:
                        reason = "stale heartbeat"
                    elif str(item.get("status") or "") not in {"running", "idle"}:
                        reason = f"task status is {item.get('status')}"
                    elif int(item.get("consecutive_failures") or 0) > 0:
                        reason = "task has unresolved failures"
            check = {
                "ok": not reason,
                "task_name": task_name,
                "age_seconds": round(age_seconds, 2) if age_seconds is not None else None,
                "reason": reason,
                "heartbeat": item,
            }
            checks[task_name] = check
            if reason:
                ready = False
                if self.alerts and reason in {"stale heartbeat", "missing heartbeat"}:
                    try:
                        if item and int(item.get("consecutive_failures") or 0) > 0:
                            heartbeat_identity = f"failure-episode:{int(item.get('failure_episode') or 0)}"
                        else:
                            heartbeat_identity = str(item.get("heartbeat_at") or "missing") if item else "missing"
                        self.alerts.emit_fatal(
                            task_name,
                            f"runtime task {task_name} is not ready: {reason}",
                            details={"reason": reason},
                            incident_id=f"heartbeat:{heartbeat_identity}",
                        )
                    except Exception as exc:
                        _logger.error("runtime readiness alert emission failed: %s", exc)
        return {"ok": ready, "stale_after_seconds": self.stale_after_seconds, "tasks": checks}


class NullRuntimeTaskMonitor:
    """Compatibility no-op for unit tests that construct services directly."""

    def register(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

    def heartbeat(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

    def startup_success(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

    def success(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

    def failure(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

    def stopped(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        return {}

    def expect_stop(self, *_args: object, **_kwargs: object) -> None:
        return None

    def watch(self, *_args: object, **_kwargs: object) -> None:
        return None

    def start_watchdog(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def stop_watchdog(self, *_args: object, **_kwargs: object) -> None:
        return None

    def readiness(self, *_args: object, **_kwargs: object) -> dict[str, object]:
        return {"ok": True, "tasks": {}}

    def public_snapshot(self) -> list[dict[str, object]]:
        return []
