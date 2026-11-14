import noDirectTransportCast from "./no-direct-transport-cast.js";
import noJsonParseOutsideBoundary from "./no-json-parse-outside-boundary.js";
import noUnvalidatedApiResponse from "./no-unvalidated-api-response.js";
import noWindowPromptForConfig from "./no-window-prompt-for-config.js";

export const rules = {
  "no-direct-transport-cast": noDirectTransportCast,
  "no-json-parse-outside-boundary": noJsonParseOutsideBoundary,
  "no-unvalidated-api-response": noUnvalidatedApiResponse,
  "no-window-prompt-for-config": noWindowPromptForConfig,
};

export default {
  meta: {
    name: "subhub-golden-principles",
  },
  rules,
};
