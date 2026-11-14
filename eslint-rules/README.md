# SubHub golden-principles ESLint rules

把当前最容易机械化的黄金原则落到前端 lint。

## Included rules

- `no-unvalidated-api-response`
  - 禁止在 `apiGet` / `apiPost` / `apiPut` / `apiDelete` / `apiUpload` 上直接使用 `unknown`、`any`、`Record<string, unknown>` 等原始边界类型
- `no-direct-transport-cast`
  - 禁止在 `frontend/src/api/client.ts` 中把 `response.json()` / `response.text()` 之类的原始传输结果直接断言成泛型 `T`
- `no-json-parse-outside-boundary`
  - 禁止在 UI / page 组件中直接 `JSON.parse`
- `no-window-prompt-for-config`
  - 禁止在页面里用 `window.prompt()` 承载持久化配置修改

## Flat config wiring

```js
import subhubGoldenPrinciples from "../eslint-rules/index.js";

export default [
  {
    files: ["frontend/src/**/*.{ts,tsx}"],
    plugins: {
      "subhub-golden": subhubGoldenPrinciples,
    },
    rules: {
      "subhub-golden/no-unvalidated-api-response": "error",
      "subhub-golden/no-direct-transport-cast": "error",
      "subhub-golden/no-json-parse-outside-boundary": "error",
      "subhub-golden/no-window-prompt-for-config": "warn",
    },
  },
];
```

当前仓库已经在 `frontend/eslint.config.js` 启用这 4 条规则，并全部设为 `error`。
