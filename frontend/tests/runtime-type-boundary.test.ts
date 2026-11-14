import assert from "node:assert/strict";
import test from "node:test";

import { parseBusinessGroupListResponse, parsePinData } from "../src/api/validators/catalog";
import { normalizeDevicePreviewResponse } from "../src/api/validators/devices";
import { resolveScenarioSelection } from "../src/contexts/ScenarioContext";
import { parseLogRoutingSessionResponse } from "../src/api/validators/llm";
import { ApiContractError } from "../src/api/validators/shared";

test("rejects a log-routing response without the required session item", () => {
  for (const payload of [{}, { item: null }, { item: undefined }]) {
    assert.throws(
      () => parseLogRoutingSessionResponse(payload),
      (error: unknown) =>
        error instanceof ApiContractError &&
        error.message === "API response is missing required item",
    );
  }
});

test("rejects an incomplete log-routing session item", () => {
  assert.throws(
    () => parseLogRoutingSessionResponse({ item: {} }),
    (error: unknown) =>
      error instanceof ApiContractError &&
      error.message === "API response contains an invalid log-routing session item",
  );
});

test("parses a complete log-routing session item", () => {
  assert.deepEqual(
    parseLogRoutingSessionResponse({
      item: {
        session_id: "session-1",
        created_at: "2026-08-31T00:00:00Z",
        updated_at: "2026-08-31T00:00:00Z",
        file_count: 1,
        evidence_count: 2,
      },
    }),
    {
      session_id: "session-1",
      created_at: "2026-08-31T00:00:00Z",
      updated_at: "2026-08-31T00:00:00Z",
      file_count: 1,
      evidence_count: 2,
    },
  );
});

test("catalog and device validators reject missing canonical fields", () => {
  assert.throws(
    () => parsePinData({ ok: true, pinned: [], groups: [{ name: "legacy", sort_order: 0, mode: "standard" }] }),
    /groups\[\]\.group_name must be a string/,
  );
  assert.throws(
    () => normalizeDevicePreviewResponse({ ok: true }),
    /metadata must be an object/,
  );
});

test("business-group list requires an explicit pool boundary", () => {
  assert.throws(
    () => parseBusinessGroupListResponse({
      ok: true,
      items: [{
        name: "AI tools",
        sort_order: 0,
        category_names: [],
        mode: "standard",
        created_by_system: false,
      }],
    }),
    /pool_names must be an array of strings/,
  );
});

test("scenario selection reports a missing requested id without fallback", () => {
  const result = resolveScenarioSelection(
    "scenario-missing",
    [{ id: "scenario-default", enabled: true }],
    false,
  );
  assert.equal(result.selectedScenario, null);
  assert.equal(result.selectedScenarioId, "scenario-missing");
  assert.equal(result.selectionIssue, "missing");
});

test("scenario selection reports a disabled requested id without fallback", () => {
  const result = resolveScenarioSelection(
    "scenario-disabled",
    [{ id: "scenario-disabled", enabled: false }, { id: "scenario-default", enabled: true }],
    false,
  );
  assert.equal(result.selectedScenario, null);
  assert.equal(result.selectedScenarioId, "scenario-disabled");
  assert.equal(result.selectionIssue, "disabled");
});
