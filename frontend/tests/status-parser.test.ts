import assert from "node:assert/strict";
import test from "node:test";
import { parseDeviceListResponse } from "../src/api/validators/devices.ts";
import { parsePoolListResponse } from "../src/api/validators/pools.ts";
import { parseSystemStatusResponse } from "../src/api/validators/status.ts";

test("parses the current GET /api/status flat success response", () => {
  const status = parseSystemStatusResponse({
    ok: true,
    runtime: {
      last_refresh_at: "2026-08-31T03:00:00Z",
      last_error: null,
      source_status: {
        standard: {
          "standard-healthy": { ok: true, node_count: 12 },
          "standard-failed": { ok: false, auto_pull_expired: true },
        },
      },
    },
    standard_source_count: 2,
    gorelay_source_count: 1,
    egress: {
      proxy_bridge: {
        code: "ok",
        severity: "info",
        summary: "healthy",
        meaning: "reachable",
        repair_hint: "none",
        last_error: "",
        actions: [],
        required: true,
      },
    },
  });

  assert.equal(status.hub_runtime.last_refresh_at, "2026-08-31T03:00:00Z");
  assert.deepEqual(status.source_summary, {
    gorelay_count: 1,
    standard_count: 2,
    standard_expired: 1,
    standard_failed: 1,
  });
  assert.equal(status.egress.proxy_bridge.code, "ok");
  assert.equal(status.egress.proxy_bridge.required, true);
});

test("rejects a status response that only has the old nested fields", () => {
  assert.throws(
    () => parseSystemStatusResponse({ ok: true, hub_runtime: {}, source_summary: {} }),
    /runtime must be an object/,
  );
});

test("rejects malformed pool and device list envelopes instead of rendering empty tables", () => {
  assert.throws(
    () => parsePoolListResponse({ ok: true }),
    /items must be an array/,
  );
  assert.throws(
    () => parseDeviceListResponse({ ok: true }),
    /items must be an array/,
  );
});

test("requires one consistent overlay snapshot for a selected scenario", () => {
  const links = {
    clash_url: "https://example.test/clash.yaml",
    shadowrocket_url: "https://example.test/shadowrocket.conf",
    shadowrocket_nodes_url: "https://example.test/nodes.txt",
    surge_url: "https://example.test/surge.conf",
    surge_mac_overlay_url: "https://example.test/surge-mac-overlay.conf",
    clash_scheme: "clash://install",
    shadowrocket_scheme: "shadowrocket://config/add/https://example.test/shadowrocket.conf",
    surge_scheme: "surge:///install-config",
    surge_mac_overlay_scheme: "surge:///install-config",
  };
  const overlay = {
    available: false,
    reason_code: "missing_templates",
    reason: "No templates",
    renderable_process_rule_count: 0,
    renderable_external_proxy_program_count: 0,
  };
  const device = {
    id: "device-1",
    device_key: "laptop",
    device_name: "Laptop",
    subscription_id: "public-1",
    enabled: true,
    last_seen_at: null,
    last_seen_ip: null,
    scenario_id: "scenario-default",
    scenario_slug: "default",
    scenario_name: "Default",
    links,
    overlay_status: overlay,
  };
  const parsed = parseDeviceListResponse({ ok: true, items: [device] });
  assert.equal(parsed.items[0].overlay_status.reason_code, "missing_templates");
  assert.throws(
    () => parseDeviceListResponse({ ok: true, items: [{ ...device, links: { ...links, shadowrocket_scheme: "shadowrocket://config/add/http%3A%2F%2Fexample.test" } }] }),
    /raw configuration URL/,
  );
  assert.throws(
    () => parseDeviceListResponse({ ok: true, items: [{ ...device, links: { ...links, shadowrocket_scheme: "shadowrocket://config/add?url=encoded" } }] }),
    /config\/add\/<raw URL>/,
  );

  assert.throws(
    () =>
      parseDeviceListResponse({
        ok: true,
        items: [
          device,
          {
            ...device,
            id: "device-2",
            overlay_status: { ...overlay, reason_code: "all_templates_disabled" },
          },
        ],
      }),
    /overlay_status must match across the selected scenario/,
  );
});
