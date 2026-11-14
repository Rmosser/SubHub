import assert from "node:assert/strict";
import test from "node:test";
import { escapeBelongsToPopup, type AttributeNode } from "../src/components/drawerKeys";

function node(attributes: Record<string, string>, parentElement: AttributeNode | null = null): AttributeNode {
  return { getAttribute: (name) => attributes[name] ?? null, parentElement };
}

test("Esc closes the drawer from an expanded disclosure button such as ReasonText", () => {
  const drawer = node({ class: "s-drawer" });
  const reasonToggle = node({ "aria-expanded": "true" }, node({ class: "s-reason" }, drawer));
  assert.equal(escapeBelongsToPopup(reasonToggle, drawer), false);
});

test("Esc first closes an expanded select, combobox or popup button inside the drawer", () => {
  const drawer = node({ class: "s-drawer" });
  assert.equal(escapeBelongsToPopup(node({ "aria-haspopup": "listbox", "aria-expanded": "true" }, drawer), drawer), true);
  assert.equal(escapeBelongsToPopup(node({ role: "combobox", "aria-expanded": "true" }, drawer), drawer), true);
  assert.equal(escapeBelongsToPopup(node({ "aria-haspopup": "true", "aria-expanded": "true" }, drawer), drawer), true);
});

test("collapsed popups and aria-haspopup=false do not hold Esc", () => {
  const drawer = node({ class: "s-drawer" });
  assert.equal(escapeBelongsToPopup(node({ "aria-haspopup": "listbox", "aria-expanded": "false" }, drawer), drawer), false);
  assert.equal(escapeBelongsToPopup(node({ role: "combobox", "aria-expanded": "false" }, drawer), drawer), false);
  assert.equal(escapeBelongsToPopup(node({ "aria-haspopup": "false", "aria-expanded": "true" }, drawer), drawer), false);
});

test("focus inside an open listbox or menu holds Esc, including popups portaled outside the drawer", () => {
  const drawer = node({ class: "s-drawer" });
  const option = node({ role: "option" }, node({ role: "listbox" }, drawer));
  assert.equal(escapeBelongsToPopup(option, drawer), true);
  const portaledItem = node({ role: "menuitem" }, node({ role: "menu" }, node({ tag: "body" })));
  assert.equal(escapeBelongsToPopup(portaledItem, drawer), true);
});

test("the search stops at the drawer boundary", () => {
  const outerMenu = node({ role: "menu" });
  const drawer = node({ class: "s-drawer" }, outerMenu);
  assert.equal(escapeBelongsToPopup(node({ class: "s-drawer-body" }, drawer), drawer), false);
  assert.equal(escapeBelongsToPopup(null, drawer), false);
});
