import assert from "node:assert/strict";
import test from "node:test";
import { isChunkLoadError } from "../src/utils/chunkLoadError";

test("a lazy chunk removed by a deploy is recognised in every browser", () => {
  for (const message of [
    "Failed to fetch dynamically imported module: https://example.test/manage/assets/index-FnrxXmTr.js",
    "error loading dynamically imported module: https://example.test/manage/assets/index-FnrxXmTr.js",
    "Importing a module script failed.",
    "Unable to preload CSS for /manage/assets/index-FnrxXmTr.css",
  ]) {
    assert.equal(isChunkLoadError(new TypeError(message)), true, message);
  }
});

test("ordinary render errors keep the in-place retry", () => {
  assert.equal(isChunkLoadError(new Error("Cannot read properties of undefined (reading 'items')")), false);
  assert.equal(isChunkLoadError(null), false);
  assert.equal(isChunkLoadError("Failed to fetch dynamically imported module"), false);
});
