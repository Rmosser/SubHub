import { isJsonParseCall, normalizeFilename } from "./shared.js";

const ALLOWED_PATH_SEGMENTS = [
  "/frontend/src/api/",
  "/frontend/src/validators/",
  "/frontend/src/validator/",
  "/frontend/src/normalizers/",
  "/frontend/src/normalizer/",
  "/frontend/src/schemas/",
];

function isAllowedFile(filename) {
  return ALLOWED_PATH_SEGMENTS.some((segment) => filename.includes(segment));
}

export default {
  meta: {
    type: "problem",
    docs: {
      description: "Keep JSON parsing inside explicit boundary validators/normalizers.",
    },
    schema: [],
    messages: {
      outsideBoundary:
        "JSON parsing belongs in dedicated boundary validators or normalizers, not inside UI or page components.",
    },
  },
  create(context) {
    const filename = normalizeFilename(context.filename ?? context.getFilename?.());
    if (!filename.includes("/frontend/src/")) {
      return {};
    }

    return {
      CallExpression(node) {
        if (!isJsonParseCall(node) || isAllowedFile(filename)) {
          return;
        }
        context.report({ node, messageId: "outsideBoundary" });
      },
    };
  },
};
