import { isPromptCall, normalizeFilename } from "./shared.js";

export default {
  meta: {
    type: "problem",
    docs: {
      description: "Avoid browser prompt dialogs for persistent configuration changes.",
    },
    schema: [],
    messages: {
      noPrompt:
        "Persistent configuration changes need explicit form controls or modals, not `window.prompt()` dialogs.",
    },
  },
  create(context) {
    const filename = normalizeFilename(context.filename ?? context.getFilename?.());
    if (!filename.includes("/frontend/src/pages/")) {
      return {};
    }

    return {
      CallExpression(node) {
        if (!isPromptCall(node)) {
          return;
        }
        context.report({ node, messageId: "noPrompt" });
      },
    };
  },
};
