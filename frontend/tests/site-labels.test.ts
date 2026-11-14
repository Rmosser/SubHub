import assert from "node:assert/strict";
import test from "node:test";
import { severityLabel } from "../src/utils/statusText";
import { paginationLabels } from "../src/utils/a11yLabels";

const zh: Record<string, string> = {
  "common.severity_error": "错误",
  "common.severity_warning": "告警",
  "common.severity_info": "提示",
  "common.severity_fatal": "致命",
  "common.pagination": "分页",
  "common.previous_page": "上一页",
  "common.next_page": "下一页",
  "common.page_number": "第 {page} 页",
};
const t = (key: string, vars: Record<string, string | number> = {}) =>
  (zh[key] ?? key).replace(/\{(\w+)\}/g, (_, name: string) => String(vars[name] ?? `{${name}}`));

test("known diagnostic severities are translated and unknown ones stay as the raw value", () => {
  assert.equal(severityLabel("error", t), "错误");
  assert.equal(severityLabel("warning", t), "告警");
  assert.equal(severityLabel("info", t), "提示");
  assert.equal(severityLabel("fatal", t), "致命");
  assert.equal(severityLabel("notice", t), "notice");
  assert.equal(severityLabel("constructor", t), "constructor");
  assert.equal(severityLabel("", t), "");
});

test("pagination gets previous, next and numbered page names", () => {
  const labels = paginationLabels(t);
  assert.equal(labels.paginationLabel, "分页");
  assert.equal(labels.previousPageLabel, "上一页");
  assert.equal(labels.nextPageLabel, "下一页");
  assert.equal(labels.pageLabel?.(3), "第 3 页");
});
