import { getTypeArguments, isUnsafeBoundaryType } from "./shared.js";

const API_CALL_NAMES = new Set(["apiGet", "apiPost", "apiPut", "apiDelete", "apiUpload"]);

export default {
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow `unknown`/`any`/`Record<string, unknown>` transport types on API boundary helpers.",
    },
    schema: [],
    messages: {
      unsafeBoundary:
        "API boundary types must be schema-validated domain types, not `unknown`, `any`, or raw `Record<string, unknown>` payloads.",
    },
  },
  create(context) {
    return {
      CallExpression(node) {
        if (node.callee?.type !== "Identifier" || !API_CALL_NAMES.has(node.callee.name)) {
          return;
        }
        const typeArguments = getTypeArguments(node);
        if (typeArguments.length === 0) {
          return;
        }
        if (!typeArguments.some(isUnsafeBoundaryType)) {
          return;
        }
        context.report({ node, messageId: "unsafeBoundary" });
      },
    };
  },
};

