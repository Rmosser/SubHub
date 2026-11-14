from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FILE_MARKERS = {
    "test_intent_round2.py": ("unit",),
    "test_intent_round3.py": ("unit",),
    "test_intent_round4.py": ("unit",),
    "test_ci_pip_cache.py": ("unit",),
    "test_client_ui_replica.py": ("unit",),
    "test_configuration_intent.py": ("unit",),
    "test_contract_lifecycle_api.py": ("api",),
    "test_contract_lifecycle_rendering.py": ("unit",),
    "test_contract_lifecycle_repo.py": ("repo",),
    "test_contract_lifecycle_storage.py": ("repo",),
    "test_contract_lifecycle_backup.py": ("api",),
    "test_config_env.py": ("unit",),
    "test_package_docs.py": ("unit",),
    "test_cli_commands.py": ("unit",),
    "test_core_api.py": ("api",),
    "test_domain_binding_service.py": ("unit",),
    "test_docs_checks.py": ("unit",),
    "test_doc_sync_check.py": ("unit",),
    "test_evaluate_pr_state.py": ("unit",),
    "test_check_ready_to_merge.py": ("unit",),
    "test_plan_required_check.py": ("unit",),
    "test_egress_diagnostics.py": ("service",),
    "test_field_cipher.py": ("unit",),
    "test_gorelay_collector.py": ("service",),
    "test_gorelay_parser.py": ("unit",),
    "test_gorelay_service.py": ("service",),
    "test_http_client_lazycat.py": ("service",),
    "test_hub_service_new.py": ("service",),
    "test_i18n.py": ("unit",),
    "test_management_and_subscription_api_new.py": ("api",),
    "test_mihomo_capabilities.py": ("unit",),
    "test_node_naming.py": ("unit",),
    "test_normalize.py": ("unit",),
    "test_policy_backup_new.py": ("api",),
    "test_qr_decoder.py": ("unit",),
    "test_review_bundle.py": ("unit", "smoke"),
    "test_runtime_recovery.py": ("repo", "service"),
    "test_rule_catalog_new.py": ("service",),
    "test_shadowrocket_capabilities.py": ("service",),
    "test_skip_proxy_decomposer.py": ("unit",),
    "test_source_fetcher_new.py": ("service",),
    "test_sqlite_repo_new.py": ("repo",),
    "test_subscription_builder_new.py": ("unit",),
    "test_subscription_delivery_guards.py": ("unit",),
    "test_proxy_maintenance.py": ("unit",),
    "test_subscription_smoke.py": ("service", "smoke"),
    "test_surge_capabilities.py": ("unit",),
    "test_ui_shell.py": ("unit",),
    "test_api_contracts.py": ("api",),
    "test_api_devices_and_subscriptions.py": ("api",),
    "test_api_llm_workflows.py": ("api",),
    "test_api_profiles.py": ("api",),
    "test_api_sources.py": ("api",),
    "test_setup.py": ("api",),
    "test_tenant_isolation.py": ("api",),
    "test_pr_feedback.py": ("unit",),
    "test_run_repair_loop.py": ("unit",),
    "test_finalize_pr_repair.py": ("unit",),
    "test_session_registry.py": ("unit",),
    "test_secret_manifest.py": ("unit",),
    "test_resume_prompt_contract.py": ("unit",),
    "test_repair_loop_sacrificial.py": ("unit",),
    "test_phase2_state_store.py": ("unit",),
    "test_dispatch_pr_event.py": ("unit",),
    "test_process_pr_queue.py": ("unit",),
    "test_github_webhook_server.py": ("unit",),
    "test_run_event_auto_wake_experiment.py": ("unit",),
    "test_probe_loop_ready.py": ("unit",),
    "test_should_trigger_codex_review.py": ("unit",),
}

SMOKE_NODEIDS = {
    "tests/test_api_devices_and_subscriptions.py::test_device_clash_bundle_export_returns_zip_with_audit",
    "tests/test_api_devices_and_subscriptions.py::test_surge_blocked_endpoints_return_structured_409_when_referenced_contract_is_empty",
    "tests/test_cli_commands.py",
    "tests/test_review_bundle.py",
    "tests/test_subscription_smoke.py",
}

SLOW_NODEIDS = {
    "tests/test_api_devices_and_subscriptions.py::test_clash_preview_summary_includes_render_warnings",
    "tests/test_api_devices_and_subscriptions.py::test_clash_subscription_and_provider_cache_headers",
    "tests/test_api_devices_and_subscriptions.py::test_clash_subscription_cache_revision_changes_after_profile_update",
    "tests/test_api_devices_and_subscriptions.py::test_clash_subscription_supports_gzip",
    "tests/test_api_sources.py::test_standard_source_manual_pull_success_clears_expired_state",
    "tests/test_management_and_subscription_api_new.py::test_diagnostics_and_status_include_standard_source_config_fingerprints",
}

MOVED_NODEIDS = {
    "tests/test_management_and_subscription_api_new.py::test_update_gorelay_source_preserves_passwords_when_fields_missing",
    "tests/test_management_and_subscription_api_new.py::test_update_gorelay_source_preserves_passwords_when_fields_empty_string",
    "tests/test_management_and_subscription_api_new.py::test_gorelay_crawl_syncs_devices_for_management_api_without_global_refresh",
    "tests/test_management_and_subscription_api_new.py::test_gorelay_crawl_failure_keeps_saved_source_configuration",
    "tests/test_management_and_subscription_api_new.py::test_gorelay_sources_include_latest_refresh_status_and_active_version",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_accepts_high_quality_airport",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_accepts_target_contract_id",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_update_accepts_existing_disabled_target_contract",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_rejects_invalid_target_contract",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_rejects_invalid_source_mode",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_accepts_optional_surge_url",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_save_failure_returns_warning_payload",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_manual_pull_endpoint",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_warning_payloads_exposed_for_save_pull_and_list",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_filtered_technical_fields_exposed",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_manual_pull_404_for_missing_source",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_pull_network_mode_default_and_override",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_rejects_invalid_pull_network_mode",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_manual_pull_success_clears_expired_state",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_qr_asset_upload_get_list_image_delete",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_qr_asset_reupload_replaces_file",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_qr_asset_upload_decodes_and_backfills_url",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_qr_asset_upload_without_decoded_url_keeps_source_unchanged",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_qr_asset_rejects_invalid_field",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_qr_asset_rejects_invalid_file_and_size",
    "tests/test_management_and_subscription_api_new.py::test_standard_source_delete_cleans_qr_assets",
    "tests/test_management_and_subscription_api_new.py::test_list_standard_sources_reports_cached_node_count",
    "tests/test_management_and_subscription_api_new.py::test_gorelay_api_accounts_and_subscription_disable",
    "tests/test_management_and_subscription_api_new.py::test_gorelay_update_binding_triggers_rebuild",
    "tests/test_management_and_subscription_api_new.py::test_gorelay_pending_and_entries_split_other_usage_to_specific_bindings",
    "tests/test_management_and_subscription_api_new.py::test_delete_gorelay_source_deletes_fallback_account",
    "tests/test_management_and_subscription_api_new.py::test_llm_export_settings_api",
    "tests/test_management_and_subscription_api_new.py::test_llm_workflow_routing_endpoints",
    "tests/test_management_and_subscription_api_new.py::test_llm_workflow_grouping_preserves_stored_contract_and_supports_description",
    "tests/test_management_and_subscription_api_new.py::test_llm_workflow_directness_preserves_stored_contract",
    "tests/test_management_and_subscription_api_new.py::test_directness_review_endpoints",
    "tests/test_management_and_subscription_api_new.py::test_llm_workflow_routing_apply_supports_selected_change_ids",
    "tests/test_management_and_subscription_api_new.py::test_llm_workflow_grouping_apply_supports_selected_change_ids",
    "tests/test_management_and_subscription_api_new.py::test_rule_categories_fall_back_to_pin_group_when_service_catalog_group_is_empty",
    "tests/test_management_and_subscription_api_new.py::test_llm_workflow_grouping_export_falls_back_to_pin_group_when_service_catalog_group_is_empty",
    "tests/test_management_and_subscription_api_new.py::test_llm_workflow_grouping_apply_persists_after_repo_restart",
    "tests/test_management_and_subscription_api_new.py::test_llm_workflow_directness_apply_supports_selected_change_ids",
    "tests/test_management_and_subscription_api_new.py::test_llm_workflow_apply_rejects_invalid_selected_change_ids",
    "tests/test_management_and_subscription_api_new.py::test_log_routing_workflow_upload_export_preview_and_apply",
    "tests/test_management_and_subscription_api_new.py::test_log_routing_workflow_parses_surge_and_shadowrocket_fallback_only",
    "tests/test_management_and_subscription_api_new.py::test_log_routing_workflow_rejects_disallowed_action_and_unknown_route",
    "tests/test_management_and_subscription_api_new.py::test_clash_preview_summary_includes_render_warnings",
    "tests/test_management_and_subscription_api_new.py::test_preview_summary_surfaces_shared_rule_precedence_warnings",
    "tests/test_management_and_subscription_api_new.py::test_preview_summary_reports_protocol_diagnostics_buckets",
    "tests/test_management_and_subscription_api_new.py::test_lazycat_profile_settings_api_and_subscription_override",
    "tests/test_management_and_subscription_api_new.py::test_clash_provider_endpoint_applies_udp_defaults_and_explicit_override",
    "tests/test_management_and_subscription_api_new.py::test_legacy_subscription_urls_continue_to_use_default_scenario",
    "tests/test_management_and_subscription_api_new.py::test_devices_preview_summary_and_content_endpoints",
    "tests/test_management_and_subscription_api_new.py::test_preview_endpoints_accept_legacy_profile_query",
    "tests/test_management_and_subscription_api_new.py::test_preview_summary_reuses_cached_artifact",
    "tests/test_management_and_subscription_api_new.py::test_clash_subscription_and_provider_cache_headers",
    "tests/test_management_and_subscription_api_new.py::test_clash_subscription_cache_revision_changes_after_profile_update",
    "tests/test_management_and_subscription_api_new.py::test_clash_subscription_supports_gzip",
    "tests/test_management_and_subscription_api_new.py::test_disabled_device_preview_endpoints_return_409",
    "tests/test_management_and_subscription_api_new.py::test_device_clash_bundle_export_returns_zip_with_audit",
    "tests/test_management_and_subscription_api_new.py::test_surge_blocked_endpoints_return_structured_409_when_referenced_contract_is_empty",
    "tests/test_management_and_subscription_api_new.py::test_profile_capabilities_unsupported_support_kind_is_classified",
    "tests/test_management_and_subscription_api_new.py::test_profile_capabilities_unsupported_views_all_include_support_kind",
    "tests/test_management_and_subscription_api_new.py::test_profile_capabilities_views_include_editing_mode",
    "tests/test_management_and_subscription_api_new.py::test_profile_capabilities_shadowrocket_map_local_is_downgraded_with_intercept_only_diagnostics",
    "tests/test_management_and_subscription_api_new.py::test_profile_capabilities_shadowrocket_script_is_supported_and_standalone",
    "tests/test_management_and_subscription_api_new.py::test_profile_capabilities_expose_new_surge_native_runtime_and_mitm_fields",
    "tests/test_management_and_subscription_api_new.py::test_profile_capabilities_skip_proxy_clash_is_adapted_mode",
    "tests/test_management_and_subscription_api_new.py::test_profile_capabilities_shadowrocket_skip_proxy_is_supported_from_real_device_validation",
    "tests/test_management_and_subscription_api_new.py::test_preview_skip_proxy_decomposition_endpoint",
    "tests/test_management_and_subscription_api_new.py::test_preview_skip_proxy_decomposition_empty_patterns",
    "tests/test_management_and_subscription_api_new.py::test_profile_capabilities_syntax_hints_present_on_experimental_fields",
    "tests/test_management_and_subscription_api_new.py::test_legacy_business_group_process_rule_requires_rebind_when_catalog_is_mixed",
    "tests/test_management_and_subscription_api_new.py::test_rebind_in_non_default_scenario_does_not_modify_global_custom_rules",
    "tests/test_management_and_subscription_api_new.py::test_default_scenario_contract_disable_counts_scenario_process_rule_references",
    "tests/test_management_and_subscription_api_new.py::test_default_scenario_rebind_updates_scenario_service_catalog_and_process_rules",
}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    smoke_files = {Path(nodeid).name for nodeid in SMOKE_NODEIDS if "::" not in nodeid}
    missing: set[str] = set()
    kept: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        if item.nodeid in MOVED_NODEIDS:
            deselected.append(item)
            continue

        filename = Path(str(item.fspath)).name
        markers = FILE_MARKERS.get(filename)
        if markers is None:
            missing.add(filename)
            continue

        for marker_name in markers:
            item.add_marker(getattr(pytest.mark, marker_name))

        if item.nodeid in SLOW_NODEIDS:
            item.add_marker(pytest.mark.slow)

        if item.nodeid in SMOKE_NODEIDS or filename in smoke_files:
            item.add_marker(pytest.mark.smoke)

        kept.append(item)

    if missing:
        raise pytest.UsageError(
            "unclassified test files found; assign a layer marker in tests/conftest.py: "
            + ", ".join(sorted(missing))
        )

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "var"))
    monkeypatch.setenv("APP_BASE_URL", "http://testserver")
    monkeypatch.setenv("MANAGE_API_REQUIRE_LOGIN", "true")
    monkeypatch.setenv("GITHUB_API_BASE", "https://127.0.0.1/invalid")
    monkeypatch.setenv("GITHUB_RAW_BASE", "https://127.0.0.1/invalid")

    import app.main

    importlib.reload(app.main)
    app.main.app.state.services = app.main.app.state.tenant_registry.initialize("test-user")
    with TestClient(
        app.main.app,
        headers={
            "X-HC-User-ID": "test-user",
            "X-HC-User-Role": "owner",
            "X-HC-User-Name": "Test User",
        },
    ) as test_client:
        yield test_client
