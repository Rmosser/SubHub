import copy

import pytest

from app.models import RouteContract, StandardSource
from app.storage.sqlite_repo import SqliteRepo


def test_backup_round_trip_preserves_action_and_removed_presets(client):
    services = client.app.state.services
    repo = services.repo
    repo.delete_route_contract("direct")
    repo.delete_route_contract("bulk")
    repo.create_route_contract(RouteContract(id="custom-stop", display_name="拒绝出口", routing_action="reject", is_system=False))
    snapshot = services.policy_backup.export_snapshot()
    assert snapshot["manifest"]["schema_version"] == "subhub.policy-backup.v2"
    definitions = {item["id"]: item for item in snapshot["scenarios"]["default"]["contract_definitions"]}
    assert "direct" not in definitions and "bulk" not in definitions
    assert definitions["custom-stop"]["routing_action"] == "reject"
    repo.create_route_contract(RouteContract(id="extra", display_name="多余出口", primary_pools=["medium"], is_system=False))
    services.policy_backup._apply_snapshot(snapshot)
    assert {item.id for item in repo.list_route_contracts()} == set(definitions)
    assert repo.get_route_contract("custom-stop").routing_action == "reject"
    reloaded = SqliteRepo(repo.settings)
    assert {item.id for item in reloaded.list_route_contracts()} == set(definitions)
    reloaded._conn.close()


def test_empty_catalog_round_trip_stays_empty(client):
    services = client.app.state.services
    for contract in services.repo.list_route_contracts():
        services.repo.delete_route_contract(contract.id)
    snapshot = services.policy_backup.export_snapshot()
    assert snapshot["scenarios"]["default"]["contract_definitions"] == []
    services.repo.create_route_contract(RouteContract(id="extra", display_name="额外", primary_pools=["medium"], is_system=False))
    services.policy_backup._apply_snapshot(snapshot)
    assert services.repo.list_route_contracts() == []
    assert services.repo.list_scenario_route_contract_views("scenario-default") == []


def test_invalid_restore_rolls_back_entire_policy(client):
    services = client.app.state.services
    before = services.policy_backup.export_snapshot()
    damaged = copy.deepcopy(before)
    damaged["scenarios"]["default"]["contract_definitions"][0]["routing_action"] = "invalid"
    with pytest.raises(ValueError):
        services.policy_backup._apply_snapshot(damaged)
    after = services.policy_backup.export_snapshot()
    assert before["scenarios"] == after["scenarios"]
    assert before["global"] == after["global"]


def test_restore_refuses_to_orphan_source_and_keeps_catalog(client):
    services = client.app.state.services
    empty = services.policy_backup.export_snapshot()
    empty["scenarios"]["default"]["contract_definitions"] = []
    empty["scenarios"]["default"]["contract_views"] = []
    services.repo.save_standard_source(StandardSource(id="source", name="源", target_contract_id="medium"))
    with pytest.raises(ValueError, match="rebind before restoring"):
        services.policy_backup._apply_snapshot(empty)
    assert services.repo.get_route_contract("medium") is not None


@pytest.mark.parametrize("damage", ["missing-action", "disabled", "unusable-pool"])
def test_restore_rejects_missing_action_or_invalid_source_target(client, damage):
    services = client.app.state.services
    repo = services.repo
    repo.save_standard_source(StandardSource(id="source", name="源", target_contract_id="hq_premium"))
    snapshot = services.policy_backup.export_snapshot()
    before = copy.deepcopy(snapshot)
    definitions = snapshot["scenarios"]["default"]["contract_definitions"]
    contract = next(item for item in definitions if item["id"] == "hq_premium")
    if damage == "missing-action":
        contract.pop("routing_action")
    elif damage == "disabled":
        next(item for item in snapshot["scenarios"]["default"]["contract_views"] if item["contract_id"] == "hq_premium")["enabled"] = False
    else:
        contract["primary_pools"] = ["chain_home"]
    with pytest.raises(ValueError):
        services.policy_backup._apply_snapshot(snapshot)
    assert services.policy_backup.export_snapshot()["scenarios"] == before["scenarios"]


def test_mutation_during_sync_remains_dirty_for_next_backup(client, monkeypatch):
    from app.services.policy_backup_service import _GitSyncResult
    backup = client.app.state.services.policy_backup
    backup.mark_dirty("before-sync")
    def sync_with_mutation(*args, **kwargs):
        backup.repo.delete_route_contract("bulk")
        backup.mark_dirty("during-sync")
        return _GitSyncResult(ok=True, changed=True, commit_sha="abc")
    monkeypatch.setattr(backup.backend, "sync_files", sync_with_mutation)
    assert backup._sync_now_blocking(False)["ok"]
    assert backup.status().dirty is True
    assert "during-sync" in backup._reasons
    monkeypatch.setattr(backup.backend, "sync_files", lambda *args, **kwargs: _GitSyncResult(ok=True, changed=True, commit_sha="def"))
    assert backup._sync_now_blocking(False)["ok"]
    assert backup.status().dirty is False


def test_snapshot_read_is_consistent_during_concurrent_deletion(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    backup = client.app.state.services.policy_backup
    repo = backup.repo
    read_started, resume_read, mutation_done = Event(), Event(), Event()
    original = repo.list_scenarios
    def pause_after_first_read():
        scenarios = original()
        read_started.set()
        assert resume_read.wait(5)
        return scenarios
    def delete_contract():
        repo.delete_route_contract("bulk")
        mutation_done.set()
    monkeypatch.setattr(repo, "list_scenarios", pause_after_first_read)
    with ThreadPoolExecutor(max_workers=2) as workers:
        snapshot_future = workers.submit(backup.export_snapshot)
        assert read_started.wait(5)
        mutation_future = workers.submit(delete_contract)
        try:
            assert not mutation_done.wait(0.05)
        finally:
            resume_read.set()
        snapshot = snapshot_future.result(5)
        mutation_future.result(5)
    assert any(item["id"] == "bulk" for item in snapshot["scenarios"]["default"]["contract_definitions"])
    assert repo.get_route_contract("bulk") is None
