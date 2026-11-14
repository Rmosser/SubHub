from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.middleware.lazycat_identity import install_lazycat_identity_middleware
from app.middleware.observability import install_observability_middleware
from app.services.egress_diagnostics import EgressDiagnostics
from app.services.field_cipher import FieldCipher
from app.routes.gorelay import router as gorelay_router
from app.routes.internal import router as internal_router
from app.routes.management import router as management_router
from app.routes.core import router as core_router
from app.routes.subscription import router as subscription_router
from app.routes.ui import router as ui_router
from app.routes.setup import router as setup_router
from app.services.core_facade import CoreFacade
from app.services.gorelay_service import GorelayService
from app.services.hub_service import HubService
from app.services.llm_workflow_service import LlmWorkflowService
from app.services.log_routing_workflow_service import LogRoutingWorkflowService
from app.services.policy_backup_service import PolicyBackupService
from app.services.review_service import ReviewService
from app.services.rule_catalog import RuleCatalog
from app.services.runtime_observability import (
    REQUIRED_RUNTIME_TASKS,
    RUNTIME_ALERT_RETRY_MAX_ITEMS,
    RUNTIME_ALERT_STARTUP_RETRY_DEADLINE_SECONDS,
    RuntimeAlertService,
    RuntimeTaskMonitor,
)
from app.services.source_fetcher import SourceFetcher
from app.services.tenant_registry import TenantRegistry
from app.storage.sqlite_repo import SqliteRepo


@dataclass
class Services:
    settings: Settings
    templates: Jinja2Templates
    repo: SqliteRepo
    rule_catalog: RuleCatalog
    source_fetcher: SourceFetcher
    egress_diagnostics: EgressDiagnostics
    gorelay_service: GorelayService
    hub_service: HubService
    policy_backup: PolicyBackupService
    llm_workflows: LlmWorkflowService
    log_routing_workflows: LogRoutingWorkflowService
    review_service: ReviewService
    core_facade: CoreFacade
    runtime_alerts: RuntimeAlertService
    runtime_monitor: RuntimeTaskMonitor


def _build_templates() -> Jinja2Templates:
    template_dir = Path(__file__).parent / "templates"
    return Jinja2Templates(directory=str(template_dir))


def _ensure_static_root() -> Path:
    static_root = Path(__file__).parent / "static"
    static_root.mkdir(parents=True, exist_ok=True)
    return static_root


def build_services(settings: Settings | None = None) -> Services:
    settings = settings or Settings.from_env()
    templates = _build_templates()
    cipher = FieldCipher(settings.field_cipher_key_path)
    repo = SqliteRepo(settings, cipher=cipher)
    runtime_alerts = RuntimeAlertService(
        repo,
        webhook_url=settings.runtime_alert_webhook_url,
        timeout_seconds=settings.runtime_alert_timeout_seconds,
    )
    runtime_monitor = RuntimeTaskMonitor(
        repo,
        stale_after_seconds=settings.runtime_heartbeat_stale_seconds,
        alerts=runtime_alerts,
    )
    rule_catalog = RuleCatalog(settings, repo)
    source_fetcher = SourceFetcher(settings)
    egress_diagnostics = EgressDiagnostics(settings)
    gorelay_service = GorelayService(settings, repo, runtime_monitor, runtime_alerts)
    hub_service = HubService(
        settings,
        repo,
        rule_catalog,
        source_fetcher,
        gorelay_service,
        runtime_monitor,
        runtime_alerts,
    )
    policy_backup = PolicyBackupService(settings, repo, runtime_monitor, runtime_alerts)
    repo.set_policy_backup_notifier(policy_backup.mark_dirty)
    llm_workflows = LlmWorkflowService(settings, repo, rule_catalog)
    review_service = ReviewService(settings, repo)
    core_facade = CoreFacade(
        settings=settings,
        repo=repo,
        rule_catalog=rule_catalog,
        hub_service=hub_service,
        egress_diagnostics=egress_diagnostics,
        gorelay_service=gorelay_service,
    )
    log_routing_workflows = LogRoutingWorkflowService(settings, repo, rule_catalog, core_facade)
    return Services(
        settings=settings,
        templates=templates,
        repo=repo,
        rule_catalog=rule_catalog,
        source_fetcher=source_fetcher,
        egress_diagnostics=egress_diagnostics,
        gorelay_service=gorelay_service,
        hub_service=hub_service,
        policy_backup=policy_backup,
        llm_workflows=llm_workflows,
        log_routing_workflows=log_routing_workflows,
        review_service=review_service,
        core_facade=core_facade,
        runtime_alerts=runtime_alerts,
        runtime_monitor=runtime_monitor,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await app.state.tenant_registry.start()
    # Tenant mode starts resident services per registered user.  The shared
    # runtime watchdog exists only for the local single-user service; an empty
    # app.state.services is expected before the first tenant is initialized.
    services = getattr(app.state, "services", None)
    if services is not None:
        # Alert receipts are durable; retry any delivery that was interrupted
        # by the previous process before resident workers begin new work.
        services.runtime_alerts.retry_pending(
            deadline_seconds=RUNTIME_ALERT_STARTUP_RETRY_DEADLINE_SECONDS,
            max_items=RUNTIME_ALERT_RETRY_MAX_ITEMS,
        )
        services.runtime_monitor.start_watchdog(
            REQUIRED_RUNTIME_TASKS,
            interval_seconds=services.settings.runtime_heartbeat_interval_seconds,
        )
    try:
        yield
    finally:
        if services is not None:
            await services.runtime_monitor.stop_watchdog()
        await app.state.tenant_registry.shutdown()

_settings = Settings.from_env()
app = FastAPI(title=_settings.app_name, version=_settings.app_version, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
install_lazycat_identity_middleware(app)
install_observability_middleware(app)
app.state.services = build_services() if not _settings.manage_api_require_login else None
app.state.tenant_registry = TenantRegistry(_settings, build_services, app.state.services)
_static_root = _ensure_static_root()
_frontend_dist_assets = _static_root / "frontend" / "dist" / "assets"
if _frontend_dist_assets.is_dir():
    app.mount(
        "/manage/assets",
        StaticFiles(directory=str(_frontend_dist_assets)),
        name="frontend-assets",
    )
app.mount(
    "/static",
    StaticFiles(directory=str(_static_root)),
    name="static",
)

app.include_router(ui_router)
app.include_router(setup_router)
app.include_router(subscription_router)
app.include_router(management_router)
app.include_router(core_router)
app.include_router(gorelay_router)
app.include_router(internal_router)
