# Agent 主配置路线图

状态：第 1 阶段已实现派生模型与兼容投影，第 3 轮修复后待独立复核；CLI 和 UI 的完整流程仍未实施。
配置原则唯一权威是 [core beliefs](../design-docs/core-beliefs.md)，本文件只规定顺序和阶段出口。

## 现有起点

- [Profile family 审计](../design-docs/profile-single-source-review.md) 提供 shared / adapted / blocked / standalone 分类与证据。
- 工作流已有 export → preview-import → apply、snapshot fingerprint、漂移 409；directness 接受后锁定。
- `subhub.patch.v1` 已有预览与应用，CLI `preview patch` / `apply patch` 已调用现有 HTTP API。
- 上述机制仍是局部能力；派生意图和兼容投影见第 1 阶段；全局批准门控和完整审计回滚尚未实现。现有 CLI 雏形不改变以下建设顺序。

## 阶段顺序与出口

| 顺序 | 阶段 | 状态 | 完成后必须能证明 |
| --- | --- | --- | --- |
| 1 | 意图模型 | 已实现派生模型、完整登记及兼容投影；第 3 轮修复后待独立复核 | 以 family 分类为起点，明确期望状态与三端投影，列清四层差异、不能表达的行为和证据；按 core beliefs #0、#1、#14–#16 验收。 |
| 2 | Agent 接口：CLI | 已有 HTTP 包装雏形，完整流程规划中 | 复用现有 HTTP API，完成提案、预检、批准、应用、诊断、追溯和恢复闭环；输入输出可预测，错误告诉调用者如何修正。服务端承担校验和授权，CLI 不成为独立语义源。 |
| 3 | UI 改为阅读、审阅与批准界面 | 已开始：配置与场景改为只读读图；审阅与批准界面尚未实现 | 按 core beliefs #3、#17 验收阅读、审阅、批准与微调；不为 Agent 操作界面优化。 |
| — | MCP | 暂缓 | CLI 经过真实任务验证并成熟后再评估；当前不设计或实现。 |

第 1 阶段实现见 [配置意图设计](../design-docs/configuration-intent.md) 和生成的 [逐字段登记表](../design-docs/intent-inventory.md)。IP 规则的匹配前 DNS 意图沿用三端现状；IP-only 分类与 DIRECT 兜底的风险只作条件性 warning，不改变订阅字节或新增 409。
Agent 代批的边界和开放条件见 core belief #14。

## 参照依据

这里只借鉴约束，不声明现有 API 已兼容这些规范，也不引入对应字段设计。

- 期望状态、观测状态与调和的区分参考 [Kubernetes 对象模型](https://kubernetes.io/docs/concepts/overview/working-with-objects/)。
- 先计划、按已保存计划应用参考 [Terraform apply](https://developer.hashicorp.com/terraform/cli/commands/apply)。
- 预检不落盘且执行同样校验参考 [AIP-163](https://google.aip.dev/163)；状态新鲜度核对参考 [AIP-154](https://google.aip.dev/154)。
- 清晰的工具边界、可预测输入输出和可操作错误参考 [Anthropic 工具实践](https://www.anthropic.com/research/writing-tools-for-agents)。
