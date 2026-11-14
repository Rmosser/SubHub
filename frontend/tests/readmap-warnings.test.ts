import assert from "node:assert/strict";
import test from "node:test";
import { POP_EDGE, POP_MAX, placePop } from "../src/pages/Profile/readmap/popPlace.ts";
import { groupWarnings, type Warning } from "../src/pages/Profile/readmap/warningGroups.ts";

const w = (code: string, message: string, target = "", bucket = "downgraded", severity = "warning"): Warning =>
  ({ code, message, target, bucket, severity });

test("folds notes of one kind into one line with its count", () => {
  const groups = groupWarnings([
    w("shadowrocket-inline-unsupported", "Shadowrocket skipped node-a: SS plugin parameters require node URI import", "node-a", "refused"),
    w("shadowrocket-inline-unsupported", "Shadowrocket skipped node-b: SS plugin parameters require node URI import", "node-b", "refused"),
    w("shadowrocket-inline-unsupported", "Shadowrocket skipped node-b: SS plugin parameters require node URI import", "node-b", "refused"),
  ]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].title, "有节点没写进配置");
  assert.equal(groups[0].count, 3);
  assert.deepEqual(groups[0].items, ["node-a", "node-b"]);
  assert.match(groups[0].lead ?? "", /SS 插件参数/);
  assert.equal(groups[0].tone, "refused");
});

test("one intent across clients and statuses reads as its setting name", () => {
  const groups = groupWarnings([
    w("intent-skip-proxy-surge-unsupported", "跳过代理：本项没有可证明等价的 surge 投影。该端仍按自己的系统代理处理。"),
    w("intent-skip-proxy-surge-pending-validation", "跳过代理：该端仍按自己的系统代理处理。", "", "pending_validation"),
  ]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].title, "跳过代理");
  assert.equal(groups[0].count, 2);
  assert.deepEqual(groups[0].items, ["该端仍按自己的系统代理处理。"]);
  assert.equal(groups[0].lead, "有的没写进配置，写进去的效果要自己核对。");
  assert.equal(groups[0].tone, "pending");
});

test("intents whose message has no name prefix get a plain title", () => {
  const [g] = groupWarnings([
    w("intent-contract-strict-surge-pending-validation", "2 个 strict 契约（示例：a）在 Surge 输出为 fallback 组。", "", "pending_validation"),
  ]);
  assert.equal(g.title, "严格契约的回退组");
  assert.equal(g.lead, "写进了配置，效果要自己核对。");
  const [h] = groupWarnings([w("intent-ip-dns-client-default-differs", "8 条 IP 网段规则保留不同客户端默认。", "", "pending_validation")]);
  assert.equal(h.title, "IP 规则查不查 DNS，各端不同");
  const [k] = groupWarnings([w("intent-shadowrocket-ip-dns-conditional", "12 条 IP 规则的域名匹配依赖兜底。", "", "pending_validation")]);
  assert.equal(k.title, "IP 规则能否命中，取决于兜底路径");
  const [r] = groupWarnings([w("intent-routing-evidence-gap-surge", "4104 项分流声明仍缺完整等价证据。", "", "pending_validation")]);
  assert.equal(r.title, "分流声明缺少等价证据");
});

test("unknown kinds keep the server's words", () => {
  const groups = groupWarnings([w("brand-new-code", "Something new happened")]);
  assert.equal(groups[0].title, "Something new happened");
  assert.equal(groups[0].lead, null);
  assert.deepEqual(groups[0].items, []);
  const two = groupWarnings([w("brand-new-code", "first"), w("brand-new-code", "second")]);
  assert.equal(two[0].count, 2);
  assert.deepEqual(two[0].items, ["first", "second"]);
});

test("refused first, then pending, then downgraded, then info", () => {
  const groups = groupWarnings([
    w("mac-only-rule-ignored", "PROCESS-NAME is rendered only in surge-mac-overlay.conf", "Direct", "downgraded", "info"),
    w("duplicate-ip-rule", "Duplicate IP rule IP-CIDR,203.0.113.0/24 ignored", "Set"),
    w("intent-excluded-routes-surge-pending-validation", "排除路由地址：不能保证。", "", "pending_validation"),
    w("shadowrocket-inline-unsupported", "Shadowrocket skipped x: other reason", "x", "refused"),
  ]);
  assert.deepEqual(groups.map((g) => g.tone), ["refused", "pending", "downgraded", "info"]);
  assert.deepEqual(groups.find((g) => g.key === "duplicate-ip-rule")?.items, ["IP-CIDR,203.0.113.0/24"]);
  assert.match(groups[0].lead ?? "", /不认这些节点/);
});

test("a lead holds for every note of its kind, or falls back to a plain one (#28)", () => {
  const ss = "SS plugin parameters require node URI import";
  const all = groupWarnings([
    w("shadowrocket-inline-unsupported", `Shadowrocket skipped a: ${ss}`, "a", "refused"),
    w("shadowrocket-inline-unsupported", `Shadowrocket skipped b: ${ss}`, "b", "refused"),
  ]);
  assert.match(all[0].lead ?? "", /SS 插件参数/);
  // The first note alone used to decide it: here it would have blamed the plugin for both.
  const mixed = groupWarnings([
    w("shadowrocket-inline-unsupported", `Shadowrocket skipped a: ${ss}`, "a", "refused"),
    w("shadowrocket-inline-unsupported", "Shadowrocket skipped b: other reason", "b", "refused"),
  ]);
  assert.doesNotMatch(mixed[0].lead ?? "", /SS 插件|不认/);
  assert.equal(mixed[0].lead, "Shadowrocket 没法把这些节点写进配置，跳过了它们。");
  const fields = groupWarnings([
    w("shadowrocket-unverified-fields-omitted", "omitted unverified fields (alpn, sni)", "a"),
    w("shadowrocket-unverified-fields-omitted", "omitted unverified fields (sni, ws-path)", "b"),
  ]);
  assert.match(fields[0].lead ?? "", /^alpn、sni、ws-path /);
});

test("a long note of an unknown kind gets a short title and keeps its words underneath (#28)", () => {
  const long = "The renderer hit a case it has no plain sentence for yet, and it says so at length here.";
  const [g] = groupWarnings([w("brand-new-code", long)]);
  assert.ok(g.title.length <= 24, g.title);
  assert.ok(g.title.endsWith("…"));
  assert.deepEqual(g.items, [long]);
  const [n] = groupWarnings([w("brand-new-code", "排除路由：这一端按自己的默认处理，结果可能和别的端不同。")]);
  assert.equal(n.title, "排除路由");
  assert.deepEqual(n.items, ["这一端按自己的默认处理，结果可能和别的端不同。"]);
  const [i] = groupWarnings([w("intent-something-surge-pending-validation", long, "", "pending_validation")]);
  assert.ok(i.title.length <= 24);
  assert.deepEqual(i.items, [long]);
});

test("the popover lines up with the chip's nearer side (#34)", () => {
  // Wide window, chip at the bar's right end: right edges match.
  assert.deepEqual(placePop(1300, 1372, 1440), { left: 1372 - POP_MAX, width: POP_MAX });
  // The bar wrapped and the chip starts the second line: left edges match instead of hanging off the left.
  assert.deepEqual(placePop(20, 92, 430), { left: 20, width: 398 });
  assert.deepEqual(placePop(20, 92, 500), { left: 20, width: POP_MAX });
  // Phone width, chip still at the right end of one line.
  assert.deepEqual(placePop(298, 370, 390), { left: 12, width: 358 });
});

test("the popover never leaves the window, whatever the width and wherever the chip (#34)", () => {
  for (let vw = 280; vw <= 2000; vw += 7) {
    for (let x = 0; x + 72 <= vw; x += 13) {
      const { left, width } = placePop(x, x + 72, vw);
      assert.ok(width > 0 && width <= POP_MAX, `${vw}/${x}: width ${width}`);
      assert.ok(left >= POP_EDGE, `${vw}/${x}: left ${left}`);
      assert.ok(left + width <= vw - POP_EDGE, `${vw}/${x}: right ${left + width}`);
    }
  }
});
