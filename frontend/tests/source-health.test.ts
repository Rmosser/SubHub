import assert from "node:assert/strict";
import test from "node:test";
import { gorelayHealth, needsAttention, pullReasons, shortUrl, sourceHealth } from "../src/pages/Sources/sourceHealth";
import { formatRelativeTime } from "../src/utils/formatting";
import type { GoRelaySource, StandardSource } from "../src/types";

test("relative time uses the largest unit", () => {
  const now = Date.parse("2026-11-12T10:26:00Z");
  assert.equal(formatRelativeTime("2026-11-12T10:24:00Z", now, "en-US"), "2 minutes ago");
  assert.equal(formatRelativeTime("2026-04-10T11:39:00Z", now, "en-US"), "7 months ago");
  assert.equal(formatRelativeTime("2026-11-12T10:25:40Z", now, "en-US"), "now");
  assert.equal(formatRelativeTime(null, now, "en-US"), "");
});

const t = (key: string, vars: Record<string, string | number> = {}) =>
  Object.entries(vars).reduce((text, [name, value]) => text.replace(`{${name}}`, String(value)), key);

function source(patch: Partial<StandardSource>): StandardSource {
  return {
    id: "s", name: "s", clash_url: "", shadowrocket_url: "", surge_url: "", login_url: "", quality_group: "",
    target_contract_id: "", target_contract_display_name: "", source_mode: "", ingest_kind: "remote_subscription",
    manual_nodes_text: "", enabled: true, last_pull_attempt_at: null, last_success_at: null, last_pull_ok: null,
    last_pull_method: "", last_pull_node_count: 0, last_pull_error: "", last_pull_reasons: [], pull_network_mode: "", auto_pull_consecutive_failures: 0,
    auto_pull_expired: false, auto_pull_expired_at: null, last_success_config_fingerprint: "", config_fingerprint: "",
    export_config: {}, pull_warning_count: 0, pull_warnings: [], cached_node_count: 0, compatibility: {}, updated_at: "",
    ...patch,
  };
}

test("pull reasons read the codes: plain codes are translated, the rest keep the server's message", () => {
  const reasons = pullReasons(source({
    last_pull_ok: false,
    last_pull_reasons: [
      { method: "clash", code: "http_status", url: "https://sub.example/link/<redacted>", message: "HTTP 404" },
      { method: "surge", code: "timeout", url: "https://sub.example:8443/surge.conf", message: "timeout" },
      { method: "shadowrocket", code: "url_not_configured", url: "", message: "url not configured" },
      { method: "manual_nodes", code: "no_valid_nodes", url: "", message: "0 valid nodes parsed; invalid line" },
    ],
  }), t);
  assert.deepEqual(reasons, [
    { client: "Clash", status: "HTTP 404", host: "sub.example/link/<redacted>" },
    { client: "Surge", status: "sources.reason_timeout", host: "sub.example:8443/surge.conf" },
    { client: "Shadowrocket", status: "sources.reason_not_configured", host: "" },
    { client: "", status: "0 valid nodes parsed; invalid line", host: "" },
  ]);
});

test("a failed pull that still serves cached nodes is amber; with nothing left it is red", () => {
  const now = Date.parse("2026-11-12T10:00:00Z");
  const cached = sourceHealth(source({ last_pull_ok: false, cached_node_count: 88, last_success_at: "2026-04-10T11:39:00Z" }), t, { now });
  assert.equal(cached.tone, "amber");
  assert.equal(cached.nodes, 88);
  assert.equal(cached.phrase, "sources.pull_failed");
  const empty = sourceHealth(source({ last_pull_ok: false }), t, { now });
  assert.equal(empty.tone, "red");
  assert.equal(empty.sub, "sources.never_succeeded");
  assert.ok(needsAttention(cached) && needsAttention(empty));
});

test("a healthy pull is etched, a disabled source is idle", () => {
  const ok = sourceHealth(source({ last_pull_ok: true, last_success_at: "2026-11-12T09:58:00Z", last_pull_node_count: 64 }), t, { now: Date.parse("2026-11-12T10:00:00Z") });
  assert.equal(ok.tone, "ok");
  assert.equal(ok.nodes, 64);
  assert.equal(needsAttention(ok), false);
  assert.equal(sourceHealth(source({ enabled: false, last_pull_ok: false }), t).tone, "idle");
});

function account(patch: Partial<GoRelaySource>): GoRelaySource {
  return {
    id: "g", name: "g", login_url: "https://gorelay.example/#/login", gorelay_username: "u", has_gorelay_password: true,
    proxy_username: "", has_proxy_password: false, selectors_json: "{}", enabled: true, updated_at: "",
    ...patch,
  };
}

test("a failed GoRelay crawl keeps the last snapshot's nodes: amber with nodes, red without", () => {
  const now = Date.parse("2026-11-12T10:00:00Z");
  const cached = gorelayHealth(account({ last_refresh_status: "failed", last_node_count: 35, last_refresh_at: "2026-11-12T09:00:00Z" }), t, { now });
  assert.equal(cached.tone, "amber");
  assert.equal(cached.nodes, 35);
  assert.equal(cached.sub, "sources.reusing_cached_nodes");
  const empty = gorelayHealth(account({ last_refresh_status: "failed", last_node_count: 0 }), t, { now });
  assert.equal(empty.tone, "red");
  assert.equal(empty.phrase, "sources.gorelay_failed_empty");
  assert.equal(gorelayHealth(account({ last_refresh_status: "empty" }), t).tone, "amber");
});

test("a GoRelay account that crawled is ok; disabled or never crawled is idle", () => {
  const ok = gorelayHealth(account({ last_refresh_status: "success", last_node_count: 12, last_refresh_at: "2026-11-12T09:58:00Z" }), t, { now: Date.parse("2026-11-12T10:00:00Z") });
  assert.equal(ok.tone, "ok");
  assert.equal(needsAttention(ok), false);
  assert.equal(gorelayHealth(account({ enabled: false, last_refresh_status: "failed" }), t).tone, "idle");
  const never = gorelayHealth(account({}), t);
  assert.equal(never.tone, "idle");
  assert.equal(never.phrase, "sources.gorelay_never");
});

test("a login URL shortens to its host", () => {
  assert.equal(shortUrl("https://gorelay.example/#/login"), "gorelay.example");
  assert.equal(shortUrl("https://gorelay.example:8443/panel/"), "gorelay.example:8443/panel/");
});
