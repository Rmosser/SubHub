import { getTypeName, isResponseMethodCall, normalizeFilename } from "./shared.js";

export default {
  meta: {
    type: "problem",
    docs: {
      description: "Disallow casting raw fetch payloads straight into generic domain types.",
    },
    schema: [],
    messages: {
      directCast:
        "Transport helpers must validate raw fetch payloads before returning domain types; do not cast raw payloads directly to `T`.",
    },
  },
  create(context) {
    const filename = normalizeFilename(context.filename ?? context.getFilename?.());
    const inApiClient = filename.endsWith("/frontend/src/api/client.ts");

    if (!inApiClient) {
      return {};
    }

    return {
      TSAsExpression(node) {
        if (getTypeName(node.typeAnnotation) === "T") {
          context.report({ node, messageId: "directCast" });
          return;
        }
        if (isResponseMethodCall(node.expression, "json") || isResponseMethodCall(node.expression, "text")) {
          context.report({ node, messageId: "directCast" });
        }
      },
    };
  },
};
