import assert from "node:assert/strict";
import test from "node:test";

import { parseCategoryCustomRules } from "../src/api/validators/catalog";
import { parseProfileEditorSchema } from "../src/api/validators/profile";
import { parseReviewSettings } from "../src/api/validators/review";
import { array, nullable, num, object, optional, response, str } from "../src/api/validators/schema";
import { ApiContractError } from "../src/api/validators/shared";
import { parseRefreshPolicyItem, parseStandardSourceList } from "../src/api/validators/sources";

const contractError = (pattern: RegExp) => (error: unknown) => error instanceof ApiContractError && pattern.test(error.message);

test("object reads only declared fields and names the field that broke the contract", () => {
  const parse = response(object<{ id: string; count: number; note?: string; at: string | null }>({
    id: str,
    count: num,
    note: optional(str),
    at: nullable(str),
  }));
  assert.deepEqual(parse({ id: "a", count: 2, at: null, extra: true }), { id: "a", count: 2, at: null });
  assert.deepEqual(parse({ id: "a", count: 2, note: null, at: "t" }), { id: "a", count: 2, at: "t" });
  assert.throws(() => parse({ id: "a", count: "2", at: null }), contractError(/response\.count must be a number/));
  assert.throws(() => parse({ id: "a", count: 2 }), contractError(/response\.at must be a string/));
});

test("array errors point at the item", () => {
  const parse = response(array(object<{ id: string }>({ id: str })));
  assert.throws(() => parse([{ id: "a" }, {}]), contractError(/response\[1\]\.id must be a string/));
});

function standardSource(overrides: Record<string, unknown> = {}) {
  return {
    id: "s1", name: "S", clash_url: "", shadowrocket_url: "", surge_url: "", login_url: "", quality_group: "",
    target_contract_id: "medium", target_contract_display_name: "Medium", source_mode: "remote", ingest_kind: "",
    manual_nodes_text: "", enabled: true, last_pull_attempt_at: null, last_success_at: null, last_pull_ok: null,
    last_pull_method: "", last_pull_node_count: 0, last_pull_error: "", last_pull_reasons: [], pull_network_mode: "direct_then_proxy",
    auto_pull_consecutive_failures: 0, auto_pull_expired: false, auto_pull_expired_at: null,
    last_success_config_fingerprint: "", config_fingerprint: "", export_config: {}, pull_warning_count: 0,
    pull_warnings: [], cached_node_count: 0,
    compatibility: { clash: { supported: [], downgraded: [], refused: [], pending_validation: [] } },
    updated_at: "2026-11-12T00:00:00Z",
    ...overrides,
  };
}

test("standard sources fail instead of inventing a missing pull state", () => {
  assert.equal(parseStandardSourceList({ ok: true, items: [standardSource()] }).items[0].id, "s1");
  const withoutError: Record<string, unknown> = standardSource();
  delete withoutError.last_pull_error;
  assert.throws(
    () => parseStandardSourceList({ ok: true, items: [withoutError] }),
    contractError(/items\[0\]\.last_pull_error must be a string/),
  );
});

test("pull reasons only carry the documented codes", () => {
  const reason = { method: "clash", code: "timeout", url: "https://a.example/s", message: "timeout" };
  assert.deepEqual(parseStandardSourceList({ ok: true, items: [standardSource({ last_pull_reasons: [reason] })] }).items[0].last_pull_reasons, [reason]);
  assert.throws(
    () => parseStandardSourceList({ ok: true, items: [standardSource({ last_pull_reasons: [{ ...reason, code: "TIMEOUT" }] })] }),
    contractError(/items\[0\]\.last_pull_reasons\[0\]\.code must be one of/),
  );
});

test("refresh policy uses the field names the server sends", () => {
  const item = { rule_catalog_cache_hours: 24, cn_cache_hours: 24, standard_source_auto_pull_enabled: true, standard_source_auto_pull_interval_minutes: 30 };
  assert.deepEqual(parseRefreshPolicyItem({ ok: true, item }).item, item);
  assert.throws(
    () => parseRefreshPolicyItem({ ok: true, item: { auto_pull_enabled: true } }),
    contractError(/item\.rule_catalog_cache_hours must be a number/),
  );
});

test("review settings come from the item and report the Gemini key", () => {
  assert.deepEqual(
    parseReviewSettings({ ok: true, item: { review_model: "gemini-2.0-flash", gemini_api_key_set: false } }),
    { review_model: "gemini-2.0-flash", gemini_api_key_set: false },
  );
  assert.throws(() => parseReviewSettings({ review_model: "x", api_key_set: true }), contractError(/response\.item must be an object/));
});

test("category custom rules need the category's effective contract", () => {
  const category = { effective_contract_id: " medium ", effective_contract_display_name: "Medium", effective_contract_source: "stored_contract", active: true };
  assert.deepEqual(parseCategoryCustomRules({ ok: true, items: [], category }), {
    effectiveContractId: "medium",
    effectiveContractDisplayName: "Medium",
    effectiveContractSource: "stored_contract",
    active: true,
    items: [],
  });
  assert.throws(() => parseCategoryCustomRules({ ok: true, items: [] }), contractError(/response\.category must be an object/));
});

test("an empty localized text object reads as no localized text", () => {
  const schema = {
    ok: true,
    groups: [],
    families: [],
    cards: [{
      id: "c", family_id: "f", group_id: "g", title: "T", description: "", mode_kind: "shared", status_badge: "stable",
      field_keys: ["k"], detail_sections: [],
      input_schema: [{ key: "k", label: "K", type: "dict", placeholder: "{}", placeholder_i18n: {} }],
    }],
    default_mode: {},
    detail_sections: {},
    legacy_handling: { title: "", message: "", action_label: "" },
  };
  const field = parseProfileEditorSchema(schema).cards[0].input_schema[0];
  assert.equal(field.placeholder, "{}");
  assert.equal(field.placeholder_i18n, undefined);
  schema.cards[0].input_schema[0].placeholder_i18n = { zh: "x" } as never;
  assert.throws(() => parseProfileEditorSchema(schema), contractError(/placeholder_i18n\.en must be a string/));
});
