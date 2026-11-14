import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";
import subhubGoldenPrinciples from "../eslint-rules/index.js";

export default tseslint.config(
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "app/static/frontend/dist/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}", "vite.config.ts", "eslint.config.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
      "subhub-golden": subhubGoldenPrinciples,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/no-explicit-any": "warn",
      "@typescript-eslint/no-unused-vars": [
        "warn",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
          caughtErrorsIgnorePattern: "^_",
        },
      ],
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],

      "subhub-golden/no-unvalidated-api-response": "error",
      "subhub-golden/no-direct-transport-cast": "error",
      "subhub-golden/no-json-parse-outside-boundary": "error",
      "subhub-golden/no-window-prompt-for-config": "error",
    },
  },
  {
    files: ["src/contexts/**/*.tsx", "src/components/ErrorBoundary.tsx"],
    rules: {
      "react-refresh/only-export-components": "off",
    },
  },
);
