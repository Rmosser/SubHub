import assert from "node:assert/strict";
import test from "node:test";
import { editableTableReducer, initialEditableTableState } from "../src/components/editableTableState";
import { PROCESS_RULE_TYPES, validateExternalProxyPrograms, validateProcessRules } from "../src/pages/Advanced/formValidation";
import { resolvePullMode, validateStandardSourceDraft } from "../src/pages/Sources/sourceForm";
import { parseExternalProxyProgramListResponse, parseProcessRuleListResponse } from "../src/api/validators/advanced";
import { apiErrorDetail } from "../src/api/validators/error";
import { apiPost, ApiError } from "../src/api/client";
import { workspaceScopeKey } from "../src/utils/workspaceScope";
import { integerDraftValue, settingsErrors } from "../src/components/settingsValidation";
import { parseJsonObject } from "../src/api/validators/json";
import { parseSetupStatus } from "../src/api/validators/setup";
import { canApplyRestore } from "../src/pages/Advanced/restoreState";
import { parsePolicyRestorePreview } from "../src/api/validators/policyBackup";
import { scenarioCreateRequestToken, withoutScenarioCreateRequest } from "../src/pages/Profile/scenarioNavigation";
import type { ExternalProxyProgramTemplate, ProcessRuleTemplate } from "../src/types";

const processRule: ProcessRuleTemplate = {
  id: "rule-1", match_type: "PROCESS-NAME", value: "Safari", contract_id: "medium", contract_display_name: "Medium",
  business_group: "Medium", sort_order: 1, enabled: true, needs_rebind: false, migration_warning: "",
};
const externalProgram: ExternalProxyProgramTemplate = {
  id: "program-1", name: "Local proxy", program_path: "/usr/bin/proxy", args: ["--config", "/a path/config.json"],
  local_port: 17890, contract_id: "medium", contract_display_name: "Medium", business_group: "Medium",
  sort_order: 1, enabled: true, needs_rebind: false, migration_warning: "",
};

test("an asynchronous table save keeps the draft through readback and failure, then allows retry", () => {
  const server = [processRule];
  const draft = [{ ...processRule, value: "Firefox" }];
  let state = initialEditableTableState(server);
  state = editableTableReducer(state, { type: "edit", items: draft });
  state = editableTableReducer(state, { type: "saving" });
  assert.equal(state.dirty, true);
  assert.equal(state.saving, true);
  state = editableTableReducer(state, { type: "server", items: [...server] });
  assert.deepEqual(state.items, draft);
  state = editableTableReducer(state, { type: "failed", error: "Gateway unavailable" });
  assert.deepEqual(state.items, draft);
  assert.equal(state.dirty, true);
  assert.equal(state.saving, false);
  assert.equal(state.error, "Gateway unavailable");
  state = editableTableReducer(state, { type: "saving" });
  const canonical = [{ ...draft[0], id: "normalized-id" }];
  state = editableTableReducer(state, { type: "saved", items: canonical });
  assert.deepEqual(state.items, canonical);
  assert.equal(state.dirty, false);
  assert.equal(state.error, "");
});

test("table row edits are ignored during an in-flight save", () => {
  const state = editableTableReducer(initialEditableTableState([processRule]), { type: "saving" });
  assert.strictEqual(editableTableReducer(state, { type: "edit", items: [] }), state);
});

test("canonical save results remain visible when the parent has not sent new props", () => {
  const originalProps = [processRule];
  const canonical = [{ ...processRule, value: "Firefox", id: "canonical-rule" }];
  let state = initialEditableTableState(originalProps);
  state = editableTableReducer(state, { type: "edit", items: canonical });
  state = editableTableReducer(state, { type: "saving" });
  state = editableTableReducer(state, { type: "saved", items: canonical });
  assert.strictEqual(state.serverItems, originalProps);
  assert.strictEqual(state.items, canonical);
  // The render's incoming-props comparison therefore sees no new server list.
  assert.equal(state.serverItems !== originalProps, false);
});

test("invalid dictionary and integer drafts block both card and legacy schema saves", () => {
  const schema = [{ key: "hosts", type: "dict" }, { key: "port", type: "int" }];
  assert.deepEqual(settingsErrors(schema, { hosts: "{broken", port: integerDraftValue("1.5") }), { hosts: "validation.dict", port: "validation.integer" });
  assert.deepEqual(settingsErrors(schema, { hosts: parseJsonObject('{"example.test":"127.0.0.1"}'), port: integerDraftValue("7890") }), {});
  for (const text of ["[]", "null", "true", '"plain text"', "1"]) assert.throws(() => parseJsonObject(text), /JSON object/);
  for (const text of ["", "1.5", "NaN", "Infinity"]) assert.equal(typeof integerDraftValue(text), "string");
});

test("restore apply requires the completed preview for the currently selected ref", () => {
  const preview = { ok: true, ref: "origin/main", source_digest: "digest", snapshot_digest: "actual-snapshot-hash", changed: true, sections: [] };
  assert.equal(canApplyRestore(preview, "origin/main", "origin/main", false), true);
  assert.equal(canApplyRestore(preview, "origin/main", "other-commit", false), false);
  assert.equal(canApplyRestore(preview, null, "origin/main", false), false);
  assert.equal(canApplyRestore(preview, "origin/main", "origin/main", true), false);
  assert.equal(canApplyRestore({ ...preview, ok: false }, "origin/main", "origin/main", false), false);
  assert.equal(canApplyRestore({ ...preview, snapshot_digest: "" }, "origin/main", "origin/main", false), false);
});

test("restore preview requires the actual snapshot digest before it can be applied", () => {
  const preview = { ok: true, ref: "origin/main", source_digest: "manifest-value", snapshot_digest: "a".repeat(64), changed: true, sections: [] };
  assert.equal(parsePolicyRestorePreview(preview).snapshot_digest, "a".repeat(64));
  assert.throws(() => parsePolicyRestorePreview({ ...preview, snapshot_digest: undefined }), /snapshot checksum/);
  assert.throws(() => parsePolicyRestorePreview({ ...preview, snapshot_digest: "manifest-value" }), /snapshot checksum/);
});

test("setup gates follow explicit per-user initialization status", () => {
  const uninitialized = { setup_required: true, initialized: false, instance_initialized: true, access_mode: "per-user" };
  assert.equal(parseSetupStatus(uninitialized).setup_required, true);
  assert.equal(parseSetupStatus({ ...uninitialized, setup_required: false, initialized: true }).initialized, true);
  assert.throws(() => parseSetupStatus({ setup_required: true }), /setup status/);
  assert.throws(() => parseSetupStatus({ ...uninitialized, initialized: true }), /setup status/);
});

test("process match types cover the canonical server options and reject Bundle ID", () => {
  for (const match_type of PROCESS_RULE_TYPES) {
    assert.equal(validateProcessRules([{ ...processRule, match_type }]), undefined);
    const response = parseProcessRuleListResponse({ ok: true, items: [{ ...processRule, match_type }] });
    assert.equal(response.items[0].match_type, match_type);
  }
  assert.equal(validateProcessRules([{ ...processRule, match_type: "bundle-id" }])?.reason, "validation.choice");
  assert.equal(validateProcessRules([{ ...processRule, value: " " }])?.field, "value");
  assert.equal(validateProcessRules([{ ...processRule, contract_id: "" }])?.field, "contract_id");
});

test("external programs preserve spaced arguments and validate the exact port bounds", () => {
  const parsed = parseExternalProxyProgramListResponse({ ok: true, items: [externalProgram] });
  assert.deepEqual(parsed.items[0].args, ["--config", "/a path/config.json"]);
  for (const local_port of [1, 65535]) assert.equal(validateExternalProxyPrograms([{ ...externalProgram, local_port }]), undefined);
  for (const local_port of [0, -1, 65536, 1.5, NaN]) assert.equal(validateExternalProxyPrograms([{ ...externalProgram, local_port }])?.reason, "validation.port");
  assert.equal(validateExternalProxyPrograms([{ ...externalProgram, program_path: " " }])?.field, "program_path");
  assert.equal(validateExternalProxyPrograms([{ ...externalProgram, sort_order: 1.5 }])?.reason, "validation.integer");
});

test("advanced list boundaries reject missing fields instead of discarding saved records", () => {
  assert.throws(() => parseProcessRuleListResponse({ ok: true }), /items array/);
  assert.throws(() => parseExternalProxyProgramListResponse({ ok: true, items: [{ ...externalProgram, args: "--config" }] }), /string array/);
  assert.throws(() => parseProcessRuleListResponse({ ok: true, items: [{ ...processRule, contract_id: null }] }), /contract_id must be a string/);
});

test("standard sources require explicit contracts and ingestion-specific fields", () => {
  const draft = { name: "Airport", ingestKind: "remote_subscription", sourceMode: "route_contract", targetContractId: "", clashUrl: "https://sub.test/clash", shadowrocketUrl: "", manualNodesText: "" };
  assert.deepEqual(validateStandardSourceDraft(draft), { shadowrocketUrl: "validation.required", targetContractId: "validation.required" });
  assert.deepEqual(validateStandardSourceDraft({ ...draft, sourceMode: "high_quality_airport", shadowrocketUrl: "https://sub.test/nodes" }), {});
  assert.deepEqual(validateStandardSourceDraft({ ...draft, ingestKind: "manual_nodes", targetContractId: "medium" }), { manualNodesText: "validation.required" });
  assert.deepEqual(validateStandardSourceDraft({ ...draft, ingestKind: "manual_nodes", targetContractId: "medium", manualNodesText: "ss://node" }), {});
  assert.equal(resolvePullMode(""), "direct_then_proxy");
  assert.equal(resolvePullMode("direct_only"), "direct_only");
});

test("workspace state keys isolate route and scenario boundaries", () => {
  assert.notEqual(workspaceScopeKey("/devices", "A"), workspaceScopeKey("/devices", "B"));
  assert.notEqual(workspaceScopeKey("/devices", "A"), workspaceScopeKey("/advanced", "A"));
});

test("scenario creation navigation is consumed before a scenario remount", () => {
  const navigation = { scenarioAction: "create", scenarioNavNonce: 123, unrelated: "keep" };
  assert.equal(scenarioCreateRequestToken(navigation, true), 123);
  const consumed = withoutScenarioCreateRequest(navigation);
  assert.deepEqual(consumed, { unrelated: "keep" });
  assert.equal(scenarioCreateRequestToken(consumed, true), 0);
  // Switching scenarios reuses the history entry, so the old request stays consumed.
  assert.equal(scenarioCreateRequestToken(consumed, true), 0);
  assert.equal(scenarioCreateRequestToken({ scenarioAction: "create", scenarioNavNonce: 124 }, true), 124);
  assert.equal(withoutScenarioCreateRequest({ scenarioAction: "create", scenarioNavNonce: 123 }), null);
});

test("refresh error details expose aggregate, result, runtime and validation evidence", () => {
  assert.equal(apiErrorDetail({ errors: ["standard pull failed", "standard pull failed", "GoRelay expired"] }, 502), "standard pull failed; GoRelay expired");
  assert.equal(apiErrorDetail({ result: { error: "GitHub rate limited" } }, 502), "GitHub rate limited");
  assert.equal(apiErrorDetail({ result: { failed_count: 3 } }, 502), "HTTP 502: 3 rule categories failed to refresh");
  assert.equal(apiErrorDetail({ runtime: { last_error: "timeout" } }, 502), "timeout");
  assert.equal(apiErrorDetail({ detail: [{ loc: ["body", "items", 0, "local_port"], msg: "must be greater than 0" }] }, 422), "body.items.0.local_port: must be greater than 0");
  assert.equal(apiErrorDetail({ detail: {} }, 502), "HTTP 502");
});

test("the API transport retains HTTP status and surfaces failed-refresh evidence", async () => {
  const originalFetch = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ ok: false, errors: ["rule catalog unavailable"] }), { status: 502, headers: { "content-type": "application/json" } });
    await assert.rejects(apiPost("/api/refresh"), (error: unknown) => error instanceof ApiError && error.status === 502 && error.detail === "rule catalog unavailable");
  } finally {
    globalThis.fetch = originalFetch;
  }
});
